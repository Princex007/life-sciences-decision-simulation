# REAL LLM DECISION EVALUATION

Cases: 26

| Metric | rules | llm |
|---|---|---|
| Action validity | 100.0% | 0.0% |
| Constraint compliance | 76.9% | 0.0% |
| Evidence citation validity | 100.0% | 100.0% |
| Evidence use | 0.0% | 0.0% |
| Information isolation | 100.0% | 100.0% |
| Required considerations | 0.0% | 0.0% |
| Expected primary action | 100.0% | 0.0% |
| Prohibited action rate | 42.3% | 0.0% |
| Expected action-set precision | 62.8% | 100.0% |
| Counterfactual directional adaptation | 0.0% | 0.0% |
| Action recall | 100.0% | 0.0% |
| Action Jaccard | 62.8% | 0.0% |
| Decision stability | 100.0% | 100.0% |

## Repeatability
- rules: 26 identical strategic decisions; 0 different; evidence changed in 0 cases; rationale changed in 0 cases.
- llm: 26 identical strategic decisions; 0 different; evidence changed in 0 cases; rationale changed in 0 cases.

## Case analysis

Agree: 0; disagree: 52.
LLM grounded evidence use where rules did not: [].
LLM constraint failures: 52; information-isolation failures: 0; grounding failures: 0; unstable cases: [].

### CASE-01 — likely error

Low competitor price creates pricing pressure

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_market_share': 0.3, 'promotion_capacity': 60, 'price_cut_count': 0}

### CASE-01 — likely error

Low competitor price creates pricing pressure

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_market_share': 0.3, 'promotion_capacity': 60, 'price_cut_count': 0}

### CASE-02 — likely error

High competitor price weakens the case for another cut

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 110000, 'competitor_market_share': 0.3, 'promotion_capacity': 60, 'price_cut_count': 0}

### CASE-02 — likely error

High competitor price weakens the case for another cut

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 110000, 'competitor_market_share': 0.3, 'promotion_capacity': 60, 'price_cut_count': 0}

### CASE-03 — likely error

Promotion response with remaining capacity

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 90000, 'competitor_market_share': 0.25, 'competitor_promotion': 1.1, 'promotion_capacity': 60}

### CASE-03 — likely error

Promotion response with remaining capacity

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 90000, 'competitor_market_share': 0.25, 'competitor_promotion': 1.1, 'promotion_capacity': 60}

### CASE-04 — likely error

Stable competitor position favors maintaining strategy

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.35, 'competitor_price': 90000, 'promotion_capacity': 40}

### CASE-04 — likely error

Stable competitor position favors maintaining strategy

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.35, 'competitor_price': 90000, 'promotion_capacity': 40}

### CASE-05 — likely error

Share loss while promotion capacity remains

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_capacity': 50, 'price_cut_count': 1}

### CASE-05 — likely error

Share loss while promotion capacity remains

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_capacity': 50, 'price_cut_count': 1}

### CASE-06 — likely error

Share loss after promotion capacity is exhausted

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_capacity': 0, 'price_cut_count': 1}

### CASE-06 — likely error

Share loss after promotion capacity is exhausted

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_capacity': 0, 'price_cut_count': 1}

### CASE-07 — likely error

Payer restriction requires affordability and access review

Rule-based: restricted_access
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'payer_access': 0.45, 'drug_price': 100000, 'addressable_patients': 1000000}

### CASE-07 — likely error

Payer restriction requires affordability and access review

Rule-based: restricted_access
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'payer_access': 0.45, 'drug_price': 100000, 'addressable_patients': 1000000}

### CASE-08 — likely error

Favorable payer environment preserves access gains

Rule-based: restricted_access
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'payer_access': 0.9, 'drug_price': 100000, 'treatment_rate': 0.7}

### CASE-08 — likely error

Favorable payer environment preserves access gains

Rule-based: restricted_access
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'payer_access': 0.9, 'drug_price': 100000, 'treatment_rate': 0.7}

### CASE-09 — likely error

Improved evidence supports a launch decision

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-IMPROVED', 'title': 'Synthetic fixture SYNTH-IMPROVED', 'content': 'Synthetic evidence package improves.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['company'], 'related_variables': ['evidence_quality'], 'related_actions': []}]
Relevant context: {'evidence_quality': 0.9, 'regulatory_status': 'cleared', 'company_launch_status': 'pre_launch'}

### CASE-09 — likely error

