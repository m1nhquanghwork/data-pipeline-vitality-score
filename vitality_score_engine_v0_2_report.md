# PawHealthAI - Vitality Score Engine v0.2

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

- `phavit/models.py` - the shapes of the data the engine passes around: what a pet profile
  holds, what a check-in holds, what a result holds (`PetProfile`, `CheckInData`,
  `BaselineSummary`, `RedFlagResult`, `VitalityScoreResult`).
- `phavit/red_flags.py` - Layer 2, the safety net (`RedFlagEngine`, `EMERGENCY_SIGNS`).
- `phavit/scoring.py` - Layer 1, the 0-100 calculation (`VitalityScoreEngine`).
- `phavit/pipeline.py` - the single front door that runs the two in the right order
  (`process_checkin`). Nothing else should be called directly.

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

- **Compares each pet only against themselves.** The baseline is the average of that
  pet's own recent appetite, energy, sleep and activity - so a naturally sleepy cat is
  not marked down for being a naturally sleepy cat.
- **Only decline costs points.** Doing better than usual scores 0, not a bonus. There
  are no fixed deductions for any particular value; what matters is the change.
- **Breed-aware.** For high-energy breeds (Vizsla, Border Collie) activity carries far
  more of the total importance - 45% rather than 20%.
- **Signal vs noise.** One indicator dipping for a week is treated as ordinary
  variation; two or more falling together takes an extra penalty.
- **Honest about not knowing.** With fewer than 4 recent check-ins the engine reports
  `Building Baseline` and shows no number at all, rather than inventing one from too
  little history.
- **Fourth-check-in unlock**: the total counts the *current* completed check-in, so
  the first score appears at 4 total (3 previous + current), not the 5th event.
  `process_checkin(pet, previous_checkins, current_checkin)` takes the two apart to
  keep that boundary unambiguous.

#### How the score is worked out

Every pet starts the week on **100** and only ever loses points. There is no way to gain
them back above 100, because the score measures decline against the pet's own normal, not
performance against other pets.

**Step 1 - Establish what is normal for this pet.**
Average their last few check-ins for each of appetite, energy, sleep quality and activity
minutes. Those four averages are the baseline. A cat who normally sleeps a lot has a high
sleep baseline; nothing is compared against a species or breed average.

**Step 2 - Compare this week, counting only what went down.**
If appetite was normally 4 and is 3 this week, that is a drop of 1. If it went *up*,
that counts as 0, not as a bonus. Activity is handled as a percentage rather than a count,
because "20 minutes less" means something very different for a Greyhound than a Pug.

**Step 3 - Decide how much each drop matters.**
The four indicators share 100% of the importance between them. For a typical pet that is
appetite 30%, energy 30%, sleep 20%, activity 20%. For a high-energy breed more of that
100% shifts onto activity. The shares always total 100%, which is what makes the two
profiles comparable to each other.

**Step 4 - Turn the drops into points.**
A pet who collapsed all the way to the bottom on every indicator at once would lose **60
points** from this step. Everything smaller is proportional. So a one-point appetite drop
for a typical pet costs 30% of 60 = **18 points**.

**Step 5 - Add a penalty if several things fall together.**
If two or more indicators dropped meaningfully in the same week, take a further **12
points**. Two things sliding at once is more meaningful than either alone - this is the
"signal versus noise" rule, and it is the one place the engine treats the whole as more
than the sum of the parts.

**Step 6 - Apply the care nudge.**
Take **8 points** if worming is overdue. This is a care-compliance prompt, not a health
measurement, and §8.2 question 8 asks whether it belongs in this score at all.

**Step 7 - Round, and clamp to the 0-100 range.**
Then read off the band: **Bright Green ≥85 · Medium Green ≥70 · Watch ≥50 · Action Needed
<50** (all provisional).

**Worked example.** A Labrador whose normal is appetite 4, energy 4, sleep 4, and 60
minutes of activity. This week appetite and energy are both 3, sleep and activity unchanged.

| Step | Working | Running score |
|------|---------|:-------------:|
| Start | | **100** |
| Appetite down 1 of 5 | 30% share × 60 = 18 | 82 |
| Energy down 1 of 5 | 30% share × 60 = 18 | 64 |
| Sleep unchanged | nothing | 64 |
| Activity unchanged | nothing | 64 |
| Two indicators fell together | flat 12 | **52** |

**52 - Watch.** Had appetite alone dropped, the pet would have finished on 82 (Medium
Green). The second indicator is what moves them a whole band, which is the intended
behaviour and the thing §8.2 question 4 asks you to sanity-check.

#### Formal notation

