"""Generic forecast plugin that reports final numeric world variables."""
from app.domain.outcome import Outcome
from app.domain.world import WorldState

class StateMetricsForecast:
    """Return final numeric variables as metrics, without domain assumptions."""
    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario) -> Outcome:
        metrics = {key: value for key, value in final_state.as_variables().items()
                   if isinstance(value, (int, float)) and not isinstance(value, bool)}
        metrics["time"] = final_state.time
        return Outcome(metrics=metrics)
