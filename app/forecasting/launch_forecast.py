"""Pharmaceutical launch forecast plugin, outside the generic simulation kernel."""
from app.domain.outcome import Outcome
from app.domain.world import WorldState

class LaunchForecast:
    """Compute patient-times-net-price launch metrics from named variables."""
    def forecast(self, final_state: WorldState, snapshots: list[WorldState], scenario,
                 context=None) -> Outcome:
        states = snapshots or [final_state]
        revenues, treated_values = [], []
        for state in states:
            eligible = (state.get("addressable_patients", 0) * state.get("diagnosis_rate", 0) *
                        state.get("treatment_rate", 0) * state.get("payer_access", 1))
            treated = int(eligible * state.get("market_share", 0))
            treated_values.append(treated)
            net_price = state.get("net_price")
            if net_price is None:
                net_price = state.get("drug_price", 0) * .85
            revenues.append(treated * net_price)
        return Outcome(metrics={"peak_sales": max(revenues, default=0),
            "cumulative_sales": sum(revenues), "market_share": final_state.get("market_share", 0),
            "patients_treated": max(treated_values, default=0)}, revenue_by_period=revenues)
