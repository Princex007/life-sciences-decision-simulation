"""Validated local JSON persistence for SimulationDefinition objects."""
from __future__ import annotations
import json
import re
from pathlib import Path
from app.domain.definitions import SimulationDefinition
from app.simulation.external_drivers import validate_external_drivers

class DefinitionValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))

class SimulationBuilderService:
    """CRUD-like local builder service; no database or engine coupling."""
    def __init__(self, storage_dir: Path | str | None = None,
                 examples_dir: Path | str | None = None,
                 forecast_model_ids: set[str] | None = None):
        project = Path(__file__).resolve().parents[2]
        self.storage_dir = Path(storage_dir) if storage_dir else project / "simulations"
        self.examples_dir = Path(examples_dir) if examples_dir else project / "examples"
        self.forecast_model_ids = forecast_model_ids or {"launch_revenue", "state_metrics"}
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[SimulationDefinition]:
        return [SimulationDefinition.from_json(str(path))
                for path in sorted(self.storage_dir.glob("*.json"))]

    def get(self, simulation_id: str) -> SimulationDefinition:
        path = self._path(simulation_id)
        if not path.is_file():
            raise FileNotFoundError(f"Simulation '{simulation_id}' was not found.")
        return SimulationDefinition.from_json(str(path))

    def create(self, definition: SimulationDefinition) -> SimulationDefinition:
        self.validate(definition)
        path = self._path(definition.metadata.id)
        if path.exists():
            raise FileExistsError(f"Simulation '{definition.metadata.id}' already exists.")
        self._write(path, definition)
        return definition

    def update(self, simulation_id: str, definition: SimulationDefinition) -> SimulationDefinition:
        if simulation_id != definition.metadata.id:
            raise DefinitionValidationError(["Path simulation ID must match metadata.id."])
        path = self._path(simulation_id)
        if not path.is_file():
            raise FileNotFoundError(f"Simulation '{simulation_id}' was not found.")
        self.validate(definition)
        self._write(path, definition)
        return definition

    def delete(self, simulation_id: str) -> None:
        path = self._path(simulation_id)
        if not path.is_file():
            raise FileNotFoundError(f"Simulation '{simulation_id}' was not found.")
        path.unlink()

    def duplicate(self, simulation_id: str, new_id: str | None = None) -> SimulationDefinition:
        source = self.get(simulation_id).model_copy(deep=True)
        base_id = new_id or f"{simulation_id}-copy"
        candidate, suffix = base_id, 2
        while self._path(candidate).exists():
            candidate, suffix = f"{base_id}-{suffix}", suffix + 1
        source.metadata.id = candidate
        source.metadata.name = f"{source.metadata.name} (copy)"
        return self.create(source)

    def load_template(self, template_id: str) -> SimulationDefinition:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", template_id):
            raise FileNotFoundError(f"Template '{template_id}' was not found.")
        path = self.examples_dir / f"{template_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Template '{template_id}' was not found.")
        definition = SimulationDefinition.from_json(str(path))
        self.validate(definition)
        return definition

    def validate(self, definition: SimulationDefinition) -> list[str]:
        errors = []
        agent_ids = [agent.id for agent in definition.agents]
        action_ids = [action.id for action in definition.action_definitions]
        trigger_ids = [trigger.id for trigger in definition.trigger_definitions]
        for label, values in (("agent", agent_ids), ("action", action_ids), ("trigger", trigger_ids)):
            duplicates = sorted({value for value in values if values.count(value) > 1})
            errors.extend(f"Duplicate {label} ID '{item}'." for item in duplicates)
        known_agents = set(agent_ids)
        known_actions = set(action_ids)
        evidence_ids = [item.id for item in definition.evidence]
        duplicates = sorted({value for value in evidence_ids if evidence_ids.count(value) > 1})
        errors.extend(f"Duplicate evidence ID '{item}'." for item in duplicates)
        for evidence in definition.evidence:
            for agent_id in evidence.visible_to_agents:
                if agent_id not in known_agents and agent_id not in {"*", "all"}:
                    errors.append(f"Evidence {evidence.id} references unknown visible agent {agent_id}")
        for action in definition.action_definitions:
            if action.agent_id not in known_agents:
                errors.append(f"Action {action.id} references unknown agent {action.agent_id}")
        for agent in definition.agents:
            for action_id in agent.available_actions:
                action = next((item for item in definition.action_definitions if item.id == action_id), None)
                if action is None:
                    errors.append(f"Agent {agent.id} references unknown action {action_id}")
                elif action.agent_id != agent.id:
                    errors.append(f"Agent {agent.id} lists action {action_id} owned by {action.agent_id}")
            policy_action_ids = set(agent.decision_policy.get("default_actions", []))
            for rule in agent.decision_policy.get("rules", []):
                policy_action_ids.update(rule.get("plausible_actions", []))
            for action_id in sorted(policy_action_ids - known_actions):
                errors.append(f"Agent {agent.id} policy references unknown action {action_id}")
        events = {"time_step", "action_transition"}
        events.update(item.event_type for item in definition.settings.initial_events)
        events.update(item.event_type for item in definition.settings.scheduled_events)
        events.update(event.get("event_type") for action in definition.action_definitions
                      for event in action.generated_events if event.get("event_type"))
        # Drivers are compiled into scheduled events at run time; their stable
        # signal type is what agent triggers subscribe to.
        events.update(driver.base_event_type() for driver in definition.external_drivers)
        errors.extend(validate_external_drivers(definition))
        for trigger in definition.trigger_definitions:
            if trigger.state_condition:
                events.add(trigger.id)
            for agent_id in trigger.affected_agents:
                if agent_id not in known_agents:
                    errors.append(f"Trigger {trigger.id} references unknown agent {agent_id}")
            for event_type in trigger.event_types:
                if event_type not in events:
                    errors.append(f"Trigger {trigger.id} references unknown event {event_type}")
        for rule in definition.transition_rules:
            # StateTransitionSystem accepts a comma-separated list and "*" as a wildcard.
            for event_type in (item.strip() for item in rule.event_type.split(",")):
                if event_type and event_type != "*" and event_type not in events:
                    errors.append(f"Transition rule {rule.id} references unknown event {event_type}")
        if definition.forecast_model_id and definition.forecast_model_id not in self.forecast_model_ids:
            errors.append(f"Forecast model {definition.forecast_model_id} is not registered")
        if definition.settings.time_horizon < 1:
            errors.append("Simulation time_horizon must be positive.")
        for event in definition.settings.scheduled_events:
            if event.time < 0 or event.time > definition.settings.time_horizon:
                errors.append(f"Scheduled event {event.id} is outside the simulation horizon.")
        if errors:
            raise DefinitionValidationError(errors)
        return []

    def _path(self, simulation_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", simulation_id):
            raise ValueError("Simulation ID may contain only letters, numbers, underscores, and hyphens.")
        return self.storage_dir / f"{simulation_id}.json"

    @staticmethod
    def _write(path: Path, definition: SimulationDefinition) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(definition.model_dump(mode="json"), indent=2), encoding="utf-8")
