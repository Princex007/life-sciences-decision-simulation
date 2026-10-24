"""Generic event and trigger driven simulation orchestration."""
import logging
from math import isfinite
from numbers import Real

from app.agents.base import DecisionPolicy, RuleBasedDecisionPolicy
from app.agents.cognition import (DecisionResponse, ObservationModel, ObservedEvent,
                                  build_decision_context)
from app.agents.evidence_retrieval import EvidenceRetriever, RuleBasedEvidenceRetriever
from app.services.evidence_store import EvidenceStore, InMemoryEvidenceStore
from app.domain.definitions import SimulationDefinition
from app.domain.event import SimulationEvent
from app.domain.scenario import Scenario, SimulationResult
from app.domain.world import WorldState
from app.forecasting.clinical_outcomes import expected_clinical_outcomes
from app.forecasting.patient_affordability import estimate_patient_cost
from app.forecasting.context import ForecastContext
from app.forecasting.registry import ForecastRegistry
from .scenario_generator import ScenarioGenerator, SimulationPath
from .external_drivers import apply_external_drivers
from .scenario_pruning import create_pruner
from .scheduler import EventScheduler
from .state_transition import StateTransitionSystem, evaluate_value
from .decision_validator import DecisionValidationError, DecisionValidator
from app.evaluation.objective_scorer import ObjectiveScorer

logger = logging.getLogger(__name__)

def decision_source_for(policy) -> str:
    """Name the mechanism that produced a decision, for the trace and the audit trail.

    An LLM-backed policy hands the decision to its deterministic fallback once the
    configured call budget is spent, so the policy type alone cannot answer this. A
    policy that records what it actually used is authoritative; otherwise fall back to
    the policy type.
    """
    recorded = getattr(policy, "last_decision_source", "")
    if recorded:
        return recorded
    return ("llm" if any(cls.__name__ == "LLMDecisionPolicy" for cls in type(policy).__mro__)
            else "existing_policy_fallback")

