"""Historical forecast: project a stored product series instead of the simulated path.

The run's agents still produce world state, but this model answers a different question:
where does the product's own recorded history point, and how far is the simulated path
from it? The fit is the same deterministic least-squares line the standalone forecaster
uses, so a pasted history and a stored history cannot quietly disagree with each other.

Nothing is smoothed, de-seasonalised or fitted with a lag: if the recorded series curves,
this reports a straight line through it and the residual error says how badly that fits.
"""
from numbers import Real

from app.domain.outcome import Outcome
from app.domain.world import WorldState
from app.forecasting.trend import fit_trend


def _numeric(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


class ProductHistoryForecast:
    """Fit the stored history, project it, and compare it with the simulated path."""

    def __init__(self, projection_periods: int = 4):
        self.projection_periods = projection_periods

    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario,
                 context=None) -> Outcome:
        history = context.history if context else None
        if history is None:
            raise ValueError("Historical forecasting needs a stored product history.")
        periods = context.projection_periods if context else self.projection_periods
        horizon = final_state.time
        future = [float(horizon + step) for step in range(1, periods + 1)]

        fit = fit_trend(history.values, projection_times=future)
        # The projected series always keeps the history's own name. Keying it by the world
        # variable it is compared with would draw the recorded trend's continuation on top
        # of the simulated path, which reads as one series when it is two different things.
        series_name = history.name
        metrics = {
            "history_points": fit.periods,
            "history_start": fit.start,
            "history_latest": fit.latest,
            "history_rmse": fit.rmse,
            f"{series_name}_trend_per_period": fit.slope,
            f"{series_name}_projected": fit.projected[-1],
        }
        simulated = final_state.get(history.variable) if history.variable else None
        if _numeric(simulated):
            metrics[f"{history.variable}_history_gap"] = fit.projected[-1] - float(simulated)
            metrics[f"{history.variable}_simulated"] = float(simulated)
        return Outcome(metrics=metrics, projections={series_name: fit.projected})
