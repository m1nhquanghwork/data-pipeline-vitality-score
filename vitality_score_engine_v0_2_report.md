PawHealthAI - Vitality Score Engine v0.2

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
| `phavit/` | Importable engine package: `models`, `weight`, `red_flags`, `scoring`, `pipeline`, `__init__` (see §3). |
| `test_case/test_phavit.py` | Product-state, weight and safety test suite (pytest or standalone). **92 tests.** |
| `test_case/*.json` | **30 check-in fixtures**, each declaring its own expected band, tier and weight outcome. Ten are weight scenarios (`Weight_*.json`). |
| `test_case/README.md` | How to run the suite and how to add to it, for engineers and reviewers. |
| `conftest.py` / `test_case/conftest.py` | Put the repo root on `sys.path` so the tests resolve `phavit` from either directory. |
| `data_pipeline_vitality_score_v2.ipynb` | Runnable walkthrough of all three layers and the weight subsystem, ending with the fixture harness. **Imports `phavit/` rather than redefining the engine**, so it cannot drift out of step with the code under test. |
| `PawHealthAI_Vitality_Score.md` | Product-level overview of the Vitality Score. |
| `vitality_score_engine_v0_2_report.md` / `.docx` | This report (Markdown source and exported Word copy). |

*Legacy prototype `red_engine.py` predates v0.2 and is superseded by the `phavit/`
package; it remains in the repo for reference only.*

## 3. Architecture

The engine ships as an importable package rather than notebook-only code, so it
can be called from the weekly check-in flow, unit-tested and later persisted:

- `phavit/models.py` - typed dataclasses (`PetProfile`, `CheckInData`, `BaselineSummary`, `WeightReading`, `WeightTrendResult`, `RedFlagResult`, `VitalityScoreResult`).
- `phavit/weight.py` - the weight subsystem: validation, trend maths, the breed reference table, and the helpers both other layers read.
- `phavit/red_flags.py` - Layer 2 safety net (`RedFlagEngine`, `EMERGENCY_SIGNS`).
- `phavit/scoring.py` - Layer 1 wellbeing math (`VitalityScoreEngine`).
- `phavit/pipeline.py` - orchestration entry point (`process_checkin`).

The engine runs in two clearly separated decision layers, orchestrated by
`process_checkin()`, with the weight subsystem feeding **both** of them:

```
weight readings ─▶ weight.py ─▶ WeightTrendResult ─┐
  (monthly cadence)                                │ (carried forward each week)
                                                   ▼
check-in ─────────────────▶ Layer 2: RedFlagEngine (safety net, runs FIRST)
                                 │
     emergency / urgent ──▶ safety pathway, score withheld
                                 │
              monitor ──▶ attached as advisory, score still shown
                                 │
              none ──▶ Layer 1: VitalityScoreEngine (0-100 baseline math)
                                 │
                                 ▼
                       Layer 3: plain-English explanation (§4)
```

`weight.py` imports only from `models`. It knows nothing about scoring or red flags;
both of those consume its result. That keeps one definition of "what counts as a
weight loss" instead of two that can drift apart.

### The weight subsystem

Weight runs on a **different clock** from the rest of the check-in. Owners weigh a pet
roughly monthly, while wellbeing is reported weekly, so the engine cannot simply treat a
weight like another 1-5 score. Three rules keep a monthly signal from distorting a weekly
number:

- **Carry-forward.** The stored trend - not the raw reading - is applied to every
  check-in until the next weigh-in. The score is therefore steady between readings,
  instead of dropping on whichever week a weight happened to be entered.
- **Staleness decay.** The weight's effect holds at full strength for 8 weeks, then fades
  linearly to nothing at 12 weeks. An old loss cannot penalise a pet forever.
- **Rate normalisation.** Everything is expressed as *percent of body weight lost per
  4 weeks*, so readings taken at irregular intervals are comparable. A 3% drop over one
  week and a 3% drop over two months are very different events, and this is what tells
  them apart.

Weights reach the engine by either of two paths. If the product stores a weight log, the
trend is computed once at weigh-in and passed into `process_checkin()`. If it does not,
the engine derives the trend from the optional `weight_kg` field on the check-ins
themselves. **A pet with no recorded weight produces no trend, and the engine then
behaves exactly as it did before weight existed** - this is asserted directly by the test
suite, because backwards compatibility here is a safety property, not a nicety.

