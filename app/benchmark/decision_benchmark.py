"""Run configured and mock-LLM policies against a synthetic case without quality claims."""
from __future__ import annotations

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.agents.llm import MockLLMDecisionPolicy
from app.domain.definitions import SimulationDefinition
from app.simulation.engine import SimulationEngine


def declining_share_fixture() -> SimulationDefinition:
    return SimulationDefinition.model_validate({
        "metadata": {"id": "synthetic-declining-share", "name": "Synthetic competitor response"},
        "initial_world_state": {"time": 0, "variables": {
            "competitor_market_share": 0.17, "competitor_price": 90000,
            "competitor_promotion": 1.0, "promotion_capacity": 100,
            "price_cut_count": 1}},
        "evidence": [{
            "evidence_id": "SYNTH-COMP-SHARE", "title": "Synthetic share response example",
            "content": "Synthetic fixture only: promotion remains available after one price cut.",
            "source": "SYNTHETIC / benchmark fixture", "source_type": "synthetic_case_note",
            "date": "2026-01-01", "domain": "synthetic_life_sciences",
            "tags": ["competitor", "market_share", "promotion"],
            "reliability_label": "illustrative", "applicable_agents": ["competitor"],
            "related_variables": ["competitor_market_share", "promotion_capacity", "price_cut_count"],
            "related_actions": ["increase_promotion", "maintain_strategy"]}],
        "agents": [{"id": "competitor", "name": "Competitor", "type": "competitor",
            "objective": "respond to share loss using remaining options",
            "observable_state": ["competitor_market_share", "competitor_price", "competitor_promotion",
                                 "promotion_capacity", "price_cut_count"],
            "available_actions": ["increase_promotion", "maintain_strategy", "price_cut"],
            "decision_policy": {"rules": [{"when_event": "market_share_decline",
                "when": [{"variable": "price_cut_count", "operator": "gte", "value": 1}],
                "plausible_actions": ["increase_promotion", "maintain_strategy"],
                "reason": "The configured single price cut is already used; promotion or maintaining remain."}],
                "default_actions": ["maintain_strategy"]}}],
        "action_definitions": [
            {"id": "increase_promotion", "name": "Increase promotion", "agent_id": "competitor",
             "strategy": "promotion", "constraints": {"compatible_when": [
                 {"variable": "promotion_capacity", "operator": "gte", "value": 10}]},
             "effects": [{"variable": "competitor_promotion", "operation": "add", "value": 0.1},
                         {"variable": "promotion_capacity", "operation": "add", "value": -10, "minimum": 0}]},
            {"id": "maintain_strategy", "name": "Maintain strategy", "agent_id": "competitor",
             "strategy": "maintain", "effects": []},
            {"id": "price_cut", "name": "Price cut", "agent_id": "competitor",
             "strategy": "price_cut", "constraints": {"compatible_when": [
                 {"variable": "price_cut_count", "operator": "eq", "value": 0}]},
             "effects": [{"variable": "competitor_price", "operation": "multiply", "value": 0.9},
                 {"variable": "price_cut_count", "operation": "add", "value": 1}]}],
        "trigger_definitions": [{"id": "share-decline", "event_types": ["market_share_decline"],
            "affected_agents": ["competitor"], "priority": 1}],
        "settings": {"time_horizon": 1, "initial_events": [{"id": "decline", "time": 0,
            "event_type": "market_share_decline", "description": "Synthetic competitor share decline"}]},
        "scenario_generation": {"policy": "exhaustive", "max_scenarios": None}})


def _mock_response(context, _prompt):
    ids = {action.id for action in context.available_actions}
    primary = "increase_promotion" if "increase_promotion" in ids else next(iter(sorted(ids)), "")
    alternatives = [action_id for action_id in ("maintain_strategy",)
                    if action_id in ids and action_id != primary]
    return DecisionResponse(primary_action=primary, alternative_actions=alternatives,
        rationale="Promotion remains feasible in the supplied synthetic record [SYNTH-COMP-SHARE].",
        facts_used=["price_cut_count = 1"], evidence_used=["SYNTH-COMP-SHARE"],
        assumptions=["The benchmark fixture's configured action set is complete."],
        strategy_change="promotion")


def run_benchmark() -> dict:
    definition = declining_share_fixture()
    policies = {"rule_based": RuleBasedDecisionPolicy(),
                "mock_llm": MockLLMDecisionPolicy(_mock_response)}
    report = {"scenario": definition.metadata.name, "synthetic": True,
        "fixture_conditions": {"share_declining": True, "promotion_capacity": 100,
                                     "price_cut_count": 1},
              "expected_plausible_actions": ["increase_promotion", "maintain_strategy"],
              "results": {}}
    for name, policy in policies.items():
        result = SimulationEngine(decision_policy=policy).run(definition.model_copy(deep=True))
        decisions = [item for item in result.scenarios[0].decision_trace if item.event_type == "decision"]
        trace = decisions[0] if decisions else None
        report["results"][name] = {"primary_action": trace.decision_response.primary_action if trace else None,
            "candidate_actions": ([trace.decision_response.primary_action,
                *trace.decision_response.alternative_actions] if trace else []),
            "scenario_count": len(result.scenarios),
            "validation": trace.validation_status if trace else "no decision",
            "evidence_ids": ([item.evidence_id for item in trace.decision_context.relevant_evidence]
                             if trace else [])}
    return report


if __name__ == "__main__":
    import json
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
