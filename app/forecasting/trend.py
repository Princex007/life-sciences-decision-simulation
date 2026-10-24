"""Deterministic least-squares trend fitting shared by forecast plugins and endpoints."""
from typing import NamedTuple


class TrendFit(NamedTuple):
    """Observed summary plus a straight-line continuation of a period series."""
    periods: int
    start: float
    latest: float
    slope: float
    intercept: float
    mean_change: float
    total_change: float
    rmse: float
    fitted: list[float]
    # What the line missed at each observed period: RMSE is these squared and averaged, so a panel
    # that shows only RMSE hides which observation the fit was worst on.
    residuals: list[float]
    projected: list[float]
    projection_times: list[float]


def fit_trend(values: list[float], periods_ahead: int = 0, times: list[float] | None = None,
              projection_times: list[float] | None = None) -> TrendFit:
    """Fit a straight line to a period series and project it forward.

    A single observation has no slope to estimate, so it projects flat rather than
    inventing a trend from one point.

    ``times`` is the period each value was actually read at, so a series with gaps
    (a driver trajectory recorded at t0, t4, t8) is fitted against real time rather
    than against its own row number. ``projection_times`` names the exact periods to
    evaluate, which is how a projection can start past the end of the observed data.
    """
    points = [float(value) for value in values]
    if not points:
        raise ValueError("Time series forecasting needs at least one observed value.")
    if periods_ahead < 0:
        raise ValueError("periods_ahead cannot be negative.")
    count = len(points)
    xs = [float(value) for value in times] if times is not None else [float(index) for index in range(count)]
    if len(xs) != count:
        raise ValueError("times must hold one period per observed value.")
    mean_x = sum(xs) / count
    mean_y = sum(points) / count
    spread = sum((xs[index] - mean_x) ** 2 for index in range(count))
    slope = 0.0 if spread == 0 else sum(
        (xs[index] - mean_x) * (points[index] - mean_y) for index in range(count)) / spread
    intercept = mean_y - slope * mean_x
    spacing = ((xs[-1] - xs[0]) / (count - 1)) if count > 1 else 1.0
    if spacing <= 0:
        raise ValueError("Period times must increase from one observation to the next.")
    fitted = [intercept + slope * x for x in xs]
    residuals = [points[index] - fitted[index] for index in range(count)]
    changes = [points[index] - points[index - 1] for index in range(1, count)]
    at = ([float(value) for value in projection_times] if projection_times is not None
          else [xs[-1] + spacing * step for step in range(1, periods_ahead + 1)])
    return TrendFit(
        periods=count, start=points[0], latest=points[-1], slope=slope, intercept=intercept,
        mean_change=sum(changes) / len(changes) if changes else 0.0,
        total_change=points[-1] - points[0],
        rmse=(sum(value * value for value in residuals) / count) ** 0.5,
        fitted=fitted, residuals=residuals, projected=[intercept + slope * x for x in at],
        projection_times=at)
