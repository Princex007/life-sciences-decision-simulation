# Generic Simulation Platform MVP

A deterministic simulation kernel that loads world variables, agents, actions, triggers, transitions, settings, forecasts, and pruning behavior from a JSON `SimulationDefinition`. The bundled US drug launch is an example domain configuration; the engine does not construct pharma agents or encode pharma state fields.

## Run

From the repository root:

```powershell
python -m app.run_simulation examples/us_drug_launch.json
python -m app.run_simulation examples/us_drug_launch.json --json
python -m pytest -q
uvicorn app.main:app --reload
```

The CLI prints an ASCII tree of retained terminal paths, scenario traces, final states, and forecast outputs. JSON mode prints the full tree and terminal scenarios. The FastAPI API accepts the same `SimulationDefinition`; its in-memory store resets when the process exits.

The local builder UI is served at `http://127.0.0.1:8000/` after starting the API with `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`. From a phone on the same private Wi-Fi, use the computer's local IPv4 address and port 8000. Definitions are saved as JSON under `simulations/` in the project directory. Run results live in memory until the server exits. The UI has a guided Drug X example, form-based agent editing, scenario comparison charts, and advanced JSON controls for actions, triggers, and transitions. Example values are synthetic and illustrative. API schema and template routes are available at `/simulations/schema` and `/simulations/templates`; saved-definition CRUD and run routes are under `/simulations`.

## Configuration

`examples/us_drug_launch.json` is the source of truth for the example. `SimulationDefinition` contains metadata, generic world variables, agent definitions and rule policies, action effects, event/state triggers, event-based transition rules, clock and scheduled events, forecast model ID, and scenario pruning settings. Expressions in effects use arithmetic over world variables and action parameters. The scheduler orders events, dispatches configured triggers, and advances time. Strategies persist in per-path agent memory; reselecting an unchanged strategy records the decision without replaying one-time action effects.

`ScenarioNode` stores parent and child lineage, state snapshots, triggering events, plausible actions, selections, and rationale. Nodes are marked `active`, `pruned`, or `terminal`; pruned nodes include policy, reason, and any retained comparison node. Only retained terminal paths receive forecasts. `ScenarioPolicy` supports `exhaustive` with a safety limit, `diversity` with configured decision dimensions, and deterministic `limited` retention.

`DecisionValidator` checks action ownership and availability, trigger activation, compatibility conditions, and constraints before applying effects. Constraints can use `{"state":{"variable":{"min":0,"max":1}}}`, `{"parameters":{"budget":{"lte":100}}}`, or condition lists using `variable`, `operator`, and `value`. State constraints check the projected post-action state; `current_state` is also supported. Decision traces contain observations, current strategy, plausible alternatives, policy rationale, and validity reason. Forecast plugins are registered by the application boundary; `LaunchForecast` is the example implementation.

## Agent decision architecture

Configured `AgentDefinition` objects hold identity, objectives, resources, constraints, observable variables, available actions, and rule configuration. Each scenario path owns independent `AgentState`, `AgentMemory`, and `BeliefState` instances. The runtime sends policies only an `AgentObservation` projected by `ObservationModel`; it never passes the mutable `WorldState` into a policy. The shared `DecisionPolicy` contract takes a `DecisionContext` and returns action IDs in a `DecisionResponse`. Both deterministic `RuleBasedDecisionPolicy` and structured `LLMDecisionPolicy` are available. Every proposed action is checked by `DecisionValidator`, effects go through `StateTransitionSystem`, and persistent strategy changes are applied by `StrategyTransitionSystem`. The trace stores the filtered context, structured response, selected branch action, and validation result. Scenario generation continues to branch over valid alternatives without probability scores.

`LLMDecisionPolicy` is now available through the LLM setting or `--policy llm`. It sends only a structured `DecisionContext` to an OpenAI-compatible chat-completions endpoint and parses JSON into a strict `DecisionResponse`; unknown action IDs are rejected before branching. `Evidence` records have explicit per-agent visibility lists. LLM trace audits store provider/model metadata, prompt version, timestamp, filtered context, redacted raw response content, parsed response, validation, and branch-selected action. No credentials are stored in definitions or traces.

## Evidence retrieval and benchmark

Evidence records carry an ID, source and type, date, domain, tags, reliability label, applicable agents, and related variables/actions. The default `RuleBasedEvidenceRetriever` selects from the definition's evidence collection only when the record is applicable to the deciding agent and has a metadata link to visible variables, available actions, agent evidence tags, or the active trigger. A `JsonEvidenceStore` is also available as a local JSON CRUD/query store (`add`, `get`, `list`, `update`, `delete`, text query, and metadata filtering); inject it into `SimulationEngine` to use stored evidence. Retrieval is deterministic and does not use embeddings or external services.

LLM decisions can include `evidence_used` IDs and cite each used record in rationale as `[EVIDENCE-ID]`. The validator rejects hidden/unknown evidence IDs, missing or unlisted citations, and parseable facts that contradict visible world variables. Direct observations go in `facts_used`; inference goes in `assumptions`. The bundled seven-item US launch evidence set and benchmark fixtures are explicitly synthetic and illustrative, not real-world life-sciences evidence. Run `python -m app.run_evidence_demo` for the evidence benchmark and the existing simulation with a deterministic mock provider. Run `python -m app.benchmark.decision_benchmark` for the compact benchmark report; it compares configured rules and a mock LLM adapter and makes no accuracy claim.

