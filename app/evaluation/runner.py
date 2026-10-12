"""Run and score decision policies on structured evaluation cases."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.agents.base import DecisionPolicy, RuleBasedDecisionPolicy
from app.agents.cognition import DecisionContext, ObservationModel, ObservedEvent, build_decision_context
from app.agents.evidence_retrieval import RuleBasedEvidenceRetriever
from app.domain.agent import AgentDefinition, AgentMemory, AgentState, BeliefState
from app.domain.event import SimulationEvent
from app.domain.world import WorldState
from app.services.evidence_store import InMemoryEvidenceStore
from app.domain.definitions import TriggerDefinition
from app.simulation.decision_validator import DecisionValidationError, DecisionValidator
from app.simulation.scheduler import TriggerMatch

from .cases import DecisionEvaluationCase


def _context(case: DecisionEvaluationCase, *, rule_policy: bool) -> tuple[DecisionContext, AgentDefinition, WorldState, TriggerMatch]:
    action_ids = [action.id for action in case.available_actions]
    # Expected action sets and rubric text are evaluator-only. Never put them in
    # the LLM context; the rule baseline alone receives its configured policy.
    config = dict(case.rule_policy) if rule_policy else {"type": "llm"}
    agent = AgentDefinition(id=case.agent_id, name=case.agent_name, type=case.agent_type,
        objective=case.objective, observable_state=case.observable_variables,
        available_actions=action_ids, constraints=case.constraints,
        decision_policy=config)
    world = WorldState(time=case.trigger.time, variables=case.initial_world_state)
    observation = ObservationModel().observe(agent, world, events=[case.trigger])
    memory_data = {key: value for key, value in case.memory.items()
                   if key in AgentMemory.model_fields}
    memory = AgentMemory.model_validate(memory_data)
    state = AgentState(agent_id=case.agent_id,
        current_strategy=case.memory.get("current_strategy"),
        previous_actions=list(case.memory.get("previous_actions", [])), memory=memory,
        belief_state=BeliefState(beliefs=case.beliefs))
    event = ObservedEvent(event_id=case.trigger.event_id, time=case.trigger.time,
        event_type=case.trigger.event_type, description=case.trigger.description,
        actor_id=case.trigger.actor_id, data={})
    context = build_decision_context(agent, state, observation, event, case.available_actions)
    evidence = RuleBasedEvidenceRetriever().retrieve(agent, context, InMemoryEvidenceStore(case.evidence))
    observation.relevant_evidence = evidence
    context = build_decision_context(agent, state, observation, event, case.available_actions)
    trigger_definition = TriggerDefinition(id=f"trigger-{case.case_id}",
        event_types=[case.trigger.event_type], affected_agents=[case.agent_id])
    trigger = TriggerMatch(trigger_definition, case.trigger)
    return context, agent, world, trigger


def _normalize(text: str) -> str:
    return re.sub(r"[_-]+", " ", text.casefold()).strip()


def _all_response_text(response) -> str:
    pieces = [response.rationale, *response.key_drivers, *response.facts_used,
              *response.assumptions]
    return _normalize(" ".join(pieces))


def _score_case(case, context, response, selected, errors, action_valid,
                constraints_valid) -> dict[str, Any]:
    known_evidence = {item.evidence_id for item in context.relevant_evidence}
    citations = set(re.findall(r"\[([A-Za-z0-9_-]+)\]", response.rationale))
    supplied_valid = (set(response.evidence_used) <= known_evidence and citations <= known_evidence
                      and citations <= set(response.evidence_used)
                      and set(response.evidence_used) <= citations)
    visible = set(context.observations.visible_world_variables)
    hidden = set(case.initial_world_state) - visible
    response_text = " ".join([response.primary_action, *response.alternative_actions,
                              response.rationale, *response.key_drivers, *response.facts_used,
                              *response.assumptions, *response.evidence_used]).casefold()
    isolation = not any(variable.casefold() in response_text for variable in hidden)
    text = _all_response_text(response)
    required = {}
    for driver in case.expected_considerations:
        token = _normalize(driver)
        required[driver] = bool(token and token in text)
    return {"action_validity": action_valid,
        "constraint_compliance": constraints_valid,
        "evidence_citation_validity": supplied_valid,
        "evidence_use": bool(response.evidence_used),
        "information_isolation": isolation,
        "required_considerations": (sum(required.values()) / len(required) if required else 1.0),
        "required_considerations_covered": required,
        "expected_primary_action": (None if case.expected_primary_action is None
                                     else selected == case.expected_primary_action),
        "prohibited_action": selected in case.prohibited_actions,
        "expected_action_set_recall": (len(set(response.alternative_actions + [selected]) &
            set(case.expected_plausible_actions)) / len(case.expected_plausible_actions)
            if case.expected_plausible_actions else 1.0),
        "action_recall": (len(set(response.alternative_actions + [selected]) &
            set(case.expected_plausible_actions)) / len(case.expected_plausible_actions)
            if case.expected_plausible_actions else 1.0),
        "action_jaccard": (len(set(response.alternative_actions + [selected]) &
            set(case.expected_plausible_actions)) /
            len(set(response.alternative_actions + [selected]) | set(case.expected_plausible_actions))
            if set(response.alternative_actions + [selected]) | set(case.expected_plausible_actions) else 1.0),
        "expected_action_set_precision": (len((set(response.alternative_actions + [selected]) - {""}) &
            set(case.expected_plausible_actions)) / len(set(response.alternative_actions + [selected]) - {""})
            if set(response.alternative_actions + [selected]) - {""} else 1.0),
        "validation_errors": list(dict.fromkeys(errors))}


class DecisionEvaluationRunner:
    def run(self, cases: list[DecisionEvaluationCase], policies: dict[str, DecisionPolicy],
            repeats: int = 2) -> dict[str, Any]:
        if repeats < 1:
            raise ValueError("repeats must be at least 1")
        if len({case.case_id for case in cases}) != len(cases):
            raise ValueError("case_id values must be unique")
        if not cases:
            raise ValueError("at least one evaluation case is required")
        if not policies:
            raise ValueError("at least one decision policy is required")
        results: dict[str, list[dict[str, Any]]] = {name: [] for name in policies}
        for policy_name, policy in policies.items():
            model = getattr(getattr(policy, "client", None), "model", "deterministic-rules")
            for repeat_index in range(repeats):
                for case in cases:
                    context, agent, world, trigger = _context(case,
                        rule_policy=isinstance(policy, RuleBasedDecisionPolicy))
                    input_json = context.model_dump_json(exclude_none=False)
                    input_hash = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
                    candidates = policy.get_plausible_actions(context)
                    candidate_ids = {action.id for action in candidates}
                    response = policy.decide(context, candidates)
                    response_errors = DecisionValidator.validate_response(context, response)
                    action_by_id = {action.id: action for action in case.available_actions}
                    selected = response.primary_action
                    action_valid = selected in candidate_ids and selected in action_by_id
                    errors = [*response.validation_errors, *response_errors]
                    constraints_valid = action_valid
                    if not action_valid:
                        errors.append(f"Selected action '{selected}' is not an allowed candidate.")
                    proposed = [selected, *response.alternative_actions]
                    for action_id in dict.fromkeys(proposed):
                        if action_id and action_id not in candidate_ids:
                            errors.append(f"Action '{action_id}' is outside the policy candidate set.")
                            constraints_valid = False
                            continue
                        if not action_id or action_id not in action_by_id:
                            constraints_valid = False
                            continue
                        try:
                            DecisionValidator().validate(agent, action_by_id[action_id], world, trigger, world.time)
                        except DecisionValidationError as error:
                            constraints_valid = False
                            errors.append(str(error))
                    if selected in case.prohibited_actions:
                        errors.append(f"Selected action '{selected}' is prohibited for this case.")
                    semantic_status = "valid" if not errors else "invalid"
                    response = response.model_copy(update={"validation_status": semantic_status,
                        "validation_errors": list(dict.fromkeys(errors))})
                    case_metrics = _score_case(case, context, response, selected,
                        errors, action_valid, constraints_valid)
                    results[policy_name].append({"case_id": case.case_id, "agent": case.agent_id,
                        "description": case.description, "dimensions": case.dimensions,
                        "policy": policy_name, "model": model, "repeat": repeat_index + 1,
                        "timestamp": datetime.now(timezone.utc).isoformat(), "input_hash": input_hash,
                        "input_context": context.model_dump(mode="json"),
                        "decision_response": response.model_dump(mode="json"),
                        "selected_action": selected, "alternatives": response.alternative_actions,
                        "action_set": [selected, *response.alternative_actions],
                        "evidence_used": response.evidence_used, "assumptions": response.assumptions,
                        "supplied_evidence_ids": sorted(item.evidence_id for item in context.relevant_evidence),
                        "candidate_action_ids": sorted(candidate_ids), "validation": semantic_status,
                        "metrics": case_metrics})
        summaries = {name: self._aggregate(cases, rows, repeats)
                     for name, rows in results.items()}
        return {"created_at": datetime.now(timezone.utc).isoformat(), "case_count": len(cases),
            "dimensions": sorted({dimension for case in cases for dimension in case.dimensions}),
            "benchmark_criteria": [{"case_id": case.case_id, "expected_plausible_actions": case.expected_plausible_actions,
                "expected_primary_action": case.expected_primary_action, "prohibited_actions": case.prohibited_actions,
                "expected_considerations": case.expected_considerations, "counterfactual_pair": case.counterfactual_pair,
                "changed_variable": case.changed_variable} for case in cases],
            "repeat_count": repeats, "policies": summaries, "results": results,
            "comparison": _compare(cases, results),
            "interpretation": _interpret(summaries)}

    @staticmethod
    def _aggregate(cases, rows, repeats):
        metrics = {"action_validity": [], "constraint_compliance": [],
            "evidence_citation_validity": [], "evidence_use": [], "information_isolation": [],
            "required_considerations": [], "prohibited_action_rate": [],
            "expected_action_set_recall": [], "expected_action_set_precision": [],
            "action_recall": [], "action_jaccard": []}
        by_case: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_case[row["case_id"]].append(row)
            for key in metrics:
                metric_key = "prohibited_action" if key == "prohibited_action_rate" else key
                value = row["metrics"][metric_key]
                metrics[key].append(float(value) if key != "prohibited_action_rate" else float(value))
        stable_cases = sum(1 for runs in by_case.values()
            if len({(row["selected_action"], tuple(sorted(row["alternatives"])),
                     tuple(sorted(row["evidence_used"])),
                     tuple(sorted(row["decision_response"].get("key_drivers", []))))
                    for row in runs}) == 1)
        adaptation_pairs = []
        grouped_cases: dict[str, list[DecisionEvaluationCase]] = defaultdict(list)
        for case in cases:
            if case.counterfactual_pair:
                grouped_cases[case.counterfactual_pair].append(case)
        for pair_id, pair_cases in grouped_cases.items():
            if len(pair_cases) < 2 or len({tuple(case.expected_plausible_actions) for case in pair_cases}) < 2:
                continue
            adaptation_pairs.append(pair_id)
        adaptation_success = 0
        for pair_id in adaptation_pairs:
            pair_cases = grouped_cases[pair_id]
            for repeat in range(repeats):
                pair_results = [next((row for row in by_case[case.case_id] if row["repeat"] == repeat + 1), None)
                                for case in pair_cases]
                if (len(pair_results) >= 2 and all(pair_results)
                        and len({row["selected_action"] for row in pair_results}) > 1
                        and all(row["selected_action"] in case.expected_plausible_actions
                                for row, case in zip(pair_results, pair_cases))):
                    adaptation_success += 1
        adaptation_total = len(adaptation_pairs) * repeats
        expected_primary_cases = {case.case_id for case in cases if case.expected_primary_action is not None}
        primary_rows = [row for row in rows if row["case_id"] in expected_primary_cases]
        primary_rate = (sum(bool(row["metrics"]["expected_primary_action"]) for row in primary_rows) /
                        len(primary_rows) if primary_rows else 1.0)
        stability = stable_cases / len(by_case) if by_case else 1.0
        return {"metrics": {key: {"value": (sum(values) / len(values) if values else 1.0),
                          "percent": round((sum(values) / len(values) if values else 1.0) * 100, 2),
                          "decisions": len(values)} for key, values in metrics.items()} |
                {"counterfactual_directional_adaptation": {"value": adaptation_success / adaptation_total if adaptation_total else 1.0,
                    "percent": round(adaptation_success / adaptation_total * 100, 2) if adaptation_total else 100,
                    "counterfactual_pairs": adaptation_total},
                 "action_adaptation": {"value": adaptation_success / adaptation_total if adaptation_total else 1.0,
                    "percent": round(adaptation_success / adaptation_total * 100, 2) if adaptation_total else 100,
                    "counterfactual_pairs": adaptation_total},
                 "decision_stability": {"value": stability, "percent": round(stability * 100, 2),
                    "cases_stable": stable_cases, "cases_total": len(by_case)},
                 "repeatability": _repeatability(rows),
                 "expected_primary_action": {"value": primary_rate, "percent": round(primary_rate * 100, 2),
                    "decisions": len(primary_rows)}},
            "case_count": len(by_case)}


def _repeatability(rows):
    by_case: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    compared = [runs for runs in by_case.values() if len(runs) > 1]
    if not compared:
        return {"cases_compared": 0, "identical_decisions": 0, "different_decisions": 0,
            "evidence_differences": 0, "rationale_differences": 0}
    action_signature = lambda row: (row["selected_action"], tuple(row["alternatives"]))
    return {"cases_compared": len(compared),
        "identical_decisions": sum(len({action_signature(row) for row in runs}) == 1 for runs in compared),
        "different_decisions": sum(len({action_signature(row) for row in runs}) > 1 for runs in compared),
        "evidence_differences": sum(len({tuple(sorted(row["evidence_used"])) for row in runs}) > 1 for runs in compared),
        "rationale_differences": sum(len({row["decision_response"]["rationale"] for row in runs}) > 1 for runs in compared)}


def _compare(cases, results):
    if len(results) < 2:
        return {"disagreements": [], "summary": "Run both policies to compare decisions."}
    names = list(results)
    left = {(row["case_id"], row["repeat"]): row for row in results[names[0]]}
    right = {(row["case_id"], row["repeat"]): row for row in results[names[1]]}
    descriptions = {case.case_id: case.description for case in cases}
    criteria = {case.case_id: case for case in cases}
    disagreements = []
    for key in sorted(left.keys() & right.keys()):
        if left[key]["selected_action"] != right[key]["selected_action"]:
            rules_row, llm_row = ((left[key], right[key]) if names[1] == "llm"
                                  else (right[key], left[key]))
            case = criteria[key[0]]
            acceptable = set(case.expected_plausible_actions)
            llm_metrics = llm_row["metrics"]
            if llm_row["selected_action"] in acceptable and rules_row["selected_action"] in acceptable:
                evaluation = "unclear"
            elif llm_row["selected_action"] in acceptable and rules_row["selected_action"] not in acceptable:
                evaluation = "plausible improvement"
            elif (not llm_metrics["action_validity"] or not llm_metrics["constraint_compliance"]
                  or not llm_metrics["information_isolation"] or not llm_metrics["evidence_citation_validity"]
                  or llm_metrics["prohibited_action"]):
                evaluation = "likely error"
            else:
                evaluation = "unclear"
            disagreements.append({"case_id": key[0], "repeat": key[1],
                names[0]: left[key]["selected_action"], names[1]: right[key]["selected_action"],
                "description": descriptions[key[0]],
                "rationales": {names[0]: left[key]["decision_response"]["rationale"],
                               names[1]: right[key]["decision_response"]["rationale"]},
                "evaluation": evaluation,
                "available_evidence": llm_row["input_context"]["relevant_evidence"],
                "relevant_context": llm_row["input_context"]["observations"]["visible_world_variables"],
                "llm_action_valid": llm_metrics["action_validity"],
                "llm_constraints_valid": llm_metrics["constraint_compliance"],
                "llm_information_isolation": llm_metrics["information_isolation"],
                "llm_evidence_grounded": llm_metrics["evidence_citation_validity"]})
    categories = {name: [entry for entry in disagreements if entry["evaluation"] == name]
                  for name in ("plausible improvement", "likely error", "unclear")}
    return {"disagreements": disagreements, "count": len(disagreements),
        "case_analysis": {"agree": len(left.keys() & right.keys()) - len(disagreements),
            "disagree": len(disagreements), "plausible_improvement": categories["plausible improvement"],
            "likely_error": categories["likely error"], "unclear": categories["unclear"],
            "llm_uses_evidence_where_rules_do_not": [case_id for case_id in criteria
                if any(row["case_id"] == case_id and row["metrics"]["evidence_citation_validity"]
                       and row["evidence_used"] for row in results.get("llm", []))
                and not any(row["case_id"] == case_id and row["evidence_used"] for row in results.get("rules", []))],
            "llm_constraint_failures": [row for row in results.get("llm", [])
                if not row["metrics"]["constraint_compliance"]],
            "llm_information_isolation_failures": [row for row in results.get("llm", [])
                if not row["metrics"]["information_isolation"]],
            "llm_grounding_failures": [row for row in results.get("llm", [])
                if not row["metrics"]["evidence_citation_validity"]],
            "llm_unstable_cases": [case_id for case_id, runs in _rows_by_case(results.get("llm", [])).items()
                if len({(row["selected_action"], tuple(row["alternatives"])) for row in runs}) > 1]}}


def _rows_by_case(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["case_id"]].append(row)
    return grouped


def _interpret(summaries):
    if len(summaries) < 2:
        return "No policy comparison is available in this run."
    names = list(summaries)
    baseline, comparison = summaries[names[0]]["metrics"], summaries[names[1]]["metrics"]
    wins = []
    for metric in ("action_validity", "constraint_compliance", "evidence_citation_validity", "evidence_use",
                   "information_isolation", "required_considerations", "action_adaptation", "decision_stability"):
        delta = comparison[metric]["value"] - baseline[metric]["value"]
        if delta > 0:
            wins.append(f"higher {metric.replace('_', ' ')}")
        elif delta < 0:
            wins.append(f"lower {metric.replace('_', ' ')}")
    prohibited_delta = (comparison["prohibited_action_rate"]["value"] -
                        baseline["prohibited_action_rate"]["value"])
    if prohibited_delta < 0:
        wins.append("lower prohibited action rate")
    elif prohibited_delta > 0:
        wins.append("higher prohibited action rate")
    if not wins:
        return "No measured difference on the reported dimensions; this is not an intelligence score."
    return f"Compared with {names[0]}, {names[1]} shows " + ", ".join(wins) + ". These are benchmark outcomes, not ground truth or an AI intelligence score."
