"""Explicit policies for retaining already-generated valid scenario branches."""
from dataclasses import dataclass
from typing import Any, Protocol
from app.domain.definitions import ScenarioGenerationSettings

@dataclass
class PrunedPath:
    path: Any
    reason: str
    competing_retained_node_id: str | None = None

@dataclass
class PruningResult:
    retained: list[Any]
    pruned: list[PrunedPath]
    policy: str

class ScenarioPolicy(Protocol):
    """Choose among already-applied, valid scenario branches."""
    name: str
    def prune(self, paths: list[Any], time: int) -> PruningResult: ...

class ExhaustivePolicy:
    """Retain every valid branch up to an explicit safety limit."""
    name = "exhaustive"
    def __init__(self, safety_limit: int): self.safety_limit = safety_limit
    def prune(self, paths: list[Any], time: int) -> PruningResult:
        retained = paths[:self.safety_limit]
        pruned = [PrunedPath(path, f"Safety limit {self.safety_limit} reached; exhaustive retention stopped.",
                             retained[-1].cursor.node_id if retained else None)
                  for path in paths[self.safety_limit:]]
        return PruningResult(retained, pruned, self.name)

class LimitedPolicy:
    """Retain the first N paths in stable generation order."""
    name = "limited"
    def __init__(self, limit: int): self.limit = limit
    def prune(self, paths: list[Any], time: int) -> PruningResult:
        retained = paths[:self.limit]
        pruned = [PrunedPath(path, f"Maximum {self.limit} retained terminal branches reached under deterministic generation order.",
                             retained[-1].cursor.node_id if retained else None)
                  for path in paths[self.limit:]]
        return PruningResult(retained, pruned, self.name)

class DiversityPolicy:
    """Retain paths with distinct first decisions for configured agents."""
    name = "diversity"
    def __init__(self, limit: int, agent_ids: list[str]):
        self.limit, self.agent_ids = limit, agent_ids
    def prune(self, paths: list[Any], time: int) -> PruningResult:
        groups, pruned = {}, []
        for path in paths:
            first = {}
            for event in path.trace:
                if event.event_type == "decision" and event.action and event.agent_id not in first:
                    first[event.agent_id] = event.action.action_id
            signature = tuple(first.get(agent_id) for agent_id in self.agent_ids)
            groups.setdefault(signature, []).append(path)
        selected, covered_actions, covered_latest = [], set(), set()
        for signature, candidates in groups.items():
            def latest(path):
                by_agent = {}
                for event in path.trace:
                    if event.event_type == "decision" and event.action and event.agent_id in self.agent_ids:
                        current = by_agent.get(event.agent_id)
                        if current is None or event.time >= current[0]:
                            by_agent[event.agent_id] = (event.time, event.action.action_id)
                return tuple(by_agent.get(agent_id, (None, None))[1] for agent_id in self.agent_ids)
            best = max(candidates, key=lambda path: (
                sum((agent_id, action) not in covered_actions for agent_id, action in zip(self.agent_ids, latest(path))),
                latest(path) not in covered_latest))
            if len(selected) < self.limit:
                selected.append(best)
                best_latest = latest(best)
                covered_latest.add(best_latest)
                covered_actions.update((agent_id, action) for agent_id, action in zip(self.agent_ids, best_latest))
                retained_id = best.cursor.node_id
                rejected = [candidate for candidate in candidates if candidate is not best]
                reason = f"Duplicate first-action diversity signature {signature!r}; a representative branch was retained."
            else:
                retained_id = selected[-1].cursor.node_id if selected else None
                rejected = candidates
                reason = f"Maximum {self.limit} retained terminal scenarios reached while preserving action diversity."
            for candidate in rejected:
                pruned.append(PrunedPath(candidate, reason, retained_id))
        return PruningResult(selected, pruned, self.name)

# Compatibility aliases for earlier configuration names.
ExhaustivePruner = ExhaustivePolicy
TopNPruner = LimitedPolicy
DiversityPruner = DiversityPolicy

def create_pruner(settings: ScenarioGenerationSettings) -> ScenarioPolicy:
    """Build the configured, deterministic scenario retention policy."""
    if settings.safety_limit < 1:
        raise ValueError("scenario safety_limit must be positive")
    if settings.policy == "exhaustive":
        return ExhaustivePolicy(settings.safety_limit)
    if settings.policy in {"limited", "top_n"}:
        if settings.max_scenarios is None or settings.max_scenarios < 1:
            raise ValueError("limited policy requires a positive max_scenarios")
        return LimitedPolicy(settings.max_scenarios)
    if settings.policy == "diversity":
        if settings.max_scenarios is None or settings.max_scenarios < 1:
            raise ValueError("diversity policy requires a positive max_scenarios")
        return DiversityPolicy(settings.max_scenarios, settings.diversity_by_agents)
    raise ValueError(f"Unknown scenario policy: {settings.policy}")
