reada# PawHealthAI - Vitality Score Engine v0.2

**Technical report for veterinary and engineering review**
Status: *Provisional - not clinically validated*
Owner: Minh · Reviewer: PawHealthAI Product & Engineering Lead

---

## 1. Purpose

Upgrade the early notebook prototype into a **validation-ready, rules-based scoring
engine and test harness** built on synthetic data. The priority for v0.2 is **safety,
explainability and testability** - not machine learning and not clinical accuracy.

The engine produces a 0-100 wellness *trend* score plus a separate acute-safety pathway.
It is explicitly **non-diagnostic**: it never names a disease and never tells a user
their pet is healthy or sick.

## 2. Deliverables

| File | Description |
|------|-------------|
| `phavit/` | Importable engine package: `models`, `red_flags`, `scoring`, `pipeline`, `__init__` (see §3). |
| `test_case/test_phavit.py` | Product-state & safety test suite (pytest or standalone). |
| `test_case/*.json` | Five check-in fixtures: `At_good_condition`, `At_risk_condition`, `Digestion_problem`, `Less_good_condition`, `Not_enough_data`. |
| `conftest.py` | Puts the repo root on `sys.path` so the tests resolve `phavit` under pytest. |
| `data_pipeline_vitality_score_v2.ipynb` | Runnable notebook: engine walkthrough plus the fixture loader. |
| `PawHealthAI_Vitality_Score.md` | Product-level overview of the Vitality Score. |
| `vitality_score_engine_v0_2_report.md` / `.docx` | This report (Markdown source and exported Word copy). |

*Legacy prototypes `vitality_score_engine.py` and `red_engine.py` predate v0.2 and are
superseded by the `phavit/` package; they remain in the repo for reference only.*

## 3. Architecture

The engine now ships as an importable package rather than notebook-only code, so it
can be called from the weekly check-in flow, unit-tested and later persisted:

- `phavit/models.py` - typed dataclasses (`PetProfile`, `CheckInData`, `BaselineSummary`, `RedFlagResult`, `VitalityScoreResult`).
- `phavit/red_flags.py` - Layer 2 safety net (`RedFlagEngine`, `EMERGENCY_SIGNS`).
- `phavit/scoring.py` - Layer 1 wellbeing math (`VitalityScoreEngine`).
- `phavit/pipeline.py` - orchestration entry point (`process_checkin`).

The engine runs in two clearly separated layers, orchestrated by `process_checkin()`:

```
check-in ─▶ Layer 2: RedFlagEngine (safety net, runs FIRST)
                 │
     emergency / urgent ──▶ safety pathway, score withheld
                 │
              monitor ──▶ attached as advisory, score still shown
                 │
              none ──▶ Layer 1: VitalityScoreEngine (0-100 baseline math)
```

### Layer 1 - Wellbeing score (baseline comparison)

- Computes the pet's **own recent baseline** (mean appetite, energy, sleep, activity)
  from history via `BaselineSummary`.
- Scores **negative deviations** from that baseline, not fixed deductions. Only drops
  reduce the score.
- **Breed-aware weighting**: high-energy breeds (e.g. Vizsla, Border Collie) weight
  activity more heavily (0.45 vs 0.20).
- **Signal vs noise**: a single one-day dip is treated as noise; **multiple indicators
  declining together** add an extra penalty.
- **Honest uncertainty**: with fewer than 4 recent check-ins the engine returns a
  `Building Baseline` state with low confidence rather than a fabricated score.
- **Fourth-check-in unlock**: the total counts the *current* completed check-in, so
  the first score appears at 4 total (3 previous + current), not the 5th event.
  `process_checkin(pet, previous_checkins, current_checkin)` takes the two apart to
  keep that boundary unambiguous.

**The equation.** With baseline means $\bar A,\bar E,\bar S,\bar M$ (appetite, energy,
sleep, activity) over the last $n \ge 4$ check-ins, take **downward deviations only**:

$$\Delta a=\max(0,\bar A-a),\quad \Delta e=\max(0,\bar E-e),\quad \Delta s=\max(0,\bar S-s),\quad \Delta m=\max\!\Big(0,\tfrac{\bar M-m}{\bar M}\Big)$$

($\Delta a,\Delta e,\Delta s$ are 1–5 point drops; $\Delta m$ is a fraction in $[0,1]$.)
Apply breed-aware weights (each set sums to 1) and the tuning constant $D = 60$:

