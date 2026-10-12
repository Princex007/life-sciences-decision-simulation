"""Run the pharma example with the configured LLM policy (or a deterministic mock)."""
import argparse
import json
import sys

from app.agents.cognition import DecisionResponse
from app.agents.llm import LLMConfigurationError, MockLLMClient
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService


def _mock_response(context, prompt):
    actions = context.available_actions
    selected = next((item for item in actions if (item.strategy or item.id) == context.current_strategy),
                    actions[0] if actions else None)
    if selected is None:
        return DecisionResponse(primary_action="", rationale="No configured action.")
    return DecisionResponse(primary_action=selected.id,
        alternative_actions=[item.id for item in actions if item.id != selected.id],
        rationale="Deterministic mock selected the first configured action compatible with current strategy.",
        key_drivers=list(context.observations.visible_world_variables)[:3],
        facts_used=[f"{key} = {value!r}" for key, value in context.observations.visible_world_variables.items()],
        assumptions=["Mock provider uses its fixed action-order rule; this is not model reasoning."],
        strategy_change=(selected.strategy or selected.id)
            if (selected.strategy or selected.id) != context.current_strategy else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("definition", nargs="?", default="examples/us_drug_launch.json")
    parser.add_argument("--mock", action="store_true", help="Use deterministic MockLLMClient instead of credentials")
    args = parser.parse_args()
    definition = SimulationDefinition.from_json(args.definition)
    client = MockLLMClient(_mock_response) if args.mock else None
    try:
        result, _duration = SimulationRunnerService(client).run(definition, "llm")
    except LLMConfigurationError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    print(f"Simulation: {result.name}; policy: llm{' (mock)' if args.mock else ''}")
    print(f"Terminal scenarios: {len(result.scenarios)}")
    seen_audits = set()
    for scenario in result.scenarios:
        for trace in scenario.decision_trace:
            audit = trace.llm_audit
            if trace.event_type != "decision" or audit is None or audit.timestamp in seen_audits:
                continue
            seen_audits.add(audit.timestamp)
            context = audit.input_context
            response = trace.decision_response
            print("\nAgent:", audit.agent_id)
            print("Trigger:", audit.trigger.event_type, "(", trace.trigger_id, ")")
            print("Current strategy:", context.current_strategy)
            print("Visible observations:", context.observations.visible_world_variables)
            print("Relevant evidence:", [item.model_dump(mode="json") for item in context.relevant_evidence])
            print("Plausible actions:", [item.id for item in context.available_actions])
            print("LLM primary action:", response.primary_action)
            print("Alternative actions:", response.alternative_actions)
            print("Rationale:", response.rationale)
            print("Facts used:", response.facts_used)
            print("Assumptions:", response.assumptions)
            print("Validation:", trace.validation_status, trace.validity_reason)
            print("Selected branch action:", trace.action.action_id if trace.action else "rejected")
    print("\nScenario outcomes and forecasts:")
    for scenario in result.scenarios:
        metrics = scenario.forecast.metrics if scenario.forecast else {}
        print(scenario.scenario_id, scenario.name, json.dumps(metrics, sort_keys=True))


if __name__ == "__main__":
    main()
