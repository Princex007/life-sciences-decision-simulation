"""HTTP endpoints delegating builder operations to application services."""
import math
from numbers import Real
from pathlib import Path
from fastapi import APIRouter, HTTPException, Response
from app.agents.assumptions import AssumptionFillError, fill_assumptions, find_gaps
from app.agents.llm import LLMClientError, OpenAICompatibleLLMClient
from app.agents.reference_suggestion import ReferenceSuggestionError
from app.agents.reference_suggestion import suggest_reference as suggest
from app.config import LLMConfigurationError
from app.domain.action import ActionEffect
from app.domain.definitions import SimulationDefinition
from app.domain.world import WorldState
from app.api.models import (DriverScenarioRequest, ReferenceAnalogueRequest,
                            ReferenceSuggestionRequest, TableImportRequest,
                            TimeSeriesForecastRequest)
from app.domain.history import ProductHistory
from app.forecasting.registry import default_registry
from app.forecasting.reference_product import scale_to_peak
from app.forecasting.trend import fit_trend
from app.services.history_store import HistoryValidationError, ProductHistoryStore
from app.services.table_import import TableImportError, decode_upload, import_series
from app.services.simulation_builder import DefinitionValidationError, SimulationBuilderService
from app.services.simulation_runner import SimulationRunnerService
from app.simulation.external_drivers import scale_value
from app.simulation.state_transition import StateTransitionSystem

router = APIRouter()
histories = ProductHistoryStore()
builder = SimulationBuilderService(history_store=histories)
_results: dict[str, dict] = {}
runner = SimulationRunnerService(history_store=histories)

def _history_summary(history_id: str | None):
    """Describe the stored series a run was fitted against, or None when unused."""
    if not history_id:
        return None
    try:
        item = histories.get(history_id)
    except (FileNotFoundError, ValueError):
        return {"history_id": history_id, "missing": True}
    return {"history_id": item.history_id, "name": item.name, "points": len(item.values),
            "first": item.values[0], "latest": item.values[-1], "variable": item.variable,
            "unit": item.unit, "cadence": item.cadence,
            "source": item.source, "evidence_grade": item.evidence_grade,
            "assumption_label": item.assumption_label,
            # The dashboard draws the recorded history next to its projection, so the run
            # result carries the series it was fitted against rather than only its ends.
            "values": item.values}


def _reference_summary(definition: SimulationDefinition):
    """Describe the analogue series a run was scaled from, with the scaled shape it used."""
    history_id = definition.reference_history_id
    if not history_id:
        return None
    try:
        item = histories.get(history_id)
    except (FileNotFoundError, ValueError):
        return {"history_id": history_id, "missing": True}
    payload = {"history_id": item.history_id, "name": item.name, "points": len(item.values),
               "first": item.values[0], "latest": item.values[-1], "variable": item.variable,
               "unit": item.unit, "cadence": item.cadence,
               "source": item.source, "evidence_grade": item.evidence_grade,
               "assumption_label": item.assumption_label, "values": item.values,
               "peak": definition.reference_peak}
    try:
        scale, scaled = scale_to_peak(item.values, definition.reference_peak)
    except ValueError:
        return payload
    payload.update({"scale": scale, "scaled_values": scaled})
    return payload


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
        "product_history": _history_summary(definition.product_history_id),
        "reference_history": _reference_summary(definition),
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

@router.post("/forecast/time-series")
def forecast_time_series(request: TimeSeriesForecastRequest):
    """Project a pasted history forward with the same deterministic fit the run forecast uses.

    No simulation, agents or world state are involved: this is a straight line through the
    numbers you supply, reported with its residual error so the fit stays checkable.
    """
    fit = fit_trend(request.values, request.periods_ahead)
    negative_at = next((index for index, value in enumerate(fit.projected, start=1) if value < 0), None)
    return {"method": "linear_least_squares", "label": request.label,
            "periods": fit.periods, "observed": request.values, "fitted": fit.fitted,
            # Reported per period so the panel can show which observations the line actually missed,
            # rather than only the RMSE that averages them away.
            "residuals": fit.residuals,
            "projected": fit.projected, "start": fit.start, "latest": fit.latest,
            "slope": fit.slope, "intercept": fit.intercept, "mean_change": fit.mean_change,
            "total_change": fit.total_change, "rmse": fit.rmse,
            "projection_below_zero_at": negative_at}