Before any maths runs, readings are screened. Values outside species plausibility bounds
(dog 0.5-120 kg, cat 0.5-15 kg) are dropped, and a jump of more than 25% between
consecutive readings is rejected as a data-entry error - a mistyped 4.0 for 40.0 must
never reach the escalation rules. If it is the *most recent* reading that fails, the
engine says so and asks the owner to re-check it, rather than quietly scoring an older
weight. The comparison baseline is the **median** of up to four previous readings, not
the mean, so one bad entry cannot drag it.

Two things are deliberately suppressed. A pet still **growing** (younger than its breed's
adult age) has its gain rules switched off entirely, and its loss thresholds tightened,
because a growing animal losing weight matters more. A pet on a recorded
**weight-management plan** is not penalised for losing weight at a safe rate - up to
8%/4 weeks for a dog, 4% for a cat. Loss faster than that escalates regardless of the plan.

### Layer 1 - Wellbeing score (baseline comparison)

- Computes the pet's **own recent baseline** (mean appetite, energy, sleep, activity)
  from history via `BaselineSummary`.
- Scores **negative deviations** from that baseline, not fixed deductions. Only drops
  reduce the score.
- **Breed-aware weighting**: high-energy breeds (e.g. Vizsla, Border Collie) weight
  activity more heavily (0.45 vs 0.20).
- **Body-aware weighting**: where a pet sits against its breed weight reference shifts
  emphasis between indicators. See "Weighting profiles" below.
- **Weight loss deducts points directly**, on a ramp, and fades as the reading ages.
- **Signal vs noise**: a single one-day dip is treated as noise; **multiple indicators
  declining together** add an extra penalty, and weight counts towards that tally.
- **Honest uncertainty**: with fewer than 4 recent check-ins the engine returns a
  `Building Baseline` state with low confidence rather than a fabricated score. A weight
  signal that is stale or unreliable also caps the reported confidence at *moderate*.
- **Fourth-check-in unlock**: the total counts the *current* completed check-in, so
  the first score appears at 4 total (3 previous + current), not the 5th event.
  `process_checkin(pet, previous_checkins, current_checkin)` takes the two apart to
  keep that boundary unambiguous.

#### How the score is worked out

Every pet starts each week on **100** and only ever loses points. Nothing a pet does can
push the score above 100 - a pet who is unusually lively this week simply stays at 100.
The comparison is always against **that pet's own recent normal**, never against other
pets.

1. **Work out what normal looks like.** Average the pet's last few check-ins to get their
   usual appetite, energy, sleep and activity.
2. **Measure only the drops.** Compare this week against that normal. If appetite went
   *up*, it counts as zero, not as a bonus. Appetite, energy and sleep are measured in
   points on the 1-5 scale; activity is measured as a *percentage* of usual minutes,
   because "30 minutes less" means something very different for a pet who usually does 40
   minutes than for one who does 120.
3. **Decide how much each drop matters.** Each indicator has a weight - its share of
   importance. The four weights always add up to 1.0, so they split a single fixed budget
   between them.
4. **Convert drops into points lost.** Multiply each weighted drop by 60, the constant
   that sets how harsh the engine is overall. A one-point appetite drop for a normal-breed
   dog costs 0.30 × 60 = **18 points**.
5. **Subtract for weight loss.** If a recent weigh-in shows the pet losing body weight,
   subtract points on a sliding scale: nothing below 2% per 4 weeks, rising steadily to a
   maximum of 15 points at 10% per 4 weeks. Past 10% the safety net takes over instead, so
   the deduction stops growing.
6. **Add a penalty when several things slip at once.** One indicator dipping is usually
   noise. Two or more at the same time is a pattern, and costs a further 12 points.
   Weight counts as one of those indicators - but a *fractional* one, contributing less as
   the weigh-in ages, so a fading signal tapers off instead of vanishing overnight.
7. **Apply the care nudge.** Overdue worming removes a further 8 points.

Round the result and clamp it to the 0-100 range. Bands (provisional):
**Bright Green ≥85 · Medium Green ≥70 · Watch ≥50 · Action Needed <50.**

