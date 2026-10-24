"""The standalone reference-analogue and driver-scenario forecasters.

Both exist so a number can be produced without building a simulation. They must therefore agree with
the run models that produce the same shape: every expectation here is either hand-derived or compared
against the plugin the builder would use, so the two paths cannot quietly fork. The driver tool is a
scenario of several drivers at once, so its parity tests cover both one driver and two drivers that
share a target variable.
"""
import re

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from app import api
from app.domain.definitions import SimulationDefinition, SimulationMetadata
from app.domain.driver import DriverPathway, DriverTrajectoryPoint, DriverVariant, ExternalDriver
from app.domain.history import ProductHistory
from app.domain.world import WorldState
from app.forecasting.context import ForecastContext
from app.forecasting.driver_projection import DriverProjectionForecast
from app.main import app
from app.services.history_store import ProductHistoryStore
from app.services.simulation_builder import SimulationBuilderService
from app.services.simulation_runner import SimulationRunnerService


def stored(history_id, values, name):
    return ProductHistory(history_id=history_id, name=name, values=values, variable="",
                          source="imported by hand", evidence_grade="user_assumption",
                          assumption_label="Typed in, not checked against any record.")


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = ProductHistoryStore(tmp_path / "histories")
    store.create(stored("rival-series", [10.0, 20.0, 30.0], "Rival quarterly units"))
    store.create(stored("flat-series", [5.0, 5.0, 5.0], "Flat mature product"))
    monkeypatch.setattr(api.routes, "histories", store)
    monkeypatch.setattr(api.routes, "builder",
        SimulationBuilderService(tmp_path / "simulations", history_store=store))
    monkeypatch.setattr(api.routes, "runner", SimulationRunnerService(history_store=store))
    api.routes._results.clear()
    with TestClient(app) as test_client:
        yield test_client
    api.routes._results.clear()


def analogue(client, history_id="rival-series", **body):
    return client.post("/forecast/reference-analogue",
                       json={"history_id": history_id, **body})


# ---------------------------------------------------------------- reference analogue

def test_the_analogue_stretches_the_stored_shape_then_projects_it(client):
    response = analogue(client, peak=60, periods_ahead=4)
    assert response.status_code == 200
    data = response.json()
    assert data["method"] == "reference_shape_scaled_to_peak"
    assert data["recorded"] == pytest.approx([10.0, 20.0, 30.0])
    assert data["recorded_peak"] == 30.0
    assert data["peak_target"] == 60.0
    assert data["scale"] == pytest.approx(2.0)
    # 20, 40, 60 at t0..t2 is the line y = 20 + 20x, so t3..t6 give:
    assert data["observed"] == pytest.approx([20.0, 40.0, 60.0])
    assert data["projected"] == pytest.approx([80.0, 100.0, 120.0, 140.0])
    assert data["label"] == "Rival quarterly units"


def test_the_analogue_carries_the_borrowed_series_provenance(client):
    data = analogue(client, peak=60).json()
    assert data["history_id"] == "rival-series"
    assert data["source"] == "imported by hand"
    assert data["evidence_grade"] == "user_assumption"
    assert data["assumption_label"] == "Typed in, not checked against any record."


def test_a_still_climbing_ramp_is_flagged_where_it_passes_the_entered_peak(client):
    data = analogue(client, peak=60).json()
    # The line continues past 60 in the very first projected period: a peak is a claim, not a ceiling.
    assert data["projection_above_entered_peak_at"] == 1


def test_a_flat_reference_holds_at_the_peak_and_raises_no_flag(client):
    data = analogue(client, history_id="flat-series", peak=10, periods_ahead=3).json()
    assert data["scale"] == pytest.approx(2.0)
    assert data["projected"] == pytest.approx([10.0, 10.0, 10.0])
    assert data["projection_above_entered_peak_at"] is None


def test_the_analogue_refuses_a_series_that_is_not_stored(client):
    response = analogue(client, history_id="gone-series", peak=60)
    assert response.status_code == 404
    assert "gone-series" in response.json()["detail"]


def test_the_analogue_needs_a_usable_peak(client):
    assert analogue(client, peak=0).status_code == 422
    assert analogue(client, peak=-5).status_code == 422
    assert "finite" in analogue(client, peak=float("inf")).json()["detail"]


def test_the_analogue_refuses_a_series_with_no_positive_value(client, tmp_path, monkeypatch):
    store = ProductHistoryStore(tmp_path / "zeros")
    store.create(stored("zero-series", [0.0, 0.0], "Nothing sold yet"))
    monkeypatch.setattr(api.routes, "histories", store)
    response = analogue(client, history_id="zero-series", peak=50)
    assert response.status_code == 422
    assert "no positive value" in response.json()["detail"]


# ---------------------------------------------------------------- driver scenario

