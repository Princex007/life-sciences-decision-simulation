"""Driver-based forecast: carry the configured external environment past the horizon.

Inside the horizon the engine applies each driver pathway at the periods its trajectory
is configured for. This model fits a straight line through a driver's own trajectory
readings, extrapolates that level into the periods after the horizon, and applies each
pathway again with the extrapolated level through the same transition semantics the
engine uses.

Three assumptions are reported rather than hidden: every pathway is assumed to keep
firing in each projected period (configured lag is not carried forward), pathway values
written as arithmetic expressions are not projected, and no stakeholder decides anything
after the horizon. What is projected here is the external environment alone.
"""
from numbers import Real

from app.domain.action import ActionEffect
from app.domain.outcome import Outcome
from app.domain.world import WorldState
from app.forecasting.trend import TrendFit, fit_trend
from app.simulation.external_drivers import scale_value
from app.simulation.state_transition import StateTransitionSystem

TRANSITION = StateTransitionSystem()


def _numeric(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


class DriverProjectionForecast:
    """Project driver levels, indicator readings and pathway effects forward."""

    def __init__(self, projection_periods: int = 4):
        self.projection_periods = projection_periods

    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario,
                 context=None) -> Outcome:
        definition = context.definition if context else None
        if definition is None:
            raise ValueError("Driver projection needs the run definition's external drivers.")
        periods = context.projection_periods if context else self.projection_periods
        horizon = final_state.time
        future = [float(horizon + step) for step in range(1, periods + 1)]
        drivers = [driver for driver in definition.external_drivers if driver.enabled]

        metrics: dict[str, float | int | str] = {}
        projections: dict[str, list[float]] = {}
        levels: dict[str, TrendFit] = {}
        carried: dict[str, float] = {}
        unprojectable: set[str] = set()
        projected_drivers = 0

        for driver in drivers:
            points = driver.resolve_trajectory()
            fit = fit_trend([float(point.level) for point in points],
                            times=[float(point.time) for point in points], projection_times=future)
            levels[driver.driver_id] = fit
            metrics[f"{driver.driver_id}_level"] = fit.latest
            metrics[f"{driver.driver_id}_level_trend_per_period"] = fit.slope
            metrics[f"{driver.driver_id}_level_projected"] = fit.projected[-1]

            indicator = driver.indicator_variable
            observed = [(float(point.time), float(point.indicator_value)) for point in points
                        if point.indicator_value is not None]
            if indicator and observed:
                readings = fit_trend([value for _, value in observed],
                                     times=[time for time, _ in observed], projection_times=future)
                projections[indicator] = readings.projected
                metrics[f"{indicator}_trend_per_period"] = readings.slope
                metrics[f"{indicator}_projected"] = readings.projected[-1]

            if any(not pathway.qualitative_only for pathway in driver.pathways):
                projected_drivers += 1
            for pathway in driver.pathways:
                if pathway.qualitative_only:
                    continue
                if not _numeric(pathway.value) or not _numeric(final_state.get(pathway.target_variable)):
                    unprojectable.add(f"{driver.driver_id}:{pathway.target_variable}")

        for step in range(periods):
            for driver in drivers:
                level = levels[driver.driver_id].projected[step]
                for pathway in driver.pathways:
                    target = pathway.target_variable
                    if pathway.qualitative_only or f"{driver.driver_id}:{target}" in unprojectable:
                        continue
                    if target not in carried:
                        carried[target] = float(final_state.get(target))
                        projections[target] = []
                    applied = scale_value(pathway.operation, pathway.value, level)
                    state = WorldState(variables={target: carried[target]})
                    TRANSITION.apply_effect(state, ActionEffect(
                        variable=target, operation=pathway.operation, value=applied,
                        minimum=pathway.minimum, maximum=pathway.maximum))
                    carried[target] = float(state.get(target))
                    projections[target].append(carried[target])

        for target, series in projections.items():
            start = final_state.get(target)
            if not series or target not in carried or not _numeric(start):
                continue
            metrics[f"{target}_projected"] = series[-1]
            metrics[f"{target}_driver_delta"] = series[-1] - float(start)

        metrics["drivers_projected"] = projected_drivers
        metrics["driver_pathways_not_projected"] = len(unprojectable)
        return Outcome(metrics=metrics, projections=projections)
