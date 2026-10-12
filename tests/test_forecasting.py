"""Hand-derived deterministic fixtures for the launch forecast equation."""
from app.domain.world import WorldState
from app.forecasting.launch_forecast import LaunchForecast

def forecast(**variables):
    state = WorldState(variables=variables)
    return LaunchForecast().forecast(state, [state], None)

def test_hand_calculation_one_million_population_and_net_price():
    # eligible = 1,000,000 * .50 * .50 * 1.0 = 250,000
    # treated = int(250,000 * .10) = 25,000
    # revenue = 25,000 * $100,000 = $2,500,000,000
    result = forecast(addressable_patients=1_000_000, diagnosis_rate=.5,
        treatment_rate=.5, payer_access=1.0, market_share=.10, net_price=100_000)
    assert result.patients_treated == 25_000
    assert result.peak_sales == 2_500_000_000
    assert result.cumulative_sales == 2_500_000_000

def test_zero_penetration_and_zero_access_produce_zero_sales():
    base = dict(addressable_patients=1_000_000, diagnosis_rate=.5, treatment_rate=.5,
                payer_access=1, market_share=0, net_price=100_000)
    zero_penetration = forecast(**base)
    assert zero_penetration.patients_treated == zero_penetration.peak_sales == 0
    base.update(payer_access=0, market_share=.8)
    zero_access = forecast(**base)
    assert zero_access.patients_treated == zero_access.cumulative_sales == 0

def test_access_bounds_low_and_high_net_price():
    common = dict(addressable_patients=100_000, diagnosis_rate=.5, treatment_rate=.5,
                  market_share=.1)
    no_access = forecast(**common, payer_access=0, net_price=100_000)
    full_access = forecast(**common, payer_access=1, net_price=100_000)
    low_price = forecast(**common, payer_access=1, net_price=10_000)
    high_price = forecast(**common, payer_access=1, net_price=200_000)
    assert no_access.patients_treated == 0
    assert full_access.patients_treated == 2_500
    assert low_price.peak_sales == 25_000_000
    assert high_price.peak_sales == 500_000_000

def test_changing_market_share_changes_volume_and_revenue():
    snapshots = [
        WorldState(variables={"addressable_patients":1_000_000,"diagnosis_rate":.5,
            "treatment_rate":.5,"payer_access":1,"market_share":.1,"net_price":100_000}),
        WorldState(time=1, variables={"addressable_patients":1_000_000,"diagnosis_rate":.5,
            "treatment_rate":.5,"payer_access":1,"market_share":.2,"net_price":100_000})]
    result = LaunchForecast().forecast(snapshots[-1], snapshots, None)
    assert result.revenue_by_period == [2_500_000_000, 5_000_000_000]
    assert result.cumulative_sales == 7_500_000_000
    assert result.peak_sales == 5_000_000_000
    assert result.patients_treated == 50_000

def test_patient_count_scales_linearly_and_gross_price_uses_current_discount():
    result = forecast(addressable_patients=200_000, diagnosis_rate=.5, treatment_rate=.8,
        payer_access=.5, market_share=.1, drug_price=10_000)
    # eligible=40,000, treated=4,000, net price=10,000*.85, revenue=$34M.
    assert result.patients_treated == 4_000
    assert result.peak_sales == 34_000_000

def test_changing_addressable_patient_count_scales_each_period():
    common = {"diagnosis_rate": .5, "treatment_rate": .5, "payer_access": 1,
              "market_share": .1, "net_price": 100_000}
    snapshots = [
        WorldState(variables={**common, "addressable_patients": 100_000}),
        WorldState(time=1, variables={**common, "addressable_patients": 200_000}),
    ]
    result = LaunchForecast().forecast(snapshots[-1], snapshots, None)
    assert result.revenue_by_period == [250_000_000, 500_000_000]
    assert result.patients_treated == 5_000
    assert result.cumulative_sales == 750_000_000