def pathway(operation="add", value=5.0, **overrides):
    return {"target_variable": "price", "operation": operation, "value": value, **overrides}


def driver(name="Regulatory pressure", **overrides):
    base = {"name": name, "basis": "observed", "levels": [1.0, 2.0], "pathway": pathway()}
    return {**base, **overrides}


def price(baseline=100.0, rate=None):
    return [{"name": "price", "value": baseline,
             **({"growth_rate": rate} if rate is not None else {})}]


def scenario(client, drivers, variables=None, periods_ahead=4):
    response = client.post("/forecast/driver-scenario",
                           json={"drivers": drivers, "variables": variables or price(),
                                 "periods_ahead": periods_ahead})
    assert response.status_code == 200, response.json()
    return response.json()


def entry(data, name):
    return next(item for item in data["drivers"] if item["name"] == name)


def variable(data, name):
    return next(item for item in data["variables"] if item["name"] == name)


def test_an_observed_driver_is_fitted_continued_and_then_applied(client):
    data = scenario(client, [driver()])
    item = entry(data, "Regulatory pressure")
    # levels 1 at t0, 2 at t1 is the line y = 1 + x, so t2..t5 are 3, 4, 5, 6.
    assert item["levels_projected"] == pytest.approx([3.0, 4.0, 5.0, 6.0])
    assert item["index_at_t0"] == 2.0
    assert item["level_slope"] == pytest.approx(1.0)
    assert item["growth_rate"] is None
    # The readings themselves imply +100% per period: (2 / 1) ** (1 / 1) - 1.
    assert item["implied_growth_rate"] == pytest.approx(1.0)
    # add scales with the index, so 5 * 3, 5 * 4, 5 * 5, 5 * 6 applied in sequence onto 100.
    assert item["applied_values"] == pytest.approx([15.0, 20.0, 25.0, 30.0])
    moved = variable(data, "price")
    assert moved["baseline"] == 100.0
    assert moved["projected"] == pytest.approx([115.0, 135.0, 160.0, 190.0])
    assert moved["series"] == pytest.approx([100.0, 115.0, 135.0, 160.0, 190.0])
    assert moved["change_from_baseline"] == pytest.approx([15.0, 35.0, 60.0, 90.0])
    assert moved["drivers"] == ["Regulatory pressure"]
    assert data["application_order"] == ["Regulatory pressure"]
    assert data["shared_targets"] == []


def test_a_compound_driver_grows_its_index_geometrically_from_the_anchor(client):
    data = scenario(client, [driver("AI capability", basis="compound", levels=[],
                                    initial_level=1.0, growth_rate=0.2,
                                    pathway=pathway("add", 10.0))], price(0.0))
    item = entry(data, "AI capability")
    assert item["index_at_t0"] == 1.0
    assert item["growth_rate"] == pytest.approx(0.2)
    # 1.0 * 1.2 ** k for k = 1..4; no straight line is fitted, so no slope or residual is claimed.
    assert item["levels_projected"] == pytest.approx([1.2, 1.44, 1.728, 2.0736])
    assert item["level_slope"] is None
    assert item["level_rmse"] is None
    assert item["implied_growth_rate"] is None
    assert item["applied_values"] == pytest.approx([12.0, 14.4, 17.28, 20.736])
    assert variable(data, "price")["projected"] == pytest.approx([12.0, 26.4, 43.68, 64.416])


def test_set_and_divide_pathways_are_absolute_and_not_scaled_by_the_index(client):
    absolute = scenario(client, [driver(pathway=pathway("set", 7.0))])
    item = entry(absolute, "Regulatory pressure")
    assert item["applied_values"] == pytest.approx([7.0, 7.0, 7.0, 7.0])
    assert variable(absolute, "price")["projected"] == pytest.approx([7.0, 7.0, 7.0, 7.0])


def test_a_multiply_pathway_is_scaled_toward_one_rather_than_by_the_index(client):
    data = scenario(client, [driver(pathway=pathway("multiply", 1.2))])
    item = entry(data, "Regulatory pressure")
    # 1 + (1.2 - 1) * index -> 1.6 at index 3, then compounded on the carried value.
    assert item["applied_values"] == pytest.approx([1.6, 1.8, 2.0, 2.2])
    assert variable(data, "price")["projected"] == pytest.approx([160.0, 288.0, 576.0, 1267.2])


def test_a_pathway_ceiling_clamps_the_projection_and_reports_the_periods_that_bound(client):
    data = scenario(client, [driver(pathway=pathway("add", 5.0, maximum=130.0))])
    assert variable(data, "price")["projected"] == pytest.approx([115.0, 130.0, 130.0, 130.0])
    assert entry(data, "Regulatory pressure")["bounded_steps"] == [2, 3, 4]
    assert variable(data, "price")["bounded_steps"] == [2, 3, 4]


