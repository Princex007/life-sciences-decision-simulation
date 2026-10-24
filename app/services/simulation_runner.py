"""Application service that assembles forecast plugins and executes definitions."""
from time import perf_counter

from app.domain.definitions import SimulationDefinition
from app.forecasting.registry import default_registry
from app.simulation.engine import SimulationEngine
from app.agents.base import RuleBasedDecisionPolicy
from app.agents.llm import LLMCallBudget, LLMClient, LLMDecisionPolicy


def create_decision_policy(mode: str, llm_client: LLMClient | None = None,
                           budget: LLMCallBudget | None = None):
    if mode == "rule_based":
        return RuleBasedDecisionPolicy()
    if mode == "llm":
        return (LLMDecisionPolicy(llm_client, budget=budget) if llm_client
                else LLMDecisionPolicy.from_environment(budget))
    raise ValueError(f"Unsupported decision policy '{mode}'.")


class SimulationRunnerService:
    def __init__(self, llm_client: LLMClient | None = None, history_store=None):
        self.llm_client = llm_client
        self.history_store = history_store

    def run(self, definition: SimulationDefinition, decision_policy: str | None = None):
        registry = default_registry()
        started = perf_counter()
        budget = LLMCallBudget(definition.settings.llm_max_calls,
                               definition.settings.llm_max_total_tokens)
        policy = create_decision_policy(decision_policy or definition.settings.decision_policy,
                                        self.llm_client, budget)
        result = SimulationEngine(registry, decision_policy=policy,
                                  history_store=self.history_store).run(definition)
        return result, perf_counter() - started