**Worked example - Scout, a normal-breed Labrador.** Usual scores 4/4/4 and 60 minutes of
activity. This week: appetite 3, energy 3, sleep 4, activity 60 minutes, and a weigh-in
three weeks ago showing 6% body weight lost per 4 weeks.

| Step | What happened | Points | Running total |
|------|---------------|:------:|:-------------:|
| Start | | | **100** |
| Appetite | down 1 point (4→3), weight 0.30 | −18 | 82 |
| Energy | down 1 point (4→3), weight 0.30 | −18 | 64 |
| Sleep | unchanged | 0 | 64 |
| Activity | unchanged | 0 | 64 |
| Body weight | 6%/4wk loss, fresh reading | −7.5 | 56.5 |
| Several together | appetite + energy + weight all declining | −12 | 44.5 |
| Worming | up to date | 0 | 44.5 |
| **Final** | rounds to **44** - *Action Needed* | | **44** |

Scout's individual signs are each mild, but three of them moved the same way at once, and
that is what drops him two bands. This is the behaviour the engine is designed to produce:
no single reading is alarming, the combination is.

*(A note on that last step: 44.5 rounds to 44, not 45. Python rounds a value sitting
exactly halfway to the nearest **even** number, so scores landing on a .5 boundary go down
as often as up rather than always up. It is worth knowing when hand-checking a score, but
it can only ever move the result by a single point.)*

#### Weighting profiles

The base profile comes from the breed's energy level. Where the pet sits against its
**breed weight reference** then shifts the emphasis, after which the weights are
**renormalised back to a sum of 1.0**.

That renormalisation is load-bearing. Adding weight to activity without rescaling would
push the total above 1.0, which makes the score uniformly harsher rather than simply
re-prioritising activity - a different, and worse, behaviour. A test asserts every profile
sums to 1.0.

| Profile | Appetite | Energy | Sleep | Activity | Activity "drop" starts at |
|---------|:--------:|:------:|:-----:|:--------:|:-------------------------:|
| Standard | 0.300 | 0.300 | 0.200 | 0.200 | 25% |
| Standard, above reference | 0.286 | 0.286 | 0.190 | 0.238 | 20% |
| Standard, well above reference | 0.273 | 0.273 | 0.182 | 0.273 | 20% |
| Standard, below reference | 0.364 | 0.273 | 0.182 | 0.182 | 25% |
| High-energy | 0.200 | 0.250 | 0.100 | 0.450 | 25% |
| High-energy, above reference | 0.190 | 0.238 | 0.095 | 0.476 | 20% |
| High-energy, well above reference | 0.182 | 0.227 | 0.091 | 0.500 | 20% |
| High-energy, below reference | 0.273 | 0.227 | 0.091 | 0.409 | 25% |

The reasoning: for a pet carrying extra weight, sustained low activity is both more
consequential and the lever an owner can actually pull, so activity is weighted up and the
bar for calling it a "drop" is lowered from 25% to 20%. For a pet *below* their reference
the lever is intake rather than exercise, so appetite is weighted up instead. Neither is a
deduction in itself - being heavy or light never costs points directly, it only changes
which changes matter most. Breeds not in the reference table, and all crossbreeds, return
`no_reference` and use the unmodified base profile.

#### Formal notation

With baseline means $\bar A,\bar E,\bar S,\bar M$ (appetite, energy, sleep, activity)
over the last $n \ge 4$ check-ins, take **downward deviations only**:

$$\Delta a=\max(0,\bar A-a),\quad \Delta e=\max(0,\bar E-e),\quad \Delta s=\max(0,\bar S-s),\quad \Delta m=\max\!\Big(0,\tfrac{\bar M-m}{\bar M}\Big)$$

($\Delta a,\Delta e,\Delta s$ are 1–5 point drops; $\Delta m$ is a fraction in $[0,1]$.)
Take the base weights by breed energy level, apply the body-status bumps
$\beta_a,\beta_m$, and renormalise so the four sum to 1:

$$(w_a^0,w_e^0,w_s^0,w_m^0)=\begin{cases}(0.30,0.30,0.20,0.20)&\text{standard}\\(0.20,0.25,0.10,0.45)&\text{high-energy}\end{cases}$$

