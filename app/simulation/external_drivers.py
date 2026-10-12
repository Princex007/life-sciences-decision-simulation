"""Compile configured external drivers into deterministic engine artifacts.

Drivers never get their own execution path. A compiled driver becomes ordinary
scheduled events plus transition rules, so its effects pass through the same
``StateTransitionSystem`` and ``DecisionValidator`` as any stakeholder action.
"""
from __future__ import annotations

from numbers import Real
from typing import Any

from pydantic import BaseModel, Field

from app.domain.definitions import (ScheduledEventDefinition, SimulationDefinition,
                                    TransitionRule)
from app.domain.driver import (DriverHypothesisRecord, DriverImpactRecord, ExternalDriver)
from app.domain.action import ActionEffect


class DriverPlan(BaseModel):
    """Everything the driver layer contributes to one simulation run."""
    scheduled_events: list[ScheduledEventDefinition] = Field(default_factory=list)
    transition_rules: list[TransitionRule] = Field(default_factory=list)
    impacts: list[DriverImpactRecord] = Field(default_factory=list)
    hypotheses: list[DriverHypothesisRecord] = Field(default_factory=list)
    active_driver_ids: list[str] = Field(default_factory=list)
    indicator_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)
    initial_indicator_values: dict[str, float] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.active_driver_ids


def scale_value(operation: str, value: Any, level: float) -> Any:
    """Scale a configured pathway value by the variant level at one period.

    Only numeric literals are scaled. String expressions are applied verbatim so
    a configured formula is never silently rewritten. ``set`` and ``divide`` are
    absolute operations and are not scaled.
    """
    if not isinstance(value, Real) or isinstance(value, bool):
        return value
    number = float(value)
    if operation in {"add", "subtract"}:
        return number * level
    if operation == "multiply":
        return 1.0 + (number - 1.0) * level
    return number


def validate_external_drivers(definition: SimulationDefinition) -> list[str]:
    """Return user-readable configuration problems for the driver layer."""
    errors: list[str] = []
    seen: set[str] = set()
    known_variables = set(definition.initial_world_state.as_variables())
    agent_ids = {agent.id for agent in definition.agents}

    for driver in definition.external_drivers:
        label = f"External driver '{driver.driver_id}'"
        if driver.driver_id in seen:
            errors.append(f"{label} is defined more than once.")
        seen.add(driver.driver_id)

        if driver.variants:
            variant_ids = [item.variant_id for item in driver.variants]
            if len(set(variant_ids)) != len(variant_ids):
                errors.append(f"{label} has duplicate variant IDs.")
            if driver.active_variant not in variant_ids:
                errors.append(f"{label} selects unknown variant '{driver.active_variant}'.")

        if not driver.resolve_trajectory():
            errors.append(f"{label} configures no trajectory points, so it can never fire.")

        for point in driver.resolve_trajectory():
            if point.time > definition.settings.time_horizon:
                errors.append(f"{label} fires at period {point.time}, beyond the "
                              f"configured horizon {definition.settings.time_horizon}.")

        unknown_agents = [agent for agent in driver.observable_by if agent not in agent_ids]
        if unknown_agents:
            errors.append(f"{label} is observable by unknown agents: {', '.join(sorted(unknown_agents))}.")

        if driver.observable_by and not driver.indicator_variable:
            errors.append(f"{label} lists observing agents but configures no indicator_variable.")

        for other in driver.interacts_with:
            if other == driver.driver_id:
                errors.append(f"{label} cannot interact with itself.")
            elif other not in {item.driver_id for item in definition.external_drivers}:
                errors.append(f"{label} references unknown driver '{other}' in interacts_with.")

        for pathway in driver.pathways:
            target = f"{label} pathway to '{pathway.target_variable}'"
            if pathway.target_variable not in known_variables and not pathway.qualitative_only:
                errors.append(f"{target} names a variable absent from initial_world_state.")
            if pathway.minimum is not None and pathway.maximum is not None \
                    and pathway.maximum < pathway.minimum:
                errors.append(f"{target} has a maximum below its minimum.")
            if pathway.lag and pathway.qualitative_only:
                errors.append(f"{target} sets a lag on a qualitative-only hypothesis, which never fires.")

        if driver.indicator_variable:
            if driver.indicator_variable in known_variables:
                errors.append(f"{label} indicator '{driver.indicator_variable}' collides with an "
                              "existing world variable; give the driver its own indicator name.")
            if driver.observable_from > definition.settings.time_horizon:
                errors.append(f"{label} becomes observable at period {driver.observable_from}, "
                              f"beyond the configured horizon {definition.settings.time_horizon}.")
    return errors


