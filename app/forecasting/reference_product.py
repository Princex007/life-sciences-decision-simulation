"""Reference-based forecast: borrow another product's recorded ramp, rescaled to your peak.

A launch with no history of its own can still be forecast: pick a comparable product whose
series is stored, and this model stretches that recorded shape onto the peak level entered in
the definition. The shape comes entirely from data the user supplied for the reference
product; only the peak is this product's own assumption.

Scaling is a single multiplier (reference peak -> entered peak), so the ramp's relative
growth is preserved exactly. The projection then continues the scaled series' least-squares
line, the same deterministic fit every other forecast path uses.
"""
from numbers import Real

from app.domain.outcome import Outcome
from app.domain.world import WorldState
from app.forecasting.trend import fit_trend


def scale_to_peak(values: list[float], peak: float) -> tuple[float, list[float]]:
    """Multiply a recorded series so its own maximum lands on the requested peak."""
    if not values:
        raise ValueError("Reference forecasting needs a stored series with values.")
    if not isinstance(peak, Real) or isinstance(peak, bool) or not float(peak) > 0:
        raise ValueError("Reference forecasting needs a positive peak value.")
    largest = max(float(value) for value in values)
    if largest <= 0:
        raise ValueError("The reference series has no positive value to scale from.")
    factor = float(peak) / largest
    return factor, [float(value) * factor for value in values]


def _numeric(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


class ReferenceProductForecast:
    """Rescale a different product's stored series onto this product's expected peak."""

    def __init__(self, projection_periods: int = 4):
        self.projection_periods = projection_periods

    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario,
                 context=None) -> Outcome:
        reference = context.reference_history if context else None
        if reference is None:
            raise ValueError("Reference forecasting needs a stored reference product history.")
        definition = context.definition if context else None
        peak = definition.reference_peak if definition else None
        if peak is None:
            raise ValueError("Reference forecasting needs the peak value this product is expected to reach.")
        factor, scaled = scale_to_peak(reference.values, peak)
        periods = context.projection_periods if context else self.projection_periods
        horizon = final_state.time
        future = [float(horizon + step) for step in range(1, periods + 1)]

        fit = fit_trend(scaled, projection_times=future)
        name = reference.name
        metrics = {
            "reference_product": name,
            "reference_points": fit.periods,
            "reference_recorded_peak": max(reference.values),
            "reference_peak_target": float(peak),
            "reference_scale": factor,
            "reference_latest_scaled": fit.latest,
            "reference_rmse": fit.rmse,
            f"{name}_trend_per_period": fit.slope,
            f"{name}_projected": fit.projected[-1],
        }
        simulated = final_state.get(reference.variable) if reference.variable else None
        if _numeric(simulated):
            metrics[f"{reference.variable}_reference_gap"] = fit.projected[-1] - float(simulated)
            metrics[f"{reference.variable}_simulated"] = float(simulated)
        return Outcome(metrics=metrics, projections={name: fit.projected})
