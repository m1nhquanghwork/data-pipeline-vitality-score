# Right-Time Referral System Actionable Plan

## Objective

Build the first version of the right-time referral system: a small, explainable decision layer that turns PHAIVIT, pet context, check-in history, calendar timing, and suppression rules into one calm recommendation or no recommendation.

The goal is not to build the full Marketplace yet. The first goal is to make Evie recommend the right thing at the right time, with a clear reason and strong safety boundaries.

## Product Principle

Every referral must pass this test:

```text
Would this feel like Evie noticed something useful for this pet, at this moment?
```

If the answer is no, do not show a referral.

The system should avoid generic Marketplace ads. Recommendations should be contextual, explainable, sparse, and suppressible.

## Workstream 1: Define the Referral Input Model

Create a typed input object that combines the signals the referral engine is allowed to use.

Proposed file:

```text
referrals/
  __init__.py
  models.py
  rules.py
  engine.py
  suppression.py
  calendar.py
tests/
  test_referrals.py
```

Minimum input fields:

- `pet_id`
- `species`
- `breed`
- `birth_date`
- `life_stage`
- `postcode`
- `phaivit_score`
- `phaivit_band`
- `phaivit_drivers`
- `phaivit_override_severity`
- `genetic_profile_available`
- `vaccination_current`
- `worming_compliant`
- `recent_checkin_flags`
- `recent_owner_concern_level`
- `recent_referrals_shown`
- `active_calendar_tags`
- `user_cohort`
- `premium_status`
- `sensitive_state`

Sensitive states should include:

- `normal`
- `emergency_or_urgent_override`
- `dormant`
- `deletion_review`
- `suspected_pet_loss`
- `confirmed_pet_loss`

## Workstream 2: Define Referral Output

Every referral decision should return either one recommendation or no recommendation.

Example output:

```json
{
  "recommendation_id": "genetic_test_unlock_v0",
  "category": "Genetic Test",
  "subcategory": "Genetic Profile",
  "surface": "weekly_checkin_completion",
  "priority": 90,
  "reason": "Bonnie has completed four Weekly Check-ins, so Evie can now combine observed patterns with genetic context.",
  "cta_label": "See the test",
  "partner_key": "genetic_test_partner",
  "suppressed": false,
  "suppression_reason": null
}
```

If no recommendation should be shown:

```json
{
  "recommendation_id": null,
  "suppressed": true,
  "suppression_reason": "No referral met the relevance threshold."
}
```

Required output fields:

- `recommendation_id`
- `category`
- `subcategory`
- `surface`
- `priority`
- `reason`
- `cta_label`
- `partner_key`
- `suppressed`
- `suppression_reason`

## Workstream 3: Build Referral Rules v0

Create 5-8 starter rules as static config. Keep them simple, readable, and testable.

Suggested file:

```text
referrals/rules.py
```

Starter rules:

1. Genetic test after fourth PHAIVIT unlock
2. Dental care from dental calendar tag or dental-related driver
3. Insurance for puppy life stage or Pet Insurance Month
4. Senior care for senior pets with mobility, weight, or activity changes
5. Training or anxiety support after repeated behaviour/anxiety check-in flags
6. Parasite prevention from seasonal, heartworm, flea, tick, or worming signals
7. Nutrition or weight support from weight/activity/appetite patterns
8. Bereavement support only through the sensitive human-review pathway

Example rule shape:

```json
{
  "rule_id": "dental_support_v0",
  "category": "Health & Wellness",
  "subcategory": "Dental Care",
  "partner_key": "dental_partner",
  "surfaces": ["marketplace", "evie_suggestion"],
  "triggers": {
    "calendar_tags": ["dental"],
    "phaivit_drivers": ["dental"],
    "life_stages": ["adult", "senior"]
  },
  "suppression": {
    "suppress_on_emergency_or_urgent": true,
    "suppress_sensitive_states": true,
    "cooldown_days": 30
  },
  "priority": 60
}
```

## Workstream 4: Build Suppression Rules

Suppression is as important as matching. It protects trust.

Global suppression rules:

- Do not show commercial referrals during emergency or urgent PHAIVIT overrides.
- Do not show any referral in suspected or confirmed pet-loss state.
- Do not show commercial content in deletion-review state.
- Do not show the same category again within 30 days.
- Do not show genetic-test referral before the earned trigger, except approved Beny/Premium variant.
- Do not show a referral if Evie cannot explain why it is relevant.
- Do not show more than one referral in a single product moment.