> **Engineering reference — skip this block unless you are implementing the engine.**
> It restates steps 1-7 above exactly and adds nothing to them.

With baseline means $\bar A,\bar E,\bar S,\bar M$ (appetite, energy, sleep, activity)
over the last $n \ge 4$ check-ins, take **downward deviations only**:

$$\Delta a=\max(0,\bar A-a),\quad \Delta e=\max(0,\bar E-e),\quad \Delta s=\max(0,\bar S-s),\quad \Delta m=\max\!\Big(0,\tfrac{\bar M-m}{\bar M}\Big)$$

($\Delta a,\Delta e,\Delta s$ are 1–5 point drops; $\Delta m$ is a fraction in $[0,1]$.)
Apply breed-aware weights (each set sums to 1) and the tuning constant $D = 60$:

$$(w_a,w_e,w_s,w_m)=\begin{cases}(0.30,0.30,0.20,0.20)&\text{normal breed}\\(0.20,0.25,0.10,0.45)&\text{high-energy breed}\end{cases}$$

$$S_1 = 100 - D\,\big(w_a\Delta a + w_e\Delta e + w_s\Delta s + w_m\Delta m\big)$$

Add the multi-decline penalty, where $k$ counts indicators that dropped meaningfully
($\Delta a\ge1,\ \Delta e\ge1,\ \Delta s\ge1,\ \Delta m\ge0.25$), then the care nudge:

$$S_2 = S_1 - 12\cdot\mathbb{1}[k\ge2], \qquad S_3 = S_2 - 8\cdot\mathbb{1}[\text{not worming\_compliant}]$$

$$\text{score} = \max\!\big(0,\ \min(100,\ \operatorname{round}(S_3))\big)$$


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

The earlier prototype attempted to list possible conditions a pet might have. That
capability has been **removed entirely**, not hidden or disabled - the engine can no
longer produce a disease name because it no longer has anywhere to put one.

What replaces it is a record of *why we escalated and what the owner should do*, never
what we think is wrong: `trigger` (a short internal label), `severity_tier`,
`clinical_reason_for_escalation` (describing the reported sign, not a cause),
`recommended_user_pathway`, and `vet_validation_required`. An automated test checks every
message the engine can produce against a list of condition names and fails the build if
one ever appears.

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

- Owners rate appetite, energy and sleep on a 1-5 scale, and we assume one owner's "3"
  this week means the same as their "3" last week. We do **not** assume one owner's 3
  means the same as another owner's 3.
- Four or more recent check-ins are enough to establish what is normal for a pet.
- The importance shares, the 60-point figure for a total collapse, the band cut-offs and
  the three-check-in look-back for "repeated" signs are all **numbers we picked**, not
  numbers derived from evidence. §8 exists to change them.
- How worried the owner says they are, and how consistently they check in, are treated as
  engagement signals only - **never** as evidence about the pet's health.

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

The score starts at 100 and only ever subtracts, and only for changes in the *downward*
direction. Two things decide what a given change costs:

1. **How much that indicator matters** relative to the other three, expressed as a share
   of 100%.
2. **How much a total collapse would cost** - set at 60 points, and shared out between
   the four indicators according to (1).

The shares always add to 100% within a profile, which is what lets the two breed profiles
be compared to one another. This is the same calculation described step by step in §3
"How the score is worked out"; below it is restated as plain point costs.

**Current weights (provisional placeholders):**

| Indicator | Normal breed | High-energy breed |
|-----------|:------------:|:-----------------:|
| Appetite  | 0.30 | 0.20 |
| Energy    | 0.30 | 0.25 |
| Sleep     | 0.20 | 0.10 |
| Activity  | 0.20 | 0.45 |

Percentage shares are hard to judge clinically, so **this is the table to review** - the
same weights expressed as points removed from the 0-100 score. Nothing here needs working
out; the numbers are what an owner would actually see happen. Appetite, energy and sleep
are 1-5 scales, so "down 1 point" means something like 4→3. Activity is compared as a
percentage of the pet's usual minutes.

*(These are the figures with no body-condition adjustment applied. A pet recorded as above
or below their breed's healthy weight range shifts the shares somewhat - see
`PawHealthAI_Vitality_Score.md` §6, which the weight subsystem added after this table was
written.)*

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

## 10. References

**How to read this list.** These references establish that the engine's *approach* is a
recognised one and that its thresholds sit in a plausible range. They are **not** the
derivation of the numbers. Every constant in this report - the 0-100 scale, the band
cut-offs at 85/70/50, the `DEVIATION_WEIGHT` of 60, the weighting profiles in §8.2, the
-8 worming nudge, the -12 compound deduction - is an engineering placeholder chosen for
v0.2. Where the literature and a constant disagree, the literature wins and the constant
should change. That is the point of §8.

