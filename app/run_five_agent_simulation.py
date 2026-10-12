"""Run one five-agent two-round local LLM simulation through the existing engine."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from app.agents.llm import LLMConfigurationError, OpenAICompatibleLLMClient
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService


ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "examples" / "local_5agent_2round_smoke.json"
EXPECTED_AGENTS = ["company", "competitor", "payer", "physician", "patient"]


class TracingLocalClient(OpenAICompatibleLLMClient):
    """Count calls and record adapter data for the trace."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = []

    def generate_decision(self, context, prompt):
        completion = super().generate_decision(context, prompt)
        self.calls.append((context.model_copy(deep=True), prompt, completion))
        return completion


def main() -> int:
    definition = SimulationDefinition.from_json(str(DEFINITION))

    try:
        configured = OpenAICompatibleLLMClient.from_environment()
    except LLMConfigurationError as error:
        print(f"CONFIGURATION FAILURE = {error}")
        return 2

    if not OpenAICompatibleLLMClient._is_local_provider(configured.provider):
        print("CONFIGURATION FAILURE = LLM_PROVIDER must select local or lm-studio.")
        return 2
    if urlparse(configured.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        print("CONFIGURATION FAILURE = local provider URL must use loopback.")
        return 2

    client = TracingLocalClient(
        api_key=configured._api_key,
        base_url=configured.base_url,
        model=configured.model,
        timeout=configured.timeout,
        provider=configured.provider,
        temperature=configured.temperature,
    )

    result, elapsed = SimulationRunnerService(client).run(definition, "llm")
    if len(result.scenarios) != 1:
        print("FAILURE = expected exactly one scenario")
        return 1

    scenario = result.scenarios[0]
    decisions = [item for item in scenario.decision_trace if item.event_type == "decision"]

    if len(decisions) != 10:
        print(f"FAILURE = expected 10 decisions; got {len(decisions)}")
        return 1

    print("ROUND | AGENT | ACTION | KEY STATE CHANGE")
    for decision in decisions:
        round_num = decision.time + 1
        agent_id = decision.agent_id
        action_id = decision.action.action_id if decision.action else "(none)"
        decision_position = scenario.decision_trace.index(decision)
        transition = next(
            (item for item in scenario.decision_trace[decision_position + 1:]
             if item.event_type == "transition" and item.agent_id == agent_id),
            None,
        )
        changes = transition.state_changes if transition and transition.state_changes else {}
        change_str = ", ".join(f"{k}={v}" for k, v in changes.items()) if changes else "none"
        print(f"{round_num} | {agent_id} | {action_id} | {change_str}")

    print("\nFINAL STATE")
    print(json.dumps(scenario.final_state.as_variables(), indent=2))

    print("\nFORECAST")
    print(json.dumps(scenario.forecast.metrics if scenario.forecast else {}, indent=2))

    print(f"\nLLM CALLS\n{len(client.calls)}")
    print(f"\nELAPSED TIME\n{elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
