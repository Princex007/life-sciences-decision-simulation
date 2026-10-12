# Project status

## Handover progress

Phases 0–3 of the handover plan are complete. Phase 4 (OpenRouter integration) and Phase 5 (final evaluation refresh) are not started. No live or billable LLM call has been made; every test and example runs on deterministic, mock, or rule-based policies.

Phase 0 snapshotted the existing work at commit `bcc41c7` before any change, so the pre-handover state is recoverable. No file was rewritten from scratch and no core architecture was replaced.

Phase 1 restored a runnable suite. `%TEMP%\pytest-of-DELL` and the project `.pytest_cache` carry deny ACLs on this machine, so every `tmp_path` fixture errored during setup; `pyproject.toml` now points pytest at project-local basetemp and cache directories. Two generic-platform tests predated the hybrid objective scorer and still asserted that the launch example branches into 9 ambiguous alternatives. Decisive objective scoring intentionally collapses that to one retained branch, so the count assertion became the diversity-uniqueness property it was guarding, and the forecast regression is rebuilt on explicitly forced Payer counterfactuals. Every decision trace and scenario node now carries a `branch_role` of `selected` or `counterfactual`.

Phase 2 added the external environment / macro-driver layer: configurable drivers (AI advances, regulation, tariffs, supply shocks) that compile into ordinary scheduled events plus transition rules, so driver effects pass through the same `StateTransitionSystem` and `DecisionValidator` as agent actions instead of getting a privileged execution path. Each driver carries variants, a time-dependent trajectory, per-pathway lag/strength/bounds, source, evidence grade, assumption labels, and an agent observation allowlist. The world-state pathway and the information pathway are kept separate; a `qualitative_only` pathway is reported as a hypothesis record and never converted into a state change. Bundled template: `examples/ai_drug_discovery.json`.

Phase 3 added the guided UI: a home view with one-click example and saved-simulation cards, a guided external-driver editor with variant selection, staged run progress, an assumptions-and-evidence panel, a trace-generated decision flowchart, variable time-series charts, driver-effect and hypothesis tables, a decision audit table, and a driver-variant comparison built on a new non-persisting `POST /simulations/preview-run` endpoint. `GET /simulations/{id}/results` now returns the scenario tree inline, removing a round trip. Charts are hand-rolled SVG; no charting dependency was added.

### Pre-existing defects fixed in Phase 3

Both were present at baseline `bcc41c7` and confirmed as such by diffing against that commit, not introduced by the handover work.

`examples/us_drug_launch.json` could not be loaded at all. Its `payer-review` and `physician-response` triggers subscribed to `evidence_update`, and `physician-response` also subscribed to `access_change`; nothing in the engine ever emits either event type, so builder validation rejected the flagship example. The two dead subscriptions were removed. No action, rule, or transition was added in their place, because roughly fifteen test files pin this example's exact numeric behavior and authoring a new event source would have meant inventing domain assumptions the handover forbids.

`SimulationBuilderService.validate()` rejected valid transition rules. `StateTransitionSystem.apply_event` splits `rule.event_type` on commas and treats `"*"` as a wildcard, and the engine emits `action_transition` after every validated action, but validation compared the raw string against a set containing neither. Validation now splits on commas, skips `"*"`, and recognizes `action_transition`. The strictness that `tests/test_builder_service.py` pins for genuinely unknown event types is unchanged.

### UI save-path data loss fixed in Phase 3

`definitionFromForm()` rebuilt the definition from scratch out of the visible form fields, so saving from the UI silently dropped `evaluation_objectives` (all five for Drug X), `clinical_outcome_assumptions`, `patient_affordability_assumptions`, `metadata.domain`, `settings.transient_variables`, every `external_drivers` entry, each variable's `evidence_grade` and `assumption_labels`, and overwrote `scenario_generation.diversity_by_agents` (for Drug X, `["competitor", "payer"]` became all five agent ids, which changes pruning behavior). The loaded definition is now preserved as a base and the form merges into it, so fields the guided forms do not edit survive a round trip. This is verified in `tests/test_builder_ui_api.py` and by an in-browser round trip.

### Verification

166 tests pass (`python -m pytest -q`), including the 7 new UI/API tests in `tests/test_builder_ui_api.py`. All nine bundled and saved definitions validate. The UI was exercised in a real browser against `uvicorn` with zero console errors: example cards load and run, the driver editor round-trips guided fields while preserving pathways/variants/trajectory, variant comparison reproduces the Phase 2 values exactly without leaking a driver into the agent's own decision variable, flowchart terminal nodes open scenario detail, and disabling a driver empties the driver-effect panels. Screenshots were unavailable in this environment (`NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`), so verification used DOM inspection and computed styles.

## Implemented and tested

The MVP loads a simulation definition from JSON and executes sequential stakeholder decisions for Company, Competitor, Payer, Physician, and Patient. The example includes event triggers, per-path strategy/memory, observation filtering, deterministic action feasibility, isolated action previews, configurable objective scoring, a hybrid scorer/policy fallback, validated state transitions, scenario branching, and a one-quarter launch forecast.