@router.post("/forecast/reference-analogue")
def forecast_reference_analogue(request: ReferenceAnalogueRequest):
    """Stretch a stored product's recorded ramp onto a peak you enter, then project that shape.

    The standalone twin of the reference-product run forecast: the same single multiplier and
    the same least-squares line, but with no world state, so nothing here is compared against a
    simulation. The recorded shape is borrowed evidence; the peak is the user's assumption.
    """
    try:
        item = histories.get(request.history_id)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if not math.isfinite(request.peak):
        raise HTTPException(422, "The peak must be a finite number.")
    try:
        scale, scaled = scale_to_peak(item.values, request.peak)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    fit = fit_trend(scaled, request.periods_ahead)
    below = next((index for index, value in enumerate(fit.projected, start=1) if value < 0), None)
    above = next((index for index, value in enumerate(fit.projected, start=1)
                  if value > float(request.peak)), None)
    return {"method": "reference_shape_scaled_to_peak", "label": item.name,
            "history_id": item.history_id, "source": item.source,
            "unit": item.unit, "cadence": item.cadence,
            "evidence_grade": item.evidence_grade, "assumption_label": item.assumption_label,
            "recorded": item.values, "recorded_peak": max(item.values),
            "peak_target": float(request.peak), "scale": scale, "periods": fit.periods,
            "observed": scaled, "fitted": fit.fitted, "projected": fit.projected,
            "start": fit.start, "latest": fit.latest, "slope": fit.slope,
            "intercept": fit.intercept, "mean_change": fit.mean_change,
            "total_change": fit.total_change, "rmse": fit.rmse,
            "projection_below_zero_at": below, "projection_above_entered_peak_at": above}


def _is_finite(value) -> bool:
    """True only for a real number the forecast can do arithmetic on; text, None and infinities cannot be projected."""
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _implied_growth(start: float, latest: float, periods: int) -> float | None:
    """The compound rate per period that the observed index readings themselves imply.

    Reported so an index continued by a fitted straight line can be compared with one declared as a
    growth rate. A series that starts or ends at or below zero has no real compound rate, so None is
    returned rather than a fabricated number.
    """
    if periods < 2 or start <= 0 or latest <= 0:
        return None
    return (latest / start) ** (1.0 / (periods - 1)) - 1.0


