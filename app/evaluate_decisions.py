"""Evaluate launch decision policies on synthetic cases and save a JSON report."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.agents.base import RuleBasedDecisionPolicy
from app.agents.llm import LLMConfigurationError, LLMDecisionPolicy
from app.evaluation.cases import build_benchmark_cases, validate_benchmark_cases
from app.evaluation.runner import DecisionEvaluationRunner


LABELS = {
    "action_validity": "Action validity", "constraint_compliance": "Constraint compliance",
    "evidence_citation_validity": "Evidence citation validity",
    "evidence_use": "Evidence use",
    "information_isolation": "Information isolation",
    "required_considerations": "Required considerations",
    "expected_primary_action": "Expected primary action",
    "prohibited_action_rate": "Prohibited action rate",
    "expected_action_set_precision": "Expected action-set precision",
    "action_adaptation": "Counterfactual directional adaptation",
    "action_recall": "Action recall", "action_jaccard": "Action Jaccard",
    "decision_stability": "Decision stability"}


def _write_benchmark_report(cases, output: Path):
    """Write the complete input and evaluator rubric before any policy is run."""
    from app.evaluation.runner import _context
    lines = ["# Decision Benchmark", "", f"Cases: {len(cases)}", "",
        "Expected answers below are evaluator-only. They are not included in the LLM DecisionContext.", ""]
    for case in cases:
        context, *_ = _context(case, rule_policy=False)
        lines += [f"## {case.case_id} — {case.agent_name}", "", f"Objective: {case.objective}",
            f"Description: {case.description}", "", "Available actions:"]
        lines.extend(f"- `{a.id}` — {a.description or a.name}; constraints: `{a.constraints}`" for a in context.available_actions)
        lines += ["", "Visible variables:"]
        lines.extend(f"- `{key}`: `{value}`" for key, value in context.observations.visible_world_variables.items())
        lines += ["", "Visible evidence:"]
        if context.relevant_evidence:
            lines.extend(f"- `{e.evidence_id}` ({e.title}): {e.content}" for e in context.relevant_evidence)
        else:
            lines.append("- None")
        lines += ["", "**Evaluator-only criteria (not sent to the LLM):**",
            f"- Expected plausible actions: {', '.join(case.expected_plausible_actions) or 'None'}",
            f"- Prohibited actions: {', '.join(case.prohibited_actions) or 'None'}",
            f"- Required strategic considerations: {', '.join(case.expected_considerations) or 'None'}",
            f"- Counterfactual relationship: {case.counterfactual_pair or 'None'}; changed variable: {case.changed_variable or 'None'}", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _format_report(result):
    policies = result["policies"]
    names = list(policies)
    headers = ["Metric", *names]
    rows = []
    for metric, label in LABELS.items():
        values = [f"{policies[name]['metrics'][metric]['percent']:.1f}%" for name in names]
        rows.append([label, *values])
    widths = [max(len(headers[index]), *(len(row[index]) for row in rows)) for index in range(len(headers))]
    title = "REAL LLM DECISION EVALUATION" if "llm" in names else "RULES BASELINE EVALUATION"
    print(f"{title}\n{'=' * len(title)}\n")
    print(f"Cases: {result['case_count']}   Repeats: {result['repeat_count']}")
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    disagreements = result.get("comparison", {}).get("disagreements", [])
    print(f"\nCase-by-case primary-action disagreements: {len(disagreements)}")
    for entry in disagreements:
        print(f"\n{entry['case_id']}: {entry[names[0]]} ({names[0]}) vs {entry[names[1]]} ({names[1]})")
        print("Why:", entry["description"])
        print(f"{names[0]} rationale: {entry['rationales'][names[0]]}")
        print(f"{names[1]} rationale: {entry['rationales'][names[1]]}")
    print("\nWhere the LLM may add value:")
    print(result["interpretation"])


def _write_quality_report(result, output: Path):
    policies = result["policies"]
    names = list(policies)
    title = "REAL LLM DECISION EVALUATION" if "llm" in names else "RULES BASELINE EVALUATION"
    lines = [f"# {title}", "", f"Cases: {result['case_count']}", "", "| Metric | " + " | ".join(names) + " |",
        "|---|" + "|".join("---" for _ in names) + "|"]
    for metric, label in LABELS.items():
        lines.append("| " + label + " | " + " | ".join(
            f"{policies[name]['metrics'][metric]['percent']:.1f}%" for name in names) + " |")
    lines += ["", "## Repeatability"]
    for name in names:
        repeat = policies[name]["metrics"]["repeatability"]
        lines.append(f"- {name}: {repeat['identical_decisions']} identical strategic decisions; "
            f"{repeat['different_decisions']} different; evidence changed in {repeat['evidence_differences']} cases; "
            f"rationale changed in {repeat['rationale_differences']} cases.")
    comparison = result.get("comparison", {}).get("case_analysis", {})
    if comparison:
        lines += ["", "## Case analysis", "",
            f"Agree: {comparison.get('agree', 0)}; disagree: {comparison.get('disagree', 0)}.",
            f"LLM grounded evidence use where rules did not: {comparison.get('llm_uses_evidence_where_rules_do_not', [])}.",
            f"LLM constraint failures: {len(comparison.get('llm_constraint_failures', []))}; "
            f"information-isolation failures: {len(comparison.get('llm_information_isolation_failures', []))}; "
            f"grounding failures: {len(comparison.get('llm_grounding_failures', []))}; "
            f"unstable cases: {comparison.get('llm_unstable_cases', [])}.", ""]
        for entry in result.get("comparison", {}).get("disagreements", []):
            lines += [f"### {entry['case_id']} — {entry['evaluation']}", "", entry["description"], "",
                f"Rule-based: {entry.get('rules', '')}", f"LLM: {entry.get('llm', '')}",
                f"Why decisions differ: {entry['rationales']}",
                f"Available evidence: {entry.get('available_evidence', [])}",
                f"Relevant context: {entry.get('relevant_context', {})}", ""]
    lines += ["", "## Interpretation", "", result["interpretation"],
        "", "These are synthetic benchmark outcomes, not predictive accuracy or model-generated self-evaluation.", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=("rules", "llm", "both"), default="both")
    parser.add_argument("--repeat", type=int, default=2, help="Runs per case for stability measurement")
    parser.add_argument("--model", help="Optional model override; API key remains server-side in LLM_API_KEY")
    parser.add_argument("--temperature", type=float, help="Optional temperature override (0 to 2)")
    parser.add_argument("--output", type=Path, help="JSON output path (defaults to a timestamped file under evaluation_results/)")
    parser.add_argument("--report", type=Path, help="Readable Markdown report path (defaults beside the JSON output)")
    parser.add_argument("--prepare-only", action="store_true", help="Write benchmark inputs and evaluator rubric without running a policy")
    parser.add_argument("--benchmark-report", type=Path, default=Path("evaluation_results/benchmark-report.md"))
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    if args.temperature is not None:
        os.environ["LLM_TEMPERATURE"] = str(args.temperature)

    cases = build_benchmark_cases()
    validate_benchmark_cases(cases)
    report_path = _write_benchmark_report(cases, args.benchmark_report)
    print(f"Prepared benchmark report: {report_path.resolve()}")
    if args.prepare_only:
        return

    policies = {}
    if args.policy in {"rules", "both"}:
        policies["rules"] = RuleBasedDecisionPolicy()
    if args.policy in {"llm", "both"}:
        try:
            policies["llm"] = LLMDecisionPolicy.from_environment()
        except LLMConfigurationError as error:
            parser.error(str(error))
    try:
        result = DecisionEvaluationRunner().run(cases, policies, repeats=args.repeat)
    except LLMConfigurationError as error:
        parser.error(str(error))
    output = args.output
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = Path("evaluation_results") / f"decision-evaluation-{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    report_output = args.report or output.with_suffix(".md")
    _write_quality_report(result, report_output)
    _format_report(result)
    print(f"\nSaved evaluation JSON: {output.resolve()}")
    print(f"Saved readable report: {report_output.resolve()}")


if __name__ == "__main__":
    main()
