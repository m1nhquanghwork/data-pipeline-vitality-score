"""
The weight subsystem - body weight trend and body-condition status.

Weight is recorded MONTHLY, not weekly, so it runs on its own cadence: a new
reading produces a `WeightTrendResult` which is stored and then read by the
weekly pipeline. Two guards keep a monthly signal from distorting a weekly
score:

  * carry-forward - the same stored result is applied to every check-in until
    the next weigh-in, so the score is stable between readings rather than
    spiking on the week a weight happens to be logged;
  * staleness decay - the deduction fades to zero between FRESH_WEEKS and
    STALE_WEEKS, so an old loss cannot penalise a pet indefinitely.

This module imports ONLY from `models`. Nothing here knows that scoring.py or
red_flags.py exist; both of those consume the result.

Every threshold below is a provisional engineering placeholder pending
veterinary review, in line with the rest of the v0.2 engine.
"""

from datetime import date, datetime
from statistics import median
from typing import List, Optional, Sequence, Tuple

from .models import CheckInData, PetProfile, WeightReading, WeightTrendResult


# --------------------------------------------------------------------------- #
# Tuning constants (provisional)                                               #
# --------------------------------------------------------------------------- #

# Below this, a change is measurement noise: hydration, a full bladder, a wet
# coat, a different set of scales, time of day.
NOISE_FLOOR_PCT = 2.0

# A loss big enough to count as a declining indicator in the score's signal-vs-
# noise tally.
NOTABLE_LOSS_PCT = 5.0

# Roughly the conventional "this needs a vet" line for unintentional loss.
URGENT_LOSS_PCT = 10.0

# Rapid gain in an adult. Attaches a monitor advisory, and - like loss - ramps
# into a score deduction; see weight_penalty().
MONITOR_GAIN_PCT = 8.0

# Where a gain reaches the full deduction. Set equal to URGENT_LOSS_PCT so a
# change of the same size costs the same points whichever way it went. Kept as
# its own constant rather than reusing the loss line, because whether the two
# directions deserve equal weight is a clinical judgement, not an arithmetic
# one: if review decides rapid gain should count for less than rapid loss,
# raising this number is the whole change.
URGENT_GAIN_PCT = 10.0

# Most points a weight change can remove from the 0-100 score, for a pet sitting
# inside their breed reference range. The cap sits at the escalation line in
# either direction, because beyond that the red-flag layer takes over anyway.
#
# scoring.py scales this per weighting profile - a pet already outside their
# healthy range has more at stake in a weight move than one comfortably inside
# it - by passing its own `cap` below. This module holds the shape of the ramp;
# the profile decides how tall it is.
MAX_WEIGHT_PENALTY = 15.0

# Staleness: full effect up to FRESH_WEEKS, fading linearly to nothing at
# STALE_WEEKS. Monthly cadence means ~4 weeks between readings, so a pet whose
# owner keeps weighing them never reaches the fade.
FRESH_WEEKS = 8.0
STALE_WEEKS = 12.0

# Data quality.
MIN_READINGS = 2          # need a previous reading to have a trend at all
BASELINE_WINDOW = 4       # median of up to this many PREVIOUS readings
MAX_STEP_CHANGE = 0.25    # >25% between consecutive readings = data entry error

# Shortest interval we will annualise over. Without a floor, an owner weighing
# twice in one week turns a 3% wobble into a 12%/4wk "collapse".
MIN_SPAN_WEEKS = 2.0

# Species plausibility bounds, kg. Anything outside is a typo, not a pet.
PLAUSIBLE_KG = {"dog": (0.5, 120.0), "cat": (0.5, 15.0)}
PLAUSIBLE_KG_DEFAULT = (0.1, 200.0)

# Safe deliberate weight loss, % of body weight per 4 weeks. Cats are held to a
# slower rate than dogs. Loss faster than this escalates even with a plan.
MANAGED_LOSS_MAX_RATE = {"dog": 8.0, "cat": 4.0}
MANAGED_LOSS_MAX_DEFAULT = 4.0

# Growing animals are expected to gain, so gain rules are suppressed and loss
# thresholds tightened by this factor (a growing pet losing weight matters more).
GROWTH_LOSS_SENSITIVITY = 0.7
DEFAULT_ADULT_FROM_MONTHS = 15


