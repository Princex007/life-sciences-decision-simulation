"""HTTP endpoints delegating builder operations to application services."""
from pathlib import Path
from fastapi import APIRouter, HTTPException, Response
from app.domain.definitions import SimulationDefinition
from app.services.simulation_builder import DefinitionValidationError, SimulationBuilderService
from app.services.simulation_runner import SimulationRunnerService

router = APIRouter()
builder = SimulationBuilderService()
_results: dict[str, dict] = {}
runner = SimulationRunnerService()

def _definition_or_404(simulation_id: str):
    try:
        return builder.get(simulation_id)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

def _validate_or_422(definition: SimulationDefinition):
    try:
        return builder.validate(definition)
    except DefinitionValidationError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error

def _results_payload(simulation_id: str, definition: SimulationDefinition, result, duration: float):
    """Shared shape for stored runs and unsaved preview runs."""
    return {"simulation_id": simulation_id, "summary": {
        "terminal_scenarios": len(result.scenarios), "pruned_nodes": len(result.pruning_records),
        "duration_seconds": duration, "forecast_model": definition.forecast_model_id,
        "scenario_policy": definition.scenario_generation.policy,
        "time_horizon": definition.settings.time_horizon,
        "step_unit": definition.settings.step_unit,
        "decision_policy": definition.settings.decision_policy,
        "llm_usage": result.llm_usage,
        "key_drivers": sorted({item.driver_id for item in result.driver_impacts}),
        "assumption_labels": sorted({label for driver in definition.external_drivers
                                     for label in driver.assumption_labels()}),
        "variable_evidence": {name: {
            "evidence_grade": meta.get("evidence_grade", ""),
            "assumption_labels": meta.get("assumption_labels", []),
            "description": meta.get("description", "")}
            for name, meta in definition.world_variable_metadata.items()}},
        "driver_impacts": [record.model_dump(mode="json") for record in result.driver_impacts],
        "driver_hypotheses": [record.model_dump(mode="json") for record in result.driver_hypotheses],
        "driver_evidence_grades": {driver.driver_id: driver.evidence_grade
                                   for driver in definition.external_drivers},
        "pruning_records": [record.model_dump(mode="json") for record in result.pruning_records],
        "scenarios": [scenario.model_dump(mode="json") for scenario in result.scenarios]}

@router.post("/simulations/preview-run")
def preview_run(definition: SimulationDefinition):
    """Run an unsaved definition without writing it to local storage.

    Used to compare external-driver variants against the same baseline.
    """
    _validate_or_422(definition)
    try:
        result, duration = runner.run(definition)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    payload = _results_payload(definition.metadata.id, definition, result, duration)
    payload["status"] = "preview"
    payload["root"] = result.root.model_dump(mode="json")
    return payload

@router.get("/simulations/schema")
def simulation_schema():
    return SimulationDefinition.model_json_schema()

@router.post("/simulations/validate")
def validate_definition(definition: SimulationDefinition):
    return {"valid": True, "errors": _validate_or_422(definition)}

@router.get("/simulations/templates")
def list_templates():
    examples = builder.examples_dir
    templates = []
    for path in sorted(examples.glob("*.json")):
        definition = SimulationDefinition.from_json(str(path))
        drivers = [driver for driver in definition.external_drivers if driver.enabled]
        templates.append({"id": path.stem, "name": definition.metadata.name,
                          "description": definition.metadata.description,
                          "summary": {
                              "domain": definition.metadata.domain,
                              "agents": [agent.name or agent.id for agent in definition.agents],
                              "time_horizon": definition.settings.time_horizon,
                              "step_unit": definition.settings.step_unit,
                              "forecast_model": definition.forecast_model_id,
                              "decision_policy": definition.settings.decision_policy,
                              "max_scenarios": definition.scenario_generation.max_scenarios,
                              "external_drivers": [
                                  {"driver_id": driver.driver_id, "name": driver.name,
                                   "category": driver.category,
                                   "active_variant": driver.active_variant,
                                   "variants": [{"variant_id": item.variant_id, "label": item.label,
                                                 "description": item.description,
                                                 "evidence_grade": item.evidence_grade}
                                                for item in driver.variants]}
                                  for driver in drivers],
                              "evidence_grades": sorted({
                                  grade for grade in [
                                      definition.world_variable_metadata.get(name, {}).get("evidence_grade")
                                      for name in definition.initial_world_state.as_variables()]
                                  if grade}),
                          }})
    return templates

