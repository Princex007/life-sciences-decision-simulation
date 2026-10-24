"""LLM-supplied assumptions for values the user left blank.

The model may only fill gaps this module detects, and every accepted value is
re-validated in code and labeled as an LLM assumption. It can never overwrite a
value the user entered, invent a world variable, or reach the engine unlabeled.
"""
from __future__ import annotations

import json
import re
from math import isfinite
from numbers import Real
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.agents.llm import DecisionPrompt, LLMCompletion
from app.domain.action import ActionDefinition, ActionEffect
from app.domain.definitions import SimulationDefinition, TriggerDefinition

# A response rejected here is never resubmitted, so one request bounds the spend.
GAP_LIMIT = 40
MAX_ACTIONS_PER_AGENT = 3
MAX_OBJECTIVE_CHARS = 400
OPERATIONS = ("set", "add", "subtract", "multiply", "divide")
TRIGGER_MODES = {"once_at_start": ["simulation_start"], "every_round": ["simulation_start", "decision_round"]}
PLACEHOLDER_OBJECTIVES = ("describe this stakeholder",)

ASSUMPTION_GRADE = "llm_assumption"
ASSUMPTION_LABEL = "value supplied by the model, not entered by you"

PROMPT_VERSION = "assumption-fill-v1"


class AssumptionFillError(RuntimeError):
    """The provider response could not be used; no partial value was applied."""


GapKindLiteral = Literal["variable_value", "agent_objective", "agent_actions", "agent_trigger"]


class Gap(BaseModel):
    kind: GapKindLiteral
    key: str
    detail: str = ""


class VariableAssumption(BaseModel):
    value: Any
    rationale: str = ""


class ActionAssumption(BaseModel):
    name: str
    variable: str
    operation: str = "set"
    value: Any
    rationale: str = ""


class AssumptionPayload(BaseModel):
    variables: dict[str, VariableAssumption] = Field(default_factory=dict)
    objectives: dict[str, str] = Field(default_factory=dict)
    actions: dict[str, list[ActionAssumption]] = Field(default_factory=dict)
    triggers: dict[str, str] = Field(default_factory=dict)


class FilledAssumption(BaseModel):
    kind: GapKindLiteral
    key: str
    value: Any
    rationale: str = ""


class RejectedAssumption(BaseModel):
    kind: GapKindLiteral
    key: str
    reason: str


class AssumptionFill(BaseModel):
    definition: SimulationDefinition
    gaps_found: list[Gap] = Field(default_factory=list)
    filled: list[FilledAssumption] = Field(default_factory=list)
    rejected: list[RejectedAssumption] = Field(default_factory=list)
    provider_call: dict[str, Any] = Field(default_factory=dict)


class AssumptionClient(Protocol):
    def generate_json(self, prompt: DecisionPrompt) -> LLMCompletion: ...


_SYSTEM = """You complete missing values in a stakeholder-decision simulation definition.
You are given a list of gaps and the surrounding configuration. Fill only those gaps.
Rules:
- Return one JSON object with the keys "variables", "objectives", "actions", and "triggers".
- Omit any key you cannot fill; never invent extra keys.
- "variables" maps a listed variable name to {"value": <plain number>, "rationale": "<one short sentence>"}.
  Values must be plain finite numbers with no units, thousands separators, or words.
- "objectives" maps a listed agent id to one short objective sentence for that agent.
- "actions" maps a listed agent id to 1 to 3 objects of
  {"name": "...", "variable": "<an existing variable name>", "operation": "set|add|subtract|multiply|divide",
   "value": <plain number>, "rationale": "<one short sentence>"}.
- "triggers" maps a listed agent id to "once_at_start" or "every_round".
- Every number you return is an illustrative assumption, not a measurement or a forecast.
- Never reference a variable, agent, or action that was not supplied to you."""


def find_gaps(definition: SimulationDefinition) -> list[Gap]:
    """Detect values a user has to enter but has not, or entered in an unusable form."""
    gaps: list[Gap] = []
    for name, value in definition.initial_world_state.variables.items():
        if isinstance(value, str) and _needs_numeric_value(value):
            gaps.append(Gap(kind="variable_value", key=name,
                detail=f"stored as the text {value!r}; actions and forecasts need a number"))
    action_agents = {action.agent_id for action in definition.action_definitions}
    trigger_agents = {agent_id for trigger in definition.trigger_definitions
                      for agent_id in trigger.affected_agents}
    for agent in definition.agents:
        objective = (agent.objective or "").strip()
        if not objective or objective.lower().startswith(PLACEHOLDER_OBJECTIVES):
            gaps.append(Gap(kind="agent_objective", key=agent.id,
                detail="objective is placeholder text"))
        if agent.id not in action_agents or not agent.available_actions:
            gaps.append(Gap(kind="agent_actions", key=agent.id,
                detail="this agent has no actions it could choose"))
        if agent.id not in trigger_agents:
            gaps.append(Gap(kind="agent_trigger", key=agent.id,
                detail="no trigger decides when this agent acts"))
    return gaps


