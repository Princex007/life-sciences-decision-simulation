"""Stored product histories: observed period series a forecast can be fitted to.

A history deliberately lives outside the simulation definition. Product data outlives
any one model, and the same observed series should be reusable across definitions
instead of being re-pasted into each file, where it could quietly diverge.
"""
from pydantic import BaseModel, Field

from app.domain.driver import EvidenceGrade


class ProductHistory(BaseModel):
    """One named, ordered series of observed values, oldest first."""
    history_id: str
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    values: list[float] = Field(min_length=2, max_length=500)
    # World variable this series is the observed history of. When it is set and the
    # variable exists in world state, the forecaster can compare the fitted line
    # against what the simulation actually produced.
    variable: str = ""
    # What one value in this series means, stated in its own unit: "treated patients per quarter",
    # "market share (fraction, 0-1)". Left blank when the supplier never said, which is exactly the
    # case a scaled analogue has to warn about instead of silently combining two metrics.
    unit: str = Field(default="", max_length=80)
    # How long one period is: "quarter", "month", "year", or a generic "period".
    cadence: str = Field(default="", max_length=40)
    source: str = Field(default="", max_length=200)
    evidence_grade: EvidenceGrade = "user_assumption"
    assumption_label: str = ("Observed values supplied by the user. Nothing here checks them "
                             "against an accounting or clinical record.")