@router.get("/simulations/templates/{template_id}")
def get_template(template_id: str):
    try:
        return builder.load_template(template_id)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except DefinitionValidationError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error

@router.get("/simulations")
def list_simulations():
    return [{"simulation_id": item.metadata.id, "name": item.metadata.name,
             "description": item.metadata.description,
             "domain": item.metadata.domain,
             "agent_count": len(item.agents),
             "time_horizon": item.settings.time_horizon,
             "external_driver_count": len([d for d in item.external_drivers if d.enabled]),
             "has_results": item.metadata.id in _results} for item in builder.list()]

@router.post("/simulations", status_code=201)
def create_simulation(definition: SimulationDefinition):
    try:
        builder.create(definition)
    except DefinitionValidationError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error
    except FileExistsError as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"simulation_id": definition.metadata.id, "name": definition.metadata.name, "status": "created"}

@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: str):
    definition = _definition_or_404(simulation_id)
    return {"simulation_id": simulation_id, "definition": definition,
            "status": "completed" if simulation_id in _results else "saved"}

@router.put("/simulations/{simulation_id}")
def update_simulation(simulation_id: str, definition: SimulationDefinition):
    try:
        builder.update(simulation_id, definition)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except DefinitionValidationError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    _results.pop(simulation_id, None)
    return {"simulation_id": simulation_id, "status": "updated"}

@router.delete("/simulations/{simulation_id}", status_code=204)
def delete_simulation(simulation_id: str):
    try:
        builder.delete(simulation_id)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    _results.pop(simulation_id, None)
    return Response(status_code=204)

@router.post("/simulations/{simulation_id}/duplicate", status_code=201)
def duplicate_simulation(simulation_id: str):
    try:
        duplicate = builder.duplicate(simulation_id)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except DefinitionValidationError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error
    return {"simulation_id": duplicate.metadata.id, "name": duplicate.metadata.name, "status": "created"}

@router.post("/simulations/{simulation_id}/validate")
def validate_simulation(simulation_id: str):
    definition = _definition_or_404(simulation_id)
    return {"valid": True, "errors": _validate_or_422(definition)}

@router.post("/simulations/{simulation_id}/run")
def run_simulation(simulation_id: str):
    definition = _definition_or_404(simulation_id)
    _validate_or_422(definition)
    try:
        result, duration = runner.run(definition)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    _results[simulation_id] = {"result": result, "duration_seconds": duration}
    return {"simulation_id": simulation_id, "status": "completed",
            "scenario_count": len(result.scenarios), "pruned_nodes": len(result.pruning_records),
            "duration_seconds": duration}

@router.get("/simulations/{simulation_id}/results")
def get_results(simulation_id: str):
    _definition_or_404(simulation_id)
    stored = _results.get(simulation_id)
    if not stored:
        raise HTTPException(409, "Simulation has not been run")
    definition = builder.get(simulation_id)
    payload = _results_payload(simulation_id, definition, stored["result"],
                               stored["duration_seconds"])
    payload["root"] = stored["result"].root.model_dump(mode="json")
    return payload

@router.get("/simulations/{simulation_id}/tree")
def get_tree(simulation_id: str):
    _definition_or_404(simulation_id)
    stored = _results.get(simulation_id)
    if not stored:
        raise HTTPException(409, "Simulation has not been run")
    result = stored["result"]
    return {"root": result.root.model_dump(mode="json"),
            "terminal_scenario_ids": [scenario.scenario_id for scenario in result.scenarios],
            "pruning_records": [record.model_dump(mode="json") for record in result.pruning_records]}

@router.get("/simulations/{simulation_id}/scenarios")
def list_scenarios(simulation_id: str):
    _definition_or_404(simulation_id)
    stored = _results.get(simulation_id)
    if not stored:
        raise HTTPException(409, "Simulation has not been run")
    return [scenario.model_dump(mode="json") for scenario in stored["result"].scenarios]

@router.get("/simulations/{simulation_id}/scenarios/{scenario_id}")
def get_scenario(simulation_id: str, scenario_id: str):
    _definition_or_404(simulation_id)
    stored = _results.get(simulation_id)
    if not stored:
        raise HTTPException(409, "Simulation has not been run")
    for scenario in stored["result"].scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise HTTPException(404, "Scenario not found")