def test_a_subtracting_driver_can_take_a_variable_below_zero(client):
    data = scenario(client, [driver(pathway=pathway("subtract", 50.0))])
    moved = variable(data, "price")
    # applied = 50 * index -> 150, 200, 250, 300 subtracted in sequence from 100.
    assert moved["projected"] == pytest.approx([-50.0, -250.0, -500.0, -800.0])
    assert moved["below_zero_at"] == 1


def test_several_drivers_on_one_variable_stack_and_attribute_the_change_they_caused(client):
    data = scenario(client, [
        driver("Price floor pressure", basis="compound", levels=[], initial_level=1.0,
               growth_rate=0.0, pathway=pathway("add", 5.0)),
        driver("Patent expiry", basis="observed", levels=[1.0, 1.0],
               pathway=pathway("multiply", 0.9))], periods_ahead=2)
    adder = entry(data, "Price floor pressure")
    multiplier = entry(data, "Patent expiry")
    assert adder["contributions"] == pytest.approx([5.0, 5.0])
    # The multiplier fires second, so it acts on the value the adder already left behind.
    assert multiplier["contributions"] == pytest.approx([-10.5, -9.95])
    assert variable(data, "price")["projected"] == pytest.approx([94.5, 89.55])
    assert data["shared_targets"] == [{"variable": "price",
                                      "drivers": ["Price floor pressure", "Patent expiry"]}]


def test_the_application_order_changes_the_end_value_when_a_multiplier_is_involved(client):
    adder = lambda: driver("Price floor pressure", basis="compound", levels=[], initial_level=1.0,
                           growth_rate=0.0, pathway=pathway("add", 5.0))
    multiplier = lambda: driver("Patent expiry", basis="observed", levels=[1.0, 1.0],
                                pathway=pathway("multiply", 0.9))
    first = scenario(client, [adder(), multiplier()], periods_ahead=2)
    reversed_ = scenario(client, [multiplier(), adder()], periods_ahead=2)
    assert variable(first, "price")["projected"] == pytest.approx([94.5, 89.55])
    # Order matters to the value, not only to the attribution: 100 * 0.9 + 5 is 95, not 94.5.
    assert variable(reversed_, "price")["projected"] == pytest.approx([95.0, 90.5])
    assert reversed_["application_order"] == ["Patent expiry", "Price floor pressure"]


def test_drivers_on_different_variables_are_projected_independently(client):
    data = scenario(client, [
        driver("Regulatory pressure", pathway=pathway("add", 5.0)),
        driver("Channel growth", basis="compound", levels=[], initial_level=2.0, growth_rate=0.5,
               pathway=pathway("multiply", 1.1, target_variable="volume"))],
        variables=price() + [{"name": "volume", "value": 40.0}], periods_ahead=3)
    assert variable(data, "price")["projected"] == pytest.approx([115.0, 135.0, 160.0])
    # 2.0 * 1.5 ** k -> 3, 4.5, 6.75; a multiply pathway is scaled toward one, so
    # 1 + (1.1 - 1) * index -> 1.3, 1.45, 1.675 applied in sequence to the carried volume.
    assert entry(data, "Channel growth")["levels_projected"] == pytest.approx([3.0, 4.5, 6.75])
    assert entry(data, "Channel growth")["applied_values"] == pytest.approx([1.3, 1.45, 1.675])
    assert variable(data, "volume")["projected"] == pytest.approx([52.0, 75.4, 126.295])
    assert data["shared_targets"] == []


def test_a_hypothesis_only_pathway_projects_its_index_but_applies_no_number(client):
    data = scenario(client, [
        driver("Cultural shift", basis="compound", levels=[], initial_level=1.0, growth_rate=0.5,
               pathway=pathway("add", 100.0, qualitative_only=True))])
    item = entry(data, "Cultural shift")
    assert item["qualitative_only"] is True
    assert item["levels_projected"] == pytest.approx([1.5, 2.25, 3.375, 5.0625])
    assert item["applied_values"] == [None, None, None, None]
    assert item["contributions"] == pytest.approx([0.0, 0.0, 0.0, 0.0])
    assert data["hypotheses"] == ["Cultural shift"]
    assert variable(data, "price")["projected"] == pytest.approx([100.0, 100.0, 100.0, 100.0])


def test_a_hypothesis_only_pathway_needs_no_effect_magnitude(client):
    # The domain default is what a builder writes when a link is declared qualitative only.
    data = scenario(client, [driver("Cultural shift",
                                    pathway={"target_variable": "price", "qualitative_only": True})])
    item = entry(data, "Cultural shift")
    assert item["applied_values"] == [None] * 4
    assert item["pathway"]["magnitude"] == 0.0
    assert variable(data, "price")["projected"] == pytest.approx([100.0] * 4)


