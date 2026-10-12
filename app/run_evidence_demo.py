"""Show synthetic evidence retrieval, compare deterministic policies, and run the example."""
import json

from app.agents.cognition import DecisionResponse
from app.agents.llm import MockLLMClient
from app.benchmark.decision_benchmark import run_benchmark
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService


def _mock_response(context, _prompt):
    actions = context.available_actions
    selected = next((item for item in actions
                     if (item.strategy or item.id) == context.current_strategy),
                    actions[0] if actions else None)
    evidence = context.relevant_evidence[:1]
    citation = f" [{evidence[0].evidence_id}]" if evidence else ""
    return DecisionResponse(primary_action=selected.id if selected else "",
        alternative_actions=[item.id for item in actions if selected and item.id != selected.id],
        rationale="Mock selection follows configured action order and supplied context." + citation,
        facts_used=[f"{key} = {value!r}" for key, value in context.observations.visible_world_variables.items()],
        evidence_used=[item.evidence_id for item in evidence],
        assumptions=["This deterministic mock is illustrative, not a model quality claim."],
        strategy_change=(selected.strategy or selected.id)
            if selected and (selected.strategy or selected.id) != context.current_strategy else None)


def main():
    benchmark = run_benchmark()
    print("Synthetic evidence benchmark")
    print(json.dumps(benchmark, indent=2, sort_keys=True))
    definition = SimulationDefinition.from_json("examples/us_drug_launch.json")
    result, _ = SimulationRunnerService(MockLLMClient(_mock_response)).run(definition, "llm")
    seen = set()
    print("\nExisting simulation using deterministic mock LLM")
    for scenario in result.scenarios:
        for trace in scenario.decision_trace:
            if trace.event_type != "decision" or not trace.decision_context:
                continue
            key = (trace.agent_id, trace.trigger_id, trace.time, trace.action.action_id if trace.action else None)
            if key in seen:
                continue
            seen.add(key)
            print(json.dumps({"agent": trace.agent_id, "time": trace.time,
                "trigger": trace.trigger_id, "evidence": [item.evidence_id for item in trace.decision_context.relevant_evidence],
                "plausible_actions": [item.action_id for item in trace.plausible_actions],
                "selected_action": trace.action.action_id if trace.action else None,
                "validation": trace.validation_status}, sort_keys=True))
    print(f"Terminal scenarios: {len(result.scenarios)}")
    print("First forecast:", json.dumps(result.scenarios[0].forecast.metrics if result.scenarios and result.scenarios[0].forecast else {}, sort_keys=True))


if __name__ == "__main__":
    main()
