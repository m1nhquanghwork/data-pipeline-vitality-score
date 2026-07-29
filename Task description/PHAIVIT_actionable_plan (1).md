# PHAIVIT Score Actionable Plan

## Objective

Turn the current PHAIVIT notebook prototype into a real, testable, product-ready scoring module that unlocks after the fourth Weekly Check-in and can later feed Pawport, Home, onboarding, and right-time Marketplace referrals.

## Product Rule

PHAIVIT should behave as follows:

- Check-ins 1-3: show `Building Baseline`
- Check-in 4: generate the pet's first PHAIVIT score
- Check-in 5 onward: update the score using the pet's growing history

This is important because the War Room onboarding PRD says the first PHAIVIT score unlocks after four Weekly Check-ins. The current notebook prototype effectively waits until the fifth event unless the caller includes the current check-in in history.

## Workstream 1: Create a PHAIVIT Module

Move the notebook logic into normal Python files so it can be imported, tested, and called from check-in completion flows.

Proposed structure:

```text
phaivit/
  __init__.py
  models.py
  red_flags.py
  scoring.py
  pipeline.py
tests/
  test_phaivit.py
```

Responsibilities:

- `models.py`: dataclasses or typed models for pet profile, check-in data, baseline summary, red-flag result, and score result
- `red_flags.py`: emergency, urgent, and monitor override logic
- `scoring.py`: baseline and 0-100 score calculation
- `pipeline.py`: orchestration layer that runs red flags first, then scoring
- `tests/test_phaivit.py`: product-state and safety tests

## Workstream 2: Fix the Fourth Check-in Unlock Boundary

The scoring pipeline should treat the current completed check-in as part of the scoreable set.

Acceptance criteria:

- 0 previous + current = `Building Baseline`
- 1 previous + current = `Building Baseline`
- 2 previous + current = `Building Baseline`
- 3 previous + current = first PHAIVIT score
- 4+ previous + current = updated PHAIVIT score

Implementation options:

- Preferred: pass `previous_checkins` and `current_checkin` separately, then have the pipeline build `all_checkins = previous_checkins + [current_checkin]`
- Alternative: require callers to pass history including current, but this is easier to misuse

## Workstream 3: Standardize PHAIVIT Output

Every score calculation should return a stable result object.

Example:

```json
{
  "pet_id": "pet_100001",
  "score": 88,
  "band": "Bright Green",
  "baseline_status": "established",
  "confidence": "moderate",
  "drivers": ["appetite below usual"],
  "override": null,
  "explanation": "Bonnie's indicators are tracking in line with her usual baseline this week.",
  "trend": "stable"
}
```

Required fields:

- `pet_id`
- `score`
- `band`
- `baseline_status`
- `confidence`
- `drivers`
- `override`
- `explanation`
- `trend`

## Workstream 4: Preserve Safety Override Behavior

Red flags must run before score calculation.

Rules:

- Emergency red flag: hide score, return `Action Needed`
- Urgent red flag: hide score, return `Action Needed`
- Monitor red flag: show score, attach advisory context
- No red flag: normal PHAIVIT score

Acceptance tests:

- Suspected toxin ingestion returns `score = null`, `band = Action Needed`, and an emergency pathway
- Collapse returns `score = null`, `band = Action Needed`, and an emergency pathway
- Blood in stool with low energy returns urgent override
- Single vomiting or diarrhoea returns monitor advisory without hiding score
- No red flags returns normal scoring result

## Workstream 5: Add Tests for Product States

Create focused tests before wiring to the app.

Required tests:

- Building baseline with fewer than four total check-ins
- First score generated on the fourth completed check-in
- Bright/Medium Green result for stable check-ins
- Watch or Action Needed result for multiple declining indicators
- Emergency override suppresses score
- Monitor override attaches advisory while preserving score
- High-energy breed weighting affects activity impact
- Malformed or missing optional fields fail safely

## Workstream 6: Wire to Weekly Check-in Completion

On every `weekly_checkin.completed` event:

1. Load pet profile.
2. Load previous check-ins for that pet.
3. Pass previous check-ins plus the current check-in into the PHAIVIT pipeline.
4. Store the result.
5. If this is the fourth completed check-in, emit `phaivit_score.first_unlocked`.
6. Otherwise emit or log `phaivit_score.updated`.

Required events:

- `weekly_checkin.completed`
- `phaivit_score.created`
- `phaivit_score.first_unlocked`
- `phaivit_score.updated`
- `phaivit_score.override_triggered`

## Workstream 7: Store PHAIVIT Results

Create or confirm a table for score history.

Suggested table: `phaivit_scores`

Minimum fields:

- `id`
- `pet_id`
- `checkin_id`
- `score`
- `band`
- `baseline_status`
- `confidence`
- `drivers_json`
- `override_json`
- `explanation`
- `trend`
- `created_at`

Notes:

- Keep score history, not just the latest score.
- Home and Pawport can read the latest result.
- Trend views can use historical rows later.

## Workstream 8: Connect Product Surfaces

Use the latest PHAIVIT result in:

- Home screen
- Pawport, in the "What's Happening" zone
- Fourth check-in completion unlock moment
- Onboarding email and in-app moments
- Future Marketplace recommendations

Fourth-check-in unlock copy should stay calm:

```text
[Pet name]'s first PHAIVIT score is ready.
You can see it on the home screen and on [pet name]'s Pawport.
```

## Workstream 9: Prepare Right-Time Referral Hooks

Do not build the full Marketplace recommendation engine yet. First, expose clean signals from PHAIVIT and pet context.

Referral inputs to expose:

- `band`
- `drivers`
- `override.severity_tier`
- `species`
- `breed`
- `age`
- `life_stage`
- `genetic_profile_available`
- `vaccination_current`
- `worming_compliant`
- `recent_health_flags`
- `calendar_tags`

These signals will later support right-time recommendations such as:

- Dental care when dental indicators or calendar timing justify it
- Insurance prompts during puppy onboarding or insurance month
- Senior care when age and score patterns suggest it
- Training support when check-ins repeatedly mention anxiety or behaviour
- Genetic test offer after the fourth check-in unlock

## First Engineering Ticket

Build the `phaivit/` module from the notebook, add tests, and fix the fourth-check-in unlock boundary.

## Definition of Done

- PHAIVIT logic runs from normal Python, not notebook-only code.
- Fourth completed Weekly Check-in produces the first PHAIVIT score.
- Tests cover baseline, first unlock, green score, declining score, emergency override, and monitor advisory.
- Output object is stable and ready to persist.
- The pipeline can be called from `weekly_checkin.completed`.
- Referral-facing signals are available for the next phase.

## Suggested Next Ticket

After the PHAIVIT module is working, create the persistence and event wiring:

- Add `phaivit_scores` storage.
- Run PHAIVIT on `weekly_checkin.completed`.
- Emit `phaivit_score.first_unlocked` on the fourth completed check-in.
- Show the latest score in Home and Pawport.