**Scope note.** Sections 1-9 above document the engine as it stood before the weight
subsystem (`phavit/weight.py`) was added. References [3]-[8] cover that later work, which
is currently documented in `PawHealthAI_Vitality_Score.md` rather than here. Bringing this
report up to date is outstanding - see the note at the end of this section.

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

> *Supports:* the 9-point BCS scale as the validated clinical measure of body condition,
> shown to be repeatable both within and between scorers.

**[4]** World Small Animal Veterinary Association, Global Nutrition Committee.
*WSAVA Global Nutrition Toolkit.*
https://wsava.org/wp-content/uploads/2021/04/WSAVA-Global-Nutrition-Toolkit-English.pdf

> *Supports:* BCS as the international standard (4-5/9 ideal for dogs, 5/9 for cats).
> **This is the reference the breed weight table in `weight.py` is a stand-in for.** Where
> an owner- or vet-recorded BCS exists it should supersede the table entirely: BCS measures
> body condition directly, while a weight range only infers it from frame.

**[5]** German, A. J. (2018). Dangerous trends in pet obesity. *Veterinary Record*,
182(1), 25. https://bvajournals.onlinelibrary.wiley.com/doi/10.1136/vr.k2

> *Supports:* the scale of overweight in the pet population - body-condition surveys of UK
> dogs put 56-65% in the overweight range - and therefore why a breed reference must be
> built from breed standards rather than from what pets actually weigh.

**[6]** Pegram, C., et al. (2021). Frequency, breed predisposition and demographic risk
factors for overweight status in dogs in the UK. *Journal of Small Animal Practice*,
62(7). VetCompass Programme, Royal Veterinary College.
https://onlinelibrary.wiley.com/doi/10.1111/jsap.13325

> *Supports:* breed-level variation in overweight risk, and hence holding the reference per
> breed rather than per species. **Read with care:** this measures overweight status
> *recorded by a vet in clinical notes* (~5.7% annual period prevalence), far below the
> 56-65% found by direct body-condition assessment [5]. The RVC describes the recorded
> figure as "the tip of the iceberg." Do not quote the two interchangeably.

### Weight change as a signal

**[7]** Freeman, L. M., Lachaud, M. P., Matthews, S., Rhodes, L. and Zollers, B. (2016).
Evaluation of weight loss over time in cats with chronic kidney disease. *Journal of
Veterinary Internal Medicine*, 30(5), 1661-1666. doi:10.1111/jvim.14561, PMID 27527534
https://onlinelibrary.wiley.com/doi/abs/10.1111/jvim.14561

> *Supports:* weight loss as an early-warning signal, and the rough placement of the 5%
> "notable" and 10% "urgent" thresholds. In 569 cats, weight loss was detectable up to
> three years before CKD diagnosis, with around 10% of body weight lost in the year
> preceding it. This is a *post-hoc* sanity check on thresholds chosen by engineering
> judgement, not their source.

**[8]** Salt, C., Morris, P. J., German, A. J., et al. (2017). Growth standard charts for
monitoring bodyweight in dogs of different sizes. *PLoS ONE*, 12(9), e0182064. WALTHAM
Centre for Pet Nutrition. doi:10.1371/journal.pone.0182064
https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0182064

> *Supports:* suppressing gain rules while a pet is still growing. Drawn from a
> primary-care database holding 3.1 million purebred dogs of the selected breeds aged
> 10.4 weeks to 2.25 years; centile curves were built for 100 breed-specific models, with
> the clinical charts based on five size categories. **The obvious upgrade path:** the
> engine gates growth on a crude "adult from N months" cut-off per breed, which these
> percentile curves would replace with a real growth trajectory.

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

### Outstanding: this report predates the weight subsystem

Sections 1-9 do not describe `phavit/weight.py` at all. Specifically still to update: the
deliverables list and fixture count in §2; the module list in §3; the score equation in §3
Layer 1 (no weight term); the Layer 2 trigger table in §3 (missing `notable_weight_loss`,
`weight_loss_with_signs`, `rapid_weight_gain`); the test results in §5; the age/species
claim in §7; the weighting table in §8.2 (predates the body-status modifiers); and §8's
open questions (nothing on the weight thresholds). Until that is done,
`PawHealthAI_Vitality_Score.md` is the current description of the weight subsystem.

---

*Every rule and threshold in v0.2 is provisional and flagged for veterinary review rather
than treated as final.*
