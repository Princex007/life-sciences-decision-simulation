"""Evaluation-only scoring of deterministic candidate-action previews."""
from __future__ import annotations

from math import isclose, isfinite
from numbers import Real
from typing import Any, Mapping

from app.domain.world import WorldState


class ObjectiveScorer:
    """Combine explicitly configured, normalized preview metrics for evaluation.

    The simulation engine may use configured scores for hybrid decisions. Scores
    are transparent configured preferences, not estimates of clinical truth or profit.
    """

    def score_actions(self, previews: Mapping[str, Mapping[str, Any]],
                      current_state: WorldState | Mapping[str, Any],
                      objective: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        components = objective.get("components", [])
        if not components:
            raise ValueError("An evaluation objective must configure at least one component.")
        weights = [self._number(item.get("weight"), "component weight") for item in components]
        if any(weight < 0 for weight in weights) or not isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("Evaluation objective component weights must be non-negative and sum to 1.")

        state = (current_state.as_variables() if isinstance(current_state, WorldState)
                 else dict(current_state))
        scores = {}
        for action_id, preview in previews.items():
            projected_state = dict(state)
            for variable, change in preview.get("after_action_changes", {}).items():
                if isinstance(change, Mapping) and "to" in change:
                    projected_state[variable] = change["to"]

            component_results = {}
            total = 0.0
            for component, weight in zip(components, weights):
                name = component["name"]
                source = component["source"]
                metric = component["metric"]
                if source == "projected_state":
                    raw = projected_state.get(metric)
                elif source in {"after_next_time_step", "configured_derived_metrics",
                                "forecast_metrics", "clinical_outcomes",
                                "patient_affordability"}:
                    raw = preview.get(source, {}).get(metric)
                else:
                    raise ValueError(f"Unsupported objective metric source: {source!r}.")
                if raw is None:
                    raise ValueError(f"Preview for '{action_id}' is missing objective metric '{name}'.")
                raw = self._number(raw, f"{action_id}.{name}")
                normalized = self._normalize(raw, component["normalization"], projected_state,
                                             action_id, name)
                preference = component.get("preference")
                if preference == "maximize":
                    desirability = normalized
                elif preference == "minimize":
                    desirability = 1.0 - normalized
                else:
                    raise ValueError(f"Unsupported preference for '{name}': {preference!r}.")
                contribution = weight * desirability
                total += contribution
                component_results[name] = {
                    "raw_value": raw,
                    "normalized_value": normalized,
                    "preference_value": desirability,
                    "weight": weight,
                    "weighted_contribution": contribution,
                }
            scores[action_id] = {"score": total, "components": component_results}
        return scores

    @classmethod
    def _normalize(cls, value: float, config: Mapping[str, Any],
                   projected_state: Mapping[str, Any], action_id: str, name: str) -> float:
        method = config.get("method")
        minimum = cls._number(config.get("minimum", 0), f"{name}.minimum")
        maximum = cls._number(config.get("maximum", 1), f"{name}.maximum")
        if maximum <= minimum:
            raise ValueError(f"Normalization maximum must exceed minimum for '{name}'.")
        if method == "min_max":
            if not minimum <= value <= maximum:
                raise ValueError(f"Metric '{name}' for '{action_id}' is outside configured normalization bounds.")
            return (value - minimum) / (maximum - minimum)
        if method == "ratio_to_projected_variable":
            denominator_name = config.get("denominator_variable")
            denominator = cls._number(projected_state.get(denominator_name),
                                     f"{name}.{denominator_name}")
            if denominator <= 0:
                raise ValueError(f"Normalization denominator for '{name}' must be positive.")
            ratio = value / denominator
            if not minimum <= ratio <= maximum:
                raise ValueError(f"Normalized metric '{name}' for '{action_id}' is outside configured bounds.")
            return (ratio - minimum) / (maximum - minimum)
        raise ValueError(f"Unsupported normalization method for '{name}': {method!r}.")

    @staticmethod
    def _number(value: Any, label: str) -> float:
        if not isinstance(value, Real) or isinstance(value, bool) or not isfinite(float(value)):
            raise ValueError(f"{label} must be a finite number.")
        return float(value)