# --------------------------------------------------------------------------- #
# Breed reference table (PROVISIONAL - needs veterinary sign-off)              #
# --------------------------------------------------------------------------- #
# These are healthy adult ranges assembled from published breed standards, NOT
# from population averages. That distinction matters: population means describe
# what pets DO weigh, and body-condition surveys of UK dogs have put 56-65% of
# them in the overweight range (German 2018, Vet Rec 182(1):25), so a population-
# derived table would read a healthy dog as underweight. Overweight risk also
# varies sharply by breed (Pegram et al. 2021, JSAP 62(7)), which is why the
# reference is held per breed rather than per species.
#
# NOTE those figures come from direct body-condition ASSESSMENT. Overweight
# status actually RECORDED in primary-care notes is far lower (~5.7% annual
# period prevalence, Pegram 2021) - do not quote the two interchangeably.
#
# Body condition score (WSAVA 9-point, validated by Laflamme 1997) is the real
# clinical reference and should supersede this table wherever an owner-reported
# BCS exists. This is the fallback for pets with no BCS captured - and it returns
# "no_reference" for any breed it does not recognise, which includes every
# crossbreed.
#
# Full citations: see the References section of PawHealthAI_Vitality_Score.md.

class BreedWeightRef:
    """Healthy adult weight range for a breed, by sex."""

    __slots__ = ("male", "female", "adult_from_months", "size_class", "source")

    def __init__(self, male, female, adult_from_months, size_class, source):
        self.male: Tuple[float, float] = male
        self.female: Tuple[float, float] = female
        self.adult_from_months: int = adult_from_months
        self.size_class: str = size_class
        self.source: str = source


_KC = "breed standard (provisional, pending vet review)"

BREED_WEIGHT_REFERENCE = {
    ("dog", "labrador"):          BreedWeightRef((29.0, 36.0), (25.0, 32.0), 18, "large", _KC),
    ("dog", "golden_retriever"):  BreedWeightRef((29.0, 34.0), (25.0, 32.0), 18, "large", _KC),
    ("dog", "german_shepherd"):   BreedWeightRef((30.0, 40.0), (22.0, 32.0), 18, "large", _KC),
    ("dog", "vizsla"):            BreedWeightRef((20.0, 29.0), (18.0, 25.0), 18, "medium", _KC),
    ("dog", "border_collie"):     BreedWeightRef((14.0, 20.0), (12.0, 19.0), 15, "medium", _KC),
    ("dog", "cocker_spaniel"):    BreedWeightRef((13.0, 16.0), (12.0, 15.0), 15, "medium", _KC),
    ("dog", "beagle"):            BreedWeightRef((10.0, 16.0), (9.0, 15.0), 15, "medium", _KC),
    ("dog", "staffordshire_bull_terrier"): BreedWeightRef((13.0, 17.0), (11.0, 15.0), 15, "medium", _KC),
    ("dog", "french_bulldog"):    BreedWeightRef((9.0, 14.0), (8.0, 13.0), 12, "small", _KC),
    ("dog", "pug"):               BreedWeightRef((6.3, 8.1), (6.3, 8.1), 12, "small", _KC),
    ("dog", "jack_russell"):      BreedWeightRef((6.0, 8.0), (5.0, 7.0), 12, "small", _KC),
    ("dog", "cavalier_king_charles_spaniel"): BreedWeightRef((5.9, 8.2), (5.4, 8.0), 12, "small", _KC),
    ("dog", "dachshund"):         BreedWeightRef((7.0, 12.0), (7.0, 12.0), 12, "small", _KC),
    ("dog", "chihuahua"):         BreedWeightRef((1.5, 3.0), (1.5, 3.0), 12, "small", _KC),
    ("dog", "great_dane"):        BreedWeightRef((54.0, 90.0), (45.0, 59.0), 24, "giant", _KC),
    ("cat", "domestic_shorthair"): BreedWeightRef((4.0, 6.0), (3.5, 5.5), 12, "small", _KC),
    ("cat", "domestic_longhair"): BreedWeightRef((4.0, 6.0), (3.5, 5.5), 12, "small", _KC),
    ("cat", "maine_coon"):        BreedWeightRef((6.8, 11.0), (4.5, 8.0), 24, "large", _KC),
    ("cat", "siamese"):           BreedWeightRef((3.5, 5.5), (2.5, 4.5), 12, "small", _KC),
}