def test_each_pathway_keeps_the_domain_semantics_and_grade_it_carries_in_a_run(client):
    data = scenario(client, [driver(pathway=pathway("add", 5.0, minimum=10.0, evidence_grade="empirical",
                                            uncertainty="+/-2 quarters"))])
    configured = entry(data, "Regulatory pressure")["pathway"]
    assert configured == {"operation": "add", "magnitude": 5.0, "minimum": 10.0, "maximum": None,
                          "evidence_grade": "empirical", "basis": "", "uncertainty": "+/-2 quarters",
                          "lag": 0}


def test_the_scenario_refuses_a_pathway_that_points_at_an_unlisted_variable(client):
    response = client.post("/forecast/driver-scenario", json={"drivers": [
        driver(pathway=pathway("add", 5.0, target_variable="market_share"))], "variables": price(),
        "periods_ahead": 4})
    assert response.status_code == 422
    assert "market_share" in response.json()["detail"]


def test_a_variable_compounds_at_its_own_rate_before_any_pathway_lands(client):
    data = scenario(client, [driver()], price(rate=0.10), periods_ahead=2)
    moved = variable(data, "price")
    # Organic: 100 -> 110 -> 121. Pathways then act on the grown value: 5 * 3 = 15 on 110,
    # and 5 * 4 = 20 on 125 * 1.1 = 137.5.
    assert moved["growth_rate"] == pytest.approx(0.10)
    assert moved["organic_series"] == pytest.approx([100.0, 110.0, 121.0])
    assert moved["projected"] == pytest.approx([125.0, 157.5])
    assert moved["organic_change"] == pytest.approx([10.0, 21.0])
    assert moved["driver_effect"] == pytest.approx([15.0, 36.5])
    assert moved["change_from_baseline"] == pytest.approx([25.0, 57.5])
    # The two reported halves always rejoin the whole, so attribution cannot drift from the total.
    assert [organic + effect for organic, effect in
            zip(moved["organic_change"], moved["driver_effect"])] == pytest.approx(
                moved["change_from_baseline"])


def test_a_variable_with_growth_and_no_pathway_is_a_line_that_moves(client):
    # A declared drift is a reason to keep the row; only a flat, untargeted one is inert.
    data = scenario(client, [driver()], price() + [{"name": "volume", "value": 40.0,
                                                    "growth_rate": 0.05}], periods_ahead=3)
    still = variable(data, "volume")
    assert still["drivers"] == []
    assert still["projected"] == pytest.approx([42.0, 44.1, 46.305])
    assert still["driver_effect"] == pytest.approx([0.0, 0.0, 0.0])
    assert variable(data, "price")["projected"] == pytest.approx([115.0, 135.0, 160.0])


def test_declared_growth_still_lands_under_a_configured_floor(client):
    data = scenario(client, [driver(pathway=pathway("subtract", 50.0, minimum=0.0))],
                    price(rate=0.10), periods_ahead=2)
    moved = variable(data, "price")
    # t1: 100 grows to 110, then 50 * 3 = 150 subtracted would give -40, so the floor holds it at 0.
    # t2: the counterfactual organic path keeps compounding to 121 while the carried value, 0,
    # grows to 0 and is clamped again.
    assert moved["projected"] == pytest.approx([0.0, 0.0])
    assert moved["organic_series"] == pytest.approx([100.0, 110.0, 121.0])
    assert entry(data, "Regulatory pressure")["bounded_steps"] == [1, 2]
    assert moved["bounded_steps"] == [1, 2]


def test_the_scenario_refuses_an_annihilating_or_unreadable_growth_rate(client):
    for rate in (-1.0, -1.5):
        response = client.post("/forecast/driver-scenario", json={"drivers": [driver()],
            "variables": price(rate=rate), "periods_ahead": 2})
        assert response.status_code == 422
        assert "annihilates" in response.json()["detail"]
    assert client.post("/forecast/driver-scenario", json={"drivers": [driver()],
        "variables": price(rate=float("nan")), "periods_ahead": 2}).status_code == 422


def test_a_flat_variable_that_no_pathway_targets_is_still_refused(client):
    response = client.post("/forecast/driver-scenario", json={"drivers": [driver()],
        "variables": price() + [{"name": "volume", "value": 40.0, "growth_rate": 0.0}],
        "periods_ahead": 2})
    assert response.status_code == 422
    assert "no growth rate of its own" in response.json()["detail"]


def test_the_scenario_refuses_a_baseline_that_no_pathway_moves(client):
    response = client.post("/forecast/driver-scenario", json={"drivers": [driver()],
        "variables": price() + [{"name": "volume", "value": 40.0}], "periods_ahead": 4})
    assert response.status_code == 422
    assert "volume" in response.json()["detail"]