Recommended implementation:

```text
referrals/suppression.py
```

Expose:

```python
def should_suppress(rule, context) -> tuple[bool, str | None]:
    ...
```

## Workstream 5: Build the Referral Ranking Engine

The engine should evaluate all rules, suppress unsafe ones, rank relevant ones, and return the top result or none.

Suggested scoring factors:

- `relevance_score`: how strongly this rule matches the pet's current context
- `timing_score`: whether this is a good moment to show it
- `priority`: business/product priority from the rule
- `trust_penalty`: penalty for weak explanation, repeated category, or borderline timing

Initial formula:

```text
final_score = relevance_score + timing_score + priority - trust_penalty
```

Recommended threshold:

```text
Only return a recommendation when final_score >= 70.
```

If no rule reaches the threshold, return no recommendation.

## Workstream 6: Add Calendar Tags

Convert the PawHealthAI Pet Calendar into a structured config.

Minimum calendar fields:

- `month`
- `start_date`
- `end_date`
- `event_name`
- `tags`
- `recommended_action_type`

Example:

```json
{
  "event_name": "Pet Dental Health Month",
  "start_date": "2026-08-01",
  "end_date": "2026-08-31",
  "tags": ["dental", "health_wellness"],
  "recommended_action_type": "marketplace_recommendation"
}
```

The referral engine should consume active calendar tags, not hard-code date logic inside every rule.

## Workstream 7: Add Tests

Required tests:

- Genetic test referral appears after fourth PHAIVIT unlock.
- Genetic test referral does not appear before earned trigger.
- Beny/Premium variant can introduce genetic test earlier if explicitly allowed.
- Dental referral appears during dental calendar period.
- Insurance referral appears for puppy or insurance calendar tag.
- Senior care referral appears for senior pet with relevant PHAIVIT drivers.
- Emergency override suppresses all commercial referrals.
- Suspected pet loss suppresses all referrals.
- Same-category referral is suppressed within cooldown window.
- No recommendation is returned when relevance is weak.

## Workstream 8: Define Initial Surfaces

Start with limited surfaces. Do not let referrals appear everywhere at once.

Phase 1 surfaces:

- Weekly Check-in completion screen
- Marketplace `Recommended for [pet name]` slot
- Optional Evie suggestion card

Do not show referrals in:

- Pawport identity zone
- Condolence or pet-loss flows
- Emergency or urgent health moments
- Generic onboarding before the earned trigger, except Beny/Premium-specific flows

## Workstream 9: Track Events

Record what the referral engine decided, even when it shows nothing.

Suggested events:

- `referral_engine.evaluated`
- `referral_recommendation.shown`
- `referral_recommendation.dismissed`
- `referral_recommendation.clicked`
- `referral_recommendation.suppressed`
- `referral_recommendation.converted`

Minimum event properties:

- `pet_id`
- `rule_id`
- `category`
- `surface`
- `final_score`
- `suppression_reason`
- `created_at`

## First Engineering Ticket

Build the referral decision engine v0 with static rules, suppression, ranking, and tests.

Scope:

- Create `referrals/` package.
- Add typed input and output models.
- Add 5-8 starter rules.
- Add suppression logic.
- Add ranking logic.
- Add tests for rule matching, suppression, and no-recommendation states.

Out of scope:

- Marketplace catalogue UI
- Partner API integration
- Payments
- Affiliate tracking
- Full personalization copy generation

## Definition of Done

- The referral engine accepts a pet/PHAIVIT/calendar context object.
- The engine returns either one recommendation or no recommendation.
- Recommendations include an explainable reason.
- Emergency, urgent, deletion-review, and pet-loss states suppress referrals.
- Same-category cooldown is enforced.
- Tests cover the core starter rules and suppression paths.
- The output can be consumed by the Weekly Check-in completion screen and Marketplace recommendation slot.

## Suggested Next Ticket

After the referral engine v0 is working:

- Wire it to `phaivit_score.first_unlocked`.
- Show the genetic-test recommendation after the fourth check-in.
- Add the Marketplace `Recommended for [pet name]` slot.
- Track shown, dismissed, clicked, suppressed, and converted events.