def build_prompt(definition: SimulationDefinition, gaps: list[Gap]) -> DecisionPrompt:
    listed = [{"kind": gap.kind, "key": gap.key, "detail": gap.detail} for gap in gaps]
    variables = {name: {"value": value,
                        "description": (definition.world_variable_metadata.get(name) or {}).get("description", "")}
                 for name, value in definition.initial_world_state.variables.items()}
    agents = [{"id": agent.id, "name": agent.name, "type": agent.type, "objective": agent.objective,
               "available_actions": agent.available_actions} for agent in definition.agents]
    payload = {"simulation": {"name": definition.metadata.name,
                              "description": definition.metadata.description,
                              "horizon": definition.settings.time_horizon,
                              "step_unit": definition.settings.step_unit},
               "world_variables": variables, "agents": agents, "gaps": listed}
    return DecisionPrompt(system=_SYSTEM, user=json.dumps(payload, indent=1), version=PROMPT_VERSION)


def fill_assumptions(definition: SimulationDefinition, client: AssumptionClient) -> AssumptionFill:
    """Ask the provider once, then apply only the values that pass validation."""
    gaps = find_gaps(definition)
    if not gaps:
        return AssumptionFill(definition=definition.model_copy(deep=True), gaps_found=[])
    considered = gaps[:GAP_LIMIT]
    completion = client.generate_json(build_prompt(definition, considered))
    try:
        payload = AssumptionPayload.model_validate(json.loads(completion.content))
    except (ValueError, ValidationError) as error:
        raise AssumptionFillError(
            f"The model response could not be read as an assumption set ({type(error).__name__}). "
            "No values were applied.") from error

    working = definition.model_copy(deep=True)
    filled: list[FilledAssumption] = []
    rejected: list[RejectedAssumption] = []
    keyed = {(gap.kind, gap.key): gap for gap in considered}

    _apply_variables(working, payload, keyed, filled, rejected)
    _apply_objectives(working, payload, keyed, filled, rejected)
    _apply_actions(working, payload, keyed, filled, rejected)
    _apply_triggers(working, payload, keyed, filled, rejected)

    usage = completion.token_usage or {}
    return AssumptionFill(definition=working, gaps_found=considered, filled=filled, rejected=rejected,
        provider_call={"model": completion.model, "provider": completion.provider,
                       "attempts": completion.attempts, "latency_ms": completion.latency_ms,
                       "prompt_tokens": usage.get("prompt_tokens", 0),
                       "completion_tokens": usage.get("completion_tokens", 0),
                       "total_tokens": usage.get("total_tokens", 0)})


def _apply_variables(working, payload, keyed, filled, rejected) -> None:
    for name, assumption in payload.variables.items():
        if ("variable_value", name) not in keyed:
            rejected.append(RejectedAssumption(kind="variable_value", key=name,
                reason="not a detected gap; the entered value was kept"))
            continue
        value = _finite_number(assumption.value)
        if value is None:
            rejected.append(RejectedAssumption(kind="variable_value", key=name,
                reason="the model did not return a plain finite number"))
            continue
        working.initial_world_state.variables[name] = value
        metadata = working.world_variable_metadata.setdefault(name, {})
        metadata["type"] = "number"
        metadata["evidence_grade"] = ASSUMPTION_GRADE
        metadata["assumption_labels"] = list(dict.fromkeys(
            [*(metadata.get("assumption_labels") or []), ASSUMPTION_LABEL]))
        filled.append(FilledAssumption(kind="variable_value", key=name, value=value,
            rationale=assumption.rationale[:300]))


def _apply_objectives(working, payload, keyed, filled, rejected) -> None:
    agents = {agent.id: agent for agent in working.agents}
    for agent_id, objective in payload.objectives.items():
        if ("agent_objective", agent_id) not in keyed or agent_id not in agents:
            rejected.append(RejectedAssumption(kind="agent_objective", key=agent_id,
                reason="not a detected gap; the entered objective was kept"))
            continue
        text = " ".join(str(objective).split())
        if not text:
            rejected.append(RejectedAssumption(kind="agent_objective", key=agent_id,
                reason="the model returned an empty objective"))
            continue
        agents[agent_id].objective = text[:MAX_OBJECTIVE_CHARS]
        filled.append(FilledAssumption(kind="agent_objective", key=agent_id,
            value=agents[agent_id].objective, rationale="written by the model from the agent's role"))