# Free-text breed strings from the app need normalising before lookup.
_BREED_ALIASES = {
    "lab": "labrador",
    "labrador_retriever": "labrador",
    "golden": "golden_retriever",
    "gsd": "german_shepherd",
    "alsatian": "german_shepherd",
    "hungarian_vizsla": "vizsla",
    "collie": "border_collie",
    "staffy": "staffordshire_bull_terrier",
    "staffie": "staffordshire_bull_terrier",
    "frenchie": "french_bulldog",
    "jack_russell_terrier": "jack_russell",
    "cavalier": "cavalier_king_charles_spaniel",
    "dsh": "domestic_shorthair",
    "dlh": "domestic_longhair",
    "moggy": "domestic_shorthair",
}

# Any breed string containing one of these is a cross - no reference applies.
_CROSSBREED_MARKERS = ("cross", "mix", "mixed", "mongrel", "unknown", "x-breed")


def normalise_breed(breed: Optional[str]) -> str:
    """Fold a free-text breed string down to a lookup key. '' if unusable."""
    if not breed:
        return ""
    key = "".join(ch.lower() if ch.isalnum() else " " for ch in breed)
    key = "_".join(key.split())
    if not key:
        return ""
    if any(marker in key for marker in _CROSSBREED_MARKERS):
        return ""
    return _BREED_ALIASES.get(key, key)


def lookup_reference(species: str, breed: Optional[str]) -> Optional[BreedWeightRef]:
    """The breed's healthy adult range, or None when we have no reference."""
    key = normalise_breed(breed)
    if not key:
        return None
    return BREED_WEIGHT_REFERENCE.get(((species or "").lower(), key))


def _age_months(birth_date: Optional[date], at: date) -> Optional[float]:
    if birth_date is None:
        return None
    return (at.toordinal() - birth_date.toordinal()) / 30.44


def _as_date(when) -> Optional[date]:
    """Accept either a check-in datetime or a plain date; anything else is None."""
    if isinstance(when, datetime):
        return when.date()
    return when if isinstance(when, date) else None


def body_status(
    kg: float,
    species: str,
    breed: Optional[str],
    sex: Optional[str],
    birth_date: Optional[date],
    at: date,
) -> Tuple[str, bool]:
    """
    Where this pet sits against their breed reference, plus whether they are
    still growing. Returns ("no_reference", is_growing) whenever the breed is
    unrecognised or the pet is not yet an adult - a growing animal cannot be
    compared to an adult range.

    Compared against the EDGES of the range, not its midpoint: the range already
    encodes frame variation, so only exceeding it means anything.
    """
    ref = lookup_reference(species, breed)
    adult_from = ref.adult_from_months if ref else DEFAULT_ADULT_FROM_MONTHS
    age = _age_months(birth_date, at)
    is_growing = age is not None and age < adult_from

    if ref is None or is_growing:
        return "no_reference", is_growing

    low, high = ref.female if (sex or "").lower() == "female" else ref.male
    if kg > high * 1.20:
        return "well_above_reference", is_growing
    if kg > high * 1.10:
        return "above_reference", is_growing
    if kg < low * 0.90:
        return "below_reference", is_growing
    return "in_reference", is_growing


