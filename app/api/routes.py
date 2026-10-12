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
        templates.append({"id": path.stem, "name": definition.metadata.name,
                          "description": definition.metadata.description})
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
             "description": item.metadata.description} for item in builder.list()]

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
    definition, result = builder.get(simulation_id), stored["result"]
    return {"simulation_id": simulation_id, "summary": {
        "terminal_scenarios": len(result.scenarios), "pruned_nodes": len(result.pruning_records),
        "duration_seconds": stored["duration_seconds"], "forecast_model": definition.forecast_model_id,
        "scenario_policy": definition.scenario_generation.policy},
        "scenarios": [scenario.model_dump(mode="json") for scenario in result.scenarios]}

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
