from app.agents.cognition import DecisionResponse
from app.agents.llm import MockLLMClient
from app.agents.evidence_retrieval import RuleBasedEvidenceRetriever
from app.agents.base import RuleBasedDecisionPolicy
from app.benchmark.decision_benchmark import run_benchmark
from app.domain.evidence import Evidence
from app.services.evidence_store import JsonEvidenceStore
from app.simulation.decision_validator import DecisionValidator
from app.agents.cognition import DecisionContext, AgentObservation, ObservedEvent
from app.domain.action import ActionDefinition
from app.domain.agent import AgentDefinition
from app.services.simulation_runner import SimulationRunnerService


def test_json_evidence_store_crud_query_and_metadata(tmp_path):
    store = JsonEvidenceStore(tmp_path)
    item = Evidence(evidence_id="E-1", title="Synthetic payer access", content="Access review.",
        source="SYNTHETIC fixture", source_type="synthetic", date="2026-01-01",
        domain="synthetic_life_sciences", tags=["payer", "access"],
        applicable_agents=["payer"], related_variables=["payer_access"])
    store.add(item)
    assert store.get("E-1").evidence_id == "E-1"
    assert [record.evidence_id for record in store.query("access")] == ["E-1"]
    assert [record.evidence_id for record in store.filter_metadata(domain="synthetic_life_sciences")] == ["E-1"]
    store.update(item.model_copy(update={"title": "Updated synthetic access"}))
    assert store.get("E-1").title == "Updated synthetic access"
    assert store.delete("E-1") and store.get("E-1") is None


def test_retriever_enforces_agent_visibility_and_context_relevance():
    records = [Evidence(evidence_id="A", title="Payer access", content="synthetic",
        applicable_agents=["payer"], related_variables=["payer_access"]),
        Evidence(evidence_id="B", title="Hidden access", content="synthetic",
        applicable_agents=["competitor"], related_variables=["payer_access"]),
        Evidence(evidence_id="C", title="Unrelated", content="synthetic",
        applicable_agents=["payer"], related_variables=["drug_price"])]
    from app.services.evidence_store import InMemoryEvidenceStore
    agent = AgentDefinition(id="payer", name="Payer", objective="manage access",
        observable_state=["payer_access"], available_actions=["restrict"])
    context = DecisionContext(agent_id="payer", agent_name="Payer", agent_type="payer", time=1,
        trigger=ObservedEvent(event_id="review", time=1, event_type="payer_review", description="Review"),
        objective="manage access", observations=AgentObservation(timestamp=1,
            visible_world_variables={"payer_access": 0.5}),
        available_actions=[ActionDefinition(id="restrict", name="Restrict", agent_id="payer")])
    found = RuleBasedEvidenceRetriever().retrieve(agent, context, InMemoryEvidenceStore(records))
    assert [item.evidence_id for item in found] == ["A"]


def test_response_validator_rejects_hidden_citations_and_contradictory_facts():
    agent = AgentDefinition(id="payer", name="Payer", objective="manage access")
    context = DecisionContext(agent_id="payer", agent_name="Payer", agent_type="payer", time=1,
        trigger=ObservedEvent(event_id="review", time=1, event_type="payer_review", description="Review"),
        objective="manage access", observations=AgentObservation(timestamp=1,
            visible_world_variables={"payer_access": 0.5}))
    response = DecisionResponse(primary_action="restrict", rationale="Source [SECRET-EVIDENCE].",
        evidence_used=["SECRET-EVIDENCE"], facts_used=["payer_access = 0.9", "share is growing"])
    errors = DecisionValidator.validate_response(context, response)
    assert any("not supplied" in error for error in errors)
    assert any("conflicts with observed" in error for error in errors)
    assert any("cannot be traced" in error for error in errors)


def test_hidden_evidence_citation_invalidates_decision_without_transition():
    from tests.test_llm_decision_policy import definition_with_evidence, llm_response
    response = llm_response(evidence_used=["EVID-PRIVATE"],
        rationale="Unsupported source [EVID-PRIVATE].")
    result, _ = SimulationRunnerService(MockLLMClient(response)).run(definition_with_evidence(), "llm")
    trace = next(item for item in result.scenarios[0].decision_trace if item.event_type == "decision")
    assert trace.validation_status == "invalid"
    assert trace.action is None
    assert result.scenarios[0].final_state.get("count") == 0


def test_benchmark_reports_expected_actions_for_each_deterministic_policy():
    report = run_benchmark()
    expected = report["expected_plausible_actions"]
    assert report["synthetic"] is True
    assert report["results"]["rule_based"]["candidate_actions"] == expected
    assert report["results"]["mock_llm"]["candidate_actions"] == expected
    assert report["results"]["mock_llm"]["validation"] == "valid"
    assert report["results"]["mock_llm"]["evidence_ids"] == ["SYNTH-COMP-SHARE"]
