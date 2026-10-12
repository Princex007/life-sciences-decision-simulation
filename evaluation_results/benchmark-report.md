# Decision Benchmark

Cases: 26

Expected answers below are evaluator-only. They are not included in the LLM DecisionContext.

## CASE-01 — Competitor

Objective: Respond strategically: Low competitor price creates pricing pressure
Description: Low competitor price creates pricing pressure

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `80000`
- `competitor_market_share`: `0.3`
- `promotion_capacity`: `60`
- `price_cut_count`: `0`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: aggressive_price_cut, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: competitor_price, pricing pressure
- Counterfactual relationship: price-level; changed variable: competitor_price

## CASE-02 — Competitor

Objective: Respond strategically: High competitor price weakens the case for another cut
Description: High competitor price weakens the case for another cut

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `110000`
- `competitor_market_share`: `0.3`
- `promotion_capacity`: `60`
- `price_cut_count`: `0`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: increase_promotion, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: competitor_price, promotion capacity
- Counterfactual relationship: price-level; changed variable: competitor_price

## CASE-03 — Competitor

Objective: Respond strategically: Promotion response with remaining capacity
Description: Promotion response with remaining capacity

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `90000`
- `competitor_market_share`: `0.25`
- `competitor_promotion`: `1.1`
- `promotion_capacity`: `60`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: increase_promotion, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: promotion_capacity, competitor_market_share
- Counterfactual relationship: None; changed variable: None

## CASE-04 — Competitor

Objective: Respond strategically: Stable competitor position favors maintaining strategy
Description: Stable competitor position favors maintaining strategy

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.35`
- `competitor_price`: `90000`
- `promotion_capacity`: `40`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy
- Prohibited actions: aggressive_price_cut
- Required strategic considerations: stable competitor share
- Counterfactual relationship: None; changed variable: None

## CASE-05 — Competitor

Objective: Respond strategically: Share loss while promotion capacity remains
Description: Share loss while promotion capacity remains

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.17`
- `promotion_capacity`: `50`
- `price_cut_count`: `1`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: increase_promotion, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: share loss, promotion_capacity
- Counterfactual relationship: share-capacity; changed variable: promotion_capacity

## CASE-06 — Competitor

Objective: Respond strategically: Share loss after promotion capacity is exhausted
Description: Share loss after promotion capacity is exhausted

Available actions:
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': [{'variable': 'promotion_capacity', 'operator': 'gte', 'value': 10}]}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.17`
- `promotion_capacity`: `0`
- `price_cut_count`: `1`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy
- Prohibited actions: increase_promotion
- Required strategic considerations: share loss, promotion capacity exhausted
- Counterfactual relationship: share-capacity; changed variable: promotion_capacity

## CASE-07 — Payer

Objective: Respond strategically: Payer restriction requires affordability and access review
Description: Payer restriction requires affordability and access review

Available actions:
- `restricted_access` — Restricted Access; constraints: `{'compatible_when': []}`
- `standard_access` — Standard Access; constraints: `{'compatible_when': []}`
- `favorable_access` — Favorable Access; constraints: `{'compatible_when': []}`

Visible variables:
- `payer_access`: `0.45`
- `drug_price`: `100000`
- `addressable_patients`: `1000000`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: restricted_access, standard_access
- Prohibited actions: None
- Required strategic considerations: payer_access, drug_price
- Counterfactual relationship: None; changed variable: None

## CASE-08 — Payer

Objective: Respond strategically: Favorable payer environment preserves access gains
Description: Favorable payer environment preserves access gains

Available actions:
- `restricted_access` — Restricted Access; constraints: `{'compatible_when': []}`
- `standard_access` — Standard Access; constraints: `{'compatible_when': []}`
- `favorable_access` — Favorable Access; constraints: `{'compatible_when': []}`

Visible variables:
- `payer_access`: `0.9`
- `drug_price`: `100000`
- `treatment_rate`: `0.7`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: favorable_access, standard_access
- Prohibited actions: None
- Required strategic considerations: favorable payer access, treatment_rate
- Counterfactual relationship: None; changed variable: None

## CASE-09 — Company

Objective: Respond strategically: Improved evidence supports a launch decision
Description: Improved evidence supports a launch decision

Available actions:
- `launch` — Launch; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `evidence_quality`: `0.9`
- `regulatory_status`: `cleared`
- `company_launch_status`: `pre_launch`

Visible evidence:
- `SYNTH-IMPROVED` (Synthetic fixture SYNTH-IMPROVED): Synthetic evidence package improves.

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: launch, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: evidence_quality, regulatory_status
- Counterfactual relationship: None; changed variable: None