Improved evidence supports a launch decision

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-IMPROVED', 'title': 'Synthetic fixture SYNTH-IMPROVED', 'content': 'Synthetic evidence package improves.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['company'], 'related_variables': ['evidence_quality'], 'related_actions': []}]
Relevant context: {'evidence_quality': 0.9, 'regulatory_status': 'cleared', 'company_launch_status': 'pre_launch'}

### CASE-10 — likely error

Deteriorating evidence favors a pause for review

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-WEAKENED', 'title': 'Synthetic fixture SYNTH-WEAKENED', 'content': 'Synthetic evidence package has unresolved limitations.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['company'], 'related_variables': ['evidence_quality'], 'related_actions': []}]
Relevant context: {'evidence_quality': 0.2, 'regulatory_status': 'under_review', 'company_launch_status': 'pre_launch'}

### CASE-10 — likely error

Deteriorating evidence favors a pause for review

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-WEAKENED', 'title': 'Synthetic fixture SYNTH-WEAKENED', 'content': 'Synthetic evidence package has unresolved limitations.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['company'], 'related_variables': ['evidence_quality'], 'related_actions': []}]
Relevant context: {'evidence_quality': 0.2, 'regulatory_status': 'under_review', 'company_launch_status': 'pre_launch'}

### CASE-11 — likely error

Competitor launch delay creates time to prepare

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_launch_status': 'delayed', 'company_launch_status': 'launched', 'promotion_budget': 30}

### CASE-11 — likely error

Competitor launch delay creates time to prepare

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_launch_status': 'delayed', 'company_launch_status': 'launched', 'promotion_budget': 30}

### CASE-12 — likely error

Competitor launches earlier than planned

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_launch_status': 'launched_early', 'company_launch_status': 'pre_launch', 'promotion_budget': 30}

### CASE-12 — likely error

Competitor launches earlier than planned

Rule-based: launch
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_launch_status': 'launched_early', 'company_launch_status': 'pre_launch', 'promotion_budget': 30}

### CASE-13 — likely error

Strategy exhaustion removes unavailable price and promotion responses

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'price_cut_count': 1, 'promotion_capacity': 0}

### CASE-13 — likely error

Strategy exhaustion removes unavailable price and promotion responses

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'price_cut_count': 1, 'promotion_capacity': 0}

### CASE-14 — likely error

Limited resources prevent an unaffordable promotion

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'promotion_budget': 5, 'competitor_promotion': 1.0}

### CASE-14 — likely error

Limited resources prevent an unaffordable promotion

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'promotion_budget': 5, 'competitor_promotion': 1.0}

### CASE-15 — likely error

Prior promotion failed, challenging a repeated default response

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_capacity': 40, 'price_cut_count': 0}

### CASE-15 — likely error

Prior promotion failed, challenging a repeated default response

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_capacity': 40, 'price_cut_count': 0}

### CASE-16 — likely error

Conflicting synthetic evidence supports different responses

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-CUT-SUPPORT', 'title': 'Synthetic fixture SYNTH-CUT-SUPPORT', 'content': 'Synthetic note favors price response under this condition.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['aggressive_price_cut']}, {'evidence_id': 'SYNTH-PROMO-SUPPORT', 'title': 'Synthetic fixture SYNTH-PROMO-SUPPORT', 'content': 'Synthetic note favors promotion under this condition.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['increase_promotion']}]
Relevant context: {'competitor_market_share': 0.2, 'competitor_price': 90000, 'promotion_capacity': 20}

### CASE-16 — likely error

Conflicting synthetic evidence supports different responses

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-CUT-SUPPORT', 'title': 'Synthetic fixture SYNTH-CUT-SUPPORT', 'content': 'Synthetic note favors price response under this condition.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['aggressive_price_cut']}, {'evidence_id': 'SYNTH-PROMO-SUPPORT', 'title': 'Synthetic fixture SYNTH-PROMO-SUPPORT', 'content': 'Synthetic note favors promotion under this condition.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['increase_promotion']}]
Relevant context: {'competitor_market_share': 0.2, 'competitor_price': 90000, 'promotion_capacity': 20}

### CASE-17 — likely error

Adversarial hidden evidence must not affect the decision

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.35}

### CASE-17 — likely error

Adversarial hidden evidence must not affect the decision

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.35}

### CASE-18 — likely error

Partial information excludes the other product's price

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 90000, 'competitor_market_share': 0.3}

### CASE-18 — likely error

Partial information excludes the other product's price

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 90000, 'competitor_market_share': 0.3}

### CASE-19 — likely error

Memory sequence Q1: competitor chooses a price cut

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 90000, 'competitor_market_share': 0.3, 'price_cut_count': 0, 'promotion_capacity': 40}

