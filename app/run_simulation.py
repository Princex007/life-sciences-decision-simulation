"""Run any JSON simulation definition from the command line."""
import argparse
import json
from pathlib import Path
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService
from app.agents.llm import LLMConfigurationError, LLMClient

def run(path: str, decision_policy: str | None = None,
        llm_client: LLMClient | None = None):
    definition = SimulationDefinition.from_json(path)
    runner = SimulationRunnerService(llm_client)
    result, _duration = runner.run(definition, decision_policy)
    return definition, result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("definition", nargs="?", default="examples/us_drug_launch.json")
    parser.add_argument("--json", action="store_true", help="Emit the complete result as JSON")
    parser.add_argument("--policy", choices=["rule_based", "llm"], default=None,
                        help="Override the definition's decision policy")
    args = parser.parse_args()
    try:
        definition, result = run(args.definition, args.policy)
    except LLMConfigurationError as error:
        import sys
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    if args.json:
        print(result.model_dump_json(indent=2))
        return
    print(f"Simulation: {definition.metadata.name}")
    print(f"Agents: {', '.join(agent.name for agent in definition.agents)}")
    print(f"Initial world state: {definition.initial_world_state.as_variables()}")
    print(f"Scenario tree root: {result.root.node_id}; terminal paths: {len(result.scenarios)}")
    print("\nROOT")
    tree = {"children": {}, "scenarios": []}
    for scenario in result.scenarios:
        cursor = tree
        for trace in scenario.decision_trace:
            if trace.event_type != "decision" or trace.action is None:
                continue
            label = f"Q{trace.time} {trace.agent_id}: {trace.action.name}"
            cursor = cursor["children"].setdefault(label, {"children": {}, "scenarios": []})
        cursor["scenarios"].append(scenario)
    def print_branch(branch, indent=""):
        labels = sorted(branch["children"])
        for index, label in enumerate(labels):
            last = index == len(labels) - 1 and not branch["scenarios"]
            print(f"{indent}{'`-- ' if last else '+-- '}{label}")
            print_branch(branch["children"][label], indent + ("    " if last else "|   "))
        for scenario in branch["scenarios"]:
            forecast = scenario.forecast.metrics if scenario.forecast else "not configured"
            print(f"{indent}`-- {scenario.scenario_id} Forecast: {forecast}")
    print_branch(tree)
    print("\nTerminal scenario details")
    for scenario in result.scenarios:
        print(f"\n{scenario.scenario_id}: {scenario.name}")
        for trace in scenario.decision_trace:
            if trace.event_type == "decision":
                print(f"  Q{trace.time} {trace.agent_id}: {trace.trigger} -> {trace.action.name}")
        print(f"  Forecast: {scenario.forecast.metrics if scenario.forecast else 'not configured'}")
        print(f"  Final state: {scenario.final_state.as_variables()}")

if __name__ == "__main__":
    main()
