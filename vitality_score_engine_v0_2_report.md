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
| `data_pipeline_vitality_score.ipynb` | Runnable test-harness notebook (top-to-bottom, no manual fixes). |
| `vitality_score_engine_v0_2.py` | Reusable, standard-library-only scoring engine. |
| `synthetic_checkins_v0_2.csv` | 63 synthetic check-ins across 11 scenarios. |
| `expected_outputs_v0_2.csv` | Scenario-level expected band, override and explanation style. |
| `actual_outputs_v0_2.csv` | Engine output per scenario (regenerated each run). |
| `vitality_score_engine_v0_2_report.md` | This report. |

## 3. Architecture

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

11 named scenarios (stable adult dog, high-energy reduced activity, senior gradual
decline, puppy variable sleep/activity, cat appetite drop, blood in stool, repeated
increased thirst, persistent low appetite + lethargy, emergency collapse, inconsistent
low-confidence history, single vomiting). For each, expected band and override tier are
declared **before** running the engine. Current result: **11/11 scenarios match
expectation.**

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

1. Are the three escalation tiers and their trigger lists clinically appropriate and complete?
2. Is "≥4 check-ins" a sensible minimum baseline, or should it vary by life stage?
3. Are the band cut-offs (85/70/50) and breed weightings reasonable starting points?
4. Should any "monitor" item (e.g. tick found, single vomiting) be escalated to urgent?
5. Is the look-back window for "repeated" signs (thirst, vomiting, appetite loss) right?
6. Is the non-diagnostic explanation wording safe and clear enough for owners?

## 9. Out of scope

Machine learning, real user data, production app screens, changes to live PawHealthAI
behaviour, and final clinical rules - all out of scope until veterinary review is complete.

---

*Every rule and threshold in v0.2 is provisional and flagged for veterinary review rather
than treated as final.*
