"""Forecast plugin that projects each moving world variable beyond the simulated horizon."""
from app.domain.outcome import Outcome
from app.domain.world import WorldState
from app.forecasting.trend import fit_trend


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class TrendProjectionForecast:
    """Fit a straight line to every variable that changed during the run and carry it forward.

    Variables that never moved are left out: a flat series has no trend to report, and
    listing every static variable would bury the ones the run actually changed.
    """

    def __init__(self, projection_periods: int = 4):
        self.projection_periods = projection_periods

    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario,
                 context=None) -> Outcome:
        periods = context.projection_periods if context else self.projection_periods
        states = snapshots or [final_state]
        names = [key for key, value in final_state.as_variables().items() if _numeric(value)]
        metrics: dict[str, float | int | str] = {}
        projections: dict[str, list[float]] = {}
        for name in names:
            values = [state.get(name) for state in states if _numeric(state.get(name))]
            if len(values) < 2 or max(values) == min(values):
                continue
            fit = fit_trend(values, periods)
            metrics[name] = fit.latest
            metrics[f"{name}_trend_per_period"] = fit.slope
            metrics[f"{name}_projected"] = fit.projected[-1]
            projections[name] = fit.projected
        return Outcome(metrics=metrics, projections=projections)
