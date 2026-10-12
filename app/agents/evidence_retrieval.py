"""Agent-scoped, deterministic retrieval from an EvidenceStore."""
from __future__ import annotations

from typing import Protocol

from app.agents.cognition import DecisionContext
from app.domain.agent import AgentDefinition
from app.domain.evidence import Evidence
from app.services.evidence_store import EvidenceStore


class EvidenceRetriever(Protocol):
    def retrieve(self, agent: AgentDefinition, decision_context: DecisionContext,
                 evidence_store: EvidenceStore) -> list[Evidence]: ...


class RuleBasedEvidenceRetriever:
    """Retrieve only applicable evidence tied to visible context metadata."""
    def retrieve(self, agent: AgentDefinition, decision_context: DecisionContext,
                 evidence_store: EvidenceStore) -> list[Evidence]:
        visible = set(decision_context.observations.visible_world_variables)
        actions = {action.id for action in decision_context.available_actions}
        trigger_text = " ".join((decision_context.trigger.event_type,
            decision_context.trigger.event_id, decision_context.trigger.description,
            str(decision_context.trigger.data.get("trigger_id", ""))))
        trigger_tokens = {part.casefold() for part in trigger_text.replace("-", " ").split() if len(part) > 2}
        agent_tags = {tag.casefold() for tag in agent.evidence_tags}
        configured_tags = decision_context.policy_configuration.get("evidence_tags", [])
        agent_tags.update(str(tag).casefold() for tag in configured_tags)
        candidates = evidence_store.list()
        result = []
        for item in candidates:
            if agent.id not in item.applicable_agents and not ({"*", "all"} & set(item.applicable_agents)):
                continue
            variable_match = bool(set(item.related_variables) & visible)
            action_match = bool(set(item.related_actions) & actions)
            tags = {tag.casefold() for tag in item.tags}
            tag_match = bool(tags & (agent_tags | trigger_tokens))
            legacy_unscoped = not (item.tags or item.related_variables or item.related_actions)
            if variable_match or action_match or tag_match or legacy_unscoped:
                result.append(item.model_copy(deep=True))
        return sorted(result, key=lambda item: item.evidence_id)