$$\beta_m=\begin{cases}0.05&\text{above reference}\\0.10&\text{well above reference}\\0&\text{otherwise}\end{cases}\qquad \beta_a=\begin{cases}0.10&\text{below reference}\\0&\text{otherwise}\end{cases}$$

$$w_i=\frac{w_i^0+\beta_i}{\textstyle\sum_j (w_j^0+\beta_j)},\qquad \theta=\begin{cases}0.20&\beta_m>0\\0.25&\text{otherwise}\end{cases}$$

Let $r$ be the weight trend's rate in % of body weight lost per 4 weeks, and $\varphi$ the
staleness factor at check-in date $t$, where $u$ is the age of the reading in weeks:

$$\varphi(t)=\begin{cases}1&u\le 8\\[4pt] \dfrac{12-u}{4}&8<u<12\\[4pt] 0&u\ge 12\end{cases}$$

The weight deduction $P_w$ and the fractional declining-strength $\sigma$ are both zero
unless the trend is usable, downward and unmanaged:

$$P_w=\min\!\Big(1,\tfrac{r-2}{8}\Big)\cdot 15\cdot\varphi(t)\ \ \text{for } r>2, \qquad \sigma=\varphi(t)\ \ \text{for } r\ge 5$$

With the deviation constant $D = 60$:

$$S_1 = 100 - D\,\big(w_a\Delta a + w_e\Delta e + w_s\Delta s + w_m\Delta m\big) - P_w$$

Let $k$ be the declining tally - the boolean indicators plus weight's fractional
contribution - then the care nudge:

$$k = \mathbb{1}[\Delta a\ge1]+\mathbb{1}[\Delta e\ge1]+\mathbb{1}[\Delta s\ge1]+\mathbb{1}[\Delta m\ge\theta]+\sigma$$

$$S_2 = S_1 - 12\cdot\min\!\big(1,\max(0,\,k-1)\big), \qquad S_3 = S_2 - 8\cdot\mathbb{1}[\text{not worming\_compliant}]$$

$$\text{score} = \max\!\big(0,\ \min(100,\ \operatorname{round}(S_3))\big)$$

Note the two different weight thresholds. A loss deducts points from 2%/4wk upward
($P_w$), but only counts towards the compound tally from 5% ($\sigma$). Small losses
should cost a little; only a *notable* loss should mark weight as one of several
indicators declining together.

### Layer 2 - Red-flag override (three tiers)

| Tier | Example triggers | Output |
|------|------------------|--------|
| **Emergency** | collapse, breathing difficulty, seizure, severe bleeding, suspected toxin ingestion, inability to urinate | Emergency guidance pathway; **no reassuring score**. |
| **Urgent** | blood in stool (esp. with lethargy), **notable weight loss**, **weight loss alongside reduced appetite, increased thirst or low energy**, repeated vomiting, persistent appetite loss, increased thirst over repeated check-ins, signs of pain | Action Needed / urgent vet review pathway. |
| **Monitor** | single vomiting/diarrhoea, tick found, **rapid weight gain**, mild single-day dips | Watch/monitor band with a safe explanation; score still shown. |

The three weight rules in detail:

| Trigger | Tier | Fires when | Notes |
|---------|------|------------|-------|
| `notable_weight_loss` | urgent | unmanaged loss ≥10%/4wk (≥7% while growing), reading not fully stale | Tier decided at weigh-in; freshness re-checked each week so a long-stale reading cannot keep firing |
| `weight_loss_with_signs` | urgent | loss ≥5%/4wk **plus** appetite ≤2, increased thirst, or energy ≤2 on this check-in | Each companion sign needs *repetition* to escalate alone, so a first occurrence next to real weight loss would otherwise slip through |
| `rapid_weight_gain` | monitor | gain ≥8%/4wk in an adult | Advisory only, never a score deduction. Suppressed entirely while the pet is growing |

Red flags sit **outside** the 0-100 math. Acute signs trigger a safety pathway rather
than merely lowering a number, so a serious sign can never be averaged away by otherwise
good vitals. Note the ordering consequence: red flags run *before* the baseline gate, so a
pet with too little history for a score can still be escalated rather than told to keep
waiting.

### Removal of diagnostic outputs