def test_the_scenario_refuses_impossible_indices_and_pathways(client):
    def refused(drivers, variables=None):
        return client.post("/forecast/driver-scenario",
                           json={"drivers": drivers, "variables": variables or price(),
                                 "periods_ahead": 4}).status_code

    assert refused([driver(levels=[1.0])]) == 422                      # no slope to continue
    assert refused([driver(basis="compound", levels=[], initial_level=1.0, growth_rate=-1.5)]) == 422
    assert refused([driver(basis="compound", levels=[], initial_level=1.0)]) == 422
    assert refused([driver(pathway=pathway("divide", 0.0))]) == 422
    assert refused([driver(pathway=pathway("add", 5.0, minimum=10.0, maximum=5.0))]) == 422
    assert refused([driver(pathway=pathway("add", "price * 2"))]) == 422       # a formula is not a number
    assert refused([driver(), driver("Regulatory pressure")]) == 422   # names must be unique


# ---------------------------------------------------------------- parity with the run model

def test_a_one_driver_scenario_reproduces_the_driver_projection_forecast_model(client):
    points = [DriverTrajectoryPoint(time=0, level=1.0), DriverTrajectoryPoint(time=1, level=2.0)]
    definition = SimulationDefinition(
        metadata=SimulationMetadata(id="parity", name="Parity"),
        initial_world_state=WorldState(time=0, variables={"price": 100}),
        agents=[], external_drivers=[ExternalDriver(
            driver_id="policy", name="Policy shock", active_variant="central",
            variants=[DriverVariant(variant_id="central", label="Central", trajectory=points)],
            pathways=[DriverPathway(target_variable="price", operation="add", value=5)])])
    outcome = DriverProjectionForecast().forecast(
        WorldState(time=1, variables={"price": 100}), [], None, ForecastContext(definition=definition))
    assert variable(scenario(client, [driver()]), "price")["projected"] \
        == pytest.approx(outcome.projections["price"])


def test_several_scenario_drivers_reproduce_the_run_model_with_several_drivers(client):
    def trajectory_points():
        return [DriverTrajectoryPoint(time=0, level=1.0), DriverTrajectoryPoint(time=1, level=2.0)]

    flat = [DriverTrajectoryPoint(time=0, level=1.0), DriverTrajectoryPoint(time=1, level=1.0)]
    definition = SimulationDefinition(
        metadata=SimulationMetadata(id="parity-two", name="Parity two"),
        initial_world_state=WorldState(time=0, variables={"price": 100}),
        agents=[], external_drivers=[
            ExternalDriver(driver_id="policy", name="Price floor pressure", active_variant="central",
                           variants=[DriverVariant(variant_id="central", label="Central",
                                                   trajectory=trajectory_points())],
                           pathways=[DriverPathway(target_variable="price", operation="add", value=5)]),
            ExternalDriver(driver_id="patent", name="Patent expiry", active_variant="central",
                           variants=[DriverVariant(variant_id="central", label="Central", trajectory=flat)],
                           pathways=[DriverPathway(target_variable="price", operation="multiply",
                                                   value=0.9)])])
    outcome = DriverProjectionForecast().forecast(
        WorldState(time=1, variables={"price": 100}), [], None, ForecastContext(definition=definition))
    data = scenario(client, [driver("Price floor pressure"),
                             driver("Patent expiry", levels=[1.0, 1.0],
                                    pathway=pathway("multiply", 0.9))])
    # The run model records a value after every pathway fires, so the end of each period is every
    # second entry. The scenario reports one value per period, after the last driver has fired.
    assert variable(data, "price")["projected"] == pytest.approx(outcome.projections["price"][1::2])


# ---------------------------------------------------------------- the three methods stay separate

def test_each_standalone_method_is_its_own_route(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/forecast/time-series", "/forecast/reference-analogue",
            "/forecast/driver-scenario"} <= set(paths)
    assert "/forecast/driver-trajectory" not in paths


def test_the_driver_card_offers_the_two_index_bases_and_a_growth_rate_per_driver():
    markup = static("index.html")
    assert "Driver-Based Forecasting" in markup
    for field in ("dtDrivers", "dtVariables", "dtAddDriver", "dtAddVariable", "dtFile", "dtVarFile"):
        assert f'id="{field}"' in markup
    # Both registers carry their own growth rate: the driver's index and the affected variable's drift.
    assert "Driver growth per period (%)" in markup
    assert "Variable growth per period (%)" in markup


def test_every_column_header_of_a_register_has_a_cell_of_its_own():
    """A row that emits fewer cells than the header has shifts every later input sideways, which is
    how a value reaches the wrong field, so cell counts are asserted rather than eyeballed."""
    markup = static("index.html")
    script = static("forecaster.js")

    def headers(table_id):
        block = markup.split(f'id="{table_id}"></tbody>')[0]
        head = block.rsplit("<thead>", 1)[1].split("</thead>")[0]
        return head.count("<th")

    def cells(builder):
        body = script.split(f"function {builder}(")[1].split("\nfunction ")[0]
        return body.count("field(row,") + body.count("createElement('td')")

    assert cells("addDriverRow") == headers("dtDrivers") == 13
    assert cells("addDriverVariableRow") == headers("dtVariables") == 5