@router.post("/forecast/driver-scenario")
def forecast_driver_scenario(request: DriverScenarioRequest):
    """Project several exogenous drivers into the horizon and apply each one's pathway.

    Each driver's index is continued the way its own basis says: a least-squares continuation of its
    recorded readings, or geometric growth from the index anchored at t0. Every pathway then fires in
    each projected period, drivers in listed order, through the same ``scale_value`` scaling and
    ``StateTransitionSystem`` bounds that ``DriverProjectionForecast`` applies past a run's horizon —
    so a one-driver scenario reproduces that run model, and several drivers stack the way the engine
    stacks them. Each affected variable can also carry a growth rate of its own — organic drift that
    happens whether or not a driver acts on it — and the answer reports the organic path separately so
    the driver contribution stays visible. No stakeholder decides anything here: only the external
    environment and the declared drift move.
    """
    names = [driver.name.strip() for driver in request.drivers]
    if any(not name for name in names):
        raise HTTPException(422, "Every driver needs a name; the period table attributes effects by it.")
    if len({name.lower() for name in names}) != len(names):
        raise HTTPException(422, "Driver names must be unique, or the result cannot say which driver moved a variable.")

    baselines: dict[str, float] = {}
    growth: dict[str, float] = {}
    for item in request.variables:
        variable = item.name.strip()
        if not variable:
            raise HTTPException(422, "Every affected variable needs a name.")
        if variable in baselines:
            raise HTTPException(422, f"Variable “{variable}” is listed twice, each time with a baseline value.")
        if not _is_finite(item.value):
            raise HTTPException(422, f"Variable “{variable}” needs a finite value at t0.")
        if item.growth_rate is not None:
            if not _is_finite(item.growth_rate):
                raise HTTPException(422, f"Variable “{variable}”: its growth rate per period must be a finite number.")
            if item.growth_rate <= -1:
                raise HTTPException(422, f"Variable “{variable}”: a growth rate of -100% or below annihilates it in "
                                         "one period. Enter a smaller decline, or set the value at t0 to zero.")
            growth[variable] = float(item.growth_rate)
        else:
            growth[variable] = 0.0
        baselines[variable] = float(item.value)

    targets: set[str] = set()
    for driver, name in zip(request.drivers, names):
        pathway = driver.pathway
        target = pathway.target_variable.strip()
        if not target:
            raise HTTPException(422, f"Driver “{name}” has no target variable; a pathway must name the quantity it moves.")
        if target not in baselines:
            raise HTTPException(422, f"Driver “{name}” targets “{target}”, which has no baseline value. "
                                     "Add it under affected variables, or point the pathway at one already listed.")
        targets.add(target)
        if pathway.qualitative_only:
            # No number is applied, so the effect fields carry no obligation — the same exemption
            # a hypothesis-only pathway has when a definition is validated for a run.
            continue
        if not _is_finite(pathway.value):
            raise HTTPException(422, f"Driver “{name}”: a pathway value written as a formula is not projected here. "
                                     "Enter the number the run would compute.")
        if pathway.operation == "divide" and float(pathway.value) == 0:
            raise HTTPException(422, f"Driver “{name}”: a divide pathway cannot have a magnitude of zero.")
        if pathway.minimum is not None and pathway.maximum is not None and pathway.minimum > pathway.maximum:
            raise HTTPException(422, f"Driver “{name}”: the pathway floor cannot be above its ceiling.")
        if driver.basis == "observed":
            if len(driver.levels) < 2:
                raise HTTPException(422, f"Driver “{name}” is continued from its own index readings: enter at "
                                         "least two, oldest first, or switch its basis to compound growth.")
            if not all(_is_finite(level) for level in driver.levels):
                raise HTTPException(422, f"Driver “{name}”: every index reading must be a finite number.")
        else:
            if not _is_finite(driver.initial_level):
                raise HTTPException(422, f"Driver “{name}” is grown from an index anchored at t0: enter that index.")
            if not _is_finite(driver.growth_rate):
                raise HTTPException(422, f"Driver “{name}”: a compound basis needs a growth rate per period.")
            if driver.growth_rate <= -1:
                raise HTTPException(422, f"Driver “{name}”: a growth rate of -100% or below annihilates the index "
                                         "in one period, so no pathway fires after it. Lower the index instead.")

    # A variable nobody acts on still moves if it was given its own growth rate; only a flat,
    # untargeted line is a row that cannot do anything.
    unclaimed = [variable for variable in baselines
                 if variable not in targets and growth[variable] == 0.0]
    if unclaimed:
        raise HTTPException(422, f"Variable “{unclaimed[0]}” holds a baseline no pathway acts on and no growth "
                                 "rate of its own, so it cannot move. Remove it, give it a growth rate, or add "
                                 "a driver whose pathway targets it.")

    horizon = request.periods_ahead
    transition = StateTransitionSystem()
    entries: list[dict] = []
    for driver, name in zip(request.drivers, names):
        pathway = driver.pathway
        if driver.basis == "observed":
            readings = [float(level) for level in driver.levels]
            fit = fit_trend(readings, horizon)
            index = {"levels_observed": readings, "levels_fitted": fit.fitted, "index_at_t0": fit.latest,
                     "levels_projected": fit.projected, "level_slope": fit.slope,
                     "level_intercept": fit.intercept, "level_rmse": fit.rmse,
                     "growth_rate": None,
                     "implied_growth_rate": _implied_growth(fit.start, fit.latest, fit.periods)}
        else:
            base, rate = float(driver.initial_level), float(driver.growth_rate)
            index = {"levels_observed": [], "levels_fitted": [], "index_at_t0": base,
                     "levels_projected": [base * (1.0 + rate) ** step for step in range(1, horizon + 1)],
                     "level_slope": None, "level_intercept": None, "level_rmse": None,
                     "growth_rate": rate, "implied_growth_rate": None}
        entries.append({"name": name, "index_basis": driver.basis,
                        "target_variable": pathway.target_variable.strip(),
                        "pathway": pathway, "qualitative_only": pathway.qualitative_only,
                        "applied_values": [None] * horizon, "contributions": [0.0] * horizon,
                        "bounded_steps": [], **index})

    carried = dict(baselines)
    organic = dict(baselines)
    units = {item.name.strip(): item.unit.strip() for item in request.variables}
    series = {variable: [carried[variable]] for variable in baselines}
    organic_series = {variable: [organic[variable]] for variable in baselines}
    for step in range(horizon):
        # Organic drift lands first, then the drivers act on the grown value: a pathway's floor or
        # ceiling has to bind on the level the variable actually holds in that period.
        for variable, rate in growth.items():
            if rate:
                organic[variable] = organic[variable] * (1.0 + rate)
                carried[variable] = carried[variable] * (1.0 + rate)
        for entry in entries:
            if entry["qualitative_only"]:
                continue
            pathway = entry["pathway"]
            target = entry["target_variable"]
            value = scale_value(pathway.operation, pathway.value, float(entry["levels_projected"][step]))
            before = carried[target]
            bounded = WorldState(variables={target: before})
            transition.apply_effect(bounded, ActionEffect(variable=target, operation=pathway.operation,
                                                          value=value, minimum=pathway.minimum,
                                                          maximum=pathway.maximum))
            unbounded = WorldState(variables={target: before})
            transition.apply_effect(unbounded, ActionEffect(variable=target, operation=pathway.operation,
                                                           value=value))
            after = float(bounded.get(target))
            entry["applied_values"][step] = float(value)
            entry["contributions"][step] = after - before
            if after != float(unbounded.get(target)):
                entry["bounded_steps"].append(step + 1)
            carried[target] = after
        for variable in baselines:
            series[variable].append(carried[variable])
            organic_series[variable].append(organic[variable])

    drivers_out = [{key: value for key, value in entry.items() if key != "pathway"} | {
        "pathway": {"operation": entry["pathway"].operation, "magnitude": float(entry["pathway"].value),
                    "minimum": entry["pathway"].minimum, "maximum": entry["pathway"].maximum,
                    "evidence_grade": entry["pathway"].evidence_grade,
                    "basis": entry["pathway"].basis, "uncertainty": entry["pathway"].uncertainty,
                    "lag": entry["pathway"].lag}} for entry in entries]

    variables_out = []
    for variable, baseline in baselines.items():
        path = series[variable]
        projected = path[1:]
        variables_out.append({
            "name": variable, "baseline": baseline, "unit": units.get(variable, ""),
            "growth_rate": growth[variable],
            "series": path, "organic_series": organic_series[variable], "projected": projected,
            "change_from_baseline": [value - baseline for value in projected],
            "organic_change": [value - baseline for value in organic_series[variable][1:]],
            "driver_effect": [value - organic_series[variable][index + 1]
                              for index, value in enumerate(projected)],
            "drivers": [entry["name"] for entry in entries if entry["target_variable"] == variable],
            "bounded_steps": sorted({step for entry in entries if entry["target_variable"] == variable
                                      for step in entry["bounded_steps"]}),
            "below_zero_at": next((index for index, value in enumerate(projected, start=1) if value < 0), None)})

    return {"method": "driver_scenario_pathway_projection", "periods_ahead": horizon,
            "application_order": [entry["name"] for entry in entries], "drivers": drivers_out,
            "variables": variables_out,
            "hypotheses": [entry["name"] for entry in entries if entry["qualitative_only"]],
            "shared_targets": [{"variable": item["name"], "drivers": item["drivers"]}
                               for item in variables_out if len(item["drivers"]) > 1]}