# --------------------------------------------------------------------------- #
# Input collection                                                             #
# --------------------------------------------------------------------------- #
def readings_from_checkins(
    checkins: Sequence[CheckInData],
    extra: Optional[Sequence[WeightReading]] = None,
) -> List[WeightReading]:
    """
    Build the weight log from the weights recorded on weekly check-ins.

    `CheckInData.weight_kg` is optional and usually absent: owners weigh their
    pet roughly monthly, so most check-ins carry nothing and are skipped. This
    is the single path from the check-in flow into the weight subsystem - the
    field is not read anywhere else.

    `extra` merges in readings captured outside the check-in flow (a vet visit,
    a bulk import). Where a check-in and an `extra` reading fall on the same day
    the `extra` one wins, because validate_readings() keeps the last entry for a
    date and the sort below is stable.
    """
    out: List[WeightReading] = []
    for c in checkins or []:
        kg = getattr(c, "weight_kg", None)
        at = _as_date(getattr(c, "timestamp", None))
        if kg is None or at is None:
            continue
        out.append(WeightReading(kg=float(kg), at=at))
    out.extend(extra or [])
    out.sort(key=lambda r: r.at)
    return out


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #
def validate_readings(
    readings: Sequence[WeightReading],
    species: str,
) -> Tuple[List[WeightReading], str, List[str]]:
    """
    Screen recorded weights before any maths touches them.

    Returns (clean_readings, status, notes) and NEVER raises - a bad weight must
    degrade to "no weight signal", not break the check-in flow.

    status is one of:
      "ok"           - usable
      "insufficient" - fewer than MIN_READINGS usable readings
      "implausible"  - the LATEST reading failed screening, so we ask the owner
                       to re-check rather than silently scoring an older weight
    """
    notes: List[str] = []
    low, high = PLAUSIBLE_KG.get((species or "").lower(), PLAUSIBLE_KG_DEFAULT)

    dated = [r for r in (readings or []) if r is not None and r.kg is not None and r.at is not None]
    newest_supplied = max((r.at for r in dated), default=None)

    # Drop non-positive values and anything outside species bounds.
    usable: List[WeightReading] = []
    for r in dated:
        if r.kg <= 0 or not (low <= r.kg <= high):
            notes.append(f"reading {r.kg}kg outside plausible range for a {species}")
            continue
        usable.append(r)

    if not usable:
        return [], "insufficient", notes

    # If the NEWEST reading was the one rejected, say so rather than silently
    # scoring an older weight - the owner should be asked to re-check it.
    if newest_supplied is not None and max(r.at for r in usable) < newest_supplied:
        return usable, "implausible", notes

    # Chronological order, one reading per day (latest wins).
    usable.sort(key=lambda r: r.at)
    deduped: List[WeightReading] = []
    for r in usable:
        if deduped and deduped[-1].at == r.at:
            deduped[-1] = r
        else:
            deduped.append(r)

    # Reject implausible jumps between consecutive readings. A mistyped 4.0 for
    # 40.0 must never reach the escalation rules.
    kept: List[WeightReading] = [deduped[0]]
    dropped_latest = False
    for r in deduped[1:]:
        prev = kept[-1].kg
        if prev > 0 and abs(r.kg - prev) / prev > MAX_STEP_CHANGE:
            notes.append(
                f"reading {r.kg}kg on {r.at.isoformat()} changes >"
                f"{int(MAX_STEP_CHANGE * 100)}% from the previous reading - excluded"
            )
            dropped_latest = r.at == deduped[-1].at
            continue
        kept.append(r)
        dropped_latest = False

    if dropped_latest:
        return kept, "implausible", notes
    if len(kept) < MIN_READINGS:
        return kept, "insufficient", notes
    return kept, "ok", notes


