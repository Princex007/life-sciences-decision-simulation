"""Hand-derived fixtures for driver-based and historical forecasting, plus the store behind them.

Every expected number below is computed by hand from the configured arithmetic, so a
change in the fitting or pathway semantics fails loudly instead of tracking itself.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.domain.definitions import SimulationDefinition, SimulationMetadata
from app.domain.driver import DriverPathway, DriverTrajectoryPoint, DriverVariant, ExternalDriver
from app.domain.history import ProductHistory
from app.domain.world import WorldState
from app.forecasting.context import ForecastContext
from app.forecasting.driver_projection import DriverProjectionForecast
from app.forecasting.product_history import ProductHistoryForecast
from app.forecasting.registry import default_registry
from app.forecasting.trend import fit_trend
from app.services.history_store import HistoryValidationError, ProductHistoryStore
from app.services.simulation_builder import DefinitionValidationError, SimulationBuilderService
from app.services.simulation_runner import SimulationRunnerService
from app.main import app

PROJECT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT / "examples"


def series(values, times=None):
    return fit_trend(values, times=times)


# ---------------------------------------------------------------- shared fitting

def test_fit_uses_real_period_times_when_supplied():
    # Two readings at t0 and t2: 1.0 and 2.0 -> slope 0.5 per period, intercept 1.0.
    fit = fit_trend([1.0, 2.0], times=[0.0, 2.0], projection_times=[3.0, 4.0])
    assert fit.slope == pytest.approx(0.5)
    assert fit.intercept == pytest.approx(1.0)
    assert fit.projected == pytest.approx([2.5, 3.0])


def test_fit_projection_starts_after_the_horizon_not_after_the_last_reading():
    # A trajectory that stops at t2 still projects from t9, so the horizon gap is honoured.
    fit = fit_trend([10, 20], times=[0.0, 2.0], projection_times=[9.0, 10.0])
    # slope 5 per period, intercept 10 -> t9 = 55, t10 = 60
    assert fit.projected == pytest.approx([55.0, 60.0])


def test_fit_rejects_mismatched_times_and_backwards_clock():
    with pytest.raises(ValueError):
        fit_trend([1, 2, 3], times=[0.0, 1.0])
    with pytest.raises(ValueError):
        fit_trend([1, 2, 3], times=[2.0, 1.0, 0.0])


def test_single_reading_projects_flat():
    fit = fit_trend([7.0], projection_times=[1.0, 2.0])
    assert fit.slope == 0.0
    assert fit.projected == [7.0, 7.0]


# ---------------------------------------------------------------- driver-based

def definition_with(driver):
    return SimulationDefinition(
        metadata=SimulationMetadata(id="driver-fixture", name="Driver fixture"),
        initial_world_state=WorldState(time=0, variables={"price": 100, "label": "basic"}),
        agents=[], external_drivers=[driver])


def driven(level_points, pathways, indicator=None, indicator_values=None, initial=None):
    readings = indicator_values or []
    points = [DriverTrajectoryPoint(time=time, level=level,
                indicator_value=(readings[index] if indicator and index < len(readings) else None))
                for index, (time, level) in enumerate(level_points)]
    return definition_with(ExternalDriver(
        driver_id="policy", name="Policy shock", category="regulatory",
        active_variant="central", indicator_variable=indicator,
        variants=[DriverVariant(variant_id="central", label="Central", trajectory=points)],
        pathways=pathways,
        initial_value=(initial if initial is not None else 0.0))), points


def context_for(definition):
    return ForecastContext(definition=definition)


def forecast(state, definition):
    return DriverProjectionForecast().forecast(state, [state], None, context_for(definition))


def test_driver_level_is_fitted_on_its_own_times_and_projected_past_the_horizon():
    definition, _ = driven([(0.0, 1.0), (2.0, 2.0)], [])
    outcome = forecast(WorldState(time=2, variables={"price": 100}), definition)
    # level: slope 0.5, latest 2.0, projected at t3..t6 -> 2.5, 3.0, 3.5, 4.0
    assert outcome.metrics["policy_level"] == pytest.approx(2.0)
    assert outcome.metrics["policy_level_trend_per_period"] == pytest.approx(0.5)
    assert outcome.metrics["policy_level_projected"] == pytest.approx(4.0)


def test_pathway_effects_compound_on_the_simulated_endpoint():
    definition, _ = driven([(0.0, 1.0), (2.0, 2.0)],
                           [DriverPathway(target_variable="price", operation="add", value=5)])
    outcome = forecast(WorldState(time=2, variables={"price": 100}), definition)
    # scaled add = 5 * level -> 12.5, 15, 17.5, 20 applied in sequence onto 100
    assert outcome.projections["price"] == pytest.approx([112.5, 127.5, 145.0, 165.0])
    assert outcome.metrics["price_projected"] == pytest.approx(165.0)
    assert outcome.metrics["price_driver_delta"] == pytest.approx(65.0)
    assert outcome.metrics["drivers_projected"] == 1
    assert outcome.metrics["driver_pathways_not_projected"] == 0


def test_indicator_trajectory_is_projected_as_its_own_series():
    definition, _ = driven([(0.0, 1.0), (2.0, 2.0)], [], indicator="policy_index",
                           indicator_values=[10.0, 20.0])
    outcome = forecast(WorldState(time=2, variables={"price": 100, "policy_index": 20}), definition)
    # indicators 10 at t0, 20 at t2 -> slope 5 -> t3..t6 = 25, 30, 35, 40
    assert outcome.projections["policy_index"] == pytest.approx([25.0, 30.0, 35.0, 40.0])
    assert outcome.metrics["policy_index_projected"] == pytest.approx(40.0)
    assert outcome.metrics["policy_index_trend_per_period"] == pytest.approx(5.0)


def test_configured_bounds_still_clamp_projected_effects():
    definition, _ = driven([(0.0, 1.0), (2.0, 2.0)],
        [DriverPathway(target_variable="price", operation="subtract", value=40, minimum=90.0)])
    outcome = forecast(WorldState(time=2, variables={"price": 100}), definition)
    # subtract 40 * level: t3 -> 40 applied to 100 gives 60, clamped up to the 90 minimum
    assert outcome.projections["price"] == pytest.approx([90.0, 90.0, 90.0, 90.0])


def test_qualitative_only_and_non_numeric_targets_are_counted_not_silently_dropped():
    definition, _ = driven([(0.0, 1.0), (2.0, 2.0)], [
        DriverPathway(target_variable="price", operation="add", value=5),
        DriverPathway(target_variable="label", operation="add", value=5),
        DriverPathway(target_variable="price", operation="add", value=1, qualitative_only=True)])
    outcome = forecast(WorldState(time=2, variables={"price": 100, "label": "basic"}), definition)
    # 'label' holds text, so only the price pathway can be carried forward.
    assert "label_projected" not in outcome.metrics
    assert outcome.metrics["driver_pathways_not_projected"] == 1


def test_disabled_drivers_project_nothing():
    definition, _ = driven([(0.0, 1.0), (2.0, 2.0)],
                           [DriverPathway(target_variable="price", operation="add", value=5)])
    definition.external_drivers[0].enabled = False
    outcome = forecast(WorldState(time=2, variables={"price": 100}), definition)
    assert outcome.projections == {}
    assert outcome.metrics["drivers_projected"] == 0


def test_driver_projection_refuses_to_run_without_the_definition():
    with pytest.raises(ValueError, match="external drivers"):
        DriverProjectionForecast().forecast(WorldState(time=2, variables={"price": 100}), [], None)


def test_driver_projection_on_the_bundled_ai_example_moves_the_configured_variables():
    definition = SimulationDefinition.from_json(str(EXAMPLES / "ai_drug_discovery.json"))
    result = SimulationRunnerService().run(
        definition.model_copy(update={"forecast_model_id": "driver_projection"}))[0]
    forecast_outcome = result.scenarios[0].forecast
    assert set(["ai_discovery_level", "ai_discovery_level_projected",
                "discovery_candidates_projected", "rd_cycle_time_years_projected"]
               ) <= set(forecast_outcome.metrics)
    for variable, values in forecast_outcome.projections.items():
        if variable == "ai_discovery_adoption_index":
            continue
        start = result.scenarios[0].final_state.get(variable)
        assert values[0] != start or forecast_outcome.metrics[f"{variable}_driver_delta"] == 0
        assert forecast_outcome.metrics[f"{variable}_projected"] == pytest.approx(values[-1])


# ---------------------------------------------------------------- historical

def history(**overrides):
    data = {"history_id": "q-series", "name": "Quarterly units", "source": "sales ledger",
            "values": [10.0, 20.0, 30.0]}
    data.update(overrides)
    return ProductHistory.model_validate(data)


def product_forecast(state, stored, periods=4):
    definition = SimulationDefinition(
        metadata=SimulationMetadata(id="history-fixture", name="History fixture"),
        initial_world_state=state, agents=[], product_history_id=stored.history_id)
    context = ForecastContext(definition=definition, history=stored,
                              projection_periods=periods)
    return ProductHistoryForecast().forecast(state, [state], None, context)


def test_stored_history_is_fitted_and_projected_from_the_horizon():
    state = WorldState(time=4, variables={"price": 100})
    outcome = product_forecast(state, history(variable=""))
    # 10, 20, 30 at t0..t2 -> slope 10, intercept 10 -> t5..t8 = 60, 70, 80, 90
    assert outcome.metrics["history_points"] == 3
    assert outcome.metrics["history_latest"] == pytest.approx(30.0)
    assert outcome.metrics["history_rmse"] == pytest.approx(0.0)
    assert outcome.projections["Quarterly units"] == pytest.approx([60.0, 70.0, 80.0, 90.0])
    assert outcome.metrics["Quarterly units_projected"] == pytest.approx(90.0)


def test_history_named_after_a_world_variable_reports_the_gap_without_borrowing_its_name():
    state = WorldState(time=4, variables={"price": 100.0})
    outcome = product_forecast(state, history(variable="price"))
    # The projection is the recorded history's continuation, so it keeps the history's own
    # name; keying it by 'price' would draw it onto the simulated path as if both were one.
    assert outcome.projections["Quarterly units"] == pytest.approx([60.0, 70.0, 80.0, 90.0])
    assert "price" not in outcome.projections
    assert outcome.metrics["price_simulated"] == pytest.approx(100.0)
    # The recorded trend reaches 90 while the run ended at 100.
    assert outcome.metrics["price_history_gap"] == pytest.approx(-10.0)


def test_historical_forecast_refuses_to_invent_a_series_when_none_is_stored():
    state = WorldState(time=4, variables={"price": 100})
    definition = SimulationDefinition(
        metadata=SimulationMetadata(id="x", name="x"), initial_world_state=state, agents=[])
    with pytest.raises(ValueError, match="stored product history"):
        ProductHistoryForecast().forecast(state, [state], None,
                                         ForecastContext(definition=definition))


# ---------------------------------------------------------------- store

def test_store_round_trips_one_file_per_history(tmp_path):
    store = ProductHistoryStore(tmp_path)
    store.create(history())
    assert store.get("q-series").values == [10.0, 20.0, 30.0]
    assert (tmp_path / "q-series.json").is_file()
    updated = store.update("q-series", history(name="Renamed", values=[1.0, 2.0, 3.0]))
    assert updated.name == "Renamed"
    assert [item.history_id for item in store.list()] == ["q-series"]
    store.delete("q-series")
    assert store.list() == []


def test_store_rejects_duplicate_missing_and_unsafe_ids(tmp_path):
    store = ProductHistoryStore(tmp_path)
    store.create(history())
    with pytest.raises(FileExistsError):
        store.create(history())
    with pytest.raises(FileNotFoundError):
        store.get("absent")
    with pytest.raises(ValueError):
        store.create(history(history_id="../escape"))


def test_store_rejects_non_finite_values(tmp_path):
    store = ProductHistoryStore(tmp_path)
    with pytest.raises(HistoryValidationError):
        store.create(history(values=[1.0, float("inf"), 3.0]))
    with pytest.raises(HistoryValidationError):
        store.create(history(values=[1.0, float("nan"), 3.0]))


# ---------------------------------------------------------------- builder rules

def definition_for_builder():
    return SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))


def test_builder_rejects_a_forecast_model_whose_input_is_missing(tmp_path):
    service = SimulationBuilderService(tmp_path, EXAMPLES, history_store=ProductHistoryStore(tmp_path))
    definition = definition_for_builder()
    definition.forecast_model_id = "product_history"
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(definition)
    assert any("stored product history" in item for item in error.value.errors)

    definition.product_history_id = "not-stored"
    with pytest.raises(DefinitionValidationError) as dangling:
        service.validate(definition)
    assert any("not stored" in item for item in dangling.value.errors)

    service.history_store.create(history())
    definition.product_history_id = "q-series"
    assert service.validate(definition) == []


def test_builder_rejects_driver_forecast_without_quantitative_drivers(tmp_path):
    service = SimulationBuilderService(tmp_path, EXAMPLES, history_store=ProductHistoryStore(tmp_path))
    definition = definition_for_builder()
    definition.forecast_model_id = "driver_projection"
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(definition)
    assert any("enabled external driver" in item for item in error.value.errors)

    definition, _ = driven([(0.0, 1.0)], [DriverPathway(target_variable="price", operation="add", value=1)])
    definition.metadata = definition_for_builder().metadata
    definition.forecast_model_id = "driver_projection"
    assert service.validate(definition) == []


# ---------------------------------------------------------------- HTTP surface

@pytest.fixture
def client(tmp_path, monkeypatch):
    store = ProductHistoryStore(tmp_path / "histories")
    store.create(history())
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(api.routes, "histories", store)
    monkeypatch.setattr(api.routes, "builder",
        SimulationBuilderService(tmp_path / "simulations", EXAMPLES, history_store=store))
    monkeypatch.setattr(api.routes, "runner", SimulationRunnerService(history_store=store))
    api.routes._results.clear()
    with TestClient(app) as test_client:
        yield test_client
    api.routes._results.clear()


def test_forecast_model_catalog_is_ordered_agent_then_driver_then_history(client):
    models = client.get("/forecast/models").json()
    assert [item["model_id"] for item in models] == [
        "state_metrics", "launch_revenue", "driver_projection", "product_history",
        "reference_product", "trend_projection"]
    assert [item["group"] for item in models] == [
        "Agent-based simulation", "Agent-based simulation", "Driver-based",
        "Historical / product-based", "Historical / product-based", "Historical / product-based"]
    assert {item["model_id"] for item in models} == default_registry().model_ids


def test_history_crud_and_referential_protection(client):
    created = client.post("/histories", json={"history_id": "ledger-2026", "name": "Ledger 2026",
        "values": [1, 2, 3, 4]}).json()
    assert created["status"] == "created"
    assert client.get("/histories/ledger-2026").json()["name"] == "Ledger 2026"
    listed = client.get("/histories").json()
    entry = next(item for item in listed if item["history_id"] == "ledger-2026")
    assert entry["points"] == 4 and entry["latest"] == 4

    definition = definition_for_builder().model_copy(deep=True)
    definition.metadata.id = "history-user"
    definition.forecast_model_id = "product_history"
    definition.product_history_id = "ledger-2026"
    assert client.post("/simulations", json=definition.model_dump(mode="json")).status_code == 201

    blocked = client.delete("/histories/ledger-2026")
    assert blocked.status_code == 409
    assert "history-user" in blocked.json()["detail"]

    assert client.delete("/simulations/history-user").status_code == 204
    assert client.delete("/histories/ledger-2026").status_code == 204
    assert client.get("/histories/ledger-2026").status_code == 404


def test_history_validation_and_update_errors_are_actionable(client):
    assert client.post("/histories", json={"history_id": "short", "name": "x", "values": [1]}
                       ).status_code == 422
    assert client.post("/histories", json={"history_id": "bad id!", "name": "x", "values": [1, 2]}
                       ).status_code == 422
    assert client.put("/histories/q-series", json={"history_id": "other", "name": "x",
                       "values": [1, 2]}).status_code == 422
    assert client.put("/histories/absent", json={"history_id": "absent", "name": "x",
                       "values": [1, 2]}).status_code == 404
    updated = client.put("/histories/q-series", json={"history_id": "q-series", "name": "Renamed",
                         "values": [5, 6, 7]}).json()
    assert updated["status"] == "updated"


def test_run_with_historical_model_reports_the_stored_series_it_used(client):
    stored = client.get("/histories/q-series").json()
    definition = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    definition.metadata.id = "history-run"
    definition.forecast_model_id = "product_history"
    definition.product_history_id = stored["history_id"]
    assert client.post("/simulations", json=definition.model_dump(mode="json")).status_code == 201
    assert client.post("/simulations/history-run/run").status_code == 200
    payload = client.get("/simulations/history-run/results").json()
    assert payload["summary"]["product_history"]["name"] == "Quarterly units"
    assert payload["summary"]["product_history"]["points"] == 3
    # The results panel draws the recorded series next to its projection, so the run result
    # has to carry the numbers it was fitted against, not just their endpoints.
    assert payload["summary"]["product_history"]["values"] == [10.0, 20.0, 30.0]
    scenario = payload["scenarios"][0]
    assert scenario["forecast"]["metrics"]["history_points"] == 3
    assert scenario["forecast"]["projections"]["Quarterly units"]


def test_run_with_driver_model_projects_configured_variables(client):
    definition = SimulationDefinition.from_json(str(EXAMPLES / "ai_drug_discovery.json"))
    definition.metadata.id = "driver-run"
    definition.forecast_model_id = "driver_projection"
    assert client.post("/simulations", json=definition.model_dump(mode="json")).status_code == 201
    assert client.post("/simulations/driver-run/run").status_code == 200
    scenario = client.get("/simulations/driver-run/results").json()["scenarios"][0]
    assert scenario["forecast"]["metrics"]["drivers_projected"] == 1
    assert "discovery_candidates_projected" in scenario["forecast"]["metrics"]
    assert scenario["forecast"]["projections"]["discovery_candidates"]


def test_missing_history_reference_fails_validation_before_the_run(client):
    definition = definition_for_builder().model_copy(deep=True)
    definition.metadata.id = "dangling"
    definition.forecast_model_id = "product_history"
    definition.product_history_id = "gone"
    assert client.post("/simulations", json=definition.model_dump(mode="json")).status_code == 422