def _register_cell_hints() -> tuple[dict[str, str], dict[str, str]]:
    hints = static("hints.js")
    block = hints.split("const HINT_FORECAST_CELL")[1].split("const HINT_FORECAST_OPTION")[0]
    driver = dict(re.findall(r"(\w+):'([^']*)'", block.split("driver:{")[1].split("variable:{")[0]))
    variable = dict(re.findall(r"(\w+):'([^']*)'", block.split("variable:{")[1]))
    return driver, variable


def test_every_register_input_explains_itself_not_just_its_column():
    """Both registers are built by script from bare inputs with no <label>, so the label-driven hint
    lookup cannot reach them. A column header several boxes away does not tell you the format, the
    range or what the model does with the number you are about to type into that box."""
    script = static("forecaster.js")
    driver, variable = _register_cell_hints()
    declared = re.findall(r"(\w+):'", re.search(r"const DRIVER_CELLS=\{(.*?)\};", script, re.S).group(1))
    assert set(driver) >= set(declared), f"driver cells with no hint: {set(declared) - set(driver)}"
    assert set(variable) >= {"name", "value", "unit", "growth"}
    for key, text in list(driver.items()) + list(variable.items()):
        assert len(text) > 100, f"{key}: the hint is too short to be an explanation"
        assert "model" in text.lower(), f"{key}: the hint never says how the model uses the field"
    for key in ("levels", "initial", "growth", "magnitude", "minimum", "maximum"):
        assert re.search(r"Format|percentage", driver[key]), f"driver {key}: no format or range stated"
    for key in ("value", "unit", "growth"):
        assert re.search(r"Format|percentage|free text", variable[key]), f"variable {key}: no format stated"


def test_every_register_choice_explains_the_rule_it_selects():
    """A dropdown whose entries mean different arithmetic is only explainable per entry, so the
    option list itself has to be covered — and covered from the panel's own lists, not a copy."""
    script, hints = static("forecaster.js"), static("hints.js")
    options = hints.split("const HINT_FORECAST_OPTION")[1].split("const HINT_LEGEND")[0]
    def values(declaration):
        return re.findall(r"'([^']+)'", re.search(declaration, script).group(1))
    for block, choices in (("basis:", ("observed", "compound")),
                          ("operation:", values(r"const PATHWAY_OPERATIONS=\[(.*?)\];")),
                          ("grade:", values(r"const PATHWAY_GRADES=\[(.*?)\];"))):
        body = options.split(block)[1].split("},", 1)[0]
        for choice in choices:
            assert f"{choice}:'" in body, f"{block[:-1]} explains nothing about {choice}"


def test_register_rows_get_their_icons_when_the_row_is_built():
    """The registers only exist after the scripts build them, so the one pass over the static markup
    cannot have attached their icons; each builder has to attach them on its own row."""
    script = static("forecaster.js")
    for builder in ("addDriverRow", "addDriverVariableRow"):
        body = script.split(f"function {builder}(")[1].split("\nfunction ")[0]
        assert "attachHints(row)" in body, f"{builder} builds cells no info icon ever appears on"
        assert "row.dataset.register=" in body, f"{builder} leaves the cells without a register to look up"


def test_no_two_scripts_declare_the_same_top_level_name():
    """Plain ``<script>`` files share one global scope, so a repeated name is a silent override.

    ``addVariableRow`` was declared once by the builder and once by the driver panel. The panel
    loads last and won, so loading an example appended world variables into the driver register and
    left the builder's variable table empty. The run then evaluated its transition expressions
    against a state with no variables, and a name the parser could not resolve came back as the
    bare string it was spelled like, which the engine tried to multiply.
    """
    declared: dict[str, list[str]] = {}
    for file in sorted((Path(__file__).resolve().parents[1] / "app" / "static").glob("*.js")):
        source = file.read_text(encoding="utf-8")
        for pattern in (r"^(?:async )?function ([A-Za-z_$][\w$]*)", r"^(?:let|const|var) ([A-Za-z_$][\w$]*)"):
            for match in re.finditer(pattern, source, re.M):
                declared.setdefault(match.group(1), []).append(file.name)
    clashes = {name: files for name, files in declared.items() if len(set(files)) > 1}
    assert not clashes, f"declared by more than one script: {clashes}"


# ---------------------------------------------------------------- the words the user reads

def static(name):
    return (Path(__file__).resolve().parents[1] / "app" / "static" / name).read_text(encoding="utf-8")