## CASE-10 — Company

Objective: Respond strategically: Deteriorating evidence favors a pause for review
Description: Deteriorating evidence favors a pause for review

Available actions:
- `launch` — Launch; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `evidence_quality`: `0.2`
- `regulatory_status`: `under_review`
- `company_launch_status`: `pre_launch`

Visible evidence:
- `SYNTH-WEAKENED` (Synthetic fixture SYNTH-WEAKENED): Synthetic evidence package has unresolved limitations.

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy
- Prohibited actions: launch
- Required strategic considerations: evidence_quality, regulatory_status
- Counterfactual relationship: None; changed variable: None

## CASE-11 — Company

Objective: Respond strategically: Competitor launch delay creates time to prepare
Description: Competitor launch delay creates time to prepare

Available actions:
- `launch` — Launch; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_launch_status`: `delayed`
- `company_launch_status`: `launched`
- `promotion_budget`: `30`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy, increase_promotion
- Prohibited actions: None
- Required strategic considerations: competitor launch delay, promotion budget
- Counterfactual relationship: None; changed variable: None

## CASE-12 — Company

Objective: Respond strategically: Competitor launches earlier than planned
Description: Competitor launches earlier than planned

Available actions:
- `launch` — Launch; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_launch_status`: `launched_early`
- `company_launch_status`: `pre_launch`
- `promotion_budget`: `30`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: launch, increase_promotion
- Prohibited actions: None
- Required strategic considerations: early competitor launch, promotion budget
- Counterfactual relationship: None; changed variable: None

## CASE-13 — Competitor

Objective: Respond strategically: Strategy exhaustion removes unavailable price and promotion responses
Description: Strategy exhaustion removes unavailable price and promotion responses

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': [{'variable': 'price_cut_count', 'operator': 'eq', 'value': 0}]}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': [{'variable': 'promotion_capacity', 'operator': 'gte', 'value': 10}]}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.17`
- `price_cut_count`: `1`
- `promotion_capacity`: `0`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy
- Prohibited actions: aggressive_price_cut, increase_promotion
- Required strategic considerations: price cut already used, promotion capacity exhausted
- Counterfactual relationship: None; changed variable: None

## CASE-14 — Company

Objective: Respond strategically: Limited resources prevent an unaffordable promotion
Description: Limited resources prevent an unaffordable promotion

Available actions:
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': [{'variable': 'promotion_budget', 'operator': 'gte', 'value': 10}]}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `promotion_budget`: `5`
- `competitor_promotion`: `1.0`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy
- Prohibited actions: increase_promotion
- Required strategic considerations: promotion budget, resource constraint
- Counterfactual relationship: None; changed variable: None

## CASE-15 — Competitor

Objective: Respond strategically: Prior promotion failed, challenging a repeated default response
Description: Prior promotion failed, challenging a repeated default response

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.17`
- `promotion_capacity`: `40`
- `price_cut_count`: `0`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: aggressive_price_cut, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: previous promotion had no effect, competitor_market_share
- Counterfactual relationship: None; changed variable: None

## CASE-16 — Competitor

Objective: Respond strategically: Conflicting synthetic evidence supports different responses
Description: Conflicting synthetic evidence supports different responses

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.2`
- `competitor_price`: `90000`
- `promotion_capacity`: `20`

Visible evidence:
- `SYNTH-CUT-SUPPORT` (Synthetic fixture SYNTH-CUT-SUPPORT): Synthetic note favors price response under this condition.
- `SYNTH-PROMO-SUPPORT` (Synthetic fixture SYNTH-PROMO-SUPPORT): Synthetic note favors promotion under this condition.

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: aggressive_price_cut, increase_promotion, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: conflicting evidence, competitor_market_share
- Counterfactual relationship: None; changed variable: None

## CASE-17 — Competitor

Objective: Respond strategically: Adversarial hidden evidence must not affect the decision
Description: Adversarial hidden evidence must not affect the decision

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.35`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy
- Prohibited actions: aggressive_price_cut
- Required strategic considerations: stable competitor share
- Counterfactual relationship: None; changed variable: None

## CASE-18 — Competitor

Objective: Respond strategically: Partial information excludes the other product's price
Description: Partial information excludes the other product's price

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `90000`
- `competitor_market_share`: `0.3`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy, increase_promotion
- Prohibited actions: aggressive_price_cut
- Required strategic considerations: competitor_market_share
- Counterfactual relationship: None; changed variable: None

## CASE-19 — Competitor