@router.post("/forecast/import-table")
def import_table(request: TableImportRequest):
    """Preview the numeric columns of an uploaded CSV or Excel file.

    Nothing is stored here: the caller picks one column from the preview and that column is
    then projected or saved as a product history through the existing, already validated paths.
    """
    try:
        return import_series(request.file_name, decode_upload(request.data), request.sheet)
    except TableImportError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error


@router.get("/forecast/models")
def forecast_models():
    """Every forecast model the engine can actually run, in the order the UI offers them.

    The backend owns this list: a model cannot appear in the dropdown without being
    registered, so an option here is always runnable.
    """
    return [info._asdict() for info in default_registry().catalog()]


@router.post("/simulations/suggest-reference")
def suggest_reference(request: ReferenceSuggestionRequest):
    """Rank stored product histories as reference analogues for a described new product.

    The provider sees the profile and the catalog only; it cannot pick a series that is
    not stored. Nothing is applied to a definition — the shortlist is returned for the
    user to choose from, so the reference stays their decision.
    """
    catalog = histories.list()
    if not catalog:
        raise HTTPException(400, "There are no stored product histories to suggest a reference from. "
                                 "Import a CSV or Excel file in the home page forecaster first.")
    client = runner.llm_client
    try:
        if client is None:
            client = OpenAICompatibleLLMClient.from_environment()
        suggestion = suggest(request.profile, catalog, client)
    except LLMConfigurationError as error:
        raise HTTPException(400, str(error)) from error
    except LLMClientError as error:
        raise HTTPException(502, f"The model could not be reached ({error}).") from error
    except ReferenceSuggestionError as error:
        raise HTTPException(422, str(error)) from error
    return {"candidates": [item.model_dump(mode="json") for item in suggestion.candidates],
            "rejected": suggestion.rejected, "histories_offered": suggestion.histories_offered,
            "provider_call": suggestion.provider_call}