def test_the_forecasting_terms_are_consistent_between_the_ui_the_routes_and_the_models():
    markup, script = static("index.html"), static("forecaster.js")
    # The three canonical method names, and one primary action button each.
    for phrase in ("Time Series Forecasting", "Analogue-Based Forecasting", "Driver-Based Forecasting",
                   "Generate Time Series Forecast", "Generate Analogue-Based Forecast",
                   "Generate Driver-Based Forecast", "Forecast horizon (periods", "Index basis",
                   "Affected model variable", "Observed driver-index values (oldest to newest)",
                   "Driver index at forecast start", "Minimum allowed value", "Maximum allowed value",
                   "Evidence quality/grade", "Hypothesis only (not evidence-backed)",
                   "Baseline value at forecast start", "Reference product history (analogue)"):
        assert phrase in markup, phrase
    # The empty state before any forecast names the button that clears it, not "the forecast".
    for phrase in ("then choose Generate Time Series Forecast",
                   "then choose Generate Analogue-Based Forecast",
                   "then choose Generate Driver-Based Forecast"):
        assert phrase in markup, phrase
    # Result headings name the kind of number, never a generic "Results".
    for phrase in ("Observed values and fitted trend", "Forecast values (projected, not observed)",
                   "Fitted trend", "Scaling factor", "Data kind", "projected — not observed",
                   "Affected variables", "How this forecast was calculated"):
        assert phrase in script, phrase
    # Internal identifiers, retired method names and retired prose must never reach what the user reads.
    for leak in ("fcMethod", "Driver trajectory forecaster", "One pathway only",
                 "Driver scenario forecaster", "Time series forecaster", "Reference analogue forecaster",
                 "Assumed peak", "Project the scenario", "Project forward", "Project the analogue"):
        assert leak not in markup, leak
        assert leak not in script, leak


def test_the_route_names_every_answer_field_with_the_same_words_the_card_uses(client):
    data = scenario(client, [driver(pathway=pathway("multiply", 1.1))], periods_ahead=2)
    assert set(data["drivers"][0]) >= {"index_basis", "levels_projected", "growth_rate",
                                       "implied_growth_rate", "contributions", "bounded_steps"}
    assert set(data) >= {"application_order", "hypotheses", "shared_targets"}
    assert data["method"] == "driver_scenario_pathway_projection"


def test_the_driver_model_is_named_the_same_way_in_the_catalog_as_on_the_card(client):
    # The card promises the same arithmetic as the run model, so the two must also share one name.
    labels = {model["model_id"]: model["label"] for model in client.get("/forecast/models").json()}
    assert labels["driver_projection"] == "Exogenous driver projection"


# ---------------------------------------------------------------- what the card is allowed to assume

def test_a_baseline_is_required_rather_than_defaulted(client):
    # A missing value used to arrive as 0.0 and project a variable from nothing at all.
    response = client.post("/forecast/driver-scenario", json={"drivers": [driver()],
                             "variables": [{"name": "price"}], "periods_ahead": 2})
    assert response.status_code == 422
    error = next(item for item in response.json()["detail"] if "value" in item["loc"][-1:])
    assert error["type"] == "missing"


def test_the_horizon_is_required_and_whole(client):
    for horizon in (0, -1, 2.5, 61):
        assert client.post("/forecast/driver-scenario", json={"drivers": [driver()],
                             "variables": price(), "periods_ahead": horizon}).status_code == 422
    assert client.post("/forecast/driver-scenario", json={"drivers": [driver()],
                         "variables": price(), "periods_ahead": 2}).status_code == 200


def test_a_variable_unit_is_stored_and_echoed_beside_its_numbers(client):
    data = scenario(client, [driver()],
                    variables=[{"name": "price", "value": 100.0, "unit": "USD per course"}])
    assert variable(data, "price")["unit"] == "USD per course"
    # No unit is a legitimate answer, but it has to be reported as unstated, not invented.
    assert variable(scenario(client, [driver()]), "price")["unit"] == ""


def test_a_product_history_keeps_the_metric_and_cadence_it_was_saved_with(client):
    created = client.post("/histories", json={"history_id": "share-ramp", "name": "Rival share",
                                              "values": [0.05, 0.11, 0.18],
                                              "unit": "market share as a fraction (0-1)",
                                              "cadence": "quarter"})
    assert created.status_code == 201
    stored_item = client.get("/histories/share-ramp").json()
    assert (stored_item["unit"], stored_item["cadence"]) == ("market share as a fraction (0-1)", "quarter")
    listed = next(item for item in client.get("/histories").json() if item["history_id"] == "share-ramp")
    assert listed["unit"] == "market share as a fraction (0-1)"
    data = analogue(client, history_id="share-ramp", peak=0.4).json()
    # The analogue answer carries the metric into the card, which labels the peak input with it.
    assert (data["unit"], data["cadence"]) == ("market share as a fraction (0-1)", "quarter")


