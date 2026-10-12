"""Generic pre-transition validation for agent decisions."""
import ast
import re
from app.domain.action import ActionDefinition
from app.domain.agent import AgentDefinition
from app.simulation.scheduler import TriggerMatch
from app.simulation.state_transition import StateTransitionSystem, evaluate_value
from app.domain.world import WorldState

class DecisionValidationError(ValueError):
    """Raised when a proposed action is not valid for its agent or state."""

class DecisionValidator:
    """Validate availability, trigger activation, compatibility, and constraints."""
    def filter_feasible_actions(self, agent: AgentDefinition, actions, world: WorldState,
                                trigger: TriggerMatch | None, time: int):
        """Return actions that pass the same deterministic checks used at execution."""
        feasible = []
        for action in actions:
            try:
                self.validate(agent, action, world, trigger, time)
            except DecisionValidationError:
                continue
            feasible.append(action)
        return feasible

    def validate(self, agent: AgentDefinition, action: ActionDefinition, world: WorldState,
                 trigger: TriggerMatch | None, time: int) -> None:
        if action.agent_id != agent.id:
            raise DecisionValidationError(f"Action '{action.id}' belongs to agent '{action.agent_id}', not '{agent.id}'.")
        if action.id not in agent.available_actions:
            raise DecisionValidationError(f"Action '{action.id}' is not available to agent '{agent.id}'.")
        self._validate_parameters(action)
        requires_trigger = action.constraints.get("requires_trigger", True)
        if requires_trigger and (trigger is None or agent.id not in trigger.definition.affected_agents):
            raise DecisionValidationError(f"Action '{action.id}' requires a valid trigger for agent '{agent.id}'.")
        state_trigger = trigger.event.data.get("trigger_id") == trigger.definition.id
        if requires_trigger and trigger.event.event_type not in trigger.definition.event_types and not state_trigger:
            raise DecisionValidationError(
                f"Trigger '{trigger.definition.id}' does not authorize event '{trigger.event.event_type}'.")
        if not self._conditions(action.constraints.get("compatible_when", []), world):
            raise DecisionValidationError(f"Action '{action.id}' is incompatible with the current state.")

        projected = world.model_copy(deep=True)
        try:
            StateTransitionSystem().apply_action(projected, action, time)
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as error:
            raise DecisionValidationError(f"Action '{action.id}' cannot be applied: {error}") from error
        self._check_constraint_map(agent.constraints, projected, world, action, f"agent '{agent.id}'")
        self._check_constraint_map(action.constraints, projected, world, action, f"action '{action.id}'")

    @staticmethod
    def validate_response(context, response) -> list[str]:
        """Check model claims against the filtered facts and evidence it received."""
        errors = []
        evidence_ids = {item.evidence_id for item in context.relevant_evidence}
        used = set(response.evidence_used)
        if used - evidence_ids:
            errors.append("Decision references evidence IDs not supplied to this agent: " +
                          ", ".join(sorted(used - evidence_ids)) + ".")
        cited = set(re.findall(r"\[([A-Za-z0-9_-]+)\]", response.rationale))
        if cited - evidence_ids:
            errors.append("Rationale cites evidence IDs not supplied to this agent: " +
                          ", ".join(sorted(cited - evidence_ids)) + ".")
        if cited - used:
            errors.append("Rationale citations must also appear in evidence_used: " +
                          ", ".join(sorted(cited - used)) + ".")
        if used - cited:
            errors.append("Every evidence_used ID must be cited in rationale: " +
                          ", ".join(sorted(used - cited)) + ".")
        overlap = set(response.facts_used) & set(response.assumptions)
        if overlap:
            errors.append("Facts and assumptions must be distinct; duplicated entries: " +
                          "; ".join(sorted(overlap)) + ".")
        visible = context.observations.visible_world_variables
        for fact in response.facts_used:
            supported = False
            for variable, actual in visible.items():
                match = re.search(rf"(?i)(?<![\w]){re.escape(variable)}\s*(?:=|\bis\b)\s*(.+?)\s*\.?$", fact)
                if not match:
                    continue
                supported = True
                claim = match.group(1).strip()
                try:
                    claimed = ast.literal_eval(claim)
                except (ValueError, SyntaxError):
                    claimed = claim.strip("'\"")
                if claimed != actual:
                    errors.append(f"Fact '{fact}' conflicts with observed {variable}={actual!r}.")
                break
            fact_evidence_ids = set(re.findall(r"(?<![\w])([A-Za-z0-9_-]+)(?=[:\]])", fact))
            if fact_evidence_ids & evidence_ids:
                supported = True
            event_facts = {event.event_id.casefold() for event in context.observations.relevant_events}
            event_facts.update(event.event_type.casefold() for event in context.observations.relevant_events)
            event_facts.update(event.description.casefold() for event in context.observations.relevant_events)
            if fact.casefold().strip(" .") in event_facts:
                supported = True
            if fact in {belief.proposition for belief in context.relevant_beliefs}:
                supported = True
            if not supported:
                errors.append(f"Fact '{fact}' cannot be traced to a visible observation, belief, event, or evidence ID.")
        return errors

    @staticmethod
    def _conditions(conditions, world):
        for condition in conditions:
            value = world.get(condition["variable"])
            expected = condition.get("value")
            op = condition.get("operator", "eq")
            checks = {"eq": lambda: value == expected, "neq": lambda: value != expected,
                      "gt": lambda: value is not None and value > expected,
                      "gte": lambda: value is not None and value >= expected,
                      "lt": lambda: value is not None and value < expected,
                      "lte": lambda: value is not None and value <= expected}
            if op not in checks or not checks[op]():
                return False
        return True

    @staticmethod
    def _validate_parameters(action: ActionDefinition) -> None:
        required = action.constraints.get("required_parameters", [])
        if isinstance(required, dict):
            required = list(required)
        for name in required:
            if name not in action.parameters or action.parameters[name] is None:
                raise DecisionValidationError(
                    f"Action '{action.id}' is missing required parameter '{name}'.")
        for name, rules in action.parameter_schema.items():
            if name not in action.parameters:
                if rules.get("required", False):
                    raise DecisionValidationError(
                        f"Action '{action.id}' is missing required parameter '{name}'.")
                continue
            value = action.parameters[name]
            value_type = rules.get("type")
            type_checks = {"number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
                           "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
                           "string": lambda: isinstance(value, str),
                           "boolean": lambda: isinstance(value, bool)}
            if value_type in type_checks and not type_checks[value_type]():
                raise DecisionValidationError(
                    f"Action '{action.id}' parameter '{name}' must be {value_type}.")
            if "one_of" in rules and value not in rules["one_of"]:
                raise DecisionValidationError(
                    f"Action '{action.id}' parameter '{name}' must be one of {rules['one_of']!r}.")
            try:
                if ("min" in rules and value < rules["min"]
                        or "max" in rules and value > rules["max"]):
                    raise DecisionValidationError(
                        f"Action '{action.id}' parameter '{name}' is outside its configured bounds.")
            except TypeError as error:
                raise DecisionValidationError(
                    f"Action '{action.id}' parameter '{name}' has incompatible configured bounds.") from error

    def _check_constraint_map(self, config, projected, current, action, subject):
        if not config:
            return
        scope_map = {key: config[key] for key in ("state", "next_state", "current_state", "parameters") if key in config}
        if not scope_map:
            scope_map = {"next_state": {key: value for key, value in config.items()
                                        if key not in {"requires_trigger", "compatible_when"}}}
        for scope, constraints in scope_map.items():
            if scope == "parameters":
                values = action.parameters
            else:
                values = current.as_variables() if scope == "current_state" else projected.as_variables()
            if isinstance(constraints, list):
                for condition in constraints:
                    actual = action.parameters.get(condition["variable"]) if scope == "parameters" else (
                        current.get(condition["variable"]) if scope == "current_state" else projected.get(condition["variable"]))
                    expected = condition.get("value")
                    if isinstance(expected, str) and scope != "parameters":
                        expected = evaluate_value(expected, projected, action.parameters)
                    op = condition.get("operator", "eq")
                    checks = {"eq": lambda: actual == expected, "neq": lambda: actual != expected,
                              "gt": lambda: actual is not None and actual > expected,
                              "gte": lambda: actual is not None and actual >= expected,
                              "lt": lambda: actual is not None and actual < expected,
                              "lte": lambda: actual is not None and actual <= expected}
                    if op not in checks or not checks[op]():
                        raise DecisionValidationError(f"Constraint failed for {subject}: {condition} (actual={actual!r}).")
                continue
            for variable, limit in constraints.items():
                actual = values.get(variable)
                if actual is None:
                    raise DecisionValidationError(f"Constraint for {subject} references missing {scope} value '{variable}'.")
                self._check_limits(actual, limit, subject, variable)

    @staticmethod
    def _check_limits(actual, limit, subject, variable):
        if not isinstance(limit, dict):
            limit = {"eq": limit}
        checks = {"min": lambda x: actual >= x, "gte": lambda x: actual >= x,
                  "max": lambda x: actual <= x, "lte": lambda x: actual <= x,
                  "gt": lambda x: actual > x, "lt": lambda x: actual < x,
                  "eq": lambda x: actual == x, "neq": lambda x: actual != x,
                  "one_of": lambda x: actual in x,
                  "between": lambda x: x[0] <= actual <= x[1]}
        for op, expected in limit.items():
            if op not in checks or not checks[op](expected):
                raise DecisionValidationError(
                    f"Constraint failed for {subject}: '{variable}' {op} {expected!r}; actual={actual!r}.")
