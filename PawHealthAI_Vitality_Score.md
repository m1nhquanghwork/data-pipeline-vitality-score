# PawHealthAI Vitality Score Engine

## What is the Vitality Score?
The Vitality Score is a 0-100 health tracking metric designed to help pet owners understand their pet's overall well-being. It is using the 4 weeks recorded data straight from PawHealthAI app. This Scoring system would help pet owners be able to keep on track with pet physical and mental health, and Evie (AI bot) be able to use this and give recommendation and advice if a particular action is needed.

## Data 
The data as being said above capture directly from the PawHealthAI app. The data collection are divdied into different data class:

### Pet Profile
This include any personal information from the pet inclding: pet name, birth, breed, postcode, streak (keep on track weekly checkin), consistency, worming compliant, vaccination current, last visit.

### Vet Interaction Log
This is the log of the vet toward pets, mostly captured by the vet and will record all observation from the vet visited.

### Dental Health Log
Design mainly for puppy teeth check-in which to keep on track of the pet dental health.

### Toileting Log
Mainly tracking bowel habits, frquency and acute overrides, this is for the purpose of tracking on digestion system and toilet habit of the pet.

### Weight Log
The pet's recorded body weight over time. Weight is **optional and monthly**, not weekly: an owner types a weight into whatever check-in they happen to weigh their pet on, and most check-ins carry none at all. Weights can also arrive from their own log — a vet visit, a bulk import — and either source feeds the same engine.

