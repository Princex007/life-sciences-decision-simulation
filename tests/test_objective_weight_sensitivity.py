from app.evaluation.objective_weight_sensitivity import run_payer_ambiguity_evaluation


def test_payer_ambiguity_evaluation_records_rankings_and_separate_outcomes():
    report = run_payer_ambiguity_evaluation()

    low = report["access_weight_0.2"]
    assert low["branch_states_are_independent"] is True
    assert len(low["outcomes"]) == 2
    by_action = {item["payer"]["selected_action"]: item for item in low["outcomes"]}
    assert set(by_action) == {"restricted_access", "favorable_access"}

    for outcome in low["outcomes"]:
        payer = outcome["payer"]
        assert payer["highest_scoring_feasible_action"] == "favorable_access"
        assert payer["highest_score"] > payer["runner_up_score"]
        assert payer["score_margin"] < payer["tie_tolerance"] == 0.005
        assert payer["decision_source"] == "existing_policy_fallback"
        assert payer["fallback_dependent"] is True
        assert outcome["all_decisions_valid"] is True
        assert len(outcome["action_sequence"]) == 5

    assert by_action["restricted_access"]["final_state"]["payer_access"] == 0.55
    assert by_action["favorable_access"]["final_state"]["payer_access"] == 0.9
    assert by_action["restricted_access"]["forecast"]["cumulative_sales"] == 22_695_000
    assert by_action["favorable_access"]["forecast"]["cumulative_sales"] == 668_695_000


def test_payer_decisive_weight_and_restricted_counterfactual_are_explicit():
    report = run_payer_ambiguity_evaluation()
    high = report["access_weight_0.3"]
    decisive = high["decisive_outcome"]
    payer = decisive["payer"]

    assert payer["highest_scoring_feasible_action"] == "favorable_access"
    assert payer["selected_action"] == "favorable_access"
    assert payer["decision_source"] == "objective_scorer"
    assert payer["decisive"] is True
    assert payer["fallback_dependent"] is False
    assert payer["score_margin"] > payer["tie_tolerance"]
    assert decisive["all_decisions_valid"] is True

    counterfactual = high["restricted_access_counterfactual"]
    assert counterfactual["payer"]["selected_action"] == "restricted_access"
    assert counterfactual["payer"]["decision_source"] == "existing_policy_fallback"
    assert counterfactual["final_state"]["payer_access"] == 0.55
    assert counterfactual["forecast"]["cumulative_sales"] == 22_695_000
    assert high["counterfactual_fallback_dependent"] is True
    assert report["llm_calls"] == 0
