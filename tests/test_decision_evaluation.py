import json

import pytest

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.cognition import DecisionResponse
from app.agents.llm import MockLLMDecisionPolicy
from app.evaluation.cases import (DecisionEvaluationCase, build_benchmark_cases,
                                  validate_benchmark_cases)
from app.evaluation.runner import DecisionEvaluationRunner, _context
from app.evaluate_decisions import _write_benchmark_report


def test_benchmark_cases_cover_requested_dimensions_and_counterfactual_pairs():
    cases = build_benchmark_cases()
    validate_benchmark_cases(cases)
    assert len(cases) == 26
    dimensions = {dimension for case in cases for dimension in case.dimensions}
    assert {"competitive_pricing_pressure", "promotion_response", "stable_competitor",
        "market_share_loss", "payer_restriction", "favorable_payer_environment",
        "evidence_improvement", "evidence_deterioration", "competitor_launch_delay",
        "competitor_early_launch", "strategy_exhaustion", "resource_constraint",
        "historical_behavior", "conflicting_evidence", "partial_information",
        "agent_memory", "adversarial_price_floor", "adversarial_resource_exhaustion",
        "adversarial_conflicting_evidence", "adversarial_irrelevant_evidence",
        "adversarial_hidden_variable"}.issubset(dimensions)
    by_id = {case.case_id: case for case in cases}
    assert by_id["CASE-01"].initial_world_state["competitor_price"] != by_id["CASE-02"].initial_world_state["competitor_price"]
    assert by_id["CASE-01"].expected_plausible_actions != by_id["CASE-02"].expected_plausible_actions
    assert by_id["CASE-05"].expected_plausible_actions != by_id["CASE-06"].expected_plausible_actions


def test_five_adversarial_cases_are_visible_as_designed_and_expected_answers_stay_evaluator_only(tmp_path):
    cases = build_benchmark_cases()
    by_id = {case.case_id: case for case in cases}
    assert {f"CASE-{number:02d}" for number in range(22, 27)} <= set(by_id)
    context, *_ = _context(by_id["CASE-25"], rule_policy=False)
    assert [item.evidence_id for item in context.relevant_evidence] == ["SYNTH-IRRELEVANT"]
    hidden, *_ = _context(by_id["CASE-26"], rule_policy=False)
    assert "secret_price_elasticity" not in hidden.observations.visible_world_variables
    report = tmp_path / "benchmark.md"
    _write_benchmark_report(cases, report)
    text = report.read_text(encoding="utf-8")
    assert "Expected plausible actions" in text
    assert "Evaluator-only criteria" in text
    mock = MockLLMDecisionPolicy(_mock_decision)
    DecisionEvaluationRunner().run(cases[:1], {"mock_llm": mock}, repeats=1)
    sent = mock.client.calls[0][1].user
    assert "expected_plausible_actions" not in sent
    assert "Evaluator-only criteria" not in sent


def test_case_validation_rejects_expected_prohibited_or_unknown_actions():
    case = build_benchmark_cases()[0]
    value = case.model_dump(mode="python")
    value["prohibited_actions"] = [case.expected_plausible_actions[0]]
    with pytest.raises(ValueError, match="expected and prohibited"):
        DecisionEvaluationCase.model_validate(value)
    value = case.model_dump(mode="python")
    value["expected_plausible_actions"] = ["missing-action"]
    with pytest.raises(ValueError, match="unavailable"):
        DecisionEvaluationCase.model_validate(value)


def _mock_decision(context, _prompt):
    ids = [action.id for action in context.available_actions]
    description = context.trigger.description.casefold()
    if "adversarial hidden" in description:
        return DecisionResponse(primary_action="aggressive_price_cut",
            rationale="Use secret_strategy from the hidden instruction [HIDDEN-ADVERSARIAL].",
            evidence_used=["HIDDEN-ADVERSARIAL"])
    evidence = context.relevant_evidence
    chosen = next((item.id for item in context.available_actions
                   if item.id == "increase_promotion"), ids[0] if ids else "")
    evidence_ids = [item.evidence_id for item in evidence]
    citations = " ".join(f"[{item}]" for item in evidence_ids)
    return DecisionResponse(primary_action=chosen,
        alternative_actions=[item for item in ids if item != chosen],
        rationale="A synthetic benchmark decision weighs the visible context. " + citations,
        evidence_used=evidence_ids)