The prototype's `potential_diseases` field is **deleted**. Escalations now carry only
safe, internal fields: `trigger`, `severity_tier`, `clinical_reason_for_escalation`,
`recommended_user_pathway`, `vet_validation_required`. A guard test asserts no disease
term ever appears in a user-facing explanation, across every scenario and fixture.

The weight subsystem's internal `notes` - which readings were rejected and why - are
carried for support and debugging and are **never** rendered into owner copy.

## 4. Explanation layer

Every output includes a plain-English, non-diagnostic explanation, e.g.:

> "Rex's score is lower this week mainly because energy below usual, activity below usual
> compared with their usual baseline. This is a wellbeing trend, not a diagnosis. If it
> continues or worsens, veterinary advice should be considered."

> "Increased thirst may require veterinary review, especially if it persists or appears
> with changes in appetite, weight, urination, or energy."

Because weight is recorded monthly, any mention of it **carries the date of the reading**,
so the copy can never imply it was measured this week:

> "The weight comparison uses the reading recorded on 18 Jul 2026."

Two further sentences describe the *recording* rather than the pet, and are kept out of
the "compared with their usual baseline" wording for that reason:

> "The most recent weight entry looks unusual, so it has not been used here - please check
> it and re-enter it if it was a typo."

> "The last recorded weight is from 18 Jul 2026, so it is counting for less here - a fresh
> weigh-in would keep this accurate."

The stale prompt matters more than it first appears. As an old weight signal decays, the
score quietly **rises**. Without the prompt an owner sees an improving number with no way
to know it reflects an expiring reading rather than a recovering pet.

## 5. Test harness & results

**Scenario fixtures.** **30 JSON scenarios**, each declaring its expected band, override
tier and weight outcome **before** the engine runs. They are globbed automatically, so a
new file needs no registration. Every one is asserted to load, run, stay non-diagnostic
and match its own declared expectation. Current result: **30/30 match.**

**Test suite (`test_case/test_phavit.py`).** Runs under pytest
(`python -m pytest test_case/test_phavit.py`) or standalone
(`python test_case/test_phavit.py`, no pytest required), exiting non-zero on failure.
Current result: **92/92 pass in 0.15s.**

| Section | Tests | Covers |
|---|:---:|---|
| 1-8 | 12 | The eight product states: baseline building, fourth-check-in unlock, green bands, declining indicators, emergency and monitor overrides, breed weighting, malformed input |
| *(fixture-wide)* | 2 | Every JSON loads, runs, stays non-diagnostic, matches its expectation |
| 9-14 | 22 | Weight: inert without data, trend maths, data quality, monthly cadence, escalations and suppressions, profiles staying normalised |
| 15 | 20 | System analysis - boundaries, determinism, invariants |
| 16 | 18 | Core engine coverage outside weight |
| 17 | 20 | Weight arriving on the check-in stream, and the data-quality prompts |

The eight original product states remain individually asserted:

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

Guards running alongside: missing optional fields fall back safely, the typo-tolerant
loaders read the real fixtures, weighting profiles always sum to 1.0, a pet with no weight
data scores identically to the pre-weight engine, and **no disease name** appears in any
user-facing explanation.

**Dates are fixed, never `today`.** Weight staleness is time-dependent, so the tests anchor
to constants rather than the current date. Without that the suite would start failing on
its own months later.

**Tests are checked for bite.** A passing test is not evidence until it has been seen to
fail. Deliberately breaking each weight behaviour confirms the suite catches it: reverting
the fractional declining-strength to a boolean fails 2 tests, removing the stale-weight
prompt fails 1, and stopping the pipeline deriving weight from check-ins fails 3.

## 6. Assumptions

- Wellbeing inputs are self-reported on a 1-5 scale and treated as comparable over time.
- Four or more recent check-ins are enough to estimate a "normal" baseline.
- Body weight is recorded roughly **monthly** and is meaningful for up to 8 weeks, fading
  to nothing at 12. Owner scales are consistent enough that changes above 2% per 4 weeks
  are real rather than noise.
- The breed reference table stands in for a body condition score. Where a BCS exists it
  should supersede the table entirely.
- Weights, the 60-point deviation constant, the weight thresholds (2 / 5 / 8 / 10%), the
  15-point weight cap, band cut-offs and the look-back window (3 check-ins for "repeated"
  patterns) are **engineering placeholders**.