$$(w_a,w_e,w_s,w_m)=\begin{cases}(0.30,0.30,0.20,0.20)&\text{normal breed}\\(0.20,0.25,0.10,0.45)&\text{high-energy breed}\end{cases}$$

$$S_1 = 100 - D\,\big(w_a\Delta a + w_e\Delta e + w_s\Delta s + w_m\Delta m\big)$$

Add the multi-decline penalty, where $k$ counts indicators that dropped meaningfully
($\Delta a\ge1,\ \Delta e\ge1,\ \Delta s\ge1,\ \Delta m\ge0.25$), then the care nudge:

$$S_2 = S_1 - 12\cdot\mathbb{1}[k\ge2], \qquad S_3 = S_2 - 8\cdot\mathbb{1}[\text{not worming\_compliant}]$$

$$\text{score} = \max\!\big(0,\ \min(100,\ \operatorname{round}(S_3))\big)$$

Bands (provisional): Bright Green ≥85 · Medium Green ≥70 · Watch ≥50 · Action Needed <50.

### Layer 2 - Red-flag override (three tiers)

| Tier | Example triggers | Output |
|------|------------------|--------|
| **Emergency** | collapse, breathing difficulty, seizure, severe bleeding, suspected toxin ingestion, inability to urinate | Emergency guidance pathway; **no reassuring score**. |
| **Urgent** | blood in stool (esp. with lethargy), repeated vomiting, persistent appetite loss, increased thirst over repeated check-ins, signs of pain | Action Needed / urgent vet review pathway. |
| **Monitor** | single vomiting/diarrhoea, tick found, mild single-day dips | Watch/monitor band with a safe explanation; score still shown. |

Red flags sit **outside** the 0-100 math. Acute signs trigger a safety pathway rather
than merely lowering a number, so a serious sign can never be averaged away by otherwise
good vitals.

### Removal of diagnostic outputs

The prototype's `potential_diseases` field is **deleted**. Escalations now carry only
safe, internal fields: `trigger`, `severity_tier`, `clinical_reason_for_escalation`,
`recommended_user_pathway`, `vet_validation_required`. A guard test in the notebook
asserts no disease term ever appears in a user-facing explanation.

## 4. Explanation layer

Every output includes a plain-English, non-diagnostic explanation, e.g.:

> "Rex's score is lower this week mainly because energy below usual, activity below usual
> compared with their usual baseline. This is a wellbeing trend, not a diagnosis. If it
> continues or worsens, veterinary advice should be considered."

> "Increased thirst may require veterinary review, especially if it persists or appears
> with changes in appetite, weight, urination, or energy."

## 5. Test harness & results

**Scenario harness (notebook).** 11 named scenarios (stable adult dog, high-energy
reduced activity, senior gradual decline, puppy variable sleep/activity, cat appetite
drop, blood in stool, repeated increased thirst, persistent low appetite + lethargy,
emergency collapse, inconsistent low-confidence history, single vomiting). For each,
expected band and override tier are declared **before** running the engine. Current
result: **11/11 scenarios match expectation.**

**Product-state suite (`test_case/test_phavit.py`).** A pytest suite that asserts the
eight product states from the actionable plan, so regressions fail loudly. It runs
under pytest (`python -m pytest test_case/test_phavit.py`) or standalone
(`python test_case/test_phavit.py`, no pytest required). Current result: **11/11 pass.**
Coverage:

| # | State asserted |
|---|----------------|
| 1 | Building Baseline while fewer than four total check-ins |
| 2 | First score unlocks on the fourth check-in (and not the third) |
| 3 | Stable check-in scores Bright/Medium Green |
| 4 | Multiple declining indicators drop the band to Watch/Action Needed |
| 5 | Emergency sign (collapse, suspected toxin) suppresses the score |
| 6 | Urgent sign (blood in stool + low energy) suppresses the score |
| 7 | Monitor sign (single vomiting) keeps the score and attaches an advisory |
| 8 | High-energy breed weighting amplifies an activity drop |

Two further guards run alongside: missing optional fields fall back safely, the
typo-tolerant loaders read the real fixtures, and **no disease name** appears in any
user-facing explanation across every scenario and fixture.

## 6. Assumptions

- Wellbeing inputs are self-reported on a 1-5 scale and treated as comparable over time.
- Four or more recent check-ins are enough to estimate a "normal" baseline.
- Weights, the 60-point deviation constant, band cut-offs and the look-back window
  (3 check-ins for "repeated" patterns) are **engineering placeholders**.
- Owner concern level and check-in consistency are engagement signals and are **not**
  treated as direct health evidence.

## 7. Limitations

