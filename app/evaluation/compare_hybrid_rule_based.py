"""Compare configured hybrid objective selection with rule-only decisions.

This is a bounded, synthetic architectural comparison. Rule-only runs use a
fresh copy of the production example with evaluation objectives disabled,
because SimulationEngine otherwise applies configured objective scoring
regardless of which policy supplies plausible actions and fallback decisions.
No LLM client is constructed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.domain.definitions import SimulationDefinition
from app.evaluation.objective_scorer import ObjectiveScorer
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.registry import ForecastRegistry
from app.simulation.engine import SimulationEngine


class DeterministicRulePolicy(RuleBasedDecisionPolicy):
    """Keep configured rule selection but avoid alternative-action branching."""

    def decide(self, context, actions):
        if not actions:
            return DecisionResponse(primary_action="", rationale="No feasible configured actions.",
                                    validation_status="invalid")
        action = next((item for item in actions
                       if (item.strategy or item.id) == context.current_strategy), actions[0])
        return DecisionResponse(primary_action=action.id,
            rationale=self.plausible_action_reason(context),
            key_drivers=self._matched_drivers(context),
            assumptions=["Deterministic rule-based fallback; no LLM was used."],
            strategy_change=(action.strategy or action.id)
                if (action.strategy or action.id) != context.current_strategy else None)


def _definition(path: Path, scenario: dict[str, Any], *, hybrid: bool) -> SimulationDefinition:
    definition = SimulationDefinition.from_json(str(path))
    definition.settings.time_horizon = 1
    definition.settings.scheduled_events = []
    definition.scenario_generation.max_scenarios = 1
    for variable, value in scenario.items():
        definition.initial_world_state.set(variable, value)
    if not hybrid:
        # The engine always scores configured objectives. Clearing this on a
        # fresh copy makes the configured RuleBasedDecisionPolicy the selector.
        definition.evaluation_objectives = {}
    return definition


def _run(path: Path, scenario: dict[str, Any], *, hybrid: bool) -> dict[str, Any]:
    definition = _definition(path, scenario, hybrid=hybrid)
    initial = definition.initial_world_state.as_variables()
    objectives = SimulationDefinition.from_json(str(path)).evaluation_objectives
    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    result = SimulationEngine(registry, decision_policy=DeterministicRulePolicy()).run(definition)
    if len(result.scenarios) != 1:
        raise AssertionError(f"Expected one bounded terminal path, got {len(result.scenarios)}.")
    terminal = result.scenarios[0]
    decisions = [trace for trace in terminal.decision_trace
                 if trace.event_type == "decision" and trace.action is not None]
    expected_agents = ["company", "competitor", "payer", "physician", "patient"]
    if [item.agent_id for item in decisions] != expected_agents:
        raise AssertionError(f"Expected five-agent trigger order, got {[d.agent_id for d in decisions]}.")

    decision_rows = []
    for item in decisions:
        selected_id = item.action.action_id
        context = item.decision_context
        applied_transition = next((trace for trace in terminal.decision_trace
            if trace.event is not None and trace.event.event_type == "action_transition"
            and trace.event.actor_id == item.agent_id), None)
        objective = objectives.get(item.agent_id)
        selected_score = None
        candidate_scores = item.decision_context.objective_scores or {}
        score_error = None
        if objective:
            try:
                computed = ObjectiveScorer().score_actions(
                    context.action_previews, item.previous_world_state, objective)
                candidate_scores = computed
                selected_score = computed[selected_id]
            except (KeyError, TypeError, ValueError) as error:
                score_error = f"{type(error).__name__}: {error}"
        compact_scores = {
            action_id: {
                "score": details["score"],
                "weighted_components": {
                    name: values["weighted_contribution"]
                    for name, values in details.get("components", {}).items()
                },
            }
            for action_id, details in candidate_scores.items()
        }
        decision_rows.append({
            "agent": item.agent_id,
            "action": selected_id,
            "decision_source": item.decision_source,
            "validation": item.validation_status,
            "validation_reason": item.validity_reason,
            "state_changes": applied_transition.state_changes if applied_transition else {},
            "candidates": [action.id for action in context.available_actions
                           if action.id in context.action_previews],
            "candidate_scores": compact_scores,
            "selected_action_score": (compact_scores.get(selected_id)
                                      if selected_score is not None else None),
            "score_error": score_error,
        })
    if any(item.validation_status != "valid" for item in decisions):
        raise AssertionError("A selected action did not pass engine validation.")
    final = terminal.final_state.as_variables()
    wanted = ["market_share", "competitor_market_share", "payer_access",
              "physician_adoption", "patient_adherence_rate"]
    return {
        "initial_state": initial,
        "decisions": decision_rows,
        "final_state": {name: final.get(name) for name in wanted},
        "forecast": terminal.forecast.metrics if terminal.forecast else {},
        "all_actions_valid": all(item.validation_status == "valid" for item in decisions),
        "action_sequence": [(item.agent_id, item.action.action_id) for item in decisions],
    }


def run_comparison() -> dict[str, Any]:
    path = Path(__file__).parents[2] / "examples" / "us_drug_launch.json"
    scenarios = {
        "baseline": {},
        "competitive_pressure": {"competitor_price": 70000},
        "restricted_access": {"payer_access": 0.50},
    }
    report: dict[str, Any] = {
        "description": "One-quarter deterministic comparison; illustrative outcomes, not predictive claims.",
        "horizon_quarters": 1,
        "llm_calls": 0,
        "scenarios": {},
    }
    for name, overrides in scenarios.items():
        rule = _run(path, overrides, hybrid=False)
        hybrid = _run(path, overrides, hybrid=True)
        report["scenarios"][name] = {
            "overrides": overrides,
            "rule_based": rule,
            "hybrid": hybrid,
            "comparison": {
                "changed_decisions": [
                    {"agent": rb["agent"], "rule_action": rb["action"],
                     "hybrid_action": hy["action"]}
                    for rb, hy in zip(rule["decisions"], hybrid["decisions"])
                    if rb["action"] != hy["action"]
                ],
                "final_state_delta_hybrid_minus_rule": {
                    key: hybrid["final_state"][key] - rule["final_state"][key]
                    for key in hybrid["final_state"]
                },
                "forecast_delta_hybrid_minus_rule": {
                    key: hybrid["forecast"][key] - rule["forecast"][key]
                    for key in hybrid["forecast"] if key in rule["forecast"]
                    and isinstance(hybrid["forecast"][key], (int, float))
                    and isinstance(rule["forecast"][key], (int, float))
                },
            },
        }
    repeat = _run(path, {}, hybrid=True)
    baseline = report["scenarios"]["baseline"]["hybrid"]
    report["baseline_hybrid_reproducibility"] = {
        "identical_action_sequence": baseline["action_sequence"] == repeat["action_sequence"],
        "identical_final_state": baseline["final_state"] == repeat["final_state"],
        "repeat_action_sequence": repeat["action_sequence"],
        "repeat_final_state": repeat["final_state"],
    }
    return report


if __name__ == "__main__":
    detailed = run_comparison()
    initial = detailed["scenarios"]["baseline"]["hybrid"]["initial_state"]
    compact = {
        "description": detailed["description"],
        "horizon_quarters": detailed["horizon_quarters"],
        "llm_calls": detailed["llm_calls"],
        "shared_baseline_initial_state": initial,
        "scenario_initial_overrides": {
            name: item["overrides"] for name, item in detailed["scenarios"].items()
        },
        "scenarios": {},
        "baseline_hybrid_reproducibility": detailed["baseline_hybrid_reproducibility"],
    }
    for name, scenario in detailed["scenarios"].items():
        compact["scenarios"][name] = {"comparison": scenario["comparison"]}
        for policy_name in ("rule_based", "hybrid"):
            result = scenario[policy_name]
            compact["scenarios"][name][policy_name] = {
                "decisions": [{
                    "agent": decision["agent"],
                    "action": decision["action"],
                    "source": decision["decision_source"],
                    "validation": decision["validation"],
                    "candidate_scores": {action_id: values["score"]
                        for action_id, values in decision["candidate_scores"].items()},
                    "selected_score": (decision["selected_action_score"]["score"]
                        if decision["selected_action_score"] else None),
                    "selected_weighted_components": (decision["selected_action_score"]["weighted_components"]
                        if decision["selected_action_score"] else {}),
                    "state_changes": decision["state_changes"],
                } for decision in result["decisions"]],
                "final_state": result["final_state"],
                "forecast": result["forecast"],
                "all_actions_valid": result["all_actions_valid"],
            }
    print(json.dumps(compact, indent=2, sort_keys=True))
