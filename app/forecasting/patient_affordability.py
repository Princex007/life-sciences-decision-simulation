"""Configurable patient cost-sharing proxy for decision previews."""
from math import isfinite
from numbers import Real
from typing import Any


def estimate_patient_cost(projected_drug_price: Any,
                          assumptions: dict[str, Any] | None) -> dict[str, Any]:
    """Estimate per-treatment-unit patient cost or explicitly mark unavailable.

    This is only projected drug price times a scenario-configured cost-share
    fraction; it does not model insurance benefits, deductibles, or observed costs.
    """
    config = assumptions or {}
    fraction = config.get("patient_cost_share_fraction")
    if (not isinstance(fraction, Real) or isinstance(fraction, bool)
            or not isfinite(fraction) or not 0 <= fraction <= 1):
        return {
            "available": False,
            "reason": "patient_cost_share_fraction must be configured as a finite fraction from 0 to 1.",
            "unit": config.get("unit", "scenario currency per treatment unit"),
        }
    if (not isinstance(projected_drug_price, Real) or isinstance(projected_drug_price, bool)
            or not isfinite(projected_drug_price) or projected_drug_price < 0):
        return {
            "available": False,
            "reason": "The projected drug_price is missing or invalid.",
            "unit": config.get("unit", "scenario currency per treatment unit"),
        }
    return {
        "available": True,
        "projected_drug_price": projected_drug_price,
        "patient_cost_share_fraction": fraction,
        "estimated_patient_cost": projected_drug_price * fraction,
        "unit": config.get("unit", "scenario currency per treatment unit"),
        "assumption_label": config.get("label", "Unspecified scenario assumption."),
    }