@router.get("/histories")
def list_histories():
    return [{"history_id": item.history_id, "name": item.name, "description": item.description,
             "points": len(item.values), "first": item.values[0], "latest": item.values[-1],
             "peak": max(item.values),
             "variable": item.variable, "unit": item.unit, "cadence": item.cadence,
             "source": item.source, "evidence_grade": item.evidence_grade,
             "referenced_by": builder.referencing_history(item.history_id)}
            for item in histories.list()]


@router.post("/histories", status_code=201)
def create_history(history: ProductHistory):
    try:
        histories.create(history)
    except HistoryValidationError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error
    except FileExistsError as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"history_id": history.history_id, "name": history.name,
            "points": len(history.values), "status": "created"}


@router.get("/histories/{history_id}")
def get_history(history_id: str):
    _history_or_404(history_id)
    return histories.get(history_id)


@router.put("/histories/{history_id}")
def update_history(history_id: str, history: ProductHistory):
    try:
        histories.update(history_id, history)
    except HistoryValidationError as error:
        raise HTTPException(422, detail={"errors": error.errors}) from error
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"history_id": history_id, "status": "updated"}


@router.delete("/histories/{history_id}", status_code=204)
def delete_history(history_id: str):
    _history_or_404(history_id)
    # A stored series can be the input to a saved simulation's forecast; deleting it
    # from under those files would leave them unrunnable with no explanation.
    referenced = builder.referencing_history(history_id)
    if referenced:
        raise HTTPException(409, f"Product history is used by saved simulations: "
                                 f"{', '.join(referenced)}. Discard them or select another history first.")
    histories.delete(history_id)
    return Response(status_code=204)


def _history_or_404(history_id: str):
    try:
        return histories.get(history_id)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/simulations/complete-gaps")
def complete_gaps(definition: SimulationDefinition):
    """Fill blank or unusable values with LLM-supplied, explicitly labeled assumptions.

    Nothing is stored: the caller receives the completed definition and the list of
    what the model supplied, so every added value stays visible and editable.
    """
    gaps = find_gaps(definition)
    if not gaps:
        return {"definition": definition.model_dump(mode="json"), "gaps": [], "filled": [],
                "rejected": [], "provider_call": None}
    client = runner.llm_client
    try:
        if client is None:
            client = OpenAICompatibleLLMClient.from_environment()
        fill = fill_assumptions(definition, client)
    except LLMConfigurationError as error:
        raise HTTPException(400, str(error)) from error
    except LLMClientError as error:
        raise HTTPException(502, f"The model could not be reached ({error}).") from error
    except AssumptionFillError as error:
        raise HTTPException(422, str(error)) from error
    _validate_or_422(fill.definition)
    return {"definition": fill.definition.model_dump(mode="json"),
            "gaps": [gap.model_dump(mode="json") for gap in fill.gaps_found],
            "filled": [item.model_dump(mode="json") for item in fill.filled],
            "rejected": [item.model_dump(mode="json") for item in fill.rejected],
            "provider_call": fill.provider_call}

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