Objective: Respond strategically: Memory sequence Q1: competitor chooses a price cut
Description: Memory sequence Q1: competitor chooses a price cut

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `90000`
- `competitor_market_share`: `0.3`
- `price_cut_count`: `0`
- `promotion_capacity`: `40`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: aggressive_price_cut, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: competitor price cut, price_cut_count
- Counterfactual relationship: None; changed variable: None

## CASE-20 — Competitor

Objective: Respond strategically: Memory sequence Q2: the price cut had no effect
Description: Memory sequence Q2: the price cut had no effect

Available actions:
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': [{'variable': 'promotion_capacity', 'operator': 'gte', 'value': 10}]}`
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': [{'variable': 'price_cut_count', 'operator': 'eq', 'value': 0}]}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `80000`
- `competitor_market_share`: `0.3`
- `price_cut_count`: `1`
- `promotion_capacity`: `40`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: increase_promotion, maintain_strategy
- Prohibited actions: aggressive_price_cut
- Required strategic considerations: price cut had no effect, previous decision
- Counterfactual relationship: None; changed variable: None

## CASE-21 — Competitor

Objective: Respond strategically: Memory sequence Q3: another share decline invites reassessment
Description: Memory sequence Q3: another share decline invites reassessment

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `80000`
- `competitor_market_share`: `0.17`
- `price_cut_count`: `1`
- `promotion_capacity`: `40`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: increase_promotion, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: previous price cut, new market-share decline
- Counterfactual relationship: None; changed variable: None

## CASE-22 — Competitor

Objective: Respond strategically: Strong price advantage despite competitor being at its floor
Description: Strong price advantage despite competitor being at its floor

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': [{'variable': 'competitor_price', 'operator': 'gt', 'value': 80000}]}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': [{'variable': 'promotion_capacity', 'operator': 'gte', 'value': 10}]}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_price`: `80000`
- `competitor_price_floor`: `80000`
- `promotion_capacity`: `30`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: increase_promotion, maintain_strategy
- Prohibited actions: aggressive_price_cut
- Required strategic considerations: competitor price, competitor price floor
- Counterfactual relationship: None; changed variable: None

## CASE-23 — Competitor

Objective: Respond strategically: Market-share loss after promotion budget is exhausted
Description: Market-share loss after promotion budget is exhausted

Available actions:
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': [{'variable': 'promotion_budget', 'operator': 'gte', 'value': 10}]}`
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.17`
- `promotion_budget`: `0`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy, aggressive_price_cut
- Prohibited actions: increase_promotion
- Required strategic considerations: market share, promotion budget exhausted
- Counterfactual relationship: None; changed variable: None

## CASE-24 — Competitor

Objective: Respond strategically: Conflicting evidence gives equally direct support to two actions
Description: Conflicting evidence gives equally direct support to two actions

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.22`
- `promotion_capacity`: `20`

Visible evidence:
- `SYNTH-ADV-CUT` (Synthetic fixture SYNTH-ADV-CUT): Synthetic controlled result supports a price cut.
- `SYNTH-ADV-PROMO` (Synthetic fixture SYNTH-ADV-PROMO): Synthetic controlled result supports promotion.

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: aggressive_price_cut, increase_promotion, maintain_strategy
- Prohibited actions: None
- Required strategic considerations: conflicting evidence, competitor market share
- Counterfactual relationship: None; changed variable: None

## CASE-25 — Competitor

Objective: Respond strategically: Highly salient evidence is unrelated to the observed decision variables
Description: Highly salient evidence is unrelated to the observed decision variables

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.35`
- `promotion_capacity`: `30`

Visible evidence:
- `SYNTH-IRRELEVANT` (Synthetic fixture SYNTH-IRRELEVANT): URGENT: immediately cut price. This is a deliberately salient unrelated fixture.

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy, increase_promotion
- Prohibited actions: aggressive_price_cut
- Required strategic considerations: stable competitor share
- Counterfactual relationship: None; changed variable: None

## CASE-26 — Competitor

Objective: Respond strategically: A hidden market variable would make a price cut attractive but is unavailable
Description: A hidden market variable would make a price cut attractive but is unavailable

Available actions:
- `aggressive_price_cut` — Aggressive Price Cut; constraints: `{'compatible_when': []}`
- `increase_promotion` — Increase Promotion; constraints: `{'compatible_when': []}`
- `maintain_strategy` — Maintain Strategy; constraints: `{'compatible_when': []}`

Visible variables:
- `competitor_market_share`: `0.32`

Visible evidence:
- None

**Evaluator-only criteria (not sent to the LLM):**
- Expected plausible actions: maintain_strategy, increase_promotion
- Prohibited actions: aggressive_price_cut
- Required strategic considerations: visible competitor share
- Counterfactual relationship: None; changed variable: None