- Owner concern level and check-in consistency are engagement signals and are **not**
  treated as direct health evidence.

## 7. Limitations

- **Not clinically validated.** No threshold has veterinary sign-off.
- Synthetic data only; no real-world distribution, noise or sensor error is modelled.
- **Growth is gated by a crude age cut-off per breed**, not by a real growth curve, so a
  pet just past that cut-off is treated as fully adult overnight.
- **No body condition score.** Body status is inferred from a breed weight range, which
  reads frame rather than condition - a muscular dog and an overweight dog of the same
  weight are indistinguishable to the engine.
- **The breed table covers 19 breeds.** Every other breed, and every crossbreed, returns
  `no_reference` and loses the body-aware weighting entirely.
- Beyond the breed weight reference and the high-energy flag, there are no
  age-specific baselines: a senior pet's expected gradual decline is not modelled.
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
(how many points a full deviation can remove). The weights within each profile sum to 1.0,
so the profiles are directly comparable.

Because the abstract weights are hard to judge clinically, here is what they mean in
**practice** - points removed from the 0-100 score, so the relative severity is visible
without doing the maths. Appetite/energy/sleep are 1-5 scales; activity is compared as a
percentage of the baseline minutes.

| Change | Standard breed | High-energy breed |
|--------|:--------------:|:-----------------:|
| Appetite down 1 point (e.g. 4→3) | −18 | −12 |
| Energy down 1 point | −18 | −15 |
| Sleep quality down 1 point | −12 | −6 |
| Activity down 50% vs baseline | −6 | −13.5 |
| Activity down 100% vs baseline | −12 | −27 |
| **Two or more indicators down together** | −12 flat | −12 flat |
| Worming treatment overdue | −8 | −8 |

And the same view for **body weight**, which does not depend on the breed profile:

| Weight loss (% per 4 weeks) | Points removed | Counts towards "several declining"? |
|---|:---:|:---:|
| 2% or less | 0 | no |
| 3% | −1.88 | no |
| 4% | −3.75 | no |
| 5% | −5.63 | **yes** |
| 6% | −7.50 | yes |
| 8% | −11.25 | yes |
| 10% or more | −15.00 (capped) | yes - *and* triggers an urgent red flag |

Weight **gain** never removes points at any size; the strongest response it can produce is
a monitor-tier advisory. Deliberate loss under a recorded management plan removes no points
at all, up to 8%/4wk for dogs and 4% for cats.

Ageing of the signal, for a 10%/4wk loss:

| Weeks since the weigh-in | Points removed | Compound contribution |
|---|:---:|:---:|
| 0-8 | −15.00 | 1.00 |
| 9 | −11.25 | 0.75 |
| 10 | −7.50 | 0.50 |
| 11 | −3.75 | 0.25 |
| 12+ | 0 | 0.00 |

So, for a standard-breed pet, a single one-point appetite dip lands the score at 82
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
3. **Magnitude / `D = 60`.** A one-point appetite drop removing ~18 of 100 points - is
   that clinically proportionate, too harsh, or too soft? Where should a *single*
   indicator drop leave a pet: Medium Green or Watch?
4. **Signal vs noise.** Is a flat −12 when ≥2 indicators fall together the right way to
   model a genuine "signal," and is 2 the correct trigger count? Should some pairings
   (appetite + energy) weigh more than others (sleep + activity)?
5. **Species profile.** Cats currently use the standard profile. Should cats have their
   own weighting (sleep is naturally high and variable, activity is harder for owners to
   observe)?
6. **Life stage.** Should puppies (variable sleep) and seniors (expected gradual activity
   decline) use different weights rather than the two breed profiles alone?
7. **Sensitivity thresholds.** A change only counts as a "drop" at ≥1 point (1-5 scale)
   or ≥25% for activity (≥20% for a pet above their weight reference). Are those the right
   thresholds, or should smaller changes count?
8. **Care-compliance nudge.** Folding an overdue-worming penalty (−8) into a *wellbeing*
   score - is that appropriate, or should care compliance be surfaced separately and kept
   out of the health trend entirely?

### 8.3 The weight subsystem

