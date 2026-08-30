# `test_phavit.py` — how to run it and how to add to it

The test suite for the PHAIVIT engine. **107 tests** covering the scoring math, the red-flag safety net, the weight subsystem and the plain-English explanation layer, plus **31 JSON scenarios** that a vet or product reviewer can read and check without opening any Python.

Everything lives in one file on purpose. The three layers are only meaningful together — a change to the weight thresholds can move a red-flag tier, which changes which band the owner sees — so splitting the suite would hide exactly the interactions worth testing.

---

## Running it

From the repo root:

```bash
python -m pytest test_case/test_phavit.py -q
```

```
92 passed in 0.16s
```

**Without pytest installed.** The file has its own runner, so it works on a machine with nothing but Python:

```bash
python test_case/test_phavit.py
```

```
  PASS  test_a_supplied_trend_takes_precedence_over_the_checkin_stream
  ...
107/107 passed
```

It exits non-zero on failure, so it drops straight into CI.

**Useful variations:**

| Command | What it does |
| --- | --- |
| `python -m pytest test_case/test_phavit.py -q` | The whole suite, quiet |
| `python -m pytest test_case/test_phavit.py -k weight -q` | Just the weight tests (18 of them) |
| `python -m pytest test_case/test_phavit.py -k "scenario or fixture" -q` | Just the JSON scenario checks |
| `python -m pytest test_case/test_phavit.py::test_blank_weeks_hold_the_score_steady` | One named test |
| `python -m pytest test_case/test_phavit.py -x --tb=short` | Stop at the first failure, short traceback |

You can run from the repo root or from inside `test_case/` — a `conftest.py` in both places puts the repo root on `sys.path` so `from phavit import ...` resolves either way. The standalone runner does the same thing itself via `sys.path.insert`.

---

## What is in it

| Section | Tests | Covers |
| --- | --- | --- |
| 1–8 | 12 | The eight product states from the actionable plan: baseline building, the fourth-check-in unlock, green bands, declining indicators, emergency and monitor overrides, breed weighting, malformed input |
| *(fixture-wide)* | 2 | Every JSON loads, runs, stays non-diagnostic, and matches its own declared expectation |
| 9–14 | 22 | The weight subsystem: inert without data, trend math, data quality, monthly cadence, escalations and suppressions, weighting profiles staying normalised |
| 15 | 20 | System analysis — boundaries, determinism, invariants |
| 16 | 18 | Core engine coverage outside weight |
| 17 | 20 | Weight arriving on the check-in stream, and the data-quality prompts |

Two rules the whole suite enforces, worth knowing before you change anything:

- **No disease names ever reach an owner.** `_assert_no_disease_terms()` checks every explanation against `DISEASE_WORDS`. Note it deliberately does *not* ban the words "diagnosis" or "disease" — the engine uses them in its safe disclaimers ("this is a wellbeing trend, not a diagnosis").
- **Dates are fixed, never `today`.** `CHECKIN_DAY = datetime(2026, 7, 20)` and `LAST_WEIGH_IN = date(2026, 7, 18)` are constants, so the weight staleness tests do not drift and start failing on their own months from now. If you add a weight test, anchor it to these rather than `datetime.now()`.

---

## Two ways to add a test

Pick by audience. **A JSON scenario** if a vet or product reviewer should be able to read it. **A Python test** if you are pinning a boundary, an invariant, or a branch that has no natural story around it.

### Adding a JSON scenario

Drop a `.json` file in this folder. It is picked up automatically — the suite globs `*.json`, so there is no list to register it in.

Minimum viable scenario:

```json
{
  "scenario": "One line a human can read: what is happening and why it matters.",
  "pet_profile": {
    "pet_id": "pet_200012", "pet_name": "Nala",
    "species": "cat", "breed": "Siamese", "sex": "female",
    "postcode": "3000", "birth_date": "2021-03-08",
    "is_high_energy": false, "worming_compliant": true,
    "vaccination_current": true, "weight_management_plan": false
  },
  "check_in_data": {
    "pet_id": "pet_200012", "timestamp": "2026-07-21T09:00:00Z",
    "appetite_score": 4, "energy_score": 4,
    "sleep_quality_score": 4, "activity_minutes": 30
  },
  "expected": { "band": "Bright Green", "score_present": true, "override_tier": null }
}
```

**Top-level keys:**

| Key | Required | Notes |
| --- | --- | --- |
| `scenario` | no | One-line human description. Write it first; if you cannot, the scenario is probably testing two things |
| `pet_profile` | **yes** | Note the JSON key is `postcode` while the model field is `post_code` |
| `check_in_data` | **yes** | The current weekly check-in |
| `previous_checkins` | no | Explicit history. **Omitted means a synthetic stable baseline of 4** — so a scenario with no history still scores |
| `weight_log.readings` | no | `[{kg, at}]`, any order. Omit to let the engine derive weight from `weight_kg` on the check-ins instead |
| `expected` | **yes** | Asserted by `test_every_scenario_matches_its_declared_expectation` |

