"""Central event queue, state-trigger dispatch, and simulation clock."""
from dataclasses import dataclass
from typing import Any
from app.domain.agent import AgentDefinition, AgentState
from app.domain.definitions import SimulationDefinition, TriggerDefinition
from app.domain.event import SimulationEvent
from app.domain.world import WorldState

@dataclass
class TriggerMatch:
    """An active configured trigger for one agent and the event context."""
    definition: TriggerDefinition
    event: SimulationEvent

class EventScheduler:
    """Own all initial, scheduled, transition-generated, and state-change events."""
    def __init__(self, definition: SimulationDefinition):
        self.definition = definition
        self._sequence = 0

    def initial_events(self) -> list[SimulationEvent]:
        """Materialize configured simulation-start events."""
        return self._scheduled(self.definition.settings.initial_events, 0)

    def scheduled_events(self, time: int) -> list[SimulationEvent]:
        """Return events configured for the current time, in priority order."""
        return self._scheduled(self.definition.settings.scheduled_events, time)

    def advance(self, world: WorldState) -> SimulationEvent:
        """Advance the generic simulation clock by the configured step duration."""
        previous_time = world.time
        duration = self.definition.settings.step_duration
        if int(duration) != duration:
            raise ValueError("MVP world time requires an integer step_duration")
        world.time += int(duration)
        return SimulationEvent(event_id=self._id("time-step"), time=world.time,
            event_type="time_step", description=f"Advance one {self.definition.settings.step_unit}",
            data={"previous_time": previous_time})

    def transition_events(self, events: list[SimulationEvent]) -> list[SimulationEvent]:
        """Normalize and deterministically order generated events."""
        return sorted(events, key=lambda event: (-event.priority, event.event_id))

    def dispatch(self, agent: AgentDefinition, memory: AgentState, world: WorldState,
                 events: list[SimulationEvent], previous_world: WorldState | None,
                 current_time: int) -> TriggerMatch | None:
        """Find the highest-priority eligible trigger for one configured agent."""
        matches: list[TriggerMatch] = []
        for trigger in self.definition.trigger_definitions:
            if agent.id not in trigger.affected_agents:
                continue
            if trigger.expires_after is not None and current_time > trigger.expires_after:
                continue
            last_time = memory.last_trigger_times.get(trigger.id)
            if last_time is not None and current_time - last_time < trigger.cooldown:
                continue
            event_match = next((event for event in events if event.event_type in trigger.event_types), None)
            condition_match = self._condition_event(trigger, world, previous_world, current_time)
            event = event_match or condition_match
            if event:
                matches.append(TriggerMatch(trigger, event))
        if not matches:
            return None
        return sorted(matches, key=lambda match: (-match.definition.priority, match.definition.id))[0]

    def state_change_events(self, previous: WorldState, current: WorldState) -> list[SimulationEvent]:
        """Emit configured state-condition events after a transition."""
        generated = []
        for trigger in self.definition.trigger_definitions:
            event = self._condition_event(trigger, current, previous, current.time)
            if event:
                generated.append(event)
        return self.transition_events(generated)

    def _condition_event(self, trigger: TriggerDefinition, current: WorldState,
                         previous: WorldState | None, time: int) -> SimulationEvent | None:
        condition = trigger.state_condition
        if not condition:
            return None
        variable = condition.get("variable")
        value = current.get(variable)
        prior = previous.get(variable) if previous else None
        threshold = condition.get("value")
        operation = condition.get("operator", "gt")
        delta = value - prior if isinstance(value, (int, float)) and isinstance(prior, (int, float)) else None
        tests = {"gt": lambda: value is not None and value > threshold,
                 "gte": lambda: value is not None and value >= threshold,
                 "lt": lambda: value is not None and value < threshold,
                 "lte": lambda: value is not None and value <= threshold,
                 "changed_by_gte": lambda: delta is not None and delta >= threshold,
                 "changed_by_lte": lambda: delta is not None and delta <= threshold}
        if operation not in tests or not tests[operation]():
            return None
        event_type = trigger.event_types[0] if trigger.event_types else trigger.id
        return SimulationEvent(event_id=self._id(trigger.id), time=time, event_type=event_type,
            description=condition.get("description", trigger.id), priority=trigger.priority,
            data={"variable": variable, "previous": prior, "value": value, "delta": delta,
                  "trigger_id": trigger.id})

    def _scheduled(self, definitions, time: int) -> list[SimulationEvent]:
        events = [SimulationEvent(event_id=item.id, time=item.time, event_type=item.event_type,
                    description=item.description, priority=item.priority, data=item.data)
                  for item in definitions if item.time == time]
        return self.transition_events(events)

    def _id(self, prefix: str) -> str:
        self._sequence += 1
        return f"evt-{prefix}-{self._sequence:06d}"
