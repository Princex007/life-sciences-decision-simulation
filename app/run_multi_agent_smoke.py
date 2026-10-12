"""Run one three-agent local LLM reaction loop through the existing engine."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.agents.llm import LLMConfigurationError, OpenAICompatibleLLMClient
from app.config import is_local_provider
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService


ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "examples" / "local_multi_agent_smoke.json"
EXPECTED_AGENTS = ["company", "competitor", "payer"]


class TracingLocalClient(OpenAICompatibleLLMClient):
    """Count calls and retain only credential-redacted adapter data for the trace."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = []

    def generate_decision(self, context, prompt):
        print(f"REQUEST = SENT for {context.agent_id} to {self.base_url}/chat/completions")
        completion = super().generate_decision(context, prompt)
        self.calls.append((context.model_copy(deep=True), prompt, completion))
        print(f"RAW ACTION ({context.agent_id}) = {completion.content.strip()!r}")
        return completion


def main() -> int:
    definition = SimulationDefinition.from_json(str(DEFINITION))
    if [agent.id for agent in definition.agents] != EXPECTED_AGENTS:
        raise RuntimeError("Smoke definition must contain exactly company, competitor, payer in order.")
    if any(len(agent.available_actions) < 2 for agent in definition.agents):
        raise RuntimeError("Each smoke agent must have at least two configured actions.")

    try:
        configured = OpenAICompatibleLLMClient.from_environment()
    except LLMConfigurationError as error:
        print(f"CONFIGURATION FAILURE = {error}")
        return 2
    if not is_local_provider(configured.provider):
        print("CONFIGURATION FAILURE = LLM_PROVIDER must select local or lm-studio.")
        return 2
    if urlparse(configured.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        print("CONFIGURATION FAILURE = local provider URL must use loopback.")
        return 2

    client = TracingLocalClient(api_key=configured._api_key, base_url=configured.base_url,
        model=configured.model, timeout=configured.timeout, provider=configured.provider,
        temperature=configured.temperature)
    print("POLICY = LLM (existing LLMDecisionPolicy)")
    print(f"MODEL = {client.model}")
    print("SCENARIOS = configured for one retained path; local decisions return one action each")
    result, elapsed = SimulationRunnerService(client).run(definition, "llm")
    print(f"SCENARIOS GENERATED = {len(result.scenarios)}")
    if len(result.scenarios) != 1:
        print("FAILURE = expected exactly one scenario")
        return 1

    scenario = result.scenarios[0]
    decisions = [item for item in scenario.decision_trace if item.event_type == "decision"]
    if [item.agent_id for item in decisions] != EXPECTED_AGENTS or len(client.calls) != 3:
        print(f"FAILURE = expected one sequential decision per agent; got {[item.agent_id for item in decisions]}")
        return 1

    for decision in decisions:
        context = decision.decision_context
        response = decision.decision_response
        decision_position = scenario.decision_trace.index(decision)
        transition = next((item for item in scenario.decision_trace[decision_position + 1:]
                           if item.event_type == "transition"), None)
        print(f"\nAgent: {decision.agent_id}")
        print(f"Objective: {decision.objective}")
        print(f"Available actions: {[action.id for action in context.available_actions] if context else []}")
        print(f"Permitted observations: {context.observations.visible_world_variables if context else {}}")
        print(f"Selected action: {response.primary_action if response else '(missing)'}")
        print(f"Validation result: {decision.validation_status}")
        print(f"State change: {transition.state_changes if transition else {}}")
        if decision.validation_status != "valid" or transition is None or not transition.state_changes:
            print(f"Rejection/detail: {decision.validity_reason}")
            return 1

    print("\nFINAL WORLD STATE:", scenario.final_state.as_variables())
    print(f"ELAPSED = {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
