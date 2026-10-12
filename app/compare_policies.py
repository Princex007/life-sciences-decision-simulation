"""Compare policy traces and outcomes on identical configured initial conditions."""
import argparse
import json
import sys

from app.agents.cognition import DecisionResponse
from app.agents.llm import LLMClient, LLMConfigurationError, MockLLMClient
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService


def _decisions(result):
    return [{"scenario_id": scenario.scenario_id, "agent_id": trace.agent_id,
        "trigger_id": trace.trigger_id, "primary_action": (trace.decision_response.primary_action
            if trace.decision_response else None),
        "alternatives": (trace.decision_response.alternative_actions if trace.decision_response else []),
        "selected_action": trace.action.action_id if trace.action else None,
        "strategy_change": trace.strategy_change,
        "validation": trace.validation_status}
        for scenario in result.scenarios for trace in scenario.decision_trace
        if trace.event_type == "decision"]


def compare(path: str, llm_client: LLMClient | None = None) -> dict:
    definition = SimulationDefinition.from_json(path)
    runner = SimulationRunnerService(llm_client)
    rule_result, _ = runner.run(definition, "rule_based")
    llm_result, _ = runner.run(definition, "llm")
    return {
        "description": "Architectural comparison only; this does not claim predictive accuracy.",
        "rule_based": {"decisions": _decisions(rule_result),
            "terminal_scenarios": len(rule_result.scenarios),
            "outcomes": [{"name": scenario.name, "final_state": scenario.final_state.as_variables(),
                "forecast": scenario.forecast.metrics if scenario.forecast else {}}
                for scenario in rule_result.scenarios]},
        "llm": {"decisions": _decisions(llm_result),
            "terminal_scenarios": len(llm_result.scenarios),
            "outcomes": [{"name": scenario.name, "final_state": scenario.final_state.as_variables(),
                "forecast": scenario.forecast.metrics if scenario.forecast else {}}
                for scenario in llm_result.scenarios]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("definition", nargs="?", default="examples/us_drug_launch.json")
    parser.add_argument("--mock", action="store_true", help="Use a deterministic mock LLM without credentials")
    args = parser.parse_args()
    client = None
    if args.mock:
        def mock_response(context, _prompt):
            action = next((item for item in context.available_actions
                           if (item.strategy or item.id) == context.current_strategy),
                          context.available_actions[0] if context.available_actions else None)
            if action is None:
                return DecisionResponse(primary_action="", rationale="No configured action.")
            return DecisionResponse(primary_action=action.id,
                alternative_actions=[item.id for item in context.available_actions if item.id != action.id],
                rationale="Deterministic mock policy selected by action order.",
                assumptions=["This mock demonstrates wiring only."],
                strategy_change=(action.strategy or action.id)
                    if (action.strategy or action.id) != context.current_strategy else None)
        client = MockLLMClient(mock_response)
    try:
        report = compare(args.definition, client)
    except LLMConfigurationError as error:
        print(f"Rule-based run is available, but LLM comparison requires configuration: {error}",
              file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