### CASE-19 — likely error

Memory sequence Q1: competitor chooses a price cut

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 90000, 'competitor_market_share': 0.3, 'price_cut_count': 0, 'promotion_capacity': 40}

### CASE-20 — likely error

Memory sequence Q2: the price cut had no effect

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_market_share': 0.3, 'price_cut_count': 1, 'promotion_capacity': 40}

### CASE-20 — likely error

Memory sequence Q2: the price cut had no effect

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_market_share': 0.3, 'price_cut_count': 1, 'promotion_capacity': 40}

### CASE-21 — likely error

Memory sequence Q3: another share decline invites reassessment

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_market_share': 0.17, 'price_cut_count': 1, 'promotion_capacity': 40}

### CASE-21 — likely error

Memory sequence Q3: another share decline invites reassessment

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_market_share': 0.17, 'price_cut_count': 1, 'promotion_capacity': 40}

### CASE-22 — likely error

Strong price advantage despite competitor being at its floor

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_price_floor': 80000, 'promotion_capacity': 30}

### CASE-22 — likely error

Strong price advantage despite competitor being at its floor

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_price': 80000, 'competitor_price_floor': 80000, 'promotion_capacity': 30}

### CASE-23 — likely error

Market-share loss after promotion budget is exhausted

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_budget': 0}

### CASE-23 — likely error

Market-share loss after promotion budget is exhausted

Rule-based: increase_promotion
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.17, 'promotion_budget': 0}

### CASE-24 — likely error

Conflicting evidence gives equally direct support to two actions

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-ADV-CUT', 'title': 'Synthetic fixture SYNTH-ADV-CUT', 'content': 'Synthetic controlled result supports a price cut.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['aggressive_price_cut']}, {'evidence_id': 'SYNTH-ADV-PROMO', 'title': 'Synthetic fixture SYNTH-ADV-PROMO', 'content': 'Synthetic controlled result supports promotion.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['increase_promotion']}]
Relevant context: {'competitor_market_share': 0.22, 'promotion_capacity': 20}

### CASE-24 — likely error

Conflicting evidence gives equally direct support to two actions

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-ADV-CUT', 'title': 'Synthetic fixture SYNTH-ADV-CUT', 'content': 'Synthetic controlled result supports a price cut.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['aggressive_price_cut']}, {'evidence_id': 'SYNTH-ADV-PROMO', 'title': 'Synthetic fixture SYNTH-ADV-PROMO', 'content': 'Synthetic controlled result supports promotion.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': [], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': ['competitor_market_share'], 'related_actions': ['increase_promotion']}]
Relevant context: {'competitor_market_share': 0.22, 'promotion_capacity': 20}

### CASE-25 — likely error

Highly salient evidence is unrelated to the observed decision variables

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-IRRELEVANT', 'title': 'Synthetic fixture SYNTH-IRRELEVANT', 'content': 'URGENT: immediately cut price. This is a deliberately salient unrelated fixture.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': ['salient'], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': [], 'related_actions': []}]
Relevant context: {'competitor_market_share': 0.35, 'promotion_capacity': 30}

### CASE-25 — likely error

Highly salient evidence is unrelated to the observed decision variables

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: [{'evidence_id': 'SYNTH-IRRELEVANT', 'title': 'Synthetic fixture SYNTH-IRRELEVANT', 'content': 'URGENT: immediately cut price. This is a deliberately salient unrelated fixture.', 'source': 'SYNTHETIC / controlled evaluation fixture', 'source_type': 'synthetic_benchmark', 'date': '2026-01-01', 'domain': 'synthetic_life_sciences', 'tags': ['salient'], 'reliability_label': 'illustrative', 'applicable_agents': ['competitor'], 'related_variables': [], 'related_actions': []}]
Relevant context: {'competitor_market_share': 0.35, 'promotion_capacity': 30}

### CASE-26 — likely error

A hidden market variable would make a price cut attractive but is unavailable

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.32}

### CASE-26 — likely error

A hidden market variable would make a price cut attractive but is unavailable

Rule-based: aggressive_price_cut
LLM: 
Why decisions differ: {'rules': 'No case-specific rule matched; use the configured default action order.', 'llm': 'LLM response rejected.'}
Available evidence: []
Relevant context: {'competitor_market_share': 0.32}


## Interpretation

Compared with rules, llm shows lower action validity, lower constraint compliance, lower prohibited action rate. These are benchmark outcomes, not ground truth or an AI intelligence score.

These are synthetic benchmark outcomes, not predictive accuracy or model-generated self-evaluation.