def compile_external_drivers(definition: SimulationDefinition) -> DriverPlan:
    """Build the events, rules, and audit records for every enabled driver."""
    errors = validate_external_drivers(definition)
    if errors:
        raise ValueError("External driver configuration is invalid: " + " ".join(errors))

    horizon = definition.settings.time_horizon
    plan = DriverPlan()
    effects_by_event: dict[str, list[ActionEffect]] = {}
    events_by_id: dict[str, ScheduledEventDefinition] = {}

    for driver in definition.external_drivers:
        if not driver.enabled:
            continue
        variant = driver.resolve_variant()
        variant_id = variant.variant_id if variant else "default"
        labels = driver.assumption_labels()
        base = driver.base_event_type()
        plan.active_driver_ids.append(driver.driver_id)

        if driver.indicator_variable:
            plan.initial_indicator_values[driver.indicator_variable] = driver.initial_value
            plan.indicator_metadata[driver.indicator_variable] = {
                "units": "driver index",
                "source": "external_driver",
                "driver_id": driver.driver_id,
                "category": driver.category,
                "evidence_grade": driver.evidence_grade,
                "assumption_labels": labels,
                "observable_by": list(driver.observable_by),
                "observable_from": driver.observable_from,
                "note": ("Written by the external-driver layer, not by an agent decision. "
                         "Held at its initial value before observable_from."),
            }

        for pathway in driver.pathways:
            if pathway.qualitative_only:
                plan.hypotheses.append(DriverHypothesisRecord(
                    driver_id=driver.driver_id, driver_name=driver.name, category=driver.category,
                    variant_id=variant_id, target_variable=pathway.target_variable,
                    operation=pathway.operation, configured_value=pathway.value,
                    basis=pathway.basis, uncertainty=pathway.uncertainty,
                    evidence_grade=pathway.evidence_grade))

        for point in driver.resolve_trajectory():
            if point.time > horizon:
                continue
            information_event = f"{base}@t{point.time}"
            _register_event(events_by_id, information_event, information_event, point.time, driver,
                            f"{driver.name} indicator update (variant '{variant_id}')",
                            point, variant_id)
            # Stable-typed signal event: agent triggers subscribe to this so a
            # driver can be observed without enumerating every period's event.
            # It carries no transition rules, so it is information-only.
            _register_event(events_by_id, f"{base}#signal@t{point.time}", base, point.time, driver,
                            f"{driver.name} signal observed (variant '{variant_id}')",
                            point, variant_id)

            if (driver.indicator_variable and point.indicator_value is not None
                    and point.time >= driver.observable_from):
                effects_by_event.setdefault(information_event, []).append(ActionEffect(
                    variable=driver.indicator_variable, operation="set",
                    value=point.indicator_value))
                plan.impacts.append(DriverImpactRecord(
                    driver_id=driver.driver_id, driver_name=driver.name, category=driver.category,
                    variant_id=variant_id, pathway="information", source_time=point.time,
                    effect_time=point.time, lag=0, level=point.level,
                    target_variable=driver.indicator_variable, operation="set",
                    configured_value=point.indicator_value, applied_value=point.indicator_value,
                    evidence_grade=driver.evidence_grade,
                    basis="Driver indicator made visible to the configured observing agents.",
                    assumption_labels=labels))

            for pathway in driver.pathways:
                if pathway.qualitative_only:
                    continue
                effect_time = point.time + pathway.lag
                if effect_time > horizon:
                    continue
                applied = scale_value(pathway.operation, pathway.value, point.level)
                bounded = pathway.minimum is not None or pathway.maximum is not None
                if pathway.lag:
                    event_type = f"{base}@t{point.time}+L{pathway.lag}"
                    _register_event(events_by_id, event_type, event_type, effect_time, driver,
                                    f"{driver.name} delayed effect (lag {pathway.lag})",
                                    point, variant_id)
                else:
                    event_type = information_event
                effects_by_event.setdefault(event_type, []).append(ActionEffect(
                    variable=pathway.target_variable, operation=pathway.operation,
                    value=applied, minimum=pathway.minimum, maximum=pathway.maximum))
                plan.impacts.append(DriverImpactRecord(
                    driver_id=driver.driver_id, driver_name=driver.name, category=driver.category,
                    variant_id=variant_id, pathway="world_state", source_time=point.time,
                    effect_time=effect_time, lag=pathway.lag, level=point.level,
                    target_variable=pathway.target_variable, operation=pathway.operation,
                    configured_value=pathway.value, applied_value=applied, bounded=bounded,
                    evidence_grade=pathway.evidence_grade, basis=pathway.basis,
                    uncertainty=pathway.uncertainty, assumption_labels=labels))

    for event_type, effects in sorted(effects_by_event.items()):
        plan.transition_rules.append(TransitionRule(
            id=f"driver-rule:{event_type}", event_type=event_type, effects=effects))

    plan.scheduled_events = [events_by_id[key] for key in sorted(
        events_by_id, key=lambda item: (-events_by_id[item].priority, events_by_id[item].time, item))]
    return plan