**Everything `expected` accepts:**

| Key | Type | Checks |
| --- | --- | --- |
| `band` | string | **Required.** One of the five bands |
| `score_present` | bool | **Required.** Whether a 0-100 number is shown at all |
| `score` | int | Exact score. Only add when the number itself is the point |
| `confidence` / `trend` / `baseline_status` | string | Compared directly against the result field |
| `override_tier` | string or `null` | **Always checked**, so `null` must be explicit for a no-flag scenario |
| `override_trigger` | string | The machine label, e.g. `"notable_weight_loss"` |
| `override_reason_includes` / `..._excludes` | list | Fragments that must / must not appear in the escalation reason |
| `weight_status` | string | `"ok"`, `"insufficient"`, `"implausible"` |
| `weight_direction` | string | `"loss"`, `"gain"`, `"stable"`, `"unknown"` |
| `weight_body_status` | string | e.g. `"in_reference"`, `"well_above_reference"`, `"no_reference"` |
| `weight_managed` / `weight_is_growing` | bool | Suppression flags |
| `drivers_include` | list | Each entry must appear as a substring of some driver |
| `explanation_includes` | string | Substring of the owner-facing explanation |

Write the `expected` block **before** running it — that is the discipline that makes these useful. A failure names the file:

```
E   AssertionError: Zz_demo_broken.json: band 'Bright Green' != 'Watch'
```

If the engine disagrees with you, work out which one is wrong before editing either. `Baseline_with_red_flag.json` exists precisely because a fixture "failed" and the engine turned out to be right: red flags run *before* the baseline gate, so a pet with too little history can still be escalated rather than told to keep waiting.

### Adding a Python test

Use the builders rather than constructing dataclasses by hand — they carry sensible defaults so your test only states what it is actually about.

| Builder | Gives you |
| --- | --- |
| `make_pet(pet_id, name, high_energy, worming)` | A `PetProfile`; a male Labrador by default |
| `mk_checkin(pet_id, **kw)` | A healthy check-in (all 4s, 60 min); override any field |
| `make_history(pet_id, n, ...)` | `n` identical stable check-ins as a baseline |
| `history_with(pet_id, n_clean, **flags)` | Stable history whose **most recent** entry carries `flags` — for the "repeated sign" rules, which look back three check-ins |
| `monthly_weights([kgs], last_on)` | Readings four weeks apart ending on `last_on` |
| `trend_for([kgs], ...)` | The stored weight signal for those readings |
| `score_with(trend, pet=None, **checkin_kw)` | A full pipeline run with a weight trend attached |
| `_weekly(pet_id, {week: kg}, n)` | *(Section 17)* `n` weekly check-ins; weeks absent from the dict carry no weight |
| `_at(weeks, **kw)` | *(Section 17)* A check-in `weeks` after `LAST_WEIGH_IN`, for ageing a trend |

A typical test reads as one sentence of setup and one of assertion:

```python
def test_rapid_gain_is_advisory_only():
    trend = trend_for([30.0, 33.0])
    r = score_with(trend)
    assert r.override.severity_tier == "monitor"
    assert r.score is not None          # a monitor flag never hides the score
```

---

## Things that will bite you

**Weight loss plus appetite loss is a red flag, not a low score.** If you write a weight test and get `score is None`, that is usually why — `weight_loss_with_signs` fired and the safety net withheld the number. Use a *sleep* or *activity* drop as your second indicator when you want to test the score math rather than the escalation.

**Readings jumping more than 25% are rejected before anything else runs.** A test using 10 kg → 13 kg to represent puppy growth is testing the typo screen, not growth. Keep synthetic changes inside the limit.

**`previous_checkins` omitted is not the same as empty.** Omitting it gives you a synthetic baseline of four; an empty list gives you a Building Baseline result.

**Both weight paths are live.** A `weight_log` in the JSON wins; without one, the engine derives the trend from `weight_kg` on the check-ins. Several older `Weight_*.json` fixtures carry both, and they agree, but nothing enforces that — if you edit one, edit the other.

**The fourth check-in unlocks the score.** `previous + current = 4`. Three previous check-ins gives a score; two does not.

---

## Checking a test actually bites

A test that passes is not evidence until you have seen it fail. Before trusting a new one, break the thing it covers and confirm it catches it:

```bash
# Temporarily revert the behaviour in phavit/, then:
python -m pytest test_case/test_phavit.py -q
```

Done against the current suite, this is what each mutation catches:

| Break | Tests that fail |
| --- | --- |
| `declining_strength()` back to a boolean cut-off | 2 |
| The stale-weight prompt removed | 1 |
| The pipeline stops deriving weight from check-ins | 3 |

**Revert with your editor's undo or a copy of the file, not `git checkout <file>`** — that restores the last *commit*, which will silently discard any uncommitted work in that file alongside your mutation.