def test_the_analogue_note_describes_a_stored_series_by_the_fields_the_list_sends(client):
    """The panel writes its borrowed-series note from the ``/histories`` list, never a fetched series.

    The list is a summary: it carries ``points`` and the recorded ``peak`` but not the values.
    Reading ``values.length`` off it threw on every page load, and because the same call runs
    inside the landing-page boot, the examples and saved simulations never appeared either.
    """
    listed = client.get("/histories").json()[0]
    assert {"points", "peak", "unit", "cadence", "evidence_grade"} <= set(listed)
    assert "values" not in listed
    script = static("forecaster.js")
    assert ".values.length" not in script
    assert "recorded periods and graded" in script


def test_the_observed_index_fit_reports_the_line_the_card_prints(client):
    data = scenario(client, [driver(levels=[1.0, 2.0, 3.0])], periods_ahead=2)
    entry_item = entry(data, "Regulatory pressure")
    # The readings are y = 1 + t, so the line the card prints has intercept 1 and slope 1.
    assert entry_item["level_intercept"] == pytest.approx(1.0)
    assert entry_item["level_slope"] == pytest.approx(1.0)
    assert entry_item["levels_fitted"] == pytest.approx([1.0, 2.0, 3.0])
    # A compound basis has no line, so it must not print one it never fitted.
    compound = entry(scenario(client, [driver(basis="compound", levels=[], initial_level=1.0,
                                              growth_rate=0.1)], periods_ahead=2),
                     "Regulatory pressure")
    assert compound["level_intercept"] is None and compound["level_slope"] is None


def test_the_documented_formula_is_the_arithmetic_the_route_performed(client):
    """The card prints these numbers as the formula it used, so each one has to reproduce the series
    it came from — a disclosed equation that does not match the code is worse than none."""
    readings = [1.0, 2.0, 3.0]
    entry_item = entry(scenario(client, [driver(levels=readings)], periods_ahead=3),
                       "Regulatory pressure")
    intercept, slope = entry_item["level_intercept"], entry_item["level_slope"]
    assert entry_item["levels_fitted"] == pytest.approx([intercept + slope * step for step in range(3)])
    assert entry_item["levels_projected"] == pytest.approx([intercept + slope * step for step in (3, 4, 5)])
    assert entry_item["level_rmse"] == pytest.approx(0.0)

    data = analogue(client, peak=60, periods_ahead=4).json()
    assert data["scale"] == pytest.approx(data["peak_target"] / data["recorded_peak"])
    assert data["observed"] == pytest.approx([value * data["scale"] for value in data["recorded"]])
    assert data["fitted"] == pytest.approx([data["intercept"] + data["slope"] * step
                                            for step in range(len(data["observed"]))])
    assert data["projected"] == pytest.approx([data["intercept"] + data["slope"] * step
                                               for step in (3, 4, 5, 6)])
    assert data["rmse"] == pytest.approx(sum((actual - fitted) ** 2
                                             for actual, fitted in zip(data["observed"], data["fitted"]))
                                         ** 0.5 / len(data["observed"]) ** 0.5)

    single = scenario(client, [driver(pathway=pathway("add", 5.0))], periods_ahead=2)
    held = variable(single, "price")
    index = entry(single, "Regulatory pressure")["levels_projected"]
    # add scales with the index, and with no organic drift the whole change is the driver's own.
    assert held["projected"] == pytest.approx([100.0 + 5.0 * index[0],
                                               100.0 + 5.0 * index[0] + 5.0 * index[1]])
    assert held["organic_series"] == pytest.approx([100.0, 100.0, 100.0])


# ---------------------------------------------------------------- the charts the results are drawn in

def test_the_result_charts_are_drawn_by_one_reusable_implementation():
    dashboard, script = static("dashboard.js"), static("forecaster.js")
    # Hover reporting, a toggleable legend, and a value marker for an entered level are all options of
    # the one chart builder; no panel may roll its own.
    for phrase in ("options.valueLines", "chart-hit", "legend-item", "aria-pressed", "chart-tip",
                   "options.annotations", "onSelect", "options.scenarioKeys"):
        assert phrase in dashboard, phrase
    assert "scenarioKeys:false" in script
    for panel in ("renderForecast", "renderAnalogue", "renderDriver"):
        body = script.split(f"function {panel}(")[1].split("\nfunction ")[0]
        assert "seriesChart(" in body, panel
        assert "svg" not in body, panel


def test_every_panel_states_that_its_error_measure_is_in_sample():
    """No panel holds a period back, so none may imply it measured out-of-sample accuracy.

    The brief asks for forecast quality or backtesting; the honest answer here is the limitation,
    stated per panel, rather than a score invented to look like skill.
    """
    script = static("forecaster.js")
    for phrase in ("The RMSE is in-sample: it measures how well the line describes the periods it was fitted to",
                   "The RMSE is in-sample to the rescaled shape",
                   "its fit RMSE is in-sample to those readings"):
        assert phrase in script, phrase