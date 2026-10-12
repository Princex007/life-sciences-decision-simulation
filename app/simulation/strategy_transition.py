"""Explicit branch-local transition of an agent's persistent strategy."""
from dataclasses import dataclass
from app.domain.agent import AgentState


@dataclass(frozen=True)
class StrategyTransition:
    previous: str | None
    current: str | None
    changed: bool


class StrategyTransitionSystem:
    def apply(self, state: AgentState, requested_strategy: str | None,
              action_id: str, time: int) -> StrategyTransition:
        # Legacy action definitions without a strategy field retain action-ID persistence.
        target = requested_strategy if requested_strategy is not None else action_id
        previous = state.current_strategy
        if previous != target:
            state.current_strategy = target
            state.memory.strategy_changes.append({"time": time, "from": previous,
                                                  "to": target, "action_id": action_id})
        return StrategyTransition(previous=previous, current=state.current_strategy,
                                  changed=previous != state.current_strategy)