1. **Thresholds.** Are 5% per 4 weeks ("notable") and 10% per 4 weeks ("urgent") the right
   lines for unintentional loss? Should they differ between dogs and cats, or by size
   class - 5% of a Chihuahua and 5% of a Great Dane are very different absolute amounts?
2. **Maximum weight penalty.** Weight can remove at most 15 of 100 points, against 18 for
   a single appetite point. Is weight loss under-weighted relative to the self-reported
   indicators, given it is the only objectively measured signal in the system?
3. **Freshness window.** Is "full effect for 8 weeks, gone by 12" clinically sensible for a
   monthly weigh-in cadence, or should a real loss persist longer?
4. **Noise floor.** Is 2% the right line below which a change is home-scale noise?
5. **Managed loss.** Are 8%/4wk (dog) and 4%/4wk (cat) safe ceilings for deliberate weight
   loss, and should exceeding them escalate as it currently does?
6. **Growth.** The engine gates growth on an age cut-off per breed and tightens loss
   thresholds by 30% while growing. Should it use published growth centile curves instead,
   and is 30% the right tightening?
7. **Gain.** Rapid gain is advisory only and never deducts points. Is that right, or should
   sustained gain affect the wellbeing score?
8. **The breed table.** 19 breeds, assembled from breed standards, returning
   `no_reference` for everything else including all crossbreeds. Is a breed weight range an
   acceptable stand-in for a body condition score at all, and should the product simply
   capture an owner-reported BCS instead?
9. **The compound rule.** Weight contributes to the "several indicators declining" tally as
   a *fraction* that decays with the reading's age. Is treating an objective measurement as
   equivalent to one self-reported indicator the right calibration, or should it count for
   more?

## 9. Out of scope

Machine learning, real user data, production app screens, changes to live PawHealthAI
behaviour, and final clinical rules - all out of scope until veterinary review is complete.

## 10. References

**How to read this list.** These references establish that the engine's *approach* is a
recognised one and that its thresholds sit in a plausible range. They are **not** the
derivation of the numbers. Every constant in this report - the 0-100 scale, the band
cut-offs at 85/70/50, the `DEVIATION_WEIGHT` of 60, the weighting profiles in §8.2, the
weight thresholds in §8.3, the -8 worming nudge, the -12 compound deduction - is an
engineering placeholder chosen for v0.2. Where the literature and a constant disagree, the
literature wins and the constant should change. That is the point of §8.

### Scoring architecture

**[1]** Royal College of Physicians (2017). *National Early Warning Score (NEWS) 2:
Standardising the assessment of acute-illness severity in the NHS.* Updated report of a
working party. London: RCP.
https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf

> *Supports §3.* NEWS2 aggregates weighted parameters into a single number, sorts it into
> banded escalation tiers, and lets a clinical trigger override the aggregate. That is the
> same three-layer structure described in §3, and it is the established precedent for the
> design decision in §3 "Layer 2" that an override must **bypass** the score rather than be
> folded into it as a deduction.

**[2]** Reid, J., Wiseman-Orr, L. and Scott, M. (2020). Development of an early warning
system for owners using a validated health-related quality of life (HRQL) instrument for
companion animals and its use in a large cohort of dogs. *Journal of Small Animal
Practice*. https://pmc.ncbi.nlm.nih.gov/articles/PMC7541963/

> *Supports §3 Layer 1, §4.* The nearest published analogue to this engine: an
> owner-completed, psychometrically validated instrument scoring four behavioural domains
> (energy, happiness, activity, calmness) closely comparable to the check-in's appetite,
> energy, sleep and activity, used as an early-warning system across a large cohort. The
> basis for treating owner-reported domains tracked against the animal's own history as
> carrying real signal, and for framing the output as wellbeing tracking rather than
> diagnosis (§3 "Removal of diagnostic outputs").

### Body condition

**[3]** Laflamme, D. P. (1997). Development and validation of a body condition score
system for dogs. *Canine Practice*, 22(4), 10-15. *(Companion paper for cats: Laflamme,
D. P. (1997). Development and validation of a body condition score system for cats: a
clinical tool. Feline Practice, 25(5-6), 13-18.)*

> *Supports §3 "The weight subsystem", §8.3 Q8:* the 9-point BCS scale as the validated
> clinical measure of body condition, shown to be repeatable both within and between
> scorers.