Decision flow:

`WorldState → event → trigger matching → stakeholder observation/context → feasible-action filtering → isolated action previews → objective scoring → decisive selection or policy fallback → action validation → state transition → branch-local next state → forecast`

Feasible action previews are made on deep-copied states. The chosen action is validated before its transition is applied. At a non-decisive objective margin, the existing policy supplies the primary choice and any alternatives; the scenario generator validates and isolates each branch.

The bounded five-agent integration test can be run with:

```powershell
python -m pytest -q tests/test_five_agent_decision_integration.py
```

The hybrid-versus-rule comparison is available as:

```powershell
python -m app.evaluation.compare_hybrid_rule_based
```

The targeted Payer ambiguity report (0.2 and 0.3 access-weight cases) is available with:

```powershell
python -c "import json; from app.evaluation.objective_weight_sensitivity import run_payer_ambiguity_evaluation; print(json.dumps(run_payer_ambiguity_evaluation(), indent=2))"
```

The broader bounded weight sweep is available as `python -m app.evaluation.objective_weight_sensitivity`; it performs many one-quarter deterministic evaluation runs. Neither evaluation constructs a real LLM client.

## Application and local inference

From the project root, start the FastAPI application and builder UI with:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/`; the OpenAPI document is at `/openapi.json`. This startup command is documented from the FastAPI entry point; this finalization run did not launch the server.

For local OpenAI-compatible inference, copy the values in `examples/local_llm.env.example` into the terminal environment or a local environment file loaded by the user's shell. Configure `LLM_PROVIDER=lm-studio` (or `local`), `LLM_BASE_URL=http://localhost:1234/v1`, and `LLM_MODEL` to the model ID served by LM Studio. Local mode does not require `LLM_API_KEY`. The model server must be running separately. No inference was performed in this finalization.

## Finalization verification

Executed the following focused regression set:

```powershell
python -m pytest -q tests/test_objective_scorer.py tests/test_hybrid_objective_decision.py tests/test_competitor_feasibility_filter.py tests/test_agent_decision_architecture.py tests/test_clinical_outcome_previews.py tests/test_patient_objective_decision.py tests/test_five_agent_decision_integration.py tests/test_objective_weight_sensitivity.py
```

Result: **53 passed in 1.30s**. The hybrid-policy tests use `MockLLMClient`; the rest use deterministic or fake policies. The new evaluation utility was also executed directly for the Payer ambiguity cases. No full test suite, full application simulation, API server startup, or real LLM/API call was run.

## Payer ambiguity evaluation

The illustrative tie tolerance is 0.005. At access/expenditure weights 0.2/0.8, favorable access scores 0.882760 and standard access scores 0.882476, a margin of 0.000284. The scorer ranks favorable access first, but the margin is non-decisive. The deterministic fallback was asked to branch into restricted and favorable access; both outcomes were retained on independent states and all five decisions validated. Their one-step modeled cumulative sales were 22,695,000 and 668,695,000 respectively.

At weights 0.3/0.7, favorable access scores 0.884915 against runner-up standard access at 0.8659165, margin 0.0189985. The scorer decisively selected favorable access, with modeled cumulative sales of 668,695,000. A separate restricted-access counterfactual produced 22,695,000; it was forced through the deterministic policy path with the Payer objective disabled on a fresh definition, so it is explicitly fallback-dependent. These are illustrative model outputs, not probabilities, validated forecasts, or evidence of real-world strategic optimality.

## Implemented but not validated against real-world data

All five stakeholder objective scorers, action-effect assumptions, forecast outputs, clinical outcome rates, and patient affordability calculations are configurable and exercised in code/tests. The example's objective weights and score normalization bounds are experimental, illustrative, and uncalibrated. The configured clinical response/adverse-event rates and patient cost-sharing fraction are synthetic assumptions. Competitor unit cost, promotional spend/budget, launch prices, and market-response equations are also illustrative.

The launch forecast calculates treated-patient counts and gross modeled revenue from configured price/access/adoption/share values. Payer expenditure is only a modeled gross drug-spend proxy; it is not net payer expenditure. Patient cost is a configured cost-sharing proxy. Clinical responder and adverse-event counts are aggregate expected values based on synthetic rates and are not clinical evidence.

## Not implemented or unavailable

The model does not support empirically grounded total profit, net payer budget impact, rebates or negotiated prices, treatment-course duration, manufacturing costs, validated patient-level outcomes, mortality, quality of life, cost-effectiveness, or causal clinical effects. Sales, market share, treatment counts, and objective scores must not be interpreted as real pharmaceutical forecasts or validated stakeholder preferences.

Credible real-world forecasts would require validated and versioned market, epidemiology, pricing/rebate, uptake, adherence, treatment-duration, cost, and clinical-effect data; evidence provenance; calibration and back-testing against observed outcomes; uncertainty analysis; and expert review of stakeholder objectives and weights. Until then, treat this as a deterministic architecture demonstrator and evaluation harness, not a production-ready or decision-support system.
