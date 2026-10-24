"""API surface the guided builder UI depends on: example metadata, driver
records in results, and preview runs that never touch local storage."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.domain.definitions import SimulationDefinition, TransitionRule
from app.main import app
from app.services.simulation_builder import DefinitionValidationError, SimulationBuilderService

PROJECT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT / "examples"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(api.routes, "builder", SimulationBuilderService(tmp_path, EXAMPLES))
    api.routes._results.clear()
    with TestClient(app) as test_client:
        yield test_client
    api.routes._results.clear()


def test_every_bundled_example_passes_builder_validation(tmp_path):
    """A bundled example must load and run from the UI without edits."""
    service = SimulationBuilderService(tmp_path, EXAMPLES)
    failures = {}
    for path in sorted(EXAMPLES.glob("*.json")):
        try:
            service.validate(SimulationDefinition.from_json(str(path)))
        except DefinitionValidationError as error:
            failures[path.name] = error.errors
    assert failures == {}


def test_transition_rule_accepts_comma_separated_and_wildcard_events(tmp_path):
    """StateTransitionSystem splits on commas and honours '*', so must validation."""
    service = SimulationBuilderService(tmp_path, EXAMPLES)
    definition = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    definition.transition_rules = [
        TransitionRule(id="multi", event_type="company_launch, price_change"),
        TransitionRule(id="wildcard", event_type="*"),
        TransitionRule(id="engine", event_type="action_transition"),
        TransitionRule(id="bad", event_type="company_launch,never_emitted"),
    ]
    with pytest.raises(DefinitionValidationError) as caught:
        service.validate(definition)
    assert caught.value.errors == ["Transition rule bad references unknown event never_emitted"]


def test_template_list_exposes_summary_for_example_cards(client):
    response = client.get("/simulations/templates")
    assert response.status_code == 200
    templates = {item["id"]: item for item in response.json()}
    # The picker is curated, so its contents are pinned exactly: a template that stops being
    # maintained has to leave the list, and nothing may appear here by accident.
    assert set(templates) == {"ai_drug_discovery", "us_drug_launch"}

    driver_example = templates["ai_drug_discovery"]["summary"]
    assert driver_example["time_horizon"] == 5
    assert driver_example["step_unit"] == "year"
    assert [driver["driver_id"] for driver in driver_example["external_drivers"]] == ["ai_discovery"]
    active = driver_example["external_drivers"][0]
    assert active["active_variant"] == "accelerated"
    assert {variant["variant_id"] for variant in active["variants"]} == {
        "conservative", "accelerated", "disruptive"}
    assert "synthetic_illustrative" in driver_example["evidence_grades"]

    launch = templates["us_drug_launch"]["summary"]
    assert launch["forecast_model"] == "launch_revenue"
    assert len(launch["agents"]) == 5
    assert launch["external_drivers"] == []


def test_saved_list_exposes_ui_metadata(client):
    definition = client.get("/simulations/templates/us_drug_launch").json()
    assert client.post("/simulations", json=definition).status_code == 201
    items = client.get("/simulations").json()
    assert len(items) == 1
    assert items[0] == {
        "simulation_id": definition["metadata"]["id"],
        "name": definition["metadata"]["name"],
        "description": definition["metadata"]["description"],
        "domain": definition["metadata"]["domain"],
        "agent_count": 5,
        "time_horizon": definition["settings"]["time_horizon"],
        "external_driver_count": 0,
        "has_results": False,
    }
    client.post(f"/simulations/{definition['metadata']['id']}/run")
    assert client.get("/simulations").json()[0]["has_results"] is True


def test_results_expose_driver_records_and_root(client):
    definition = client.get("/simulations/templates/ai_drug_discovery").json()
    assert client.post("/simulations", json=definition).status_code == 201
    simulation_id = definition["metadata"]["id"]
    assert client.post(f"/simulations/{simulation_id}/run").status_code == 200

    payload = client.get(f"/simulations/{simulation_id}/results").json()
    summary = payload["summary"]
    assert summary["key_drivers"] == ["ai_discovery"]
    assert summary["time_horizon"] == 5
    assert summary["assumption_labels"]
    assert summary["variable_evidence"]["rd_cost_index"]["evidence_grade"] == "synthetic_illustrative"

    assert payload["driver_evidence_grades"] == {"ai_discovery": "synthetic_illustrative"}
    impacts = payload["driver_impacts"]
    assert impacts and all(record["driver_id"] == "ai_discovery" for record in impacts)
    assert {"information", "world_state"} == {record["pathway"] for record in impacts}
    lagged = [record for record in impacts if record["lag"]]
    assert lagged and all(record["effect_time"] == record["source_time"] + record["lag"]
                          for record in lagged)

    hypotheses = payload["driver_hypotheses"]
    assert [record["target_variable"] for record in hypotheses] == ["probability_of_technical_success"]
    assert hypotheses[0]["status"] == "qualitative_hypothesis_not_applied"
    final_variables = payload["scenarios"][0]["final_state"]["variables"]
    assert "probability_of_technical_success" not in final_variables

    assert payload["root"]["node_type"] == "root"
    assert payload["scenarios"][0]["terminal_node_id"]


def test_preview_run_compares_variants_without_persisting(client, tmp_path):
    definition = client.get("/simulations/templates/ai_drug_discovery").json()
    driver = definition["external_drivers"][0]
    runs = {}
    for variant in ("conservative", "accelerated", "disruptive"):
        candidate = dict(definition)
        candidate["external_drivers"] = [{**driver, "active_variant": variant}]
        response = client.post("/simulations/preview-run", json=candidate)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "preview"
        runs[variant] = payload["scenarios"][0]["final_state"]["variables"]

    cycle_time = [runs[variant]["rd_cycle_time_years"] for variant in
                  ("conservative", "accelerated", "disruptive")]
    assert cycle_time == sorted(cycle_time, reverse=True)
    adoption = [runs[variant]["ai_discovery_adoption_index"] for variant in
                ("conservative", "accelerated", "disruptive")]
    assert adoption == sorted(adoption)
    # The driver never writes to the agent's own decision variable.
    assert len({runs[variant]["company_ai_allocation"] for variant in runs}) == 1

    assert list(tmp_path.glob("*.json")) == []
    assert client.get("/simulations").json() == []


def test_preview_run_rejects_invalid_definitions(client):
    definition = client.get("/simulations/templates/us_drug_launch").json()
    definition["trigger_definitions"][0]["event_types"] = ["never_emitted"]
    response = client.post("/simulations/preview-run", json=definition)
    assert response.status_code == 422
    assert "never_emitted" in response.json()["detail"]["errors"][0]