def _apply_actions(working, payload, keyed, filled, rejected) -> None:
    agents = {agent.id: agent for agent in working.agents}
    existing_ids = {action.id for action in working.action_definitions}
    for agent_id, assumptions in payload.actions.items():
        if ("agent_actions", agent_id) not in keyed or agent_id not in agents:
            rejected.append(RejectedAssumption(kind="agent_actions", key=agent_id,
                reason="not a detected gap; this agent's actions were left as configured"))
            continue
        if len(assumptions) > MAX_ACTIONS_PER_AGENT:
            rejected.append(RejectedAssumption(kind="agent_actions", key=agent_id,
                reason=f"the model proposed {len(assumptions)} actions; only the first "
                       f"{MAX_ACTIONS_PER_AGENT} were considered"))
        agent = agents[agent_id]
        for assumption in assumptions[:MAX_ACTIONS_PER_AGENT]:
            reason = _action_rejection(working, assumption)
            if reason:
                rejected.append(RejectedAssumption(kind="agent_actions", key=agent_id, reason=reason))
                continue
            action_id = _unique_id(f"{agent_id}_{_slug(assumption.name)}", existing_ids)
            existing_ids.add(action_id)
            working.action_definitions.append(ActionDefinition(
                id=action_id, name=assumption.name.strip()[:80], agent_id=agent_id,
                description=f"LLM assumption: {assumption.rationale.strip()[:200] or 'plausible choice for this role'}",
                effects=[ActionEffect(variable=assumption.variable, operation=assumption.operation,
                                      value=_finite_number(assumption.value))]))
            agent.available_actions = list(dict.fromkeys([*agent.available_actions, action_id]))
            policy = dict(agent.decision_policy or {})
            policy["default_actions"] = list(agent.available_actions)
            agent.decision_policy = policy
            filled.append(FilledAssumption(kind="agent_actions", key=agent_id,
                value=f"{action_id} ({assumption.operation} {assumption.variable} "
                      f"{'to' if assumption.operation == 'set' else 'by'} {assumption.value})",
                rationale=assumption.rationale[:300]))


def _apply_triggers(working, payload, keyed, filled, rejected) -> None:
    agents = {agent.id: agent for agent in working.agents}
    for agent_id, mode in payload.triggers.items():
        if ("agent_trigger", agent_id) not in keyed or agent_id not in agents:
            rejected.append(RejectedAssumption(kind="agent_trigger", key=agent_id,
                reason="not a detected gap; this agent's timing was left as configured"))
            continue
        if mode not in TRIGGER_MODES:
            rejected.append(RejectedAssumption(kind="agent_trigger", key=agent_id,
                reason="the model did not choose once_at_start or every_round"))
            continue
        trigger_id = f"auto-trigger-{agent_id}"
        if any(trigger.id == trigger_id for trigger in working.trigger_definitions):
            trigger_id = f"{trigger_id}-filled"
        working.trigger_definitions.append(TriggerDefinition(id=trigger_id,
            event_types=list(TRIGGER_MODES[mode]), affected_agents=[agent_id], priority=50))
        if mode == "every_round":
            _ensure_round_events(working)
        filled.append(FilledAssumption(kind="agent_trigger", key=agent_id, value=mode,
            rationale="chosen by the model from the agent's role"))


def _ensure_round_events(working: SimulationDefinition) -> None:
    """A per-round trigger needs the scheduled events that the guided builder normally writes."""
    from app.domain.definitions import ScheduledEventDefinition
    existing = {event.time for event in working.settings.scheduled_events
                if "decision_round" in event.event_type}
    for step in range(1, working.settings.time_horizon + 1):
        if step in existing:
            continue
        working.settings.scheduled_events.append(ScheduledEventDefinition(
            id=f"auto-round-{step}", time=step, event_type="decision_round",
            description="Guided builder round decision point", priority=40))
    working.settings.scheduled_events.sort(key=lambda event: (event.time, event.id))


def _action_rejection(working, assumption: ActionAssumption) -> str:
    if not assumption.name.strip():
        return "an action was missing a name"
    if assumption.variable not in working.initial_world_state.variables:
        return f"references {assumption.variable!r}, which is not a world variable in this definition"
    if assumption.operation not in OPERATIONS:
        return f"uses the unsupported operation {assumption.operation!r}"
    value = _finite_number(assumption.value)
    if value is None:
        return "the effect value is not a plain finite number"
    if assumption.operation == "divide" and value == 0:
        return "the effect would divide by zero"
    return ""


def _finite_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    if not isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _needs_numeric_value(text: str) -> bool:
    cleaned = text.strip().lstrip("$£€").replace(",", "")
    if not cleaned:
        return True
    return bool(re.fullmatch(r"[-+]?\d*\.?\d+\s*(%|[kmbt]|thousand|million|billion|trillion)?",
                             cleaned, re.IGNORECASE))


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.strip().lower())).strip("_") or "action"


def _unique_id(candidate: str, taken: set[str]) -> str:
    if candidate not in taken:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in taken:
        suffix += 1
    return f"{candidate}_{suffix}"
