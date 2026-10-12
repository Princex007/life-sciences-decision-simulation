"""Run exactly one real LLM decision through the existing simulation engine."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.agents.llm import (
    LLMConfigurationError,
    LLMDecisionPolicy,
    OpenAICompatibleLLMClient,
)
from app.domain.definitions import SimulationDefinition
from app.services import simulation_runner
from app.services.simulation_runner import SimulationRunnerService


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEFINITION = ROOT / "examples" / "us_drug_launch.json"


class TracingLocalClient(OpenAICompatibleLLMClient):
    """Observe one real adapter call without logging request headers or credentials."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.request_count = 0
        self.last_completion = None

    def generate_decision(self, context, prompt):
        if self.request_count >= 1:
            raise RuntimeError("Smoke run blocked a second LLM request.")
        self.request_count += 1
        endpoint = self.base_url + "/chat/completions"
        print(f"REQUEST = SENT ({endpoint})")
        try:
            completion = super().generate_decision(context, prompt)
        except Exception as error:
            detail = str(error)
            if "HTTP " in detail:
                print(f"RESPONSE = RECEIVED ({detail})")
            else:
                print(f"RESPONSE = FAILURE ({type(error).__name__}: {detail})")
            raise
        self.last_completion = completion
        print("RESPONSE = RECEIVED")
        print(f"    configured model: {completion.model}")
        print(f"    server model field: {completion.model_version or '(not supplied)'}")
        print(f"    response content characters: {len(completion.content)}")
        return completion


def _single_decision_slice(definition: SimulationDefinition) -> SimulationDefinition:
    """Use the existing example but keep only its initial company decision trigger."""
    definition.trigger_definitions = [
        trigger for trigger in definition.trigger_definitions
        if trigger.id == "company-start"
    ]
    if len(definition.trigger_definitions) != 1:
        raise RuntimeError("Expected the bundled company-start trigger exactly once.")
    start_events = [event for event in definition.settings.initial_events
        if event.event_type == "simulation_start"]
    definition.settings.initial_events = []
    definition.settings.scheduled_events = [
        start_events[0].model_copy(update={"id": "smoke-company-start", "time": 1})
    ] if start_events else []
    definition.settings.time_horizon = 1
    if len(definition.settings.scheduled_events) != 1:
        raise RuntimeError("Expected exactly one scheduled simulation_start event at the final step.")
    return definition


def _traced_service_policy_selection(client: TracingLocalClient):
    """Log the actual policy selected by SimulationRunnerService, then delegate unchanged."""
    original_factory = simulation_runner.create_decision_policy

    def traced_factory(mode, llm_client=None):
        policy = original_factory(mode, llm_client)
        print(f"POLICY = LLM ({type(policy).__name__}, mode={mode!r})")
        if not isinstance(policy, LLMDecisionPolicy):
            raise RuntimeError("Smoke run did not select LLMDecisionPolicy.")
        original_decide = policy.decide

        def traced_decide(context, actions):
            print("[3] Agent reached LLMDecisionPolicy with DecisionContext")
            print(f"    agent: {context.agent_id}; trigger: {context.trigger.event_type}")
            print(f"    visible variables: {sorted(context.observations.visible_world_variables)}")
            print(f"    configured actions: {[action.id for action in context.available_actions]}")
            response = original_decide(context, actions)
            if client.last_completion is None:
                print("PARSE = FAILURE (no completion content received)")
                print(f"REJECTION = {response.validation_errors}")
            elif response.validation_status == "invalid":
                print("PARSE = FAILURE (local response was not an exact plausible candidate action ID)")
                print(f"REJECTION = {response.validation_errors}")
            else:
                print("PARSE = SUCCESS (exact candidate action ID)")
                print(f"    extracted action: {response.primary_action!r}")
            return response

        policy.decide = traced_decide
        return policy

    return original_factory, traced_factory


def main() -> int:
    print("[1] Loading the existing US drug-launch simulation definition")
    definition = SimulationDefinition.from_json(str(DEFAULT_DEFINITION))
    definition = _single_decision_slice(definition)
    print("    smoke slice: one final-step event, one active trigger, one decision horizon")

    try:
        configured = OpenAICompatibleLLMClient.from_environment()
    except LLMConfigurationError as error:
        print(f"[configuration failed] {error}")
        return 2
    parsed_url = urlparse(configured.base_url)
    if configured.provider.strip().casefold() not in {"local", "lm-studio", "lm_studio", "lmstudio"}:
        print("[configuration failed] Refusing to send this smoke run to a non-local provider.")
        return 2
    if parsed_url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        print("[configuration failed] Local provider URL must use localhost or a loopback IP.")
        return 2

    client = TracingLocalClient(api_key=configured._api_key, base_url=configured.base_url,
        model=configured.model, timeout=configured.timeout, provider=configured.provider,
        temperature=configured.temperature)
    print("    local provider configuration loaded (API key value not displayed)")
    print(f"MODEL = {client.model}")
    print(f"    endpoint root: {client.base_url}")

    original_factory, traced_factory = _traced_service_policy_selection(client)
    simulation_runner.create_decision_policy = traced_factory
    try:
        print("[run] Executing SimulationRunnerService.run(..., decision_policy='llm')")
        result, elapsed = SimulationRunnerService(client).run(definition, "llm")
    finally:
        simulation_runner.create_decision_policy = original_factory

    decision_traces = [trace for scenario in result.scenarios for trace in scenario.decision_trace
        if trace.event_type == "decision"]
    print(f"[trace] real adapter calls: {client.request_count}; simulation decisions: {len(decision_traces)}")
    if client.request_count != 1 or len(decision_traces) != 1:
        print("[failure] Smoke run did not produce exactly one provider call and one decision.")
        return 1

    trace = decision_traces[0]
    audit = trace.llm_audit
    print("[trace] parsed decision response:")
    print(f"    primary: {trace.decision_response.primary_action!r}")
    if client.last_completion is not None:
        print(f"RAW ACTION = {audit.raw_provider_response.strip() if audit else client.last_completion.content.strip()!r}")

    validation_ok = trace.validation_status == "valid"
    print(f"VALIDATION = {'SUCCESS' if validation_ok else 'FAILURE'} ({trace.validation_status})")
    if not validation_ok:
        print(f"REJECTION = {trace.validity_reason or trace.decision_response.validation_errors}")
    action = trace.action.action_id if trace.action else "rejected"
    print(f"FINAL ACTION = {action}")
    print("STATE TRANSITION:")
    transitions = [item for scenario in result.scenarios for item in scenario.decision_trace
        if item.event_type == "transition" and item.state_changes]
    if trace.action and transitions:
        for transition in transitions:
            print(f"    {transition.description}: {transition.state_changes}")
        print("    final company_launch_status:",
              result.scenarios[0].final_state.get("company_launch_status"))
    else:
        print("    no action transition was applied; the decision was rejected safely")
        print("    final company_launch_status:",
              result.scenarios[0].final_state.get("company_launch_status"))
    print(f"[done] elapsed simulation time: {elapsed:.2f}s")
    return 0 if validation_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