Because weight runs on a slower clock than the rest of the check-in, it gets its own handling throughout. See [How Weight Affects the Score](#how-weight-affects-the-score).

### Check-in Data
The check-in data records all the pet's health data, including vet interation log, dental health log and toileting log. This is the main data for recording and calculating vitality score for pet.

## The Three-Layer System
The Vitality Score runs on a carefully designed architecture to ensure it is both smart and safe.

### Layer 1: The Wellness Trend Engine (The "Math")
This layer tracks general, day-to-day wellness based on weekly check-ins.
* **What it tracks:** It looks at factors like activity levels, energy, appetite, and sleep quality — plus body weight, which is recorded monthly rather than weekly and is handled on its own clock.
* **Smart Adjustments:** The engine is customized for the pet's breed and age. For example, high-energy breeds like Vizslas will have their activity levels weighted much more heavily than a low-energy breed. Body condition adjusts this too: for a pet carrying weight above their breed's healthy range, activity counts for more, because sustained low activity matters more for them and it is the lever an owner can actually pull. For a pet below their range, appetite counts for more instead.
* **Signal vs. Noise:** The system knows the difference between a minor fluctuation and a real health issue. A single week of slightly reduced appetite is considered "noise" and won't severely penalize the score. However, reduced appetite combined with lower energy and a behavioral change is a "signal" that triggers a larger score drop. Weight joins that same tally — weight loss alongside another declining indicator is treated as more concerning than either on its own.

### Layer 2: The Red Flag Engine (The "Safety Net")
This is the system's built-in safety mechanism. It handles acute or serious medical signs separately so they don't get lost in the general math.
* **Immediate Action:** If an owner logs a high-severity warning sign—such as blood in the stool or a sudden collapse in appetite combined with lethargy—this layer immediately takes over.
* **Bypassing the Math:** It completely bypasses the 0-100 scoring system and immediately places the pet into the "Action Needed" zone, prompting the owner to contact a vet.
* **Weight triggers:** Three of the safety rules come from the weight log. A **notable unintentional loss** (around 10% of body weight per four weeks) routes to urgent vet review on its own. **Weight loss alongside another sign** — reduced appetite, increased thirst, or low energy on the same check-in — is also urgent, because each of those signs normally needs to repeat before it escalates, so a first occurrence next to real weight loss would otherwise slip through. **Rapid weight gain** in an adult is advisory only: it prompts a look at portions and treats, and never reduces the score.

### Layer 3: Clear, Cautious Explanations
PawHealthAI ensures that pet owners are never left guessing.
* **Evie's Explanations:** Every time the Vitality Score changes, the virtual assistant, Evie, explains exactly *why* in one simple sentence. For example: "Bonnie's score improved this week because her energy and appetite both returned to her normal range".
* **Safety First:** The system avoids making medical diagnoses (like guessing a dog has diabetes). Instead, it stays cautious and focuses on explaining the observed trends and recommending professional vet advice when necessary .
* **Always dated:** Because weight is monthly, any mention of it names the day it was recorded — "the weight comparison uses the reading recorded on 26 Jun 2026" — so nothing implies the pet was weighed this week.
* **Honest about gaps:** If the latest weight fails screening, Evie says the entry looks unusual and asks for it to be re-entered, rather than quietly scoring an older reading. If the last weigh-in has aged past two months, she says it is counting for less and asks for a fresh one. Without that second prompt an owner would watch the score drift upward as an old reading expired and reasonably read it as their pet recovering.

## How Weight Affects the Score

Weight is the one indicator recorded monthly while everything else is weekly, so it cannot be dropped into the math the same way. The rule the engine follows throughout is that **weight is a safety and context signal first, and a scoring term second** — it can lower a score, it can never raise one, and body size on its own is never a deduction.

### 1. Screening the reading
Before any math runs, a recorded weight is checked:

* It must be physically plausible for the species (roughly 0.5–120 kg for a dog, 0.5–15 kg for a cat). A 60 kg cat is a typo, not a pet.
* Only one reading counts per day; the last one entered wins.
* A jump of more than 25% from the previous reading is rejected — a mistyped 4.0 for 40.0 must never reach the safety rules.

A bad weight degrades to "no weight signal"; it never breaks the check-in. And if the reading that failed is the **newest** one, the owner is asked to re-check it rather than the engine silently scoring an older weight.

### 2. Finding the pet's normal
The baseline is the **median** of up to the last four readings, not the average. A median means one bad entry cannot drag the pet's normal along with it.

### 3. Measuring the change
The change is expressed as a percentage of the baseline, then normalised to a **percent-per-four-weeks rate** so readings taken at irregular intervals stay comparable. The rate is measured against the most recent previous reading that is at least two weeks old — comparing today against a weigh-in from three days ago would turn ordinary scale-to-scale variation into an apparent collapse.

| Rate of loss | What it means |
| --- | --- |
| Under 2% per 4 weeks | Noise — hydration, a full bladder, a wet coat, different scales |
| 2–5% | Counts against the score, gently |
| 5% or more | Counts as a declining indicator in the signal-vs-noise tally |
| Around 10% | The safety net takes over and routes to vet review |
| Gain of 8% or more in an adult | Advisory prompt only, no score change |

### 4. Turning it into points
Between 2% and 10% the deduction ramps smoothly from **0 to 15 points**. It stops at 15 because past that point the Red Flag Engine has taken over anyway, and a score is no longer what the owner needs to see.

**Worked example — Scout, a 6-year-old Labrador.** Weighed on three check-ins across two months: 32.0 kg, then 30.6 kg, then 29.4 kg.

* Baseline = median of the two earlier readings = **31.3 kg**
* Change = 1.9 kg below baseline = **6.07%**, over a four-week gap = **6.07% per 4 weeks**
* That sits about halfway between the 2% floor and the 10% line, so it removes **7.6 points**
* Nothing else has moved, so **Scout scores 92 — Bright Green**, with "weight below usual" named as the reason

The score is still reassuring, which is right: a 6% loss is worth mentioning, not worth alarming anyone about. Had the same loss appeared alongside reduced appetite, the Red Flag Engine would have escalated it instead.

### 5. Weekly, but optional
Weight is recorded whenever the owner gets to it, and the score has to stay steady in between. Two rules make that work:

* **Carry-forward.** A check-in with no weight adds no new reading; the last trend keeps applying unchanged. Weighed in week 4 and then not again, Scout's score holds flat from week 5 through week 12 — the deduction does not spike on whichever week the scales came out.
* **Decay.** The deduction applies in full for eight weeks, then fades to nothing by twelve. An old reading cannot penalise a pet indefinitely.

What is carried forward is the **trend**, never the reading itself. Copying the last weight into blank weeks would look equivalent and is not: it would refill the baseline with duplicates until a genuine loss read as perfectly stable, and it would erase the one fact the decay depends on — when the pet was actually last weighed.

### 6. Body condition, not body size
Separately from the trend, the engine compares the pet against a **healthy adult weight range for their breed**, held per breed and per sex. These come from published breed standards rather than population averages, and the distinction matters: body-condition surveys of UK dogs have put 56–65% of them in the overweight range [5], so a table built from what pets *do* weigh would read a healthy dog as underweight. Overweight risk also varies sharply by breed [6], which is why the reference is held per breed rather than per species.

Being above or below that range **never deducts points**. It shifts emphasis:

* **Above the range** — activity is weighted more heavily, and the drop that counts as "activity below usual" tightens from a 25% fall to 20%.
* **Below the range** — appetite is weighted more heavily, since intake rather than exercise is the lever that matters.

The four indicator weights are always rescaled back to a total of 100% afterwards, so this re-prioritises what matters for that pet rather than simply making the score harsher.

The table only covers recognised breeds and only applies to adults; crossbreeds and growing animals return "no reference" and are scored without it. A vet-recorded body condition score (the 9-point WSAVA scale) is the proper clinical reference and should override the table wherever one exists.

### 7. When weight loss is the goal
Two situations suppress the alarms:

* **A recorded weight-management plan.** An owner deliberately slimming their pet should not be alerted for succeeding. Escalation is suppressed while the loss stays within a safe rate — about 8% per four weeks for a dog, 4% for a cat. Faster than that escalates anyway, plan or not.
* **A growing puppy or kitten.** Gain is expected, so the gain rules switch off entirely until the breed's adult age. The loss thresholds tighten instead, because a growing animal *losing* weight matters more, not less.

### 8. Confidence
Weight can move the score by real points, so the engine lowers its stated confidence when the weight signal cannot be trusted — a rejected entry, or a reading that has aged past eight weeks. A pet who has simply never been weighed is left alone: with no weight at all the score behaves exactly as it did before weight existed, and claiming reduced confidence would be false precision.

> **Every threshold on this page is a provisional engineering placeholder pending veterinary review**, in line with the rest of the v0.2 engine. The percentages, the 15-point cap, the eight- and twelve-week decay window and the breed table are all tuning constants, not clinical findings.

## The Health Zones
The score is visualized on a circular meter broken down into four color-coded zones:
* **Bright Green (85–100):** The pet is doing wonderfully. Consistently high scores may trigger community sharing prompts.
* **Medium Green (70–84):** The pet is tracking normally and maintaining standard wellness.
* **Watch Zone / Yellow (50–69):** The pet is below their usual baseline. Evie will prompt the owner to monitor closely and provide a link to book a vet visit via a directory.
* **Action Needed (Below 50):** Indicates a critical drop in wellness or a Red Flag trigger, prompting immediate vet contact.

---

## References

**How to read this list.** These references establish that the engine's *approach* is a recognised one and that its thresholds sit in a plausible range. They are **not** the derivation of the numbers. Every specific constant — the 0–100 scale, the band cut-offs at 85/70/50, the indicator weightings, the 15-point weight cap, the eight- and twelve-week decay window, the breed table itself — is an engineering placeholder chosen for v0.2 and pending veterinary review. Anywhere the two disagree, the literature wins and the constant should change.

### The scoring architecture

**[1]** Royal College of Physicians (2017). *National Early Warning Score (NEWS) 2: Standardising the assessment of acute-illness severity in the NHS.* Updated report of a working party. London: RCP. https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf
> *Supports:* the three-layer shape. NEWS2 aggregates weighted parameters into a single number, sorts it into banded escalation tiers, and allows a clinical trigger to override the aggregate — the same structure as Layer 1 (the math), the Health Zones (the bands) and Layer 2 (the safety net). The precedent for why an override must bypass the score rather than be folded into it.

**[2]** Reid, J., Wiseman-Orr, L. and Scott, M. (2020). Development of an early warning system for owners using a validated health-related quality of life (HRQL) instrument for companion animals and its use in a large cohort of dogs. *Journal of Small Animal Practice*. https://pmc.ncbi.nlm.nih.gov/articles/PMC7541963/
> *Supports:* Layer 1's core premise — that owner-reported behavioural domains, tracked over time against the animal's own history, carry usable early-warning signal. The VetMetrica instrument scores four domains (energy, happiness, activity, calmness) closely comparable to the check-in's appetite, energy, sleep and activity. The nearest published analogue to the Vitality Score, and the reason the score is framed as wellbeing tracking rather than diagnosis.

### Body condition

**[3]** Laflamme, D. P. (1997). Development and validation of a body condition score system for dogs. *Canine Practice*, 22(4), 10–15. *(Companion paper for cats: Laflamme, D. P. (1997). Development and validation of a body condition score system for cats: a clinical tool. Feline Practice, 25(5–6), 13–18.)*
> *Supports:* the 9-point BCS scale as the validated clinical measure of body condition, shown to be repeatable within and between scorers.

**[4]** World Small Animal Veterinary Association, Global Nutrition Committee. *WSAVA Global Nutrition Toolkit.* https://wsava.org/wp-content/uploads/2021/04/WSAVA-Global-Nutrition-Toolkit-English.pdf
> *Supports:* BCS as the international standard, with 4–5/9 ideal for dogs and 5/9 for cats. **This is the reference the breed weight table is a stand-in for.** Where an owner- or vet-recorded BCS exists it should supersede the table entirely, since BCS measures body condition directly while a weight range only infers it from frame.

**[5]** German, A. J. (2018). Dangerous trends in pet obesity. *Veterinary Record*, 182(1), 25. https://bvajournals.onlinelibrary.wiley.com/doi/10.1136/vr.k2
> *Supports:* the scale of overweight in the pet population, and the reason a breed reference must be built from breed standards rather than from what pets actually weigh.

**[6]** Pegram, C., et al. (2021). Frequency, breed predisposition and demographic risk factors for overweight status in dogs in the UK. *Journal of Small Animal Practice*, 62(7). VetCompass Programme, Royal Veterinary College. https://onlinelibrary.wiley.com/doi/10.1111/jsap.13325
> *Supports:* breed-level variation in overweight risk. **Read with care:** this measures overweight status *recorded by a vet in clinical notes* (~5.7% annual period prevalence), which is far below the 56–65% found by direct body-condition assessment [5]. The RVC describes the recorded figure as "the tip of the iceberg." The gap between the two is itself an argument for owner-side weight tracking.

### Weight change as a signal

**[7]** Freeman, L. M., Lachaud, M. P., Matthews, S., Rhodes, L. and Zollers, B. (2016). Evaluation of weight loss over time in cats with chronic kidney disease. *Journal of Veterinary Internal Medicine*, 30(5), 1661–1666. doi:10.1111/jvim.14561, PMID 27527534 https://onlinelibrary.wiley.com/doi/abs/10.1111/jvim.14561
> *Supports:* weight loss as an early-warning signal, and the rough placement of the 5% "notable" and 10% "urgent" thresholds. In a cohort of 569 cats, weight loss was detectable up to three years before CKD diagnosis, with around 10% of body weight lost in the year preceding it. Note this is a *post-hoc* sanity check on thresholds that were chosen by engineering judgement, not their source.

**[8]** Salt, C., Morris, P. J., German, A. J., et al. (2017). Growth standard charts for monitoring bodyweight in dogs of different sizes. *PLoS ONE*, 12(9), e0182064. WALTHAM Centre for Pet Nutrition. doi:10.1371/journal.pone.0182064 https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0182064
> *Supports:* suppressing gain rules while a pet is still growing. Drawn from a primary-care record database holding 3.1 million purebred dogs of the selected breeds aged 10.4 weeks to 2.25 years; centile curves were constructed for 100 breed-specific models, with the clinical charts based on five size categories. **The obvious upgrade path:** the engine currently gates growth on a crude "adult from N months" cut-off per breed; these percentile curves would replace it with a real growth trajectory.

### Known citation gaps

Two parts of the engine are **not** covered by anything above, and should not be presented as though they are:

* **The breed weight table.** No open, normative, per-breed healthy-weight dataset exists. The 19 entries are assembled from published breed standards and are the weakest-sourced component of the system. Reference [4] is the intended replacement wherever a BCS is available.
* **The non-diagnostic constraint.** The engine's most important safety property — that it never names a disease — currently rests on product judgement rather than a cited standard. Veterinary telehealth and VCPR guidance (AVMA, RCVS) is the likely place to look, and this should be resolved before any external publication. 