def _register_event(events: dict[str, ScheduledEventDefinition], event_id: str, event_type: str,
                    time: int, driver: ExternalDriver, description: str, point: Any,
                    variant_id: str) -> None:
    if event_id in events:
        return
    events[event_id] = ScheduledEventDefinition(
        id=event_id, time=time, event_type=event_type, description=description,
        priority=driver.priority,
        data={"driver_id": driver.driver_id, "driver_name": driver.name,
              "category": driver.category, "variant_id": variant_id,
              "level": point.level, "indicator_value": point.indicator_value,
              "evidence_grade": driver.evidence_grade,
              "assumption_labels": driver.assumption_labels(),
              "source": driver.source, "external_driver": True})


def apply_external_drivers(definition: SimulationDefinition) -> tuple[SimulationDefinition, DriverPlan]:
    """Return a definition copy with compiled driver artifacts merged in.

    The caller's definition is never mutated, so scenario branches and repeated
    runs stay independent.
    """
    if not any(driver.enabled for driver in definition.external_drivers):
        return definition, DriverPlan()

    plan = compile_external_drivers(definition)
    working = definition.model_copy(deep=True)

    for name, value in plan.initial_indicator_values.items():
        if working.initial_world_state.get(name) is None:
            working.initial_world_state.set(name, value)
    working.world_variable_metadata.update(plan.indicator_metadata)

    existing_events = {item.id for item in working.settings.scheduled_events}
    working.settings.scheduled_events.extend(
        item for item in plan.scheduled_events if item.id not in existing_events)

    existing_rules = {item.id for item in working.transition_rules}
    working.transition_rules.extend(
        item for item in plan.transition_rules if item.id not in existing_rules)

    for agent in working.agents:
        if agent.observable_state == "all":
            continue
        observable = [name for name, metadata in plan.indicator_metadata.items()
                      if agent.id in metadata["observable_by"]]
        agent.observable_state.extend(
            name for name in observable if name not in agent.observable_state)
    return working, plan
