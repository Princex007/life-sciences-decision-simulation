"""Deterministic policy implementations over filtered DecisionContext objects."""
from typing import Protocol

from app.domain.action import ActionDefinition
from app.agents.cognition import DecisionContext, DecisionResponse


class DecisionPolicy(Protocol):
    """Provider contract; implementations never receive or mutate WorldState."""
    def get_plausible_actions(self, context: DecisionContext) -> list[ActionDefinition]: ...
    def decide(self, context: DecisionContext,
               actions: list[ActionDefinition]) -> DecisionResponse: ...


class RuleBasedDecisionPolicy:
    """Evaluate configured rule conditions using only visible observations."""
    def get_plausible_actions(self, context: DecisionContext) -> list[ActionDefinition]:
        config = self._agent_policy(context)
        for rule in config.get("rules", []):
            if rule.get("when_event") and rule["when_event"] not in {
                    context.trigger.event_type, context.trigger.data.get("trigger_id")}:
                continue
            if self._all_conditions(rule.get("when", []), context.observations.visible_world_variables):
                return self._resolve_actions(context, rule.get("plausible_actions", []))
        defaults = config.get("default_actions", [item.id for item in context.available_actions])
        return self._resolve_actions(context, defaults)

    def decide(self, context: DecisionContext,
               actions: list[ActionDefinition]) -> DecisionResponse:
        if not actions:
            return DecisionResponse(primary_action="", rationale="No valid configured actions.",
                                    validation_status="invalid")
        current = next((action for action in actions
                        if (action.strategy or action.id) == context.current_strategy), None)
        primary = current or actions[0]
        return DecisionResponse(primary_action=primary.id,
            alternative_actions=[action.id for action in actions if action.id != primary.id],
            rationale=self.plausible_action_reason(context),
            key_drivers=self._matched_drivers(context),
            assumptions=["The configured rule set is the complete decision policy for this context."],
            strategy_change=(primary.strategy or primary.id)
                if (primary.strategy or primary.id) != context.current_strategy else None)

    @staticmethod
    def _agent_policy(context: DecisionContext) -> dict:
        return context.policy_configuration

    def plausible_action_reason(self, context: DecisionContext) -> str:
        config = self._agent_policy(context)
        for rule in config.get("rules", []):
            if rule.get("when_event") and rule["when_event"] not in {
                    context.trigger.event_type, context.trigger.data.get("trigger_id")}:
                continue
            if self._all_conditions(rule.get("when", []), context.observations.visible_world_variables):
                return rule.get("reason", f"Configured rule matched event '{context.trigger.event_type}'.")
        return config.get("default_reason", "Configured default action set.")

    def _resolve_actions(self, context: DecisionContext, ids: list[str]) -> list[ActionDefinition]:
        by_id = {action.id: action for action in context.available_actions}
        return [by_id[action_id] for action_id in ids
                if action_id in by_id and by_id[action_id].agent_id == context.agent_id]

    @staticmethod
    def _all_conditions(conditions: list[dict], variables: dict) -> bool:
        return all(RuleBasedDecisionPolicy._condition(condition, variables) for condition in conditions)

    @staticmethod
    def _condition(condition: dict, variables: dict) -> bool:
        variable = condition.get("variable")
        actual = variables.get(variable)
        expected = condition.get("value")
        if isinstance(expected, dict) and "variable" in expected:
            expected = variables.get(expected["variable"])
        operator = condition.get("operator", "eq")
        operations = {"gt": lambda: actual > expected, "gte": lambda: actual >= expected,
                      "lt": lambda: actual < expected, "lte": lambda: actual <= expected,
                      "eq": lambda: actual == expected, "neq": lambda: actual != expected}
        try:
            return bool(operations[operator]()) if operator in operations and actual is not None else False
        except TypeError:
            return False

    def _matched_drivers(self, context: DecisionContext) -> list[str]:
        for rule in self._agent_policy(context).get("rules", []):
            if rule.get("when_event") and rule["when_event"] not in {
                    context.trigger.event_type, context.trigger.data.get("trigger_id")}:
                continue
            if self._all_conditions(rule.get("when", []), context.observations.visible_world_variables):
                return [condition["variable"] for condition in rule.get("when", [])]
        return []