# --------------------------------------------------------------------------- #
# Trend                                                                        #
# --------------------------------------------------------------------------- #
def compute_weight_trend(
    readings: Sequence[WeightReading],
    *,
    species: str,
    breed: Optional[str] = None,
    sex: Optional[str] = None,
    birth_date: Optional[date] = None,
    weight_management_plan: bool = False,
) -> WeightTrendResult:
    """
    Build the stored weight signal. Call this when a new weight is recorded
    (`pet_weight.recorded`), not on every weekly check-in.

    The baseline is the MEDIAN of up to BASELINE_WINDOW previous readings, so a
    single bad entry cannot drag it.
    """
    clean, status, notes = validate_readings(readings, species)

    if status != "ok":
        latest = clean[-1] if clean else None
        return WeightTrendResult(
            status=status,
            current_kg=latest.kg if latest else None,
            as_of=latest.at if latest else None,
            notes=notes,
        )

    current = clean[-1]
    window = clean[-(BASELINE_WINDOW + 1):-1]      # previous readings only
    baseline = median(r.kg for r in window)

    pct_change = (baseline - current.kg) / baseline * 100.0

    # Rate is measured over the gap since the MOST RECENT previous reading, not
    # across the whole baseline window: that is the interval in which the change
    # from the pet's observed normal actually appeared. Spanning the full window
    # would divide one month's loss across four and hide it.
    # Anchor the rate on the most recent previous reading that is at least
    # MIN_SPAN_WEEKS old. For monthly weigh-ins that is always the immediately
    # previous reading, so behaviour is unchanged; for weights arriving with
    # WEEKLY check-ins it steps back far enough that one noisy reading is
    # measured over a real interval instead of a single week.
    anchor = window[-1]
    for r in reversed(window):
        if (current.at - r.at).days / 7.0 >= MIN_SPAN_WEEKS:
            anchor = r
            break

    weeks_span = max((current.at - anchor.at).days / 7.0, MIN_SPAN_WEEKS)
    rate = pct_change * 4.0 / weeks_span

    status_label, is_growing = body_status(
        current.kg, species, breed, sex, birth_date, current.at
    )

    if rate > NOISE_FLOOR_PCT:
        direction = "loss"
    elif rate < -NOISE_FLOOR_PCT:
        direction = "gain"
    else:
        direction = "stable"

    # A growing animal losing weight matters more, so tighten the loss lines.
    sensitivity = GROWTH_LOSS_SENSITIVITY if is_growing else 1.0
    urgent_at = URGENT_LOSS_PCT * sensitivity

    managed_ceiling = MANAGED_LOSS_MAX_RATE.get(
        (species or "").lower(), MANAGED_LOSS_MAX_DEFAULT
    )
    managed = (
        weight_management_plan
        and direction == "loss"
        and rate <= managed_ceiling
    )
    if managed:
        notes.append("loss is within the recorded weight-management plan")

    # Trend-only escalation. The compound rule (loss alongside appetite, thirst
    # or energy signs) needs the current check-in, so it lives in red_flags.py.
    tier = None
    if direction == "loss" and not managed and rate >= urgent_at:
        tier = "urgent"
    elif (
        direction == "gain"
        and not is_growing
        and status_label != "below_reference"
        and abs(rate) >= MONITOR_GAIN_PCT
    ):
        # Suppressed for a pet below their breed reference for the same reason
        # weight_penalty() is: they are regaining. Telling the owner of an
        # underweight pet to review portions and treats would be worse advice
        # than saying nothing, and the two layers must not disagree about
        # whether the gain is a problem.
        tier = "monitor"

    return WeightTrendResult(
        status="ok",
        direction=direction,
        pct_change=round(pct_change, 2),
        rate_per_4w=round(rate, 2),
        baseline_kg=round(baseline, 2),
        current_kg=current.kg,
        as_of=current.at,
        weeks_span=round(weeks_span, 1),
        body_status=status_label,
        is_growing=is_growing,
        managed=managed,
        tier=tier,
        notes=notes,
    )


def trend_from_checkins(
    pet: PetProfile,
    checkins: Sequence[CheckInData],
    extra: Optional[Sequence[WeightReading]] = None,
) -> Optional[WeightTrendResult]:
    """
    Derive the weight signal straight from the check-in stream.

    This is the default path for pets whose weights arrive with their check-ins.
    Where a weight log is stored separately - computed once at weigh-in and read
    back each week, as the module docstring describes - pass that stored result
    to process_checkin() instead and this is never called.

    Returns None when no weight has ever been recorded, so the engine falls back
    to behaving exactly as it did before weight existed.
    """
    readings = readings_from_checkins(checkins, extra)
    if not readings:
        return None
    return compute_weight_trend(
        readings,
        species=pet.species,
        breed=pet.breed,
        sex=pet.sex,
        birth_date=pet.birth_date,
        weight_management_plan=pet.weight_management_plan,
    )


# --------------------------------------------------------------------------- #
# Score integration helpers                                                    #
# --------------------------------------------------------------------------- #
def staleness_factor(trend: Optional[WeightTrendResult], at) -> float:
    """
    How much of the weight signal still applies at date `at`. 1.0 while fresh,
    fading linearly to 0.0 once the last reading is STALE_WEEKS old.
    """
    when = _as_date(at)
    if trend is None or trend.as_of is None or when is None:
        return 0.0
    weeks = (when - trend.as_of).days / 7.0
    if weeks <= FRESH_WEEKS:
        return 1.0
    if weeks >= STALE_WEEKS:
        return 0.0
    return (STALE_WEEKS - weeks) / (STALE_WEEKS - FRESH_WEEKS)