**[4]** World Small Animal Veterinary Association, Global Nutrition Committee.
*WSAVA Global Nutrition Toolkit.*
https://wsava.org/wp-content/uploads/2021/04/WSAVA-Global-Nutrition-Toolkit-English.pdf

> *Supports §3 "The weight subsystem", §7:* BCS as the international standard (4-5/9 ideal
> for dogs, 5/9 for cats). **This is the reference the breed weight table in `weight.py` is
> a stand-in for.** Where an owner- or vet-recorded BCS exists it should supersede the
> table entirely: BCS measures body condition directly, while a weight range only infers it
> from frame.

**[5]** German, A. J. (2018). Dangerous trends in pet obesity. *Veterinary Record*,
182(1), 25. https://bvajournals.onlinelibrary.wiley.com/doi/10.1136/vr.k2

> *Supports §3 "The weight subsystem":* the scale of overweight in the pet population -
> body-condition surveys of UK dogs put 56-65% in the overweight range - and therefore why
> a breed reference must be built from breed standards rather than from what pets actually
> weigh. A population-derived table would read a healthy dog as underweight.

**[6]** Pegram, C., et al. (2021). Frequency, breed predisposition and demographic risk
factors for overweight status in dogs in the UK. *Journal of Small Animal Practice*,
62(7). VetCompass Programme, Royal Veterinary College.
https://onlinelibrary.wiley.com/doi/10.1111/jsap.13325

> *Supports §3 "The weight subsystem":* breed-level variation in overweight risk, and hence
> holding the reference per breed rather than per species. **Read with care:** this measures
> overweight status *recorded by a vet in clinical notes* (~5.7% annual period prevalence),
> far below the 56-65% found by direct body-condition assessment [5]. The RVC describes the
> recorded figure as "the tip of the iceberg." Do not quote the two interchangeably.

### Weight change as a signal

**[7]** Freeman, L. M., Lachaud, M. P., Matthews, S., Rhodes, L. and Zollers, B. (2016).
Evaluation of weight loss over time in cats with chronic kidney disease. *Journal of
Veterinary Internal Medicine*, 30(5), 1661-1666. doi:10.1111/jvim.14561, PMID 27527534
https://onlinelibrary.wiley.com/doi/abs/10.1111/jvim.14561

> *Supports §8.3 Q1:* weight loss as an early-warning signal, and the rough placement of
> the 5% "notable" and 10% "urgent" thresholds. In 569 cats, weight loss was detectable up
> to three years before CKD diagnosis, with around 10% of body weight lost in the year
> preceding it. This is a *post-hoc* sanity check on thresholds chosen by engineering
> judgement, not their source.

**[8]** Salt, C., Morris, P. J., German, A. J., et al. (2017). Growth standard charts for
monitoring bodyweight in dogs of different sizes. *PLoS ONE*, 12(9), e0182064. WALTHAM
Centre for Pet Nutrition. doi:10.1371/journal.pone.0182064
https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0182064

> *Supports §3 "The weight subsystem", §7, §8.3 Q6:* suppressing gain rules while a pet is
> still growing. Drawn from a primary-care database holding 3.1 million purebred dogs of
> the selected breeds aged 10.4 weeks to 2.25 years; centile curves were built for 100
> breed-specific models, with the clinical charts based on five size categories.
> **The obvious upgrade path:** the engine gates growth on a crude "adult from N months"
> cut-off per breed, which these percentile curves would replace with a real growth
> trajectory.

### Known citation gaps

Two parts of the engine are **not** covered by anything above and should not be presented
as though they are:

1. **The breed weight table.** No open, normative, per-breed healthy-weight dataset exists.
   The 19 entries in `weight.py` are assembled from published breed standards and are the
   weakest-sourced component of the system. Reference [4] is the intended replacement
   wherever a BCS is available.
2. **The non-diagnostic constraint.** The engine's most important safety property - that it
   never names a disease (§3 "Removal of diagnostic outputs") - rests on product judgement
   rather than a cited standard. Veterinary telehealth and VCPR guidance (AVMA, RCVS) is
   the likely place to look. This should be resolved before any external publication.

---

*Every rule and threshold in v0.2 is provisional and flagged for veterinary review rather
than treated as final.*
