"""Reusable declarative state transition system."""
import ast
import operator
from typing import Any
from app.domain.action import Action, ActionDefinition, ActionEffect
from app.domain.definitions import TransitionRule
from app.domain.event import SimulationEvent
from app.domain.world import WorldState

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

def evaluate_value(value: Any, state: WorldState, parameters: dict[str, Any] | None = None) -> Any:
    """Resolve a literal, variable/parameter reference, or safe arithmetic expression."""
    parameters = parameters or {}
    if not isinstance(value, str):
        if isinstance(value, dict) and "parameter" in value:
            return parameters[value["parameter"]]
        if isinstance(value, dict) and "variable" in value:
            return state.get(value["variable"])
        return value
    tree = ast.parse(value, mode="eval").body
    context = {**state.as_variables(), **parameters, "time": state.time}
    def visit(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in context:
            return context[node.id]
        if isinstance(node, ast.Name):
            # Bare identifiers can represent categorical state values (e.g. status="active").
            return node.id
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](visit(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"min", "max", "abs", "round"}:
            functions = {"min": min, "max": max, "abs": abs, "round": round}
            return functions[node.func.id](*(visit(arg) for arg in node.args))
        raise ValueError(f"Unsupported transition expression: {value!r}")
    return visit(tree)

class TransitionResult:
    """State transition result including a before/after change map and events."""
    def __init__(self, previous: WorldState, state: WorldState, events: list[SimulationEvent]):
        self.previous_state = previous
        self.state = state
        old, new = previous.as_variables(), state.as_variables()
        self.changes = {key: new.get(key) for key in old.keys() | new.keys()
                        if old.get(key) != new.get(key)}
        if previous.time != state.time:
            self.changes["time"] = state.time
        self.events = events

class StateTransitionSystem:
    """Applies action effects and event-bound transition rules without domain logic."""
    def apply_action(self, state: WorldState, action: ActionDefinition, time: int) -> TransitionResult:
        """Apply one configured action exactly once and emit its configured events."""
        previous = state.model_copy(deep=True)
        for effect in action.effects:
            self.apply_effect(state, effect, action.parameters)
        events = [SimulationEvent(event_id=f"evt:{time}:{action.id}:{index}", time=time,
                    event_type=item["event_type"], description=item.get("description", action.description),
                    actor_id=action.agent_id, priority=int(item.get("priority", 0)), data=item.get("data", {}))
                  for index, item in enumerate(action.generated_events)]
        return TransitionResult(previous, state, events)

    def apply_event(self, state: WorldState, event: SimulationEvent,
                    rules: list[TransitionRule]) -> TransitionResult:
        """Apply all transition rules configured for an event type."""
        previous = state.model_copy(deep=True)
        for rule in rules:
            rule_events = [item.strip() for item in rule.event_type.split(",")]
            if event.event_type in rule_events or "*" in rule_events:
                for effect in rule.effects:
                    self.apply_effect(state, effect, {})
        return TransitionResult(previous, state, [])

    @staticmethod
    def apply_effect(state: WorldState, effect: ActionEffect,
                     parameters: dict[str, Any] | None = None) -> None:
        """Apply a generic set/add/multiply/subtract/divide operation.

        Public because the driver forecast applies the identical semantics to periods
        beyond the simulated horizon, where there is no event to route the effect through.
        """
        value = evaluate_value(effect.value, state, parameters or {})
        current = state.get(effect.variable, 0)
        operations = {"set": lambda: value, "add": lambda: current + value,
                      "subtract": lambda: current - value, "multiply": lambda: current * value,
                      "divide": lambda: current / value}
        if effect.operation not in operations:
            raise ValueError(f"Unsupported transition operation: {effect.operation}")
        updated = operations[effect.operation]()
        if effect.minimum is not None:
            updated = max(effect.minimum, updated)
        if effect.maximum is not None:
            updated = min(effect.maximum, updated)
        state.set(effect.variable, updated)