- **Not clinically validated.** No threshold has veterinary sign-off.
- Synthetic data only; no real-world distribution, noise or sensor error is modelled.
- No age/species-specific baselines beyond the high-energy breed flag.
- Single-channel: it cannot detect anything the owner does not report.
- The 1-5 self-report scale is coarse and subjective between owners.

## 8. Open questions for veterinary review

### 8.1 General

1. Are the three escalation tiers and their trigger lists clinically appropriate and complete?
2. Is "≥4 check-ins" a sensible minimum baseline, or should it vary by life stage?
3. Are the band cut-offs (85/70/50) reasonable starting points?
4. Should any "monitor" item (e.g. tick found, single vomiting) be escalated to urgent?
5. Is the look-back window for "repeated" signs (thirst, vomiting, appetite loss) right?
6. Is the non-diagnostic explanation wording safe and clear enough for owners?

### 8.2 The weighting mechanic (focus of this review)

The score starts at 100 and only ever subtracts for **downward** deviations from the
pet's own baseline. Two things decide how much a given change costs: the **weight** of
that indicator (its relative importance) and the shared **deviation constant** `D = 60`
(how many points a full deviation can remove). The weights within each breed profile
sum to 1.0, so the profiles are directly comparable.

**Current weights (provisional placeholders):**

| Indicator | Normal breed | High-energy breed |
|-----------|:------------:|:-----------------:|
| Appetite  | 0.30 | 0.20 |
| Energy    | 0.30 | 0.25 |
| Sleep     | 0.20 | 0.10 |
| Activity  | 0.20 | 0.45 |

Because the abstract weights are hard to judge clinically, here is what they mean in
**practice** — points removed from the 0-100 score, so the relative severity is visible
without doing the maths. Appetite/energy/sleep are 1-5 scales; activity is compared as a
percentage of the baseline minutes.

| Change | Normal breed | High-energy breed |
|--------|:------------:|:-----------------:|
| Appetite down 1 point (e.g. 4→3) | −18 | −12 |
| Energy down 1 point | −18 | −15 |
| Sleep quality down 1 point | −12 | −6 |
| Activity down 50% vs baseline | −6 | −13.5 |
| Activity down 100% vs baseline | −12 | −27 |
| **Two or more indicators down together** | −12 flat | −12 flat |
| Worming treatment overdue | −8 | −8 |

So, for a normal-breed pet, a single one-point appetite dip lands the score at 82
(Medium Green); appetite **and** energy both dropping a point lands it at 100−18−18−12 =
52 (bottom of Watch). For a high-energy breed the same two-point wellbeing drop is
softened, but a halving of activity is penalised far more heavily.

**Questions for the reviewing vet:**

1. **Relative ordering.** For a typical adult dog, is *appetite ≈ energy > sleep ≈
   activity* the right priority? Should appetite outrank energy (or vice-versa) rather
   than being equal?
2. **Breed-aware activity.** Is weighting activity 0.45 (vs 0.20) for high-energy breeds
   clinically justified, and *which* breeds should qualify? Should this be driven by
   breed, by life stage, or by an owner-declared activity norm instead of a single flag?
3. **Magnitude / `D = 60`.** A one-point appetite drop removing ~18 of 100 points — is
   that clinically proportionate, too harsh, or too soft? Where should a *single*
   indicator drop leave a pet: Medium Green or Watch?
4. **Signal vs noise.** Is a flat −12 when ≥2 indicators fall together the right way to
   model a genuine "signal," and is 2 the correct trigger count? Should some pairings
   (appetite + energy) weigh more than others (sleep + activity)?
5. **Species profile.** Cats currently use the normal-breed profile. Should cats have
   their own weighting (sleep is naturally high and variable, activity is harder for
   owners to observe)?
6. **Life stage.** Should puppies (variable sleep) and seniors (expected gradual activity
   decline) use different weights rather than the two breed profiles alone?
7. **Sensitivity thresholds.** A change only counts as a "drop" at ≥1 point (1-5 scale)
   or ≥25% for activity. Are those the right thresholds, or should smaller changes count?
8. **Care-compliance nudge.** Folding an overdue-worming penalty (−8) into a *wellbeing*
   score — is that appropriate, or should care compliance be surfaced separately and kept
   out of the health trend entirely?

## 9. Out of scope

Machine learning, real user data, production app screens, changes to live PawHealthAI
behaviour, and final clinical rules - all out of scope until veterinary review is complete.

---

*Every rule and threshold in v0.2 is provisional and flagged for veterinary review rather
than treated as final.*
