"""External environment / macro-driver configuration.

Drivers are not stakeholder agents. They describe trends or shocks outside the
normal stakeholder interaction model that change world variables, or that agents
can observe as an indicator before the world-state effect lands.

Every causal link is explicitly configured. Nothing here derives a numeric
effect from a category name, and a pathway marked ``qualitative_only`` is
reported as a hypothesis and never converted into a state change.
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceGrade = Literal[
    "empirical",
    "user_assumption",
    "model_hypothesis",
    "synthetic_illustrative",
]

EffectOperation = Literal["set", "add", "subtract", "multiply", "divide"]


class DriverPathway(BaseModel):
    """One explicitly configured causal link from a driver to a state variable."""
    target_variable: str
    operation: EffectOperation = "add"
    value: Any = 0
    minimum: float | None = None
    maximum: float | None = None
    lag: int = Field(default=0, ge=0)
    basis: str = ""
    uncertainty: str = ""
    evidence_grade: EvidenceGrade = "user_assumption"
    qualitative_only: bool = False


class DriverTrajectoryPoint(BaseModel):
    """A driver reading at one period.

    ``level`` scales the strength of every quantitative pathway firing at this
    point. ``indicator_value`` is the observable reading written to the driver's
    indicator variable; when omitted, no indicator write happens at this point.
    """
    time: int = Field(ge=0)
    level: float = 1.0
    indicator_value: float | None = None
    description: str = ""


class DriverVariant(BaseModel):
    """A named scenario assumption set for one driver."""
    variant_id: str
    label: str
    description: str = ""
    assumption_label: str = ""
    evidence_grade: EvidenceGrade = "user_assumption"
    trajectory: list[DriverTrajectoryPoint] = Field(default_factory=list)


class ExternalDriver(BaseModel):
    """A configurable external force acting on the simulated world."""
    driver_id: str
    name: str
    category: str = "unspecified"
    description: str = ""
    enabled: bool = True
    active_variant: str = "central"
    variants: list[DriverVariant] = Field(default_factory=list)
    trajectory: list[DriverTrajectoryPoint] = Field(default_factory=list)
    indicator_variable: str | None = None
    initial_value: float = 0.0
    observable_by: list[str] = Field(default_factory=list)
    observable_from: int = Field(default=0, ge=0)
    event_type: str | None = None
    priority: int = 50
    source: str = ""
    evidence_grade: EvidenceGrade = "synthetic_illustrative"
    assumption_label: str = "Illustrative, uncalibrated external-driver assumption."
    pathways: list[DriverPathway] = Field(default_factory=list)
    interacts_with: list[str] = Field(default_factory=list)

    def base_event_type(self) -> str:
        return self.event_type or f"external_driver_{self.driver_id}"

    def resolve_variant(self) -> DriverVariant | None:
        return next((item for item in self.variants
                     if item.variant_id == self.active_variant), None)

    def resolve_trajectory(self) -> list[DriverTrajectoryPoint]:
        """Use the active variant's trajectory, falling back to the driver's own."""
        variant = self.resolve_variant()
        points = variant.trajectory if variant and variant.trajectory else self.trajectory
        ordered: dict[int, DriverTrajectoryPoint] = {}
        for point in points:
            ordered[point.time] = point
        return [ordered[time] for time in sorted(ordered)]

    def assumption_labels(self) -> list[str]:
        labels = []
        if self.assumption_label:
            labels.append(self.assumption_label)
        variant = self.resolve_variant()
        if variant and variant.assumption_label:
            labels.append(variant.assumption_label)
        return labels


class DriverImpactRecord(BaseModel):
    """One quantitative pathway effect that the engine will actually apply."""
    driver_id: str
    driver_name: str
    category: str
    variant_id: str
    pathway: Literal["world_state", "information"]
    source_time: int
    effect_time: int
    lag: int
    level: float
    target_variable: str
    operation: str
    configured_value: Any = None
    applied_value: Any = None
    bounded: bool = False
    evidence_grade: str = "user_assumption"
    basis: str = ""
    uncertainty: str = ""
    assumption_labels: list[str] = Field(default_factory=list)


class DriverHypothesisRecord(BaseModel):
    """A configured pathway deliberately left qualitative and unapplied."""
    driver_id: str
    driver_name: str
    category: str
    variant_id: str
    target_variable: str
    operation: str
    configured_value: Any = None
    basis: str = ""
    uncertainty: str = ""
    evidence_grade: str = "model_hypothesis"
    status: str = "qualitative_hypothesis_not_applied"