The default remains `rule_based`. Cloud LLM mode requires `LLM_API_KEY` and `LLM_MODEL`. Local OpenAI-compatible inference does not require a cloud key: set `LLM_PROVIDER=local` or `lm-studio`, `LLM_BASE_URL` (for LM Studio, commonly `http://localhost:1234/v1`), and `LLM_MODEL` to the model ID exposed by that server. See [examples/local_llm.env.example](examples/local_llm.env.example). Optional settings are `LLM_TEMPERATURE` and `LLM_TIMEOUT_SECONDS`. Run a deterministic mock version without credentials using `python -m app.run_llm_demo --mock`; run against the configured server using `python -m app.run_llm_demo`. Compare policies with `python -m app.compare_policies examples/us_drug_launch.json`; append `--mock` to exercise the comparison without credentials. This comparison describes decisions and outcomes and makes no accuracy claim.

## Launch forecast equation

For every saved world-state snapshot, the launch forecast computes:

```text
eligible_patients = addressable_patients × diagnosis_rate × treatment_rate × payer_access
patients_treated  = int(eligible_patients × market_share)
net_price         = net_price, when supplied; otherwise drug_price × 0.85
period_revenue    = patients_treated × net_price
peak_sales        = maximum period_revenue across snapshots
cumulative_sales  = sum of period_revenue across snapshots
```

`patients_treated` reports the last snapshot's treated count, and `market_share` reports the last snapshot's share. These equations are covered by hand-calculated deterministic fixtures in `tests/test_forecasting.py`, including zero/full access, penetration changes, price scaling, and the fallback discount.

## Current limitations

- Supported action and agent state/parameter constraints are checked by `DecisionValidator`; custom policy semantics beyond the configured condition schema remain code-defined.
- Trigger state conditions support simple variable comparisons and numeric deltas; there is no compound condition language.
- The diversity policy retains representative terminal paths, while the tree can include explored branches that were later pruned.
- JSON expressions are intentionally a small arithmetic subset. Forecast behavior is Python plug-in code, not JSON-defined.
- The launch model is illustrative and uncalibrated; it is not clinical, regulatory, or commercial advice.
- The browser editor provides form controls for agent names, types, objectives, observations, and available actions. Advanced agent settings and action, trigger, transition, and event-schedule definitions remain available as JSON; forecast plugins and supported effect expressions are code-defined.
- Beliefs are currently qualitative summaries of directly observed variables; policies do not infer uncertain hidden facts.
- The LLM adapter currently targets OpenAI-compatible Chat Completions APIs. Belief updates are qualitative and limited to visible variables/events and exposed evidence; no probabilistic belief model is implemented.
- The local JSON evidence store is an injectable service; the builder UI does not yet manage evidence records.
- Evidence retrieval uses explicit deterministic metadata links, not semantic search. Empty-metadata legacy records remain visible to their explicit allowlisted agents for compatibility.

## Decision evaluation

`app.evaluation.cases.DecisionEvaluationCase` defines a reusable controlled case, and `build_benchmark_cases()` supplies the 21 core synthetic pharmaceutical-launch cases plus five adversarial cases for price floors, exhausted promotion budget, conflicting evidence, irrelevant evidence, and hidden variables. Expected considerations, acceptable actions, prohibited actions, and optional primary actions are evaluator criteria; they are not passed to the LLM.

Prepare an auditable case-by-case input and evaluator-rubric report before running a model:

```powershell
python -m app.evaluate_decisions --prepare-only
```

This writes `evaluation_results/benchmark-report.md`. Full runs also write a readable Markdown report beside the JSON result. Per-decision JSON includes the exact filtered model context; evaluator criteria are stored separately at the top level.

Run the rule baseline without credentials:

```powershell
python -m app.evaluate_decisions --policy rules
```

Run a configured real provider, or compare it with rules:

```powershell
python -m app.evaluate_decisions --policy llm
python -m app.evaluate_decisions --policy both
```

Cloud evaluation reads `LLM_API_KEY` only from the server environment; local/lm-studio evaluation needs no API key. `LLM_MODEL`, `LLM_BASE_URL`, `LLM_PROVIDER`, and `LLM_TEMPERATURE` are configurable there; `--model` and `--temperature` can override model settings without accepting credentials on the command line. JSON results are saved under `evaluation_results/` by default, or to `--output`. Per-decision records include case and policy, model, timestamp, input hash, structured response, exact filtered input context, action set, evidence IDs, validation, and decomposed metrics; they exclude API keys and raw provider requests. `--repeat N` runs each case N times and reports action, evidence, rationale, and overall strategic decision stability.

Metrics remain separate: action validity, constraint compliance, evidence-citation validity, evidence use, information isolation, required-consideration coverage, prohibited-action rate, counterfactual directional adaptation, decision stability, action precision, action recall, Action Jaccard, and optional expected-primary adherence. Free-text coverage uses deterministic required-driver matching; there is no LLM judge or single intelligence score. The rules command uses the configured generic default action ordering, not a tuned expert rule set; treat it as a simple deterministic baseline. `MockLLMDecisionPolicy` is used only in unit tests for deterministic harness and evidence-grounding checks. A mock result is not evidence of real LLM reasoning quality; run the configured `--policy both --repeat 2` command to compare one provider with the same rules baseline.
