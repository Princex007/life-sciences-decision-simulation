"""Every forecast scenario is refused before it can produce an answer that means nothing.

Two layers are checked here. The unit layer calls the validators directly, one configuration
problem at a time, so each rule has a test that names it. The integration layer goes through the
builder service and the HTTP routes, because a rule that only holds when the whole definition is
assembled is not a rule the UI can rely on.
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from pydantic import ValidationError

from app import api
from app.domain.definitions import (ScheduledEventDefinition, SimulationDefinition,
                                    SimulationMetadata)
from app.domain.driver import (DriverPathway, DriverTrajectoryPoint, DriverVariant,
                               ExternalDriver)
from app.domain.history import ProductHistory
from app.domain.world import WorldState
from app.forecasting.registry import FORECAST_CATALOG, ForecastRegistry, default_registry
from app.main import app
from app.services.history_store import ProductHistoryStore
from app.services.simulation_builder import DefinitionValidationError, SimulationBuilderService
from app.services.simulation_runner import SimulationRunnerService
from app.simulation.external_drivers import validate_external_drivers

PROJECT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT / "examples"


def definition(**overrides):
    """The smallest definition the validators accept, so any reported error is the injected one."""
    base = SimulationDefinition(
        metadata=SimulationMetadata(id="validation-fixture", name="Validation fixture"),
        initial_world_state=WorldState(time=0, variables={"price": 100.0, "label": "basic"}),
        agents=[], external_drivers=[])
    return base.model_copy(update=overrides)


def trajectory(*times):
    return [DriverTrajectoryPoint(time=time, level=1.0 + index) for index, time in enumerate(times)]


def driver(**overrides):
    base = {"driver_id": "policy", "name": "Policy shock",
            "variants": [DriverVariant(variant_id="central", label="Central", trajectory=trajectory(0, 1))],
            "pathways": [DriverPathway(target_variable="price", operation="add", value=5.0)]}
    return ExternalDriver(**{**base, **overrides})


def errors_of(configured):
    return validate_external_drivers(definition(external_drivers=[configured]))


def stored(history_id="q-series", values=(10.0, 20.0, 30.0)):
    return ProductHistory(history_id=history_id, name=history_id.title(), values=list(values),
                          variable="", source="imported by hand", evidence_grade="user_assumption",
                          assumption_label="Typed in, not checked against any record.")


@pytest.fixture
def service(tmp_path):
    return SimulationBuilderService(tmp_path, EXAMPLES, history_store=ProductHistoryStore(tmp_path / "h"))


# ---------------------------------------------------------------- the control

def test_a_minimal_scenario_validates_clean(service):
    assert service.validate(definition()) == []


# ---------------------------------------------------------------- driver configuration rules

def test_a_driver_defined_twice_is_refused():
    errors = validate_external_drivers(definition(external_drivers=[driver(), driver()]))
    assert any("defined more than once" in item for item in errors)


def test_two_variants_sharing_an_id_are_refused():
    configured = driver(variants=[
        DriverVariant(variant_id="central", label="Central", trajectory=trajectory(0)),
        DriverVariant(variant_id="central", label="Also central", trajectory=trajectory(1))])
    assert any("duplicate variant IDs" in item for item in errors_of(configured))


def test_a_driver_with_no_trajectory_can_never_fire():
    configured = driver(variants=[], trajectory=[])
    assert any("configures no trajectory points" in item for item in errors_of(configured))


def test_a_reading_past_the_horizon_is_refused_rather_than_silently_never_applied():
    # The compiler drops points beyond the horizon instead of firing them, so validation is the
    # only place a user learns that the shock they configured never happens.
    configured = driver(variants=[DriverVariant(variant_id="central", label="Central",
                                                trajectory=trajectory(0, 1, 20))])
    assert any("beyond the configured horizon" in item for item in errors_of(configured))


def test_a_driver_that_becomes_observable_after_the_horizon_is_refused():
    configured = driver(indicator_variable="policy_index", observable_from=99)
    errors = validate_external_drivers(definition(external_drivers=[configured]))
    assert any("becomes observable at period 99" in item for item in errors)


def test_naming_observers_without_an_indicator_is_refused():
    # Agents cannot observe a driver that publishes no reading, so the list would be decoration.
    assert any("configures no indicator_variable" in item for item
               in errors_of(driver(observable_by=["someone"])))


def test_a_driver_cannot_declare_itself_as_its_own_interaction():
    assert any("cannot interact with itself" in item for item
               in errors_of(driver(interacts_with=["policy"])))


def test_a_lag_on_a_pathway_that_never_fires_is_refused():
    configured = driver(pathways=[DriverPathway(target_variable="price", operation="add", value=5.0,
                                                lag=2, qualitative_only=True)])
    assert any("on a qualitative-only hypothesis" in item for item in errors_of(configured))


def test_a_pathway_may_stay_qualitative_about_a_variable_it_never_moves():
    # Hypothesis-only pathways are reported, not applied, so they are allowed to name nothing.
    configured = driver(pathways=[DriverPathway(target_variable="absent", qualitative_only=True)])
    assert errors_of(configured) == []


# ---------------------------------------------------------------- domain bounds

def test_a_trajectory_point_cannot_be_placed_before_the_first_period():
    with pytest.raises(ValidationError):
        DriverTrajectoryPoint(time=-1, level=1.0)


def test_a_pathway_cannot_fire_before_its_period():
    with pytest.raises(ValidationError):
        DriverPathway(target_variable="price", lag=-1)


def test_a_driver_cannot_become_observable_in_the_past():
    with pytest.raises(ValidationError):
        ExternalDriver(driver_id="policy", name="Policy", observable_from=-1)


def test_the_active_variant_wins_and_later_readings_at_one_period_replace_earlier_ones():
    configured = driver(
        trajectory=trajectory(0, 5),
        variants=[DriverVariant(variant_id="central", label="Central",
                                trajectory=[DriverTrajectoryPoint(time=1, level=2.0),
                                            DriverTrajectoryPoint(time=1, level=9.0)])])
    assert [point.level for point in configured.resolve_trajectory()] == [9.0]


def test_a_driver_with_an_unknown_active_variant_is_refused():
    assert any("selects unknown variant" in item for item in errors_of(driver(active_variant="tail")))


# ---------------------------------------------------------------- what a model needs to say anything

def an_enabled_reference_scenario(store, peak=60.0):
    store.create(stored("rival-series"))
    return definition(forecast_model_id="reference_product", reference_history_id="rival-series",
                      reference_peak=peak)


@pytest.mark.parametrize("peak", [0, -5, float("inf"), float("nan"), "60", True, None])
def test_a_reference_peak_that_cannot_scale_a_shape_is_refused(service, peak):
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(an_enabled_reference_scenario(service.history_store, peak))
    assert any("positive peak" in item for item in error.value.errors)


def test_a_valid_reference_peak_is_accepted(service):
    assert service.validate(an_enabled_reference_scenario(service.history_store)) == []


def test_a_driver_model_with_only_disabled_drivers_is_refused(service):
    configured = definition(forecast_model_id="driver_projection",
                            external_drivers=[driver(enabled=False)])
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(configured)
    assert any("enabled external driver" in item for item in error.value.errors)


def test_a_driver_model_whose_only_pathways_are_hypotheses_is_refused(service):
    # Nothing numeric would be projected, so the run would report an empty forecast panel.
    configured = definition(forecast_model_id="driver_projection", external_drivers=[
        driver(pathways=[DriverPathway(target_variable="price", qualitative_only=True)])])
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(configured)
    assert any("qualitative-only pathways are never applied" in item for item in error.value.errors)


def test_a_driver_model_with_one_quantitative_pathway_is_accepted(service):
    assert service.validate(definition(forecast_model_id="driver_projection",
                                       external_drivers=[driver()])) == []


def test_a_series_reference_without_any_history_store_says_so(service):
    storeless = SimulationBuilderService(service.storage_dir, EXAMPLES)
    with pytest.raises(DefinitionValidationError) as error:
        storeless.validate(definition(product_history_id="q-series"))
    assert any("no history store is configured" in item for item in error.value.errors)


# ---------------------------------------------------------------- the rest of a definition

def test_a_horizon_of_no_periods_is_refused(service):
    configured = definition()
    configured.settings.time_horizon = 0
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(configured)
    assert any("time_horizon must be positive" in item for item in error.value.errors)


def test_a_scheduled_event_outside_the_horizon_is_refused(service):
    configured = definition()
    configured.settings.scheduled_events = [ScheduledEventDefinition(
        id="late", time=40, event_type="time_step")]
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(configured)
    assert any("outside the simulation horizon" in item for item in error.value.errors)


def test_duplicated_ids_are_refused_because_lookups_would_pick_one_arbitrarily(service):
    example = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    example.agents.append(example.agents[0].model_copy(deep=True))
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(example)
    assert any(item.startswith("Duplicate agent ID") for item in error.value.errors)


# ---------------------------------------------------------------- the catalog itself

def test_every_catalogued_requirement_is_one_the_builder_actually_checks():
    # A misspelled requirement would silently disable its own check, so the two lists are pinned.
    assert {info.requires for info in FORECAST_CATALOG} <= {
        "", "product_history", "reference_product", "external_drivers"}


def test_the_registry_reports_nothing_for_a_model_it_never_catalogued():
    registry = default_registry()
    assert registry.info("state_metrics").group == "Agent-based simulation"
    assert registry.info("invented_model") is None


def test_an_unregistered_model_id_cannot_be_resolved():
    with pytest.raises(ValueError, match="not registered"):
        ForecastRegistry().get("product_history")


# ---------------------------------------------------------------- HTTP integration

@pytest.fixture
def client(tmp_path, monkeypatch):
    store = ProductHistoryStore(tmp_path / "histories")
    store.create(stored("rival-series"))
    monkeypatch.setattr(api.routes, "histories", store)
    monkeypatch.setattr(api.routes, "builder",
        SimulationBuilderService(tmp_path / "simulations", EXAMPLES, history_store=store))
    monkeypatch.setattr(api.routes, "runner", SimulationRunnerService(history_store=store))
    api.routes._results.clear()
    with TestClient(app) as test_client:
        yield test_client
    api.routes._results.clear()


def posted(client, configured):
    configured.metadata = SimulationMetadata(id="posted", name="Posted")
    return client.post("/simulations", json=configured.model_dump(mode="json"))


def refused_by(response):
    """Definition errors arrive as a list under detail, not as one sentence."""
    return " ".join(response.json()["detail"]["errors"])


def test_the_api_refuses_a_forecast_model_whose_inputs_are_missing(client):
    refused = posted(client, definition(forecast_model_id="reference_product",
                                        reference_history_id="rival-series"))
    assert refused.status_code == 422
    assert "positive peak" in refused_by(refused)

    accepted = posted(client, definition(forecast_model_id="reference_product",
                                         reference_history_id="rival-series", reference_peak=60.0))
    assert accepted.status_code == 201


def test_the_api_refuses_a_driver_model_that_could_project_nothing(client):
    payload = definition(forecast_model_id="driver_projection",
                         external_drivers=[driver(enabled=False)]).model_dump(mode="json")
    response = client.post("/simulations", json=payload)
    assert response.status_code == 422
    assert "enabled external driver" in refused_by(response)


def test_a_run_refuses_a_stored_series_when_the_server_has_no_history_store():
    # The builder is not the only door: a definition loaded from disk can name a series the
    # process cannot resolve, and the run must say that instead of forecasting from nothing.
    runner = SimulationRunnerService(history_store=None)
    configured = definition(forecast_model_id="product_history", product_history_id="q-series")
    with pytest.raises(ValueError, match="no history store is configured"):
        runner.run(configured)
