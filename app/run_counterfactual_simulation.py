"""Run and compare two counterfactual five-agent two-round local LLM simulations.

Baseline: Default local 5-agent 2-round definition.
Counterfactual: Meaningful upstream change (competitor_price reduced from 950 to 600,
representing aggressive competitor price defense).
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from urllib.parse import urlparse

from app.agents.llm import LLMConfigurationError, OpenAICompatibleLLMClient
from app.domain.definitions import SimulationDefinition
from app.services.simulation_runner import SimulationRunnerService
from app.run_five_agent_simulation import TracingLocalClient


ROOT = Path(__file__).resolve().parents[1]
BASELINE_DEFINITION_PATH = ROOT / "examples" / "local_5agent_2round_smoke.json"
EXPECTED_AGENTS = ["company", "competitor", "payer", "physician", "patient"]


def extract_trace_summary(scenario):
    decisions = [item for item in scenario.decision_trace if item.event_type == "decision"]
    summary = []
    for decision in decisions:
        round_num = decision.time + 1
        agent_id = decision.agent_id
        action_id = decision.action.action_id if decision.action else "(none)"
        decision_position = scenario.decision_trace.index(decision)
        transition = next(
            (item for item in scenario.decision_trace[decision_position + 1:]
             if item.event_type == "transition" and item.agent_id == agent_id),
            None,
        )
        changes = transition.state_changes if transition and transition.state_changes else {}
        summary.append({
            "round": round_num,
            "agent": agent_id,
            "action": action_id,
            "changes": changes,
        })
    return summary


def get_client() -> TracingLocalClient:
    try:
        configured = OpenAICompatibleLLMClient.from_environment()
    except LLMConfigurationError as error:
        print(f"CONFIGURATION FAILURE = {error}")
        raise SystemExit(2)

    if not OpenAICompatibleLLMClient._is_local_provider(configured.provider):
        print("CONFIGURATION FAILURE = LLM_PROVIDER must select local or lm-studio.")
        raise SystemExit(2)
    if urlparse(configured.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        print("CONFIGURATION FAILURE = local provider URL must use loopback.")
        raise SystemExit(2)

    return TracingLocalClient(
        api_key=configured._api_key,
        base_url=configured.base_url,
        model=configured.model,
        timeout=configured.timeout,
        provider=configured.provider,
        temperature=configured.temperature,
    )


def run_single(name: str, definition: SimulationDefinition, client: TracingLocalClient):
    print(f"\n==========================================")
    print(f"RUNNING {name.upper()}")
    print(f"==========================================")
    start_calls = len(client.calls)
    result, elapsed = SimulationRunnerService(client).run(definition, "llm")
    call_count = len(client.calls) - start_calls

    if len(result.scenarios) != 1:
        raise RuntimeError(f"{name}: expected exactly one scenario")

    scenario = result.scenarios[0]
    trace = extract_trace_summary(scenario)

    print("ROUND | AGENT | ACTION | KEY STATE CHANGE")
    for step in trace:
        change_str = ", ".join(f"{k}={v}" for k, v in step["changes"].items()) if step["changes"] else "none"
        print(f"{step['round']} | {step['agent']} | {step['action']} | {change_str}")

    return {
        "scenario": scenario,
        "trace": trace,
        "calls": call_count,
        "elapsed": elapsed,
        "final_state": scenario.final_state.as_variables(),
        "forecast": scenario.forecast.metrics if scenario.forecast else {},
    }


def main() -> int:
    client = get_client()

    # A. Baseline
    baseline_def = SimulationDefinition.from_json(str(BASELINE_DEFINITION_PATH))
    baseline_result = run_single("Baseline", baseline_def, client)

    # B. Counterfactual: Meaningful upstream change (competitor_price = 600 vs 950)
    counterfactual_def = baseline_def.model_copy(deep=True)
    counterfactual_def.metadata.id = "counterfactual-competitor-price-600"
    counterfactual_def.metadata.name = "Counterfactual: Aggressive Competitor Price (600)"
    counterfactual_def.initial_world_state.variables["competitor_price"] = 600
    # Update initial market_share per transition formula for consistency:
    # 0.70 * 0.10 * 0.60 * (600 / 1000) * 1.0 = 0.0252
    counterfactual_def.initial_world_state.variables["market_share"] = 0.0252

    cf_result = run_single("Counterfactual (competitor_price=600)", counterfactual_def, client)

    # Determine changed decisions
    changed_agents = []
    for b_step, c_step in zip(baseline_result["trace"], cf_result["trace"]):
        if b_step["action"] != c_step["action"]:
            changed_agents.append({
                "round": b_step["round"],
                "agent": b_step["agent"],
                "baseline_action": b_step["action"],
                "counterfactual_action": c_step["action"],
            })

    total_calls = baseline_result["calls"] + cf_result["calls"]
    total_runtime = baseline_result["elapsed"] + cf_result["elapsed"]

    print("\n==========================================")
    print("COUNTERFACTUAL COMPARISON SUMMARY")
    print("==========================================")
    print(f"\n1. BASELINE ACTION SEQUENCE:")
    for step in baseline_result["trace"]:
        print(f"  R{step['round']} {step['agent']}: {step['action']}")

    print(f"\n2. COUNTERFACTUAL ACTION SEQUENCE:")
    for step in cf_result["trace"]:
        print(f"  R{step['round']} {step['agent']}: {step['action']}")

    print(f"\n3. DOWNSTREAM AGENT(S) CHANGED DECISION:")
    if changed_agents:
        for ca in changed_agents:
            print(f"  Round {ca['round']} {ca['agent']}: '{ca['baseline_action']}' -> '{ca['counterfactual_action']}'")
    else:
        print("  None (all downstream agents maintained identical action selections across both runs)")

    print(f"\n4. FINAL STATE COMPARISON:")
    all_keys = sorted(set(baseline_result["final_state"]) | set(cf_result["final_state"]))
    for key in all_keys:
        bv = baseline_result["final_state"].get(key)
        cv = cf_result["final_state"].get(key)
        diff = " (DIFFERENCE)" if bv != cv else ""
        print(f"  {key}: Baseline={bv} | Counterfactual={cv}{diff}")

    print(f"\n5. FORECAST COMPARISON:")
    f_keys = sorted(set(baseline_result["forecast"]) | set(cf_result["forecast"]))
    for key in f_keys:
        bf = baseline_result["forecast"].get(key)
        cf = cf_result["forecast"].get(key)
        diff = " (DIFFERENCE)" if bf != cf else ""
        print(f"  {key}: Baseline={bf} | Counterfactual={cf}{diff}")

    print(f"\n6. TOTAL LLM CALLS: {total_calls}")
    print(f"7. TOTAL RUNTIME: {total_runtime:.2f}s (Baseline: {baseline_result['elapsed']:.2f}s, Counterfactual: {cf_result['elapsed']:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
