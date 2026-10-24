"""Forecast plugin registry and the ordered catalog the UI renders from.

The catalog is the single source of truth for which forecast models exist, how they are
grouped and in what order they are offered. The builder validates a definition against
the same registry, so a model cannot appear in the dropdown without being runnable.
"""
from typing import NamedTuple

from app.forecasting.driver_projection import DriverProjectionForecast
from app.forecasting.launch_forecast import LaunchForecast
from app.forecasting.product_history import ProductHistoryForecast
from app.forecasting.reference_product import ReferenceProductForecast
from app.forecasting.state_metrics import StateMetricsForecast
from app.forecasting.trend_projection import TrendProjectionForecast


class ForecastModelInfo(NamedTuple):
    model_id: str
    label: str
    group: str
    description: str
    # What the definition must also supply before this model can produce anything:
    # "product_history", "reference_product" or "external_drivers". Empty means the run
    # state is enough.
    requires: str = ""


# Offered in this order: what the agents decided, then what the external environment
# does next, then what a recorded product series says.
FORECAST_CATALOG = (
    ForecastModelInfo("state_metrics", "State metrics", "Agent-based simulation",
                      "Reports the final numeric world variables the agents' decisions produced."),
    ForecastModelInfo("launch_revenue", "Launch revenue", "Agent-based simulation",
                      "Applies the configured launch funnel to the simulated state: eligible patients, treated patients, revenue."),
    ForecastModelInfo("driver_projection", "Exogenous driver projection", "Driver-based",
                      "Carries every enabled driver's index past the horizon and applies its configured pathways to the world variables they act on.",
                      "external_drivers"),
    ForecastModelInfo("product_history", "Stored product history", "Historical / product-based",
                      "Fits the stored product series, projects it, and compares it with the simulated path.",
                      "product_history"),
    ForecastModelInfo("reference_product", "Reference product analogue", "Historical / product-based",
                      "Rescales another product's recorded ramp onto the peak you enter, then projects that shape.",
                      "reference_product"),
    ForecastModelInfo("trend_projection", "Trend projection from this run", "Historical / product-based",
                      "Fits a line through every variable this run actually moved and extends it past the horizon."),
)


class ForecastRegistry:
    def __init__(self):
        self._models = {}

    def register(self, model_id, model):
        self._models[model_id] = model

    def get(self, model_id):
        try:
            return self._models[model_id]
        except KeyError as error:
            raise ValueError(f"Forecast model is not registered: {model_id}") from error

    @property
    def model_ids(self) -> set[str]:
        return set(self._models)

    def catalog(self) -> list[ForecastModelInfo]:
        """The catalogued models this registry can actually run, in offered order."""
        return [info for info in FORECAST_CATALOG if info.model_id in self._models]

    def info(self, model_id: str) -> ForecastModelInfo | None:
        return next((item for item in FORECAST_CATALOG if item.model_id == model_id), None)


def default_registry() -> ForecastRegistry:
    """Every bundled forecast plugin, shared by the runner and definition validation."""
    registry = ForecastRegistry()
    models = {"state_metrics": StateMetricsForecast(),
              "launch_revenue": LaunchForecast(),
              "driver_projection": DriverProjectionForecast(),
              "product_history": ProductHistoryForecast(),
              "reference_product": ReferenceProductForecast(),
              "trend_projection": TrendProjectionForecast()}
    for info in FORECAST_CATALOG:
        registry.register(info.model_id, models[info.model_id])
    return registry
