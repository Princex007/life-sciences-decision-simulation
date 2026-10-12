"""Aggregate clinical outcome estimates from a configured treatment forecast."""
from math import isfinite
from numbers import Real
from typing import Any


def expected_clinical_outcomes(patients_treated: Any,
                              assumptions: dict[str, Any] | None) -> dict[str, Any]:
    """Return expected aggregate counts, or an explicit unavailable result.

    Rates are scenario assumptions, not empirical estimates. The caller supplies
    patients_treated from the existing forecast; this module adds no treatment
    volume or clinical outcome formula of its own.
    """
    rates = assumptions or {}
    response_rate = rates.get("treatment_response_rate")
    adverse_event_rate = rates.get("adverse_event_rate")
    for name, rate in (("treatment_response_rate", response_rate),
                       ("adverse_event_rate", adverse_event_rate)):
        if (not isinstance(rate, Real) or isinstance(rate, bool)
                or not isfinite(rate) or not 0 <= rate <= 1):
            return {
                "available": False,
                "reason": f"{name} must be configured as a finite rate from 0 to 1.",
                "forecast_horizon": rates.get("forecast_horizon"),
            }

    if (not isinstance(patients_treated, Real) or isinstance(patients_treated, bool)
            or not isfinite(patients_treated) or patients_treated < 0):
        return {
            "available": False,
            "reason": "The forecast did not provide a valid patients_treated metric.",
            "forecast_horizon": rates.get("forecast_horizon"),
        }

    return {
        "available": True,
        "patients_treated": patients_treated,
        "expected_responders": patients_treated * response_rate,
        "expected_adverse_events": patients_treated * adverse_event_rate,
        "forecast_horizon": rates.get("forecast_horizon"),
        "assumption_label": rates.get("label", "Unspecified scenario assumptions."),
    }
