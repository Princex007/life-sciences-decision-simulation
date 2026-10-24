"""Reference-based forecasting: another product's recorded ramp, rescaled to a typed peak.

Every expected number here is derived by hand from the scaling and the least-squares fit,
so a change in either has to be deliberate rather than tracked by a recomputed fixture.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.agents.llm import LLMCompletion
from app.agents.reference_suggestion import (
    ReferenceSuggestionError, history_digest, suggest_reference)
from app.domain.definitions import SimulationDefinition, SimulationMetadata
from app.domain.history import ProductHistory
from app.domain.world import WorldState
from app.forecasting.context import ForecastContext
from app.forecasting.reference_product import ReferenceProductForecast, scale_to_peak
from app.services.history_store import ProductHistoryStore
from app.services.simulation_builder import DefinitionValidationError, SimulationBuilderService
from app.services.simulation_runner import SimulationRunnerService
from app.main import app

PROJECT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT / "examples"

# [10, 20, 30] scaled to a peak of 60 is a 2.0x match: [20, 40, 60].
# Fitted at t0..t2 that is y = 20 + 20x, so from a horizon of t4 the four projected
# periods are t5..t8 = 120, 140, 160, 180.


def reference_history(**overrides):
    data = {"history_id": "rival-series", "name": "Rival quarterly units",
            "description": "A different product's recorded ramp", "source": "published filings",
            "values": [10.0, 20.0, 30.0], "variable": "units", "evidence_grade": "empirical"}
    data.update(overrides)
    return ProductHistory.model_validate(data)


def forecast(state, stored, peak, periods=4, definition=None):
    definition = definition or SimulationDefinition(
        metadata=SimulationMetadata(id="reference-fixture", name="Reference fixture"),
        initial_world_state=state, agents=[], reference_history_id=stored.history_id,
        reference_peak=peak)
    context = ForecastContext(definition=definition, reference_history=stored,
                              projection_periods=periods)
    return ReferenceProductForecast().forecast(state, [state], None, context)


# ---------------------------------------------------------------- scaling

def test_scaling_moves_the_recorded_peak_onto_the_entered_peak():
    factor, scaled = scale_to_peak([10.0, 20.0, 30.0], 60)
    assert factor == pytest.approx(2.0)
    assert scaled == pytest.approx([20.0, 40.0, 60.0])


def test_a_matching_peak_is_a_one_to_one_borrow():
    factor, scaled = scale_to_peak([10.0, 20.0, 30.0], 30)
    assert factor == pytest.approx(1.0)
    assert scaled == pytest.approx([10.0, 20.0, 30.0])


def test_scaling_needs_a_positive_peak_and_a_series_with_a_positive_maximum():
    with pytest.raises(ValueError, match="positive peak"):
        scale_to_peak([1.0, 2.0], 0)
    with pytest.raises(ValueError, match="positive peak"):
        scale_to_peak([1.0, 2.0], -5)
    with pytest.raises(ValueError, match="positive peak"):
        scale_to_peak([1.0, 2.0], "60")
    with pytest.raises(ValueError, match="no positive value"):
        scale_to_peak([0.0, -3.0], 60)
    with pytest.raises(ValueError, match="stored series"):
        scale_to_peak([], 60)


# ---------------------------------------------------------------- the forecast model

def test_reference_shape_is_rescaled_then_projected_from_the_horizon():
    state = WorldState(time=4, variables={"units": 25.0})
    outcome = forecast(state, reference_history(), 60)
    assert outcome.metrics["reference_scale"] == pytest.approx(2.0)
    assert outcome.metrics["reference_recorded_peak"] == pytest.approx(30.0)
    assert outcome.metrics["reference_peak_target"] == pytest.approx(60.0)
    assert outcome.metrics["reference_points"] == 3
    assert outcome.metrics["reference_rmse"] == pytest.approx(0.0)
    assert outcome.projections["Rival quarterly units"] == pytest.approx([120.0, 140.0, 160.0, 180.0])
    assert outcome.metrics["Rival quarterly units_trend_per_period"] == pytest.approx(20.0)


def test_reference_projection_keeps_the_analogue_name_and_only_borrows_the_gap():
    state = WorldState(time=4, variables={"units": 25.0})
    outcome = forecast(state, reference_history(), 60)
    # The rescaled analogue reaches 180 while this run ended at 25, so the gap is 155.
    assert outcome.metrics["units_reference_gap"] == pytest.approx(155.0)
    assert outcome.metrics["units_simulated"] == pytest.approx(25.0)
    assert "units" not in outcome.projections


def test_reference_comparison_is_skipped_when_the_series_names_no_world_variable():
    state = WorldState(time=4, variables={"units": 25.0})
    outcome = forecast(state, reference_history(variable=""), 60)
    assert "units_reference_gap" not in outcome.metrics


def test_reference_forecast_needs_both_the_series_and_the_peak():
    state = WorldState(time=4, variables={"units": 25.0})
    with pytest.raises(ValueError, match="reference product history"):
        ReferenceProductForecast().forecast(state, [state], None,
            ForecastContext(definition=SimulationDefinition(
                metadata=SimulationMetadata(id="x", name="x"), initial_world_state=state, agents=[])))
    definition = SimulationDefinition(
        metadata=SimulationMetadata(id="x", name="x"), initial_world_state=state, agents=[],
        reference_history_id="rival-series")
    with pytest.raises(ValueError, match="peak"):
        ReferenceProductForecast().forecast(state, [state], None,
            ForecastContext(definition=definition, reference_history=reference_history()))


# ---------------------------------------------------------------- builder rules

def builder_definition():
    definition = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    definition.forecast_model_id = "reference_product"
    return definition


def test_builder_rejects_a_reference_forecast_with_no_input(tmp_path):
    service = SimulationBuilderService(tmp_path, EXAMPLES, history_store=ProductHistoryStore(tmp_path))
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(builder_definition())
    assert any("stored reference product" in item for item in error.value.errors)

    broken = builder_definition()
    broken.reference_history_id = "not-stored"
    with pytest.raises(DefinitionValidationError) as dangling:
        service.validate(broken)
    assert any("Reference history 'not-stored' is not stored" in item for item in dangling.value.errors)

    no_peak = builder_definition()
    no_peak.reference_history_id = "rival-series"
    service.history_store.create(reference_history())
    with pytest.raises(DefinitionValidationError) as missing_peak:
        service.validate(no_peak)
    assert any("positive peak" in item for item in missing_peak.value.errors)

    ready = builder_definition()
    ready.reference_history_id = "rival-series"
    ready.reference_peak = 60
    assert service.validate(ready) == []


def test_builder_refuses_a_reference_that_is_the_products_own_history(tmp_path):
    service = SimulationBuilderService(tmp_path, EXAMPLES, history_store=ProductHistoryStore(tmp_path))
    service.history_store.create(reference_history())
    definition = builder_definition()
    definition.reference_history_id = "rival-series"
    definition.product_history_id = "rival-series"
    definition.reference_peak = 60
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(definition)
    assert any("different stored series" in item for item in error.value.errors)


def test_own_history_requirement_is_still_checked_without_a_reference(tmp_path):
    service = SimulationBuilderService(tmp_path, EXAMPLES, history_store=ProductHistoryStore(tmp_path))
    definition = builder_definition()
    definition.forecast_model_id = "product_history"
    definition.reference_history_id = "rival-series"
    definition.reference_peak = 60
    with pytest.raises(DefinitionValidationError) as error:
        service.validate(definition)
    assert any("stored product history" in item for item in error.value.errors)


# ---------------------------------------------------------------- engine wiring

def test_engine_loads_the_reference_series_from_the_history_store(tmp_path):
    store = ProductHistoryStore(tmp_path)
    store.create(reference_history())
    definition = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    definition.forecast_model_id = "reference_product"
    definition.reference_history_id = "rival-series"
    definition.reference_peak = 60
    result = SimulationRunnerService(history_store=store).run(definition)[0]
    outcome = result.scenarios[0].forecast
    assert outcome.metrics["reference_scale"] == pytest.approx(60 / 30)
    assert outcome.projections["Rival quarterly units"]

    absent = definition.model_copy(deep=True)
    absent.metadata.id = "absent-reference"
    absent.reference_history_id = "gone"
    with pytest.raises(ValueError, match="gone"):
        SimulationRunnerService(history_store=store).run(absent)


# ---------------------------------------------------------------- suggestions

class FakeClient:
    """One canned provider response, with the prompt kept so it can be inspected."""
    provider = "fake"
    model = "fake-ranking-model"

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        return LLMCompletion(content=json.dumps(self.payload), provider=self.provider,
                             model=self.model, latency_ms=12.0,
                             token_usage={"prompt_tokens": 900, "completion_tokens": 100,
                                          "total_tokens": 1000})


PROFILE = ("A once-monthly injectable for chronic migraine, prescribed by neurologists, "
           "launched through specialty pharmacies at a premium price with a patient support program.")


def test_suggestion_keeps_only_stored_ids_and_quotes_the_profile_verbatim():
    client = FakeClient({"candidates": [
        {"history_id": "rival-series", "reason": "Same injectable launch channel.",
         "cited_profile_text": ["prescribed by neurologists", "a premium price"]},
        {"history_id": "invented-product", "reason": "Not stored anywhere."}]})
    result = suggest_reference(PROFILE, [reference_history()], client)
    assert [item.history_id for item in result.candidates] == ["rival-series"]
    assert result.candidates[0].name == "Rival quarterly units"
    assert result.candidates[0].cited_profile_text == ["prescribed by neurologists", "a premium price"]
    assert result.candidates[0].unmatched_quotes == []
    assert result.rejected == [{"history_id": "invented-product",
        "reason": "not a stored product history, so it cannot be plotted or fitted"}]
    assert result.provider_call["total_tokens"] == 1000


def test_a_paraphrased_quote_is_reported_not_passed_off_as_profile_text():
    client = FakeClient({"candidates": [{"history_id": "rival-series",
        "reason": "Close enough.", "cited_profile_text": ["chronic migraine", "sold in Europe"]}]})
    result = suggest_reference(PROFILE, [reference_history()], client)
    assert result.candidates[0].cited_profile_text == ["chronic migraine"]
    assert result.candidates[0].unmatched_quotes == ["sold in Europe"]


def test_quote_matching_ignores_case_and_line_wrapping():
    client = FakeClient({"candidates": [{"history_id": "rival-series", "reason": "Channel match.",
        "cited_profile_text": ["PRESCRIBED   BY\nneurologists"]}]})
    result = suggest_reference(PROFILE, [reference_history()], client)
    assert result.candidates[0].cited_profile_text == ["PRESCRIBED BY neurologists"]


def test_more_than_five_ranked_series_are_truncated_explicitly():
    stored = [reference_history(history_id=f"series-{index}", name=f"Series {index}")
              for index in range(7)]
    client = FakeClient({"candidates": [{"history_id": item.history_id, "reason": "shape"}
                                        for item in stored]})
    result = suggest_reference(PROFILE, stored, client)
    assert len(result.candidates) == 5
    assert {"history_id": "series-5", "reason": "only the top 5 ranked references are shown"} in result.rejected
    assert result.histories_offered == 7


def test_duplicate_ids_are_collapsed():
    client = FakeClient({"candidates": [
        {"history_id": "rival-series", "reason": "first"},
        {"history_id": "rival-series", "reason": "again"}]})
    result = suggest_reference(PROFILE, [reference_history()], client)
    assert len(result.candidates) == 1
    assert any("twice" in item["reason"] for item in result.rejected)


def test_an_unreadable_response_raises_without_a_partial_shortlist():
    missing_list = FakeClient({"unexpected": "shape"})
    with pytest.raises(ReferenceSuggestionError, match="no 'candidates' list"):
        suggest_reference(PROFILE, [reference_history()], missing_list)
    not_json = FakeClient({})
    not_json.generate_json = lambda prompt: LLMCompletion(content="not json", provider="fake",
                                                          model="fake")
    with pytest.raises(ReferenceSuggestionError, match="not JSON"):
        suggest_reference(PROFILE, [reference_history()], not_json)


def test_nothing_is_stored_means_no_suggestion_is_possible():
    with pytest.raises(ReferenceSuggestionError, match="no stored product histories"):
        suggest_reference(PROFILE, [], FakeClient({"candidates": []}))


def test_the_prompt_sees_each_series_shape_but_no_invented_numbers():
    digest = history_digest(reference_history(values=[10.0, 20.0, 30.0]))
    assert digest["peak"] == 30.0
    # Quartiles of the ramp, floored to a recorded period and expressed against the peak.
    assert digest["shape_relative_to_peak"] == [0.333, 0.333, 0.667, 0.667, 1.0]


# ---------------------------------------------------------------- HTTP surface

@pytest.fixture
def client(tmp_path, monkeypatch):
    store = ProductHistoryStore(tmp_path / "histories")
    store.create(reference_history())
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


def test_run_summary_carries_the_scaled_analogue_series(client):
    definition = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    definition.metadata.id = "reference-run"
    definition.forecast_model_id = "reference_product"
    definition.reference_history_id = "rival-series"
    definition.reference_peak = 60
    definition.reference_profile = PROFILE
    definition.reference_rationale = "Rival quarterly units: channel match, applied from a profile match by you."
    assert client.post("/simulations", json=definition.model_dump(mode="json")).status_code == 201
    assert client.post("/simulations/reference-run/run").status_code == 200
    payload = client.get("/simulations/reference-run/results").json()
    summary = payload["summary"]["reference_history"]
    assert summary["name"] == "Rival quarterly units"
    assert summary["peak"] == 60
    assert summary["scale"] == pytest.approx(2.0)
    # The dashboard draws this series, so the run result must carry the rescaled numbers.
    assert summary["scaled_values"] == pytest.approx([20.0, 40.0, 60.0])
    assert summary["values"] == pytest.approx([10.0, 20.0, 30.0])
    scenario = payload["scenarios"][0]
    assert scenario["forecast"]["metrics"]["reference_scale"] == pytest.approx(2.0)
    assert scenario["forecast"]["projections"]["Rival quarterly units"]


def test_a_reference_pointing_at_a_deleted_series_is_shown_as_broken(client):
    definition = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    definition.metadata.id = "reference-preview"
    definition.forecast_model_id = "state_metrics"
    definition.reference_history_id = "rival-series"
    definition.reference_peak = 60
    assert client.post("/simulations/preview-run",
                       json=definition.model_dump(mode="json")).status_code == 200
    assert client.delete("/histories/rival-series").status_code == 204
    definition.metadata.id = "reference-broken"
    assert client.post("/simulations", json=definition.model_dump(mode="json")).status_code == 422


def test_suggest_reference_endpoint_returns_ranked_stored_series(client, monkeypatch):
    monkeypatch.setattr(api.routes.runner, "llm_client",
        FakeClient({"candidates": [{"history_id": "rival-series", "reason": "Channel match.",
                                    "cited_profile_text": ["premium price"]}]}))
    response = client.post("/simulations/suggest-reference", json={"profile": PROFILE})
    assert response.status_code == 200
    body = response.json()
    assert [item["history_id"] for item in body["candidates"]] == ["rival-series"]
    assert body["candidates"][0]["cited_profile_text"] == ["premium price"]
    assert body["histories_offered"] == 1
    assert body["provider_call"]["model"] == "fake-ranking-model"


def test_suggest_reference_refuses_a_profile_too_short_to_match(client):
    assert client.post("/simulations/suggest-reference", json={"profile": "too short"}
                       ).status_code == 422


def test_suggest_reference_without_a_configured_provider_is_a_clear_error(client, monkeypatch):
    response = client.post("/simulations/suggest-reference", json={"profile": PROFILE})
    assert response.status_code == 400
    assert "LLM_API_KEY" in response.json()["detail"]
