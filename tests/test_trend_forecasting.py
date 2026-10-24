"""Deterministic trend fitting: the shared math, the run forecast plugin and the standalone endpoint."""
from math import sqrt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.domain.definitions import SimulationDefinition
from app.domain.world import WorldState
from app.forecasting.registry import default_registry
from app.forecasting.trend import fit_trend
from app.forecasting.trend_projection import TrendProjectionForecast
from app.main import app
from app.services.simulation_builder import SimulationBuilderService
from app.services.simulation_runner import SimulationRunnerService

PROJECT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT / "examples"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(api.routes, "builder", SimulationBuilderService(tmp_path, EXAMPLES))
    api.routes._results.clear()
    with TestClient(app) as test_client:
        yield test_client
    api.routes._results.clear()


def test_straight_line_recovers_slope_and_projects_it_forward():
    fit = fit_trend([10, 12, 14, 16], periods_ahead=3)
    assert (fit.start, fit.latest, fit.slope) == (10, 16, 2)
    assert fit.projected == [18, 20, 22]
    assert fit.rmse == 0
    assert fit.mean_change == fit.total_change / 3 == 2


def test_residual_error_measures_distance_from_the_fitted_line():
    # mean x=1, mean y=1, spread=2, covariance=3 -> slope 1.5, intercept -0.5.
    fit = fit_trend([0, 0, 3])
    assert fit.slope == pytest.approx(1.5)
    assert fit.intercept == pytest.approx(-0.5)
    assert fit.fitted == pytest.approx([-0.5, 1.0, 2.5])
    assert fit.rmse == pytest.approx(sqrt(0.5))


def test_a_single_observation_projects_flat_instead_of_inventing_a_trend():
    fit = fit_trend([7], periods_ahead=2)
    assert fit.slope == 0
    assert fit.projected == [7, 7]


def test_an_empty_series_and_a_negative_horizon_are_rejected():
    with pytest.raises(ValueError, match="at least one observed value"):
        fit_trend([])
    with pytest.raises(ValueError, match="cannot be negative"):
        fit_trend([1, 2], periods_ahead=-1)


def test_forecast_reports_trend_only_for_variables_that_moved():
    snapshots = [WorldState(time=step, variables={"market_share": 0.1 * (step + 1), "price": 100})
                 for step in range(3)]
    outcome = TrendProjectionForecast(projection_periods=4).forecast(snapshots[-1], snapshots, None)
    assert set(outcome.metrics) == {"market_share", "market_share_trend_per_period",
                                    "market_share_projected"}
    assert outcome.metrics["market_share"] == pytest.approx(0.3)
    assert outcome.metrics["market_share_trend_per_period"] == pytest.approx(0.1)
    assert outcome.projections["market_share"][-1] == pytest.approx(0.7)
    assert outcome.metrics["market_share_projected"] == pytest.approx(0.7)


def test_forecast_of_a_run_with_no_movement_produces_no_trends():
    state = WorldState(variables={"price": 100})
    outcome = TrendProjectionForecast().forecast(state, [state, state], None)
    assert outcome.metrics == {}
    assert outcome.projections == {}


def test_definition_validation_and_the_runner_share_one_forecast_registry():
    service = SimulationBuilderService(Path(__file__).parent, EXAMPLES)
    assert service.forecast_model_ids == default_registry().model_ids
    assert "trend_projection" in service.forecast_model_ids


def test_time_series_endpoint_projects_a_pasted_history(client):
    response = client.post("/forecast/time-series",
                           json={"values": [10, 12, 14, 16], "periods_ahead": 3, "label": "Revenue"})
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "linear_least_squares"
    assert body["label"] == "Revenue"
    assert body["observed"] == [10, 12, 14, 16]
    assert body["fitted"] == pytest.approx([10, 12, 14, 16])
    assert body["projected"] == pytest.approx([18, 20, 22])
    assert body["rmse"] == pytest.approx(0)
    assert body["projection_below_zero_at"] is None


def test_time_series_endpoint_requires_more_than_one_point(client):
    assert client.post("/forecast/time-series", json={"values": [10]}).status_code == 422
    assert client.post("/forecast/time-series", json={"values": [1, 2], "periods_ahead": 0}).status_code == 422


def test_endpoint_flags_where_a_declining_line_leaves_the_valid_range(client):
    body = client.post("/forecast/time-series",
                       json={"values": [10, 8, 6], "periods_ahead": 4}).json()
    assert body["projected"] == pytest.approx([4, 2, 0, -2])
    assert body["projection_below_zero_at"] == 4


def test_the_endpoint_reports_each_observed_period_s_residual(client):
    # RMSE averages the miss away; the panel prints the residual per period, so the route has to send it.
    body = client.post("/forecast/time-series",
                       json={"values": [10, 13, 14, 19], "periods_ahead": 2}).json()
    assert body["residuals"] == pytest.approx([actual - fitted for actual, fitted
                                               in zip(body["observed"], body["fitted"])])
    assert body["rmse"] == pytest.approx(sqrt(sum(value ** 2 for value in body["residuals"])
                                              / len(body["residuals"])))


def test_the_standalone_trend_matches_the_run_model_on_the_same_series(client):
    """The card claims one fit for both paths, so the endpoint and the plugin are run over identical
    numbers and every reported figure has to agree — not a tolerance on the method, the outputs."""
    values = [10, 12.5, 14, 15.5, 17]
    body = client.post("/forecast/time-series", json={"values": values, "periods_ahead": 3}).json()
    states = [WorldState(time=step, variables={"units": value}) for step, value in enumerate(values)]
    outcome = TrendProjectionForecast(projection_periods=3).forecast(states[-1], states, None)
    assert body["projected"] == pytest.approx(outcome.projections["units"])
    assert body["slope"] == pytest.approx(outcome.metrics["units_trend_per_period"])
    assert body["latest"] == pytest.approx(outcome.metrics["units"])
    assert body["projected"][-1] == pytest.approx(outcome.metrics["units_projected"])
    fit = fit_trend(values, 3)
    assert body["intercept"] == pytest.approx(fit.intercept)
    assert body["fitted"] == pytest.approx(fit.fitted)
    assert body["residuals"] == pytest.approx(fit.residuals)


def test_the_printed_line_reproduces_the_series_it_describes(client):
    # The formula block prints a + b·t from these two coefficients; check they really generate the answer.
    body = client.post("/forecast/time-series",
                       json={"values": [10, 13, 14, 19], "periods_ahead": 3}).json()
    line = [body["intercept"] + body["slope"] * step for step in range(7)]
    assert line[:4] == pytest.approx(body["fitted"])
    assert line[4:] == pytest.approx(body["projected"])


def test_bundled_example_runs_with_the_trend_forecast_model():
    definition = SimulationDefinition.from_json(str(EXAMPLES / "us_drug_launch.json"))
    definition.forecast_model_id = "trend_projection"
    result, _ = SimulationRunnerService().run(definition)
    assert result.scenarios
    for scenario in result.scenarios:
        assert scenario.forecast.projections
        assert all(key.endswith(("_trend_per_period", "_projected")) or
                   key in scenario.forecast.projections for key in scenario.forecast.metrics)
        for name, projected in scenario.forecast.projections.items():
            assert scenario.forecast.metrics[f"{name}_projected"] == pytest.approx(projected[-1])