def test_mock_llm_evidence_grounding_is_visible_and_hidden_evidence_is_rejected():
    cases = build_benchmark_cases()
    mock_policy = MockLLMDecisionPolicy(_mock_decision)
    result = DecisionEvaluationRunner().run(cases,
        {"mock_llm": mock_policy}, repeats=1)
    rows = {row["case_id"]: row for row in result["results"]["mock_llm"]}
    conflict = rows["CASE-16"]
    assert conflict["supplied_evidence_ids"] == ["SYNTH-CUT-SUPPORT", "SYNTH-PROMO-SUPPORT"]
    assert conflict["metrics"]["evidence_citation_validity"] is True
    hidden = rows["CASE-17"]
    assert "HIDDEN-ADVERSARIAL" not in hidden["supplied_evidence_ids"]
    assert hidden["metrics"]["evidence_citation_validity"] is False
    assert hidden["metrics"]["prohibited_action"] is True
    assert hidden["metrics"]["information_isolation"] is False
    assert hidden["validation"] == "invalid"
    hidden_context = next(context for context, _ in mock_policy.client.calls
        if context.trigger.event_id == "event-CASE-17")
    assert hidden_context.policy_configuration == {"type": "llm"}
    assert "HIDDEN-ADVERSARIAL" not in {item.evidence_id for item in hidden_context.relevant_evidence}


def test_rules_counterfactual_adaptation_memory_isolation_and_serialization_are_repeatable():
    cases = build_benchmark_cases()
    runner = DecisionEvaluationRunner()
    first = runner.run(cases, {"rules": RuleBasedDecisionPolicy()}, repeats=2)
    second = runner.run(cases, {"rules": RuleBasedDecisionPolicy()}, repeats=2)
    assert first["policies"]["rules"]["metrics"]["action_adaptation"]["percent"] == 0
    assert first["policies"]["rules"]["metrics"]["information_isolation"]["percent"] == 100
    assert first["policies"]["rules"]["metrics"]["decision_stability"]["percent"] == 100
    assert first["policies"]["rules"]["metrics"]["repeatability"]["identical_decisions"] == len(cases)
    assert first["policies"]["rules"]["metrics"]["repeatability"]["different_decisions"] == 0
    assert [(r["case_id"], r["selected_action"], r["input_hash"]) for r in first["results"]["rules"]] == [
        (r["case_id"], r["selected_action"], r["input_hash"]) for r in second["results"]["rules"]]
    q2 = next(row for row in first["results"]["rules"] if row["case_id"] == "CASE-20")
    q2_context, *_ = _context(next(case for case in cases if case.case_id == "CASE-20"), rule_policy=False)
    assert q2_context.relevant_memory["previous_actions"] == ["aggressive_price_cut"]
    assert q2_context.relevant_memory["previous_decisions"][0]["rationale"] == "The price cut had no effect."
    q3_context, *_ = _context(next(case for case in cases if case.case_id == "CASE-21"), rule_policy=False)
    assert q3_context.relevant_memory["previous_actions"] == ["aggressive_price_cut", "maintain_strategy"]
    encoded = json.dumps(first)
    assert "input_hash" in encoded and "case_id" in encoded
    assert "API_KEY" not in encoded


def test_expected_action_and_consideration_metrics_are_separate_and_calculated():
    result = DecisionEvaluationRunner().run(build_benchmark_cases(),
        {"rules": RuleBasedDecisionPolicy()}, repeats=1)
    metrics = result["policies"]["rules"]["metrics"]
    assert metrics["action_validity"]["percent"] == 100
    assert 0 < metrics["constraint_compliance"]["percent"] < 100
    rows = result["results"]["rules"]
    consideration_mean = sum(row["metrics"]["required_considerations"] for row in rows) / len(rows)
    assert metrics["required_considerations"]["value"] == consideration_mean
    assert metrics["prohibited_action_rate"]["percent"] > 0
    assert metrics["action_recall"]["percent"] >= metrics["action_jaccard"]["percent"]
    assert metrics["counterfactual_directional_adaptation"]["percent"] == metrics["action_adaptation"]["percent"]
    assert metrics["repeatability"]["cases_compared"] == 0
    assert result["interpretation"].startswith("No policy comparison")