class SimulationEngine:
    """Execute JSON-defined events, triggers, policies, and transition rules."""
    def __init__(self, forecast_registry: ForecastRegistry | None = None,
                 decision_policy: DecisionPolicy | None = None,
                 observation_model: ObservationModel | None = None,
                 evidence_store: EvidenceStore | None = None,
                 evidence_retriever: EvidenceRetriever | None = None,
                 history_store=None):
        self.forecast_registry = forecast_registry or ForecastRegistry()
        self.decision_policy = decision_policy or RuleBasedDecisionPolicy()
        self.observation_model = observation_model or ObservationModel()
        self.evidence_store = evidence_store
        self.evidence_retriever = evidence_retriever or RuleBasedEvidenceRetriever()
        self.history_store = history_store

    def _stored_history(self, history_id, label):
        """Resolve a series the definition points at; both stored-series models share this."""
        if not history_id:
            return None
        if self.history_store is None:
            raise ValueError(f"Simulation selects {label} '{history_id}' "
                             "but no history store is configured.")
        try:
            return self.history_store.get(history_id)
        except FileNotFoundError as error:
            raise ValueError(str(error)) from error

    def _history_for(self, definition: SimulationDefinition):
        return self._stored_history(definition.product_history_id, "product history")

    def _reference_history_for(self, definition: SimulationDefinition):
        return self._stored_history(definition.reference_history_id, "reference product history")

    def run(self, definition: SimulationDefinition) -> SimulationResult:
        definition, driver_plan = apply_external_drivers(definition)
        settings = definition.settings
        if settings.time_horizon < 1:
            raise ValueError("time_horizon must be positive")
        generator = ScenarioGenerator(create_pruner(definition.scenario_generation))
        transition = StateTransitionSystem()
        scheduler = EventScheduler(definition)
        policy = self.decision_policy
        evidence_store = self.evidence_store or InMemoryEvidenceStore(definition.evidence)
        root_path, root = generator.root_path(definition.initial_world_state, definition.agents)
        paths = [root_path]
        # Driver, historical and reference forecasts read run inputs that are not world
        # state, so they get them through one context built for this run.
        forecast_context = ForecastContext(definition=definition, history=self._history_for(definition),
                                           reference_history=self._reference_history_for(definition))
        for time in range(0, settings.time_horizon + 1):
            if time:
                advanced = []
                for path in paths:
                    path._previous_world = path.world.model_copy(deep=True)
                    event = scheduler.advance(path.world)
                    result = transition.apply_event(path.world, event, definition.transition_rules)
                    generator.append_transition(path, event, result)
                    path.snapshots.append(path.world.model_copy(deep=True))
                    advanced.append(path)
                paths = advanced
            events = scheduler.initial_events() if time == 0 else scheduler.scheduled_events(time)
            paths = self._resolve(paths, events, time, definition, scheduler, generator, transition, policy,
                                evidence_store, forecast_context)
        scenarios = []
        key_drivers = sorted(set(driver_plan.active_driver_ids))
        for index, path in enumerate(paths, 1):
            path.cursor.status = "terminal"
            scenario = Scenario(scenario_id=f"scenario-{index:03d}", name=self._name(path, definition),
                actions=path.actions, final_state=path.world, key_drivers=list(key_drivers),
                decision_trace=path.trace,
                snapshots=path.snapshots, agent_states=list(path.agents.values()), terminal_node_id=path.cursor.node_id)
            forecast_id = definition.forecast_model_id
            if forecast_id:
                model = self.forecast_registry.get(forecast_id)
                scenario.forecast = model.forecast(path.world, path.snapshots, scenario, forecast_context)
            scenarios.append(scenario)
        result = SimulationResult(simulation_id=definition.metadata.id, name=definition.metadata.name,
            root=root, scenarios=scenarios, pruning_records=generator.pruning_records,
            driver_impacts=driver_plan.impacts, driver_hypotheses=driver_plan.hypotheses)
        usage_summary = getattr(policy, "usage_summary", None)
        if callable(usage_summary):
            result.llm_usage = usage_summary()
        return result

    def _resolve(self, paths, events, time, definition, scheduler, generator, transition, policy,
                 evidence_store, forecast_context=None):
        for path in paths:
            path.decided_agents.clear()
        while True:
            next_paths = []
            did_branch = False
            did_decide = False
            for path in paths:
                previous = getattr(path, "_previous_world", None)
                path_events = getattr(path, "_pending_events", events)
                recorded = {item.event.event_id for item in path.trace if item.event is not None}
                for event in path_events:
                    if event.event_id not in recorded:
                        generator.append_event(path, event)
                        recorded.add(event.event_id)
                        rule_result = transition.apply_event(path.world, event,
                                                             definition.transition_rules)
                        if rule_result.changes:
                            generator.append_transition(path, event, rule_result)
                matches = []
                for agent in definition.agents:
                    if agent.id in path.decided_agents:
                        continue
                    match = scheduler.dispatch(agent, path.agents[agent.id], path.world,
                                               path_events, previous, time)
                    if match:
                        matches.append((match.definition.priority, agent.id, agent, match))
                if not matches:
                    if hasattr(path, "_pending_events"):
                        del path._pending_events
                    next_paths.append(path)
                    continue
                _, _, agent, match = sorted(matches, key=lambda item: (-item[0], item[1]))[0]
                action_map = {item.id: item for item in definition.action_definitions
                              if item.agent_id == agent.id}
                state_changes = self._changes(previous, path.world)
                observation = self.observation_model.observe(agent, path.world,
                    events=[match.event], state_changes=state_changes)
                observed_trigger = ObservedEvent(event_id=match.event.event_id,
                    time=match.event.time, event_type=match.event.event_type,
                    description=match.event.description, actor_id=match.event.actor_id,
                    data={"trigger_id": match.definition.id})
                state = path.agents[agent.id]
                state.belief_state.update_observation(observation.visible_world_variables,
                    time, [item.event_id for item in observation.relevant_events])
                state.remember_event({"time": time, "event_id": match.event.event_id,
                    "event_type": match.event.event_type, "trigger_id": match.definition.id,
                    "description": match.event.description})
                available = [action_map[action_id] for action_id in agent.available_actions
                             if action_id in action_map]
                context = build_decision_context(agent, state, observation, observed_trigger, available)
                observation.relevant_evidence = self.evidence_retriever.retrieve(agent, context, evidence_store)
                context = build_decision_context(agent, state, observation, observed_trigger, available)
                validator = DecisionValidator()
                proposed = validator.filter_feasible_actions(agent,
                    policy.get_plausible_actions(context), path.world, match, time)
                if proposed:
                    objective = definition.evaluation_objectives.get(agent.id)
                    uses_forecast_metrics = bool(objective and any(
                        component.get("source") == "forecast_metrics"
                        for component in objective.get("components", [])))
                    uses_clinical_metrics = bool(objective and any(
                        component.get("source") == "clinical_outcomes"
                        for component in objective.get("components", [])))
                    needs_forecast = (uses_forecast_metrics or uses_clinical_metrics
                                      or bool(definition.clinical_outcome_assumptions))
                    forecast_model = (self.forecast_registry.get(definition.forecast_model_id)
                                      if needs_forecast and definition.forecast_model_id else None)
                    context.action_previews = self._build_action_previews(
                        path.world, agent, proposed, definition, transition, time, forecast_model,
                        forecast_context)
                    if objective is None:
                        context.decision_source = decision_source_for(policy)
                        response = policy.decide(context, proposed)
                        context.decision_source = decision_source_for(policy)
                    else:
                        scores = None
                        score_error = None
                        ranking = []
                        margin = None
                        tolerance = objective.get("score_tie_tolerance", 0.005)
                        try:
                            scores = ObjectiveScorer().score_actions(
                                context.action_previews, path.world, objective)
                            expected_ids = {action.id for action in proposed}
                            if set(scores) != expected_ids:
                                raise ValueError("Objective scorer did not return a score for every feasible action.")
                            if any(not isinstance(item.get("score"), Real)
                                   or isinstance(item.get("score"), bool)
                                   or not isfinite(float(item["score"])) for item in scores.values()):
                                raise ValueError("Objective scorer returned a missing or non-finite score.")
                            if (not isinstance(tolerance, Real) or isinstance(tolerance, bool)
                                    or not isfinite(float(tolerance)) or tolerance < 0):
                                raise ValueError("Objective score tie tolerance must be a finite non-negative number.")
                            ranking = sorted(proposed,
                                key=lambda action: (-scores[action.id]["score"], action.id))
                            margin = (float(scores[ranking[0].id]["score"])
                                      - float(scores[ranking[1].id]["score"])) if len(ranking) > 1 else None
                        except Exception as error:
                            logger.warning("Objective scoring unavailable for agent %s; using existing policy (%s: %s)",
                                           agent.id, type(error).__name__, error)
                            score_error = type(error).__name__
                            scores = None
                        if scores is None:
                            context.objective_scores = {}
                            context.objective_score_margin = None
                            context.decision_reason = (f"Objective scoring unavailable ({score_error}); "
                                                       "delegated to the configured decision policy.")
                            context.decision_source = "existing_policy_fallback"
                            response = policy.decide(context, proposed)
                            context.decision_source = decision_source_for(policy)
                        else:
                            context.objective_scores = scores
                            context.objective_score_margin = margin
                            if len(ranking) == 1 or margin > float(tolerance):
                                selected = ranking[0]
                                context.decision_source = "objective_scorer"
                                context.decision_reason = ("Only one feasible scored action." if len(ranking) == 1
                                    else f"Top score exceeded runner-up by {margin:.6g}, greater than tie tolerance {float(tolerance):.6g}.")
                                response = DecisionResponse(primary_action=selected.id,
                                    rationale="Selected by the configured evaluation objective score.")
                            else:
                                context.decision_reason = (f"Top-score margin {margin:.6g} is within experimental tie tolerance "
                                                           f"{float(tolerance):.6g}; delegated to existing policy.")
                                response = policy.decide(context, proposed)
                                context.decision_source = decision_source_for(policy)
                else:
                    response = DecisionResponse(primary_action="",
                        rationale="No feasible configured actions remain.",
                        validation_status="invalid", validation_errors=[
                            "No feasible actions remain after deterministic validation."])
                semantic_errors = DecisionValidator.validate_response(context, response)
                proposed_ids = [response.primary_action, *response.alternative_actions] if proposed else []
                action_by_id = {action.id: action for action in available}
                candidate_ids = {action.id for action in proposed}
                requested = []
                validation_errors = list(dict.fromkeys([*response.validation_errors, *semantic_errors]))
                invalid_action_reference = bool(semantic_errors or response.validation_status == "invalid" or not proposed)
                for action_id in proposed_ids:
                    if action_id not in candidate_ids:
                        validation_errors.append(
                            f"Decision response action ID '{action_id}' was not in the plausible candidate set.")
                        invalid_action_reference = True
                        continue
                    action = action_by_id.get(action_id)
                    if action is None:
                        validation_errors.append(f"Policy proposed unknown or unavailable action ID '{action_id}'.")
                        invalid_action_reference = True
                        continue
                    if action.id in {item.id for item in requested}:
                        continue
                    try:
                        validator.validate(agent, action, path.world, match, time)
                    except DecisionValidationError as error:
                        validation_errors.append(str(error))
                        continue
                    requested.append(action)
                if invalid_action_reference:
                    requested = []
                if requested:
                    primary = next((action for action in requested if action.id == response.primary_action), requested[0])
                    expected_strategy = primary.strategy if primary.strategy is not None else primary.id
                    expected_change = (expected_strategy
                        if expected_strategy != context.current_strategy else None)
                    if response.strategy_change not in (None, expected_change):
                        validation_errors.append(
                            f"Strategy change '{response.strategy_change}' is not configured for action '{primary.id}'.")
                    response = response.model_copy(update={"primary_action": primary.id,
                        "alternative_actions": [action.id for action in requested if action.id != primary.id],
                        "strategy_change": expected_change,
                        "validation_status": "valid" if not validation_errors else "partially_valid",
                        "validation_errors": validation_errors})
                else:
                    response = response.model_copy(update={"validation_status": "invalid",
                        "validation_errors": list(dict.fromkeys([*response.validation_errors, *validation_errors]))})
                allowed_evidence = {item.evidence_id for item in context.relevant_evidence}
                allowed_events = {item.event_id for item in context.observations.relevant_events}
                allowed_events.update(item.get("event_id") for item in
                    context.relevant_memory.get("important_events", []) if item.get("event_id"))
                visible_variables = set(context.observations.visible_world_variables)
                valid_beliefs = []
                for belief in response.belief_updates:
                    if not set(belief.evidence_ids).issubset(allowed_evidence):
                        validation_errors.append(f"Belief '{belief.id}' references evidence not visible to this agent.")
                        continue
                    if not set(belief.related_variables).issubset(visible_variables):
                        validation_errors.append(f"Belief '{belief.id}' references variables not visible to this agent.")
                        continue
                    if not set(belief.related_events).issubset(allowed_events):
                        validation_errors.append(f"Belief '{belief.id}' references events not visible to this agent.")
                        continue
                    valid_beliefs.append(belief)
                if validation_errors:
                    status = "invalid" if not requested else "partially_valid"
                    response = response.model_copy(update={"validation_status": status,
                        "validation_errors": list(dict.fromkeys([*response.validation_errors, *validation_errors])),
                        "belief_updates": valid_beliefs})
                definitions = requested
                alternative_reason = response.rationale
                audit = policy.audit_for(context, response, response.validation_status,
                    response.validation_errors, response.primary_action if requested else None) \
                    if proposed and hasattr(policy, "audit_for") \
                    and context.decision_source != "objective_scorer" else None
                if not definitions:
                    generator.record_invalid_decision(path, agent, match, context, response, audit)
                    path.decided_agents.add(agent.id)
                    did_decide = True
                    path._pending_events = path_events
                    next_paths.append(path)
                    continue
                branches = generator.branch(path, agent, match, definitions, transition, time,
                                            context, response, alternative_reason, audit)
                for child, result in branches:
                    trans_evt = SimulationEvent(event_id=f"trans:{time}:{agent.id}", time=time,
                                                event_type="action_transition",
                                                description=f"Action transition for {agent.id}",
                                                actor_id=agent.id)
                    rule_result = transition.apply_event(child.world, trans_evt, definition.transition_rules)
                    if rule_result.changes:
                        generator.append_transition(child, trans_evt, rule_result)
                    for event in result.events:
                        rule_result_ev = transition.apply_event(child.world, event, definition.transition_rules)
                        if rule_result_ev.changes:
                            generator.append_transition(child, event, rule_result_ev)
                    generated = result.events + scheduler.state_change_events(result.previous_state, child.world)
                    child_events = scheduler.transition_events(path_events + generated)
                    child._pending_events = child_events
                    next_paths.append(child)
                did_branch = True
            paths = next_paths
            if not did_branch and not did_decide:
                for path in paths:
                    if hasattr(path, "_pending_events"):
                        del path._pending_events
                return generator.prune(paths, time)

    @staticmethod
    def _name(path: SimulationPath, definition: SimulationDefinition) -> str:
        names = {agent.id: agent.name for agent in definition.agents}
        decisions = [f"{names.get(item.agent_id, item.agent_id)}: {item.action.name}"
                     for item in path.trace if item.event_type == "decision" and item.action]
        return " / ".join(decisions) or "Baseline"

    @staticmethod
    def _changes(previous, current):
        if previous is None:
            return {}
        old, new = previous.as_variables(), current.as_variables()
        return {key: new.get(key) for key in old.keys() | new.keys() if old.get(key) != new.get(key)}

    @staticmethod
    def _build_action_previews(world, agent, actions, definition, transition, time,
                               forecast_model=None, forecast_context=None):
        """Calculate candidate consequences on isolated states using configured transitions."""
        derived_effects = {}
        for configured_action in definition.action_definitions:
            if configured_action.agent_id != agent.id:
                continue
            for effect in configured_action.effects:
                if isinstance(effect.value, str):
                    derived_effects.setdefault(effect.variable,
                        (effect.value, configured_action.parameters))

        step_variables = set()
        for rule in definition.transition_rules:
            event_types = {item.strip() for item in rule.event_type.split(",")}
            if "time_step" in event_types or "*" in event_types:
                step_variables.update(effect.variable for effect in rule.effects)
        observable = (set(world.as_variables()) if agent.observable_state == "all"
                      else set(agent.observable_state))

        previews = {}
        for action in actions:
            hypothetical = world.model_copy(deep=True)
            action_result = transition.apply_action(hypothetical, action, time)
            action_changes = {}
            for variable, after in action_result.changes.items():
                before = world.get(variable)
                change = {"from": before, "to": after}
                if isinstance(before, Real) and not isinstance(before, bool) and isinstance(after, Real):
                    change["delta"] = after - before
                action_changes[variable] = change

            derived_metrics = {}
            for variable, (expression, parameters) in derived_effects.items():
                try:
                    value = evaluate_value(expression, hypothetical, parameters)
                except (ValueError, KeyError, TypeError, ZeroDivisionError):
                    continue
                if isinstance(value, Real) and not isinstance(value, bool):
                    derived_metrics[variable] = value

            next_step_state = hypothetical.model_copy(deep=True)
            preview_scheduler = EventScheduler(definition)
            next_step_event = preview_scheduler.advance(next_step_state)
            next_step_result = transition.apply_event(
                next_step_state, next_step_event, definition.transition_rules)
            market_metrics = {variable: next_step_state.get(variable)
                for variable in sorted(step_variables & observable & set(next_step_result.changes))}

            forecast_metrics = {}
            if forecast_model is not None:
                try:
                    outcome = forecast_model.forecast(next_step_state.model_copy(deep=True),
                        [world.model_copy(deep=True), next_step_state.model_copy(deep=True)], None,
                        forecast_context)
                    forecast_metrics = dict(outcome.metrics)
                except Exception as error:
                    logger.warning("Forecast preview unavailable for candidate %s (%s)",
                                   action.id, type(error).__name__)

            preview = {
                "after_action_changes": action_changes,
                "configured_derived_metrics": derived_metrics,
                "after_next_time_step": market_metrics,
                "clinical_outcomes": expected_clinical_outcomes(
                    forecast_metrics.get("patients_treated"),
                    definition.clinical_outcome_assumptions),
                "patient_affordability": estimate_patient_cost(
                    hypothetical.get("drug_price"), definition.patient_affordability_assumptions),
                "scope": "One configured time_step; other agents' decisions and generated-event reactions are not simulated.",
            }
            if forecast_metrics:
                preview["forecast_metrics"] = forecast_metrics
            previews[action.id] = preview
        return previews