def weight_penalty(
    trend: Optional[WeightTrendResult],
    at,
    cap: Optional[float] = None,
) -> float:
    """
    Points removed from the 0-100 score for a weight change in EITHER direction.
    Zero unless there is a usable, fresh, unsuppressed trend past the noise floor.

    Ramps linearly from NOISE_FLOOR_PCT (0 points) to the escalation line for
    that direction (`cap`, defaulting to MAX_WEIGHT_PENALTY), where the red-flag
    layer takes over. `cap` is how scoring.py applies a weighting profile's
    `weight_cap_multiplier` without this module needing to know profiles exist -
    it changes how tall the ramp is, never where it starts or tops out, so the
    escalation boundaries are untouched.
    Because the ramp is driven by the RATE - percent of body weight per 4 weeks -
    a gain and a loss of the same size cost the same points, and a fixed number
    of kilos means what it should for the animal carrying them: 5kg off a beagle
    is a collapse, 5kg off a Great Dane is a fortnight of wet weather.

    Two suppressions apply to gain and have no equivalent for loss, because the
    same number means something different when a pet is meant to be putting
    weight on:

      * growth - a puppy or kitten gaining is the intended outcome, and there is
        no adult range to compare them against in the first place;
      * recovery - a pet already below their breed reference regaining weight is
        the problem resolving, not a new one. Deducting there would take points
        off a pet for getting better, and would fall hardest on the pets that
        had the furthest to come back.
    """
    if trend is None or trend.status != "ok":
        return 0.0
    if cap is None:
        cap = MAX_WEIGHT_PENALTY

    if trend.direction == "loss":
        if trend.managed:
            return 0.0
        rate, escalation_at = trend.rate_per_4w, URGENT_LOSS_PCT
    elif trend.direction == "gain":
        if trend.is_growing or trend.body_status == "below_reference":
            return 0.0
        # rate_per_4w is signed - negative for gain - so take the magnitude.
        rate, escalation_at = abs(trend.rate_per_4w), URGENT_GAIN_PCT
    else:
        return 0.0

    if rate <= NOISE_FLOOR_PCT:
        return 0.0

    span = escalation_at - NOISE_FLOOR_PCT
    ramp = min(1.0, (rate - NOISE_FLOOR_PCT) / span)
    return ramp * cap * staleness_factor(trend, at)


def declining_strength(trend: Optional[WeightTrendResult], at) -> float:
    """
    How strongly weight counts towards the score's multiple-indicators-declining
    tally, as a fraction in [0.0, 1.0].

    A fraction rather than a boolean so the compound deduction fades in step with
    the direct penalty. A hard cut-off meant a signal one day short of
    STALE_WEEKS carried its full compound weight and the next week carried none,
    moving the score by double figures on no new data.
    """
    if trend is None or trend.status != "ok" or trend.direction != "loss":
        return 0.0
    if trend.managed or trend.rate_per_4w < NOTABLE_LOSS_PCT:
        return 0.0
    return staleness_factor(trend, at)


def signal_quality(trend: Optional[WeightTrendResult], at) -> str:
    """
    How far the score can trust the weight signal at date `at`. Lets scoring.py
    adjust its stated confidence without duplicating the staleness and status
    rules that belong to this module.

      "none"       - no trend at all: nothing recorded, or too few readings to
                     compare. The score is identical to the pre-weight engine in
                     both cases, so confidence is untouched.
      "ok"         - a usable trend, fresh enough to apply in full.
      "stale"      - a real trend that is fading with age. The pet needs
                     re-weighing, not re-checking.
      "unreliable" - the latest reading failed screening. The owner should
                     correct the entry.

    "stale" and "unreliable" are kept apart because they call for different
    things from the owner, and the score says so in different words.
    """
    if trend is None or trend.status == "insufficient":
        return "none"
    if trend.status != "ok":
        return "unreliable"
    return "ok" if staleness_factor(trend, at) >= 1.0 else "stale"
