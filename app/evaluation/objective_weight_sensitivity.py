"""Stress-test hybrid outcomes under bounded illustrative objective weights.

All runs use fresh copies of the existing one-quarter example scenario and a
deterministic rule-policy fallback. Weight changes are applied only in memory;
the production JSON and engine behavior are not modified.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.agents.cognition import DecisionResponse
from app.domain.definitions import SimulationDefinition
from app.evaluation.compare_hybrid_rule_based import DeterministicRulePolicy
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.registry import ForecastRegistry
from app.simulation.engine import SimulationEngine


WEIGHT_GRID = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
SCENARIOS = {
    "baseline": {},
    "competitive_pressure": {"competitor_price": 70000},
    "restricted_access": {"payer_access": 0.50},
}


class PayerBranchPolicy(DeterministicRulePolicy):
    """Expose exactly the requested payer alternatives at an ambiguous score."""

    def __init__(self, forced_payer_action: str | None = None, branch_payer: bool = False):
        self.forced_payer_action = forced_payer_action
        self.branch_payer = branch_payer

    def decide(self, context, actions):
        if context.agent_id == "payer" and self.forced_payer_action:
            return DecisionResponse(primary_action=self.forced_payer_action,
                rationale="Evaluation-only counterfactual Payer action.")
        if context.agent_id == "payer" and self.branch_payer:
            action_ids = {action.id for action in actions}
            if {"restricted_access", "favorable_access"}.issubset(action_ids):
                return DecisionResponse(primary_action="restricted_access",
                    alternative_actions=["favorable_access"],
                    rationale="Evaluation-only branch over two feasible Payer choices.")
        return super().decide(context, actions)


def _selection_diagnostics(decision, objective: dict[str, Any] | None) -> dict[str, Any]:
    scores = decision.decision_context.objective_scores or {}
    ranked = sorted(scores.items(), key=lambda item: (-item[1]["score"], item[0]))
    highest = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = (highest[1]["score"] - runner_up[1]["score"]
              if highest and runner_up else None)
    tolerance = objective.get("score_tie_tolerance") if objective else None
    source = decision.decision_source
    return {
        "highest_scoring_feasible_action": highest[0] if highest else None,
        "highest_score": highest[1]["score"] if highest else None,
        "runner_up_action": runner_up[0] if runner_up else None,
        "runner_up_score": runner_up[1]["score"] if runner_up else None,
        "score_margin": margin,
        "tie_tolerance": tolerance,
        "selected_action": decision.action.action_id if decision.action else None,
        "decision_source": source,
        "decisive": source == "objective_scorer",
        "fallback_dependent": bool(objective) and source != "objective_scorer",
        "objective_scores": {action_id: value["score"]
                              for action_id, value in scores.items()},
    }


def _run_one(scenario: dict[str, Any], changes: dict[str, list[float]] | None = None) -> dict[str, Any]:
    path = Path(__file__).parents[2] / "examples" / "us_drug_launch.json"
    definition = SimulationDefinition.from_json(str(path))
    definition.settings.time_horizon = 1
    definition.settings.scheduled_events = []
    definition.scenario_generation.max_scenarios = 1
    for variable, value in scenario.items():
        definition.initial_world_state.set(variable, value)
    if changes:
        for objective_agent, component_weights in changes.items():
            components = definition.evaluation_objectives[objective_agent]["components"]
            if len(components) != len(component_weights):
                raise ValueError(f"Invalid component-weight count for {objective_agent}.")
            if abs(sum(component_weights) - 1.0) > 1e-9:
                raise ValueError(f"Weights for {objective_agent} must sum to one.")
            for component, weight in zip(components, component_weights):
                component["weight"] = weight

    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    result = SimulationEngine(registry, decision_policy=DeterministicRulePolicy()).run(definition)
    if len(result.scenarios) != 1:
        raise AssertionError("Sensitivity run did not produce exactly one terminal scenario.")
    terminal = result.scenarios[0]
    decisions = [entry for entry in terminal.decision_trace
                 if entry.event_type == "decision" and entry.action]
    expected = ["company", "competitor", "payer", "physician", "patient"]
    if [entry.agent_id for entry in decisions] != expected:
        raise AssertionError("A stakeholder did not act in the expected order.")
    if any(entry.validation_status != "valid" for entry in decisions):
        raise AssertionError("Sensitivity run contained an invalid selected action.")
    payer_objective = definition.evaluation_objectives.get("payer")
    return {
        "actions": {entry.agent_id: entry.action.action_id for entry in decisions},
        "sources": {entry.agent_id: entry.decision_source for entry in decisions},
        "payer_scores": decisions[2].decision_context.objective_scores,
        "payer_margin": decisions[2].objective_score_margin,
        "payer_selection": _selection_diagnostics(decisions[2], payer_objective),
        "final_state": {name: terminal.final_state.get(name) for name in (
            "payer_access", "market_share", "competitor_market_share",
            "physician_adoption", "patient_adherence_rate")},
        "forecast": terminal.forecast.metrics if terminal.forecast else {},
    }


def _bounded_definition(path: Path, payer_access_weight: float) -> SimulationDefinition:
    definition = SimulationDefinition.from_json(str(path))
    definition.settings.time_horizon = 1
    definition.settings.scheduled_events = []
    definition.scenario_generation.max_scenarios = 10
    components = definition.evaluation_objectives["payer"]["components"]
    components[0]["weight"] = payer_access_weight
    components[1]["weight"] = 1.0 - payer_access_weight
    return definition


def _terminal_summary(scenario, payer_objective) -> dict[str, Any]:
    decisions = [entry for entry in scenario.decision_trace
                 if entry.event_type == "decision" and entry.action]
    payer_decision = next(entry for entry in decisions if entry.agent_id == "payer")
    return {
        "payer": _selection_diagnostics(payer_decision, payer_objective),
        "action_sequence": [{"agent": item.agent_id, "action": item.action.action_id,
                             "source": item.decision_source,
                             "validation": item.validation_status}
                            for item in decisions],
        "final_state": scenario.final_state.as_variables(),
        "forecast": scenario.forecast.metrics if scenario.forecast else {},
        "all_decisions_valid": all(item.validation_status == "valid" for item in decisions),
    }


def _run_ambiguity_case(weight: float, *, branch: bool = False,
                        forced_action: str | None = None) -> dict[str, Any]:
    path = Path(__file__).parents[2] / "examples" / "us_drug_launch.json"
    definition = _bounded_definition(path, weight)
    if forced_action:
        # Counterfactual only: remove the Payer objective on this fresh copy so
        # the requested action enters through the regular fake-policy path.
        definition.evaluation_objectives.pop("payer")
    registry = ForecastRegistry()
    registry.register("launch_revenue", LaunchForecast())
    policy = PayerBranchPolicy(forced_payer_action=forced_action, branch_payer=branch)
    result = SimulationEngine(registry, decision_policy=policy).run(definition)
    if not result.scenarios:
        raise AssertionError("Payer sensitivity case produced no terminal scenarios.")
    summaries = [_terminal_summary(item, definition.evaluation_objectives.get("payer"))
                 for item in result.scenarios]
    if any(not item["all_decisions_valid"] for item in summaries):
        raise AssertionError("Payer sensitivity branch contained an invalid decision.")
    return {"outcomes": summaries,
            "branch_states_are_independent": len({id(item.final_state)
                for item in result.scenarios}) == len(result.scenarios)}


def run_payer_ambiguity_evaluation() -> dict[str, Any]:
    """Compare separate feasible outcomes at weights 0.2 and 0.3.

    The 0.2 engine run branches at the actual ambiguous Payer decision.
    At 0.3 the engine selects decisively; a separate copied definition is
    used for the restricted-access counterfactual while retaining other
    stakeholders' normal hybrid scoring.
    """
    path = Path(__file__).parents[2] / "examples" / "us_drug_launch.json"
    branch_02 = _run_ambiguity_case(0.2, branch=True)
    outcomes_02 = branch_02["outcomes"]
    if {item["payer"]["selected_action"] for item in outcomes_02} != {
            "restricted_access", "favorable_access"}:
        raise AssertionError("Ambiguous Payer run did not retain both requested alternatives.")
    outcomes_03 = _run_ambiguity_case(0.3)["outcomes"]
    if len(outcomes_03) != 1 or outcomes_03[0]["payer"]["selected_action"] != "favorable_access":
        raise AssertionError("Weight 0.3 should have one decisive favorable-access outcome.")
    counterfactual_restricted_03 = _run_ambiguity_case(
        0.3, forced_action="restricted_access")["outcomes"]
    if len(counterfactual_restricted_03) != 1:
        raise AssertionError("Expected one restricted-access counterfactual at weight 0.3.")
    return {
        "scenario": "baseline",
        "initial_state": SimulationDefinition.from_json(str(path)).initial_world_state.as_variables(),
        "tie_tolerance": 0.005,
        "access_weight_0.2": {
            "weights": {"payer_access": 0.2, "modeled_drug_expenditure_proxy": 0.8},
            "outcomes": outcomes_02,
            "branch_states_are_independent": branch_02["branch_states_are_independent"],
        },
        "access_weight_0.3": {
            "weights": {"payer_access": 0.3, "modeled_drug_expenditure_proxy": 0.7},
            "decisive_outcome": outcomes_03[0],
            "restricted_access_counterfactual": counterfactual_restricted_03[0],
            "counterfactual_fallback_dependent": True,
        },
        "llm_calls": 0,
    }


def _weights_for_sweep(agent: str, component_index: int, value: float,
                       base_weights: list[float]) -> list[float]:
    rest = sum(weight for index, weight in enumerate(base_weights)
               if index != component_index)
    if rest <= 0:
        raise ValueError(f"Cannot redistribute remaining weights for {agent}.")
    result = [value if index == component_index else
              (1.0 - value) * weight / rest
              for index, weight in enumerate(base_weights)]
    if abs(sum(result) - 1.0) > 1e-9:
        raise AssertionError("Weight redistribution did not preserve a unit sum.")
    return result


def run_sensitivity() -> dict[str, Any]:
    path = Path(__file__).parents[2] / "examples" / "us_drug_launch.json"
    source = SimulationDefinition.from_json(str(path))
    base_weights = {
        agent: [component["weight"] for component in objective["components"]]
        for agent, objective in source.evaluation_objectives.items()
    }
    baselines = {scenario_name: _run_one(overrides)
                 for scenario_name, overrides in SCENARIOS.items()}

    sweeps: dict[str, Any] = {}
    for agent, original_weights in base_weights.items():
        components = source.evaluation_objectives[agent]["components"]
        if len(components) < 2:
            continue
        sweeps[agent] = {}
        for index, component in enumerate(components):
            metric_name = component["name"]
            cases = []
            for scenario_name, overrides in SCENARIOS.items():
                for value in WEIGHT_GRID:
                    weights = _weights_for_sweep(agent, index, value, original_weights)
                    output = _run_one(overrides, {agent: weights})
                    cases.append({
                        "scenario": scenario_name,
                        "varied_metric": metric_name,
                        "varied_weight": value,
                        "weights": weights,
                        "payer_action": output["actions"]["payer"],
                        "actions": output["actions"],
                        "sources": output["sources"],
                        "payer_scores": output["payer_scores"],
                        "payer_margin": output["payer_margin"],
                        "final_state": output["final_state"],
                        "forecast": output["forecast"],
                    })
            sweeps[agent][metric_name] = cases

    return {
        "description": "One-factor-at-a-time illustrative weight stress test; not a probability distribution or calibrated analysis.",
        "weight_grid": list(WEIGHT_GRID),
        "scenario_overrides": deepcopy(SCENARIOS),
        "baseline_weights": base_weights,
        "company_weight_variation": "Not applicable: Company has one configured component, so its weight must remain 1.0.",
        "baseline_hybrid_runs": baselines,
        "sweeps": sweeps,
        "llm_calls": 0,
    }


if __name__ == "__main__":
    detailed = run_sensitivity()
    payer_rows = []
    for scenario_name in SCENARIOS:
        for case in detailed["sweeps"]["payer"]["payer_access"]:
            if case["scenario"] != scenario_name:
                continue
            payer_rows.append({
                "scenario": scenario_name,
                "access_weight": case["weights"][0],
                "expenditure_weight": case["weights"][1],
                "payer_action": case["payer_action"],
                "payer_source": case["sources"]["payer"],
                "score_margin": case["payer_margin"],
                "payer_selection": case["payer_selection"],
                "payer_scores": {key: value["score"]
                    for key, value in case["payer_scores"].items()},
                "other_actions": {key: value for key, value in case["actions"].items()
                                  if key != "payer"},
                "final_state": case["final_state"],
                "forecast": {key: case["forecast"][key] for key in (
                    "cumulative_sales", "patients_treated", "market_share")},
            })
    other_summary = {}
    for agent, metric_sweeps in detailed["sweeps"].items():
        if agent == "payer":
            continue
        other_summary[agent] = {}
        for metric, cases in metric_sweeps.items():
            other_summary[agent][metric] = {}
            for scenario_name in SCENARIOS:
                selected = [item for item in cases if item["scenario"] == scenario_name]
                states = [item["final_state"] for item in selected]
                forecasts = [item["forecast"] for item in selected]
                other_summary[agent][metric][scenario_name] = {
                    "weight_to_agent_action": {str(item["varied_weight"]): item["actions"][agent]
                                                for item in selected},
                    "weight_to_payer_action": {str(item["varied_weight"]): item["payer_action"]
                                               for item in selected},
                    "distinct_action_sequences": list(dict.fromkeys(
                        tuple(item["actions"][key] for key in
                              ("company", "competitor", "payer", "physician", "patient"))
                        for item in selected)),
                    "outcome_ranges": {
                        "payer_access": [min(s["payer_access"] for s in states),
                                         max(s["payer_access"] for s in states)],
                        "market_share": [min(s["market_share"] for s in states),
                                         max(s["market_share"] for s in states)],
                        "cumulative_sales": [min(f["cumulative_sales"] for f in forecasts),
                                              max(f["cumulative_sales"] for f in forecasts)],
                        "patients_treated": [min(f["patients_treated"] for f in forecasts),
                                             max(f["patients_treated"] for f in forecasts)],
                    },
                }
    baseline_summary = {
        scenario: {
            "actions": outcome["actions"],
            "sources": outcome["sources"],
            "final_state": outcome["final_state"],
            "forecast": outcome["forecast"],
            "payer_scores": {key: value["score"]
                for key, value in outcome["payer_scores"].items()},
        } for scenario, outcome in detailed["baseline_hybrid_runs"].items()
    }
    compact = {
        "description": detailed["description"],
        "weight_grid": detailed["weight_grid"],
        "baseline_weights": detailed["baseline_weights"],
        "scenario_overrides": detailed["scenario_overrides"],
        "company_weight_variation": detailed["company_weight_variation"],
        "baseline_hybrid_runs": baseline_summary,
        "payer_sensitivity": payer_rows,
        "other_stakeholder_sensitivity": other_summary,
        "llm_calls": detailed["llm_calls"],
        "payer_ambiguity_evaluation": run_payer_ambiguity_evaluation(),
    }
    print(json.dumps(compact, indent=2, sort_keys=True))
