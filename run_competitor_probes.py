"""Run one Context A Competitor decision against the configured local LLM."""
from __future__ import annotations

import time
import os
import json
from pathlib import Path
from copy import deepcopy
from datetime import datetime
from urllib.parse import urlparse

from app.agents.cognition import ObservationModel, ObservedEvent, build_decision_context
from app.agents.evidence_retrieval import RuleBasedEvidenceRetriever
from app.agents.llm import DecisionPromptBuilder, LLMDecisionPolicy, OpenAICompatibleLLMClient
from app.domain.agent import AgentState
from app.domain.definitions import SimulationDefinition
from app.domain.event import SimulationEvent
from app.domain.world import WorldState
from app.services.evidence_store import InMemoryEvidenceStore


def main() -> None:
    definition = SimulationDefinition.from_json(
        str(Path(__file__).parent / "examples" / "us_drug_launch.json"))
    agent = next(item for item in definition.agents if item.id == "competitor")
    action_map = {item.id: item for item in definition.action_definitions
                  if item.agent_id == agent.id}
    # These are the scenario's actual actions corresponding to promotion and price.
    promotion = action_map["increase_promotion"]
    price = action_map["aggressive_price_cut"]
    observations = ObservationModel()
    retriever = RuleBasedEvidenceRetriever()
    evidence_store = InMemoryEvidenceStore(definition.evidence)
    trigger = ObservedEvent(event_id="competitor-probe", time=0,
        event_type="company_launch", description="Company launches product",
        actor_id="company", data={"trigger_id": "competitor-response"})
    actions = [promotion, price]
    candidate_ids = [action.id for action in actions]
    if candidate_ids != ["increase_promotion", "aggressive_price_cut"]:
        print(f"PROMPT VALIDATION FAILED: unexpected action IDs {candidate_ids!r}; no LLM calls made.")
        return

    base_variables = deepcopy(definition.initial_world_state.variables)
    if base_variables.get("drug_price") != 100000:
        print("PROMPT VALIDATION FAILED: initial drug_price is not 100000; no LLM calls made.")
        return

    def make_context(competitor_price: int):
        variables = deepcopy(base_variables)
        variables["drug_price"] = 100000
        variables["competitor_price"] = competitor_price
        world = WorldState(time=0, variables=variables)
        state = AgentState(agent_id=agent.id, current_strategy=agent.initial_strategy)
        event = SimulationEvent(event_id=trigger.event_id, time=0,
            event_type=trigger.event_type, description=trigger.description,
            actor_id=trigger.actor_id)
        observation = observations.observe(agent, world, events=[event])
        state.belief_state.update_observation(observation.visible_world_variables, 0,
            [trigger.event_id])
        context = build_decision_context(agent, state, observation, trigger, actions)
        observation.relevant_evidence = retriever.retrieve(agent, context, evidence_store)
        return build_decision_context(agent, state, observation, trigger, actions), world

    context_a, world_a = make_context(110000)
    prompt_builder = DecisionPromptBuilder()
    prompt_a = prompt_builder.build_local_action_prompt(context_a, actions)

    def prompt_data(prompt):
        prefix = "Relevant DecisionContext:\n"
        body, candidate_tail = prompt.user.split("\n\nPlausible candidate action IDs:", 1)
        return json.loads(body[len(prefix):]), json.loads(candidate_tail)

    data_a, ids_a = prompt_data(prompt_a)
    problems = []
    if world_a.get("competitor_price") != 110000:
        problems.append("Context A world does not contain competitor_price=110000")
    if world_a.get("drug_price") != 100000:
        problems.append("Context A world does not contain drug_price=100000")
    if data_a.get("observations", {}).get("competitor_price") != 110000:
        problems.append("Prompt A does not contain competitor_price=110000")
    if data_a.get("observations", {}).get("drug_price") != 100000:
        problems.append("Prompt A does not contain drug_price=100000")
    if ids_a != candidate_ids:
        problems.append("prompt candidate IDs do not match the verified existing actions and order")

    print("Context A relevant observations:", context_a.observations.visible_world_variables)
    print(f"Prompt A size: system={len(prompt_a.system)} chars, "
          f"user={len(prompt_a.user)} chars, total={len(prompt_a.system) + len(prompt_a.user)} chars")
    if problems:
        print("PROMPT VALIDATION FAILED; no LLM calls made:")
        for problem in problems:
            print(f"- {problem}")
        return
    print("PROMPT VALIDATION PASSED: drug_price=100000, competitor_price=110000, "
          "candidate IDs are increase_promotion then aggressive_price_cut.")

    client = OpenAICompatibleLLMClient(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1"),
        model=os.getenv("LLM_MODEL", "qwen2.5-1.5b-instruct"),
        provider=os.getenv("LLM_PROVIDER", "lm-studio"),
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "45")),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
    )
    print(f"Effective timeout: {client.timeout:g} seconds")
    if client.timeout != 90:
        print("CONFIGURATION INVALID: this one-call run requires LLM_TIMEOUT_SECONDS=90; no LLM call made.")
        return
    if not OpenAICompatibleLLMClient._is_local_provider(client.provider) or \
            urlparse(client.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        print("CONFIGURATION INVALID: expected local LM Studio loopback endpoint; no LLM calls made.")
        return

    call_count = 0
    original_generate = client.generate_decision

    def counted_generate(context, prompt):
        nonlocal call_count
        call_count += 1
        request_start = datetime.now().astimezone()
        elapsed_start = time.perf_counter()
        print(f"Request start: {request_start.isoformat(timespec='seconds')}")
        try:
            completion = original_generate(context, prompt)
        except Exception as error:
            elapsed = time.perf_counter() - elapsed_start
            request_end = datetime.now().astimezone()
            print(f"Request end: {request_end.isoformat(timespec='seconds')}")
            print(f"Request elapsed: {elapsed:.2f} seconds")
            print(f"Request error type: {type(error).__name__}")
            print(f"Request error details: {error!r}")
            print(f"Request error message: {error}")
            raise
        elapsed = time.perf_counter() - elapsed_start
        request_end = datetime.now().astimezone()
        print(f"Request end: {request_end.isoformat(timespec='seconds')}")
        print(f"Request elapsed: {elapsed:.2f} seconds")
        return completion

    client.generate_decision = counted_generate
    policy = LLMDecisionPolicy(client)
    try:
        response = policy.decide(context_a, actions)
        if policy._last_completion is None:
            print("Context A selected=(no action; request failed)")
            print(f"Complete policy error details: {response.validation_errors!r}")
        elif response.validation_status == "invalid":
            print("Context A selected=(rejected)")
            print(f"Complete validation details: {response.validation_errors!r}")
        else:
            print(f"Context A selected={response.primary_action}")
    except Exception as error:
        print(f"Context A decision error type: {type(error).__name__}")
        print(f"Context A decision error details: {error!r}")
        print(f"Context A decision error message: {error}")
    print(f"LLM calls={call_count}")


if __name__ == "__main__":
    main()
