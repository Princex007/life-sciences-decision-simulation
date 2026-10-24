import pytest

from pathlib import Path

from app.services.simulation_builder import DefinitionValidationError, SimulationBuilderService
from app.domain.definitions import SimulationDefinition, TransitionRule
from app.domain.agent import AgentDefinition
from app.domain.action import ActionDefinition, ActionEffect
from app.domain.definitions import TriggerDefinition

# Retired from the example picker, kept as a fixture: it is the only definition in the repository
# with a `sales` world variable and a `market_open` opening event, which the test below adds an
# action and a trigger against.
PRICING_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "market_pricing_competition.json"


@pytest.fixture
def service(tmp_path):
    project = __import__("pathlib").Path(__file__).resolve().parents[1]
    return SimulationBuilderService(tmp_path / "saved", project / "examples")


def test_templates_validate_and_local_crud_round_trip(service):
    definition = service.load_template("us_drug_launch")
    assert service.validate(definition) == []
    service.create(definition)
    loaded = service.get(definition.metadata.id)
    assert loaded.model_dump(mode="json") == definition.model_dump(mode="json")
    loaded.metadata.description = "Updated description"
    service.update(loaded.metadata.id, loaded)
    assert service.get(loaded.metadata.id).metadata.description == "Updated description"
    assert [item.metadata.id for item in service.list()] == [loaded.metadata.id]
    service.delete(loaded.metadata.id)
    with pytest.raises(FileNotFoundError):
        service.get(loaded.metadata.id)


def test_duplicate_uses_available_local_id(service):
    source = service.load_template("us_drug_launch")
    service.create(source)
    first = service.duplicate(source.metadata.id)
    second = service.duplicate(source.metadata.id)
    assert first.metadata.id == f"{source.metadata.id}-copy"
    assert second.metadata.id == f"{source.metadata.id}-copy-2"
    assert first.metadata.name.endswith("(copy)")


def test_definition_can_add_arbitrary_agent_action_and_trigger(service):
    definition = SimulationDefinition.from_json(str(PRICING_FIXTURE))
    definition.agents.append(AgentDefinition(id="market_observer", name="Market Observer",
        objective="Record market activity", available_actions=["record_activity"],
        decision_policy={"default_actions": ["record_activity"]}))
    definition.action_definitions.append(ActionDefinition(id="record_activity", name="Record activity",
        agent_id="market_observer", effects=[ActionEffect(variable="sales", operation="add", value=0)]))
    definition.trigger_definitions.append(TriggerDefinition(id="observer_open", event_types=["market_open"],
        affected_agents=["market_observer"]))
    service.create(definition)
    loaded = service.get(definition.metadata.id)
    assert loaded.agents[-1].id == "market_observer"
    assert loaded.action_definitions[-1].agent_id == "market_observer"
    assert loaded.trigger_definitions[-1].affected_agents == ["market_observer"]


def test_validation_reports_broken_agent_action_references(service):
    definition = service.load_template("us_drug_launch")
    definition.action_definitions[0].agent_id = "missing-agent"
    with pytest.raises(DefinitionValidationError, match="unknown agent missing-agent"):
        service.validate(definition)


def test_validation_rejects_unregistered_forecast_and_event_references(service):
    definition = service.load_template("us_drug_launch")
    definition.forecast_model_id = "unknown_forecast"
    definition.transition_rules.append(TransitionRule(id="bad-transition", event_type="never_emitted"))
    with pytest.raises(DefinitionValidationError) as caught:
        service.validate(definition)
    assert any("not registered" in error for error in caught.value.errors)
    assert any("unknown event never_emitted" in error for error in caught.value.errors)


def test_saved_id_must_match_metadata_and_path_ids_are_safe(service):
    definition = service.load_template("us_drug_launch")
    with pytest.raises(DefinitionValidationError, match="must match metadata.id"):
        service.update("other-id", definition)
    with pytest.raises(ValueError, match="only letters"):
        service.get("../outside")
