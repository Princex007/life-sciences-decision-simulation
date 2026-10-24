"""Quantitative scenario outcome."""
from pydantic import BaseModel, Field

class Outcome(BaseModel):
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    revenue_by_period: list[float] = Field(default_factory=list)
    # Straight-line continuation of a variable past the simulated horizon, keyed by variable.
    projections: dict[str, list[float]] = Field(default_factory=dict)

    def __getattr__(self, name: str):
        """Compatibility access to metrics and generic model-specific measures."""
        metrics = super().__getattribute__("metrics")
        if name in metrics:
            return metrics[name]
        raise AttributeError(name)
