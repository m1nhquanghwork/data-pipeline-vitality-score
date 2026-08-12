"""
WS5 - product-state and safety tests for the PHAIVIT engine.

Covers the eight states the actionable plan requires:
  1. Building baseline with fewer than four total check-ins
  2. First score generated on the fourth completed check-in
  3. Bright / Medium Green for stable check-ins
  4. Watch or Action Needed for multiple declining indicators
  5. Emergency override suppresses the score
  6. Monitor override attaches an advisory while preserving the score
  7. High-energy breed weighting affects activity impact
  8. Malformed or missing optional fields fail safely

...and the weight subsystem (weight.py) feeding those same layers:
  9.  Inert with no, insufficient or implausible weight data
  10. Trend maths: noise floor, median baseline, rate normalised by elapsed time
  11. Monthly cadence: carry-forward between weigh-ins, decay once stale
  12. Escalations: severe loss, loss alongside another sign, rapid gain
  13. Suppressions: managed weight plans, growing puppies
  14. Weighting profiles stay normalised when body status shifts them

Runs two ways:
  * with pytest:   python -m pytest test_case/test_phavit.py
  * standalone:    python test_case/test_phavit.py   (no pytest needed)
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

# Allow standalone execution (`python test_case/test_phavit.py`) by putting the
# repo root on sys.path. Under pytest the root conftest.py already handles this.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phavit.models import CheckInData, PetProfile, VitalityScoreResult, WeightReading
from phavit.pipeline import process_checkin
from phavit.red_flags import EMERGENCY_SIGNS
from phavit.scoring import BASE_PROFILES, VitalityScoreEngine
from phavit.weight import compute_weight_trend, staleness_factor, weight_penalty

TEST_DIR = Path(__file__).resolve().parent

VALID_BANDS = {
    "Bright Green", "Medium Green", "Watch", "Action Needed", "Building Baseline",
}

# Disease NAMES must NEVER surface in a user-facing explanation. Note we do NOT
# list "diagnosis"/"disease" here: the engine deliberately uses them in its safe
# disclaimers ("this is a wellbeing trend, not a diagnosis").
DISEASE_WORDS = [
    "diabetes", "cancer", "parvo", "kidney disease", "pancreatitis",
    "arthritis", "tumour", "tumor", "leukaemia", "leukemia",
]

# Fixed dates so the weight tests never drift relative to "now".
CHECKIN_DAY = datetime(2026, 7, 20)
LAST_WEIGH_IN = date(2026, 7, 18)


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #
def mk_checkin(pet_id: str = "pet_1", **kw) -> CheckInData:
    """A check-in with sensible defaults; override any field via kwargs."""
    base = dict(
        pet_id=pet_id,
        timestamp=datetime(2026, 7, 20),
        appetite_score=4,
        energy_score=4,
        sleep_quality_score=4,
        activity_minutes=60,
    )
    base.update(kw)
    return CheckInData(**base)


def make_history(pet_id: str, n: int, appetite=4, energy=4, sleep=4, activity=60) -> List[CheckInData]:
    """A stable synthetic baseline: the same scores repeated n times."""
    return [
        CheckInData(
            pet_id=pet_id,
            timestamp=datetime(2026, 1, i + 1),
            appetite_score=appetite,
            energy_score=energy,
            sleep_quality_score=sleep,
            activity_minutes=activity,
        )
        for i in range(n)
    ]


def history_with(pet_id: str, n_clean: int = 3, **flags) -> List[CheckInData]:
    """
    Stable history whose MOST RECENT entry carries the given flags. Used to set
    up the "repeated sign" rules, which look back over the last three check-ins.
    """
    return make_history(pet_id, n_clean) + [mk_checkin(pet_id, **flags)]


def make_pet(pet_id="pet_1", name="Rex", high_energy=False, worming=True) -> PetProfile:
    return PetProfile(
        pet_id=pet_id, name=name, species="dog", breed="Labrador", sex="male",
        post_code=4217, birth_date=date(2020, 1, 1), is_high_energy=high_energy,
        worming_compliant=worming, vaccination_current=True,
    )


# --------------------------------------------------------------------------- #
# Weight builders                                                              #
# --------------------------------------------------------------------------- #
def monthly_weights(kgs: List[float], last_on: date = LAST_WEIGH_IN) -> List[WeightReading]:
    """Readings ~4 weeks apart, oldest first, ending on `last_on`."""
    n = len(kgs)
    return [
        WeightReading(kg=kg, at=last_on - timedelta(weeks=4 * (n - 1 - i)))
        for i, kg in enumerate(kgs)
    ]


def trend_for(kgs, *, species="dog", breed="Labrador", sex="male",
              birth_date=date(2020, 1, 1), plan=False, last_on=LAST_WEIGH_IN):
    """The stored monthly weight signal for a series of readings."""
    return compute_weight_trend(
        monthly_weights(kgs, last_on),
        species=species, breed=breed, sex=sex,
        birth_date=birth_date, weight_management_plan=plan,
    )


def score_with(trend, pet=None, **checkin_kw):
    """Run a full check-in with a stored weight trend attached."""
    pet = pet or make_pet()
    return process_checkin(
        pet,
        make_history(pet.pet_id, 4),
        mk_checkin(pet.pet_id, timestamp=CHECKIN_DAY, **checkin_kw),
        weight_trend=trend,
    )


# --------------------------------------------------------------------------- #
# Typo-tolerant loaders for the real JSON fixtures                             #
# --------------------------------------------------------------------------- #
def load_pet_profile(p: dict) -> PetProfile:
    return PetProfile(
        pet_id=p["pet_id"],
        name=p["pet_name"],                    # JSON uses pet_name
        species=p["species"],
        breed=p["breed"],
        sex=p["sex"],
        post_code=int(p["postcode"]),          # JSON uses postcode
        birth_date=date.fromisoformat(p["birth_date"]),
        is_high_energy=p["is_high_energy"],
        worming_compliant=p["worming_compliant"],
        vaccination_current=p["vaccination_current"],
        weight_management_plan=p.get("weight_management_plan", False),
    )


def load_checkin(c: dict) -> CheckInData:
    return CheckInData(
        pet_id=c["pet_id"],
        timestamp=datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00")),
        # `appetite_scorew` is a typo in the fixtures; fall back gracefully.
        appetite_score=c.get("appetite_score", c.get("appetite_scorew")),
        energy_score=c["energy_score"],
        sleep_quality_score=c["sleep_quality_score"],
        activity_minutes=c["activity_minutes"],
        toileting_status=c.get("toileting_status", "normal"),
        water_intake_status=c.get("water_intake_status", "normal"),
        blood_in_stool=c.get("blood_in_stool", False),
        vomiting=c.get("vomiting", False),
        # `diarrhea` (and non-ASCII variants) are typos in the fixtures.
        diarrhoea=c.get("diarrhoea", c.get("diarrhea", False)),
        breathing_difficulty=c.get("breathing_difficulty", False),
        collapse=c.get("collapse", False),
        seizure=c.get("seizure", False),
        suspected_toxin_ingestion=c.get("suspected_toxin_ingestion", False),
        unable_to_urinate=c.get("unable_to_urinate", False),
        severe_bleeding=c.get("severe_bleeding", False),
        tick_found=c.get("tick_found", False),
        pain_or_discomfort_signs=c.get("pain_or_discomfort_signs", False),
        weight_kg=c.get("weight_kg"),
        owner_concern_level=c.get("owner_concern_level"),
    )


def load_previous_checkins(data: dict, pet_id: str) -> List[CheckInData]:
    """
    A scenario may declare its own history. When it does not, fall back to the
    synthetic stable baseline so the older fixtures keep working unchanged.
    """
    raw = data.get("previous_checkins")
    if raw is None:
        return make_history(pet_id, 4)
    return [load_checkin(c) for c in raw]


def load_weight_trend(data: dict, pet: PetProfile):
    """Build the stored monthly weight signal from a scenario's `weight_log`."""
    log = data.get("weight_log") or {}
    raw = log.get("readings")
    if not raw:
        return None
    readings = [
        WeightReading(kg=float(r["kg"]), at=date.fromisoformat(r["at"])) for r in raw
    ]
    return compute_weight_trend(
        readings,
        species=pet.species,
        breed=pet.breed,
        sex=pet.sex,
        birth_date=pet.birth_date,
        weight_management_plan=pet.weight_management_plan,
    )


def run_scenario(path: Path):
    """
    Load one scenario JSON and run it through the full pipeline.

    Schema (everything except pet_profile / check_in_data is optional):
      scenario           - one-line human description
      pet_profile        - as before, plus optional weight_management_plan
      previous_checkins  - explicit history; synthetic stable baseline if absent
      weight_log.readings- [{kg, at}] monthly weigh-ins, any order
      check_in_data      - the current weekly check-in
      expected           - declared outcome, asserted by the scenario test below
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    pet = load_pet_profile(data["pet_profile"])
    trend = load_weight_trend(data, pet)
    result = process_checkin(
        pet,
        load_previous_checkins(data, pet.pet_id),
        load_checkin(data["check_in_data"]),
        weight_trend=trend,
    )
    return data, pet, result


def _assert_no_disease_terms(text: str) -> None:
    low = text.lower()
    for word in DISEASE_WORDS:
        assert word not in low, f"disease term '{word}' leaked into: {text!r}"


# --------------------------------------------------------------------------- #
# 1. Building baseline with fewer than four total check-ins                    #
# --------------------------------------------------------------------------- #
def test_building_baseline_under_four_total():
    pet = make_pet()
    # 2 previous + current = 3 total -> still building.
    r = process_checkin(pet, make_history(pet.pet_id, 2), mk_checkin(pet.pet_id))
    assert r.score is None
    assert r.band == "Building Baseline"
    assert r.baseline_status == "building"
    assert r.confidence == "low"


# --------------------------------------------------------------------------- #
# 2. First score generated on the fourth completed check-in                    #
# --------------------------------------------------------------------------- #
def test_first_score_unlocks_on_fourth_checkin():
    pet = make_pet()
    # 3 previous + current = 4 total -> first score.
    r4 = process_checkin(pet, make_history(pet.pet_id, 3), mk_checkin(pet.pet_id))
    assert r4.score is not None
    assert r4.baseline_status == "established"

    # And exactly one fewer (2 previous) must still be building — proves the boundary.
    r3 = process_checkin(pet, make_history(pet.pet_id, 2), mk_checkin(pet.pet_id))
    assert r3.score is None


# --------------------------------------------------------------------------- #
# 3. Bright / Medium Green for stable check-ins                                #
# --------------------------------------------------------------------------- #
def test_stable_checkin_scores_green():
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 4), mk_checkin(pet.pet_id))
    assert r.score == 100
    assert r.band in ("Bright Green", "Medium Green")
    assert r.override is None


# --------------------------------------------------------------------------- #
# 4. Watch or Action Needed for multiple declining indicators                  #
# --------------------------------------------------------------------------- #
def test_multiple_declines_drop_the_band():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4, appetite=4, energy=4, sleep=4, activity=60)
    current = mk_checkin(pet.pet_id, appetite_score=2, energy_score=2, activity_minutes=20)
    r = process_checkin(pet, hist, current)
    assert r.score < 70
    assert r.band in ("Watch", "Action Needed")
    # The multi-decline signal should be reflected in the drivers.
    assert any("several indicators" in d for d in r.drivers)


# --------------------------------------------------------------------------- #
# 5. Emergency override suppresses the score                                   #
# --------------------------------------------------------------------------- #
def test_emergency_override_suppresses_score():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)   # plenty of history, otherwise good vitals
    for sign in ("collapse", "suspected_toxin_ingestion"):
        r = process_checkin(pet, hist, mk_checkin(pet.pet_id, **{sign: True}))
        assert r.score is None, sign
        assert r.band == "Action Needed", sign
        assert r.override is not None and r.override.severity_tier == "emergency", sign
        _assert_no_disease_terms(r.explanation)


def test_urgent_override_suppresses_score():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    # Blood in stool with low energy -> urgent.
    r = process_checkin(pet, hist, mk_checkin(pet.pet_id, blood_in_stool=True, energy_score=2))
    assert r.score is None
    assert r.band == "Action Needed"
    assert r.override.severity_tier == "urgent"
    assert r.override.trigger == "blood_in_stool"


# --------------------------------------------------------------------------- #
# 6. Monitor override attaches an advisory while preserving the score          #
# --------------------------------------------------------------------------- #
def test_monitor_override_keeps_score_and_adds_advisory():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    r = process_checkin(pet, hist, mk_checkin(pet.pet_id, vomiting=True))  # single GI upset
    assert r.score is not None                      # score preserved
    assert r.override is not None and r.override.severity_tier == "monitor"
    assert r.override.recommended_user_pathway in r.explanation  # advisory attached
    _assert_no_disease_terms(r.explanation)


# --------------------------------------------------------------------------- #
# 7. High-energy breed weighting affects activity impact                       #
# --------------------------------------------------------------------------- #
def test_high_energy_weighting_amplifies_activity_drop():
    hist_normal = make_history("pet_n", 4)
    hist_high = make_history("pet_h", 4)
    # Only activity drops; every other vital equals baseline.
    drop = dict(activity_minutes=20)
    normal = process_checkin(make_pet("pet_n", high_energy=False),
                             hist_normal, mk_checkin("pet_n", **drop))
    high = process_checkin(make_pet("pet_h", high_energy=True),
                           hist_high, mk_checkin("pet_h", **drop))
    # The same activity drop must hurt the high-energy breed more.
    assert high.score < normal.score


# --------------------------------------------------------------------------- #
# 8. Malformed or missing optional fields fail safely                          #
# --------------------------------------------------------------------------- #
def test_missing_optional_fields_are_safe():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    # Only the required fields supplied; every optional field falls back to default.
    minimal = CheckInData(
        pet_id=pet.pet_id, timestamp=datetime(2026, 7, 20),
        appetite_score=4, energy_score=4, sleep_quality_score=4, activity_minutes=60,
    )
    r = process_checkin(pet, hist, minimal)
    assert isinstance(r, VitalityScoreResult)
    assert r.band in VALID_BANDS
    assert r.score is None or 0 <= r.score <= 100


def test_loader_tolerates_fixture_typos():
    # A payload carrying the real fixtures' misspellings must still load and run.
    data = {
        "pet_profile": {
            "pet_id": "pet_x", "pet_name": "Typo", "species": "dog", "breed": "Vizsla",
            "sex": "female", "postcode": "4000", "birth_date": "2022-01-01",
            "is_high_energy": True, "worming_compliant": True, "vaccination_current": True,
        },
        "check_in_data": {
            "pet_id": "pet_x", "timestamp": "2026-04-29T10:15:00Z",
            "appetite_scorew": 3, "energy_score": 4, "sleep_quality_score": 4,
            "activity_minutes": 65, "diarrhea": False,
        },
    }
    pet = load_pet_profile(data["pet_profile"])
    current = load_checkin(data["check_in_data"])
    assert current.appetite_score == 3          # picked up despite the typo key
    r = process_checkin(pet, make_history("pet_x", 4), current)
    assert r.band in VALID_BANDS


# --------------------------------------------------------------------------- #
# Fixture smoke test: every real JSON loads, runs, and stays safe              #
# --------------------------------------------------------------------------- #
def test_all_fixtures_load_run_and_stay_non_diagnostic():
    fixtures = sorted(TEST_DIR.glob("*.json"))
    assert fixtures, "no JSON fixtures found in test_case/"
    for path in fixtures:
        _, _, r = run_scenario(path)
        assert r.band in VALID_BANDS, path.name
        assert r.score is None or 0 <= r.score <= 100, path.name
        assert r.baseline_status in {"established", "building", "override"}, path.name
        _assert_no_disease_terms(r.explanation)


def test_every_scenario_matches_its_declared_expectation():
    """
    Each fixture declares its expected outcome in the JSON itself, so a vet or
    product reviewer can read the scenario and its expectation without opening
    any Python. The expectation is written BEFORE the engine runs, the same
    discipline the notebook harness uses.
    """
    fixtures = sorted(TEST_DIR.glob("*.json"))
    for path in fixtures:
        data, _, r = run_scenario(path)
        exp = data.get("expected")
        assert exp, f"{path.name} declares no `expected` block"
        who = path.name

        assert r.band == exp["band"], f"{who}: band {r.band!r} != {exp['band']!r}"
        assert (r.score is not None) == exp["score_present"], f"{who}: score {r.score!r}"

        if "score" in exp:
            assert r.score == exp["score"], f"{who}: score {r.score!r} != {exp['score']!r}"
        for field in ("confidence", "trend", "baseline_status"):
            if field in exp:
                assert getattr(r, field) == exp[field], f"{who}: {field} {getattr(r, field)!r}"

        tier = r.override.severity_tier if r.override else None
        assert tier == exp.get("override_tier"), f"{who}: tier {tier!r}"
        if "override_trigger" in exp:
            trigger = r.override.trigger if r.override else None
            assert trigger == exp["override_trigger"], f"{who}: trigger {trigger!r}"

        reason = r.override.clinical_reason_for_escalation if r.override else ""
        for fragment in exp.get("override_reason_includes", []):
            assert fragment in reason, f"{who}: reason {reason!r} missing {fragment!r}"
        for fragment in exp.get("override_reason_excludes", []):
            assert fragment not in reason, f"{who}: reason {reason!r} should not mention {fragment!r}"

        wt = r.weight_trend
        for key, attr in (
            ("weight_status", "status"),
            ("weight_direction", "direction"),
            ("weight_body_status", "body_status"),
            ("weight_managed", "managed"),
            ("weight_is_growing", "is_growing"),
        ):
            if key in exp:
                assert wt is not None, f"{who}: expected {key} but no weight_log"
                assert getattr(wt, attr) == exp[key], (
                    f"{who}: {attr} {getattr(wt, attr)!r} != {exp[key]!r}"
                )

        for fragment in exp.get("drivers_include", []):
            assert any(fragment in d for d in r.drivers), f"{who}: driver {fragment!r} missing from {r.drivers}"
        if "explanation_includes" in exp:
            assert exp["explanation_includes"] in r.explanation, who


# --------------------------------------------------------------------------- #
# 9. Weight: inert without usable data (backwards compatibility)               #
# --------------------------------------------------------------------------- #
def test_no_weight_data_leaves_score_untouched():
    """The whole feature must be inert when no weight has been recorded."""
    pet = make_pet()
    without = process_checkin(pet, make_history(pet.pet_id, 4), mk_checkin(pet.pet_id))
    assert without.score == 100
    assert without.weight_trend is None


def test_single_reading_is_insufficient_and_inert():
    trend = trend_for([30.0])
    assert trend.status == "insufficient"
    assert weight_penalty(trend, CHECKIN_DAY) == 0.0
    assert score_with(trend).score == 100


def test_stable_weight_costs_nothing():
    trend = trend_for([30.0, 30.2, 29.9, 30.1])
    assert trend.direction == "stable"
    assert score_with(trend).score == 100


# --------------------------------------------------------------------------- #
# 10. Weight: trend maths                                                      #
# --------------------------------------------------------------------------- #
def test_noise_floor_absorbs_small_changes():
    # ~1.5% down: scales, hydration, time of day.
    trend = trend_for([30.0, 30.0, 30.0, 29.55])
    assert trend.direction == "stable"
    assert weight_penalty(trend, CHECKIN_DAY) == 0.0


def test_median_baseline_resists_one_bad_entry():
    # A single high outlier inside the window must not create a fake "loss".
    clean = trend_for([30.0, 30.0, 30.0, 30.0])
    with_outlier = trend_for([30.0, 34.0, 30.0, 30.0])
    assert with_outlier.baseline_kg == clean.baseline_kg


def test_notable_loss_lowers_the_score_with_a_driver():
    trend = trend_for([30.0, 30.0, 30.0, 28.2])          # ~6% down
    assert trend.direction == "loss"
    r = score_with(trend)
    assert r.score is not None and r.score < 100
    assert any("weight below usual" in d for d in r.drivers)
    # Monthly cadence: the copy must date the reading, not imply it is from this week.
    assert "reading recorded on" in r.explanation
    # And reassuring copy must not contradict a driver that just cost points.
    assert "tracking in line with their usual baseline" not in r.explanation


def test_rate_is_normalised_by_elapsed_time():
    """The same 6% loss spread over 12 weeks is gentler than over 4."""
    fast = compute_weight_trend(
        [WeightReading(30.0, date(2026, 6, 20)), WeightReading(28.2, date(2026, 7, 18))],
        species="dog", breed="Labrador", sex="male", birth_date=date(2020, 1, 1),
    )
    slow = compute_weight_trend(
        [WeightReading(30.0, date(2026, 4, 25)), WeightReading(28.2, date(2026, 7, 18))],
        species="dog", breed="Labrador", sex="male", birth_date=date(2020, 1, 1),
    )
    assert fast.rate_per_4w > slow.rate_per_4w
    assert weight_penalty(fast, CHECKIN_DAY) > weight_penalty(slow, CHECKIN_DAY)


# --------------------------------------------------------------------------- #
# 11. Weight: data quality                                                     #
# --------------------------------------------------------------------------- #
def test_mistyped_weight_never_fires_an_alert():
    """4.0 typed for 40.0 must be excluded, not treated as an 87% collapse."""
    trend = trend_for([30.0, 30.0, 30.0, 3.0])
    assert trend.status == "implausible"
    r = score_with(trend)
    assert r.score is not None              # no override
    assert r.score == 100                   # and no deduction
    assert r.override is None


def test_out_of_species_range_is_discarded():
    trend = trend_for([5.0, 5.0, 5.0, 60.0], species="cat", breed="Siamese")
    assert trend.status in ("implausible", "insufficient")
    assert weight_penalty(trend, CHECKIN_DAY) == 0.0


# --------------------------------------------------------------------------- #
# 12. Weight: monthly cadence - carry-forward and staleness                    #
# --------------------------------------------------------------------------- #
def test_penalty_is_stable_between_weigh_ins():
    """
    Carry-forward: the same stored trend applied on consecutive weekly check-ins
    must produce the same deduction, so the score does not sawtooth.
    """
    trend = trend_for([30.0, 30.0, 30.0, 28.2], last_on=date(2026, 7, 18))
    week1 = weight_penalty(trend, datetime(2026, 7, 20))
    week2 = weight_penalty(trend, datetime(2026, 7, 27))
    week3 = weight_penalty(trend, datetime(2026, 8, 3))
    assert week1 == week2 == week3 > 0


def test_stale_trend_decays_to_nothing():
    trend = trend_for([30.0, 30.0, 30.0, 28.2], last_on=date(2026, 1, 10))
    assert staleness_factor(trend, datetime(2026, 2, 20)) == 1.0     # < 8 weeks
    mid = staleness_factor(trend, datetime(2026, 3, 20))             # between 8 and 12
    assert 0.0 < mid < 1.0
    assert staleness_factor(trend, datetime(2026, 7, 20)) == 0.0     # long stale
    assert weight_penalty(trend, datetime(2026, 7, 20)) == 0.0


# --------------------------------------------------------------------------- #
# 13. Weight: safety escalations and suppressions                              #
# --------------------------------------------------------------------------- #
def test_severe_loss_escalates_to_urgent():
    trend = trend_for([30.0, 30.0, 30.0, 26.4])          # ~12% down
    r = score_with(trend)
    assert r.score is None
    assert r.band == "Action Needed"
    assert r.override.severity_tier == "urgent"
    assert r.override.trigger == "notable_weight_loss"
    _assert_no_disease_terms(r.explanation)


def test_loss_with_low_appetite_escalates_even_when_not_repeated():
    """
    Appetite loss alone needs repetition to escalate; alongside real weight loss
    a first occurrence should still be caught.
    """
    trend = trend_for([30.0, 30.0, 30.0, 28.2])          # ~6% down, below the urgent line
    r = score_with(trend, appetite_score=2)
    assert r.score is None
    assert r.override.trigger == "weight_loss_with_signs"
    assert r.override.severity_tier == "urgent"
    _assert_no_disease_terms(r.explanation)


def test_rapid_gain_is_advisory_not_a_deduction():
    trend = trend_for([30.0, 30.0, 30.0, 33.0])          # ~10% up
    r = score_with(trend)
    assert r.score is not None                            # score preserved
    assert r.override is not None and r.override.severity_tier == "monitor"
    assert r.override.trigger == "rapid_weight_gain"
    assert not any("weight below usual" in d for d in r.drivers)


def test_growing_puppy_gain_is_not_flagged():
    puppy_birth = date(2026, 2, 1)                        # ~5 months at the reading
    trend = trend_for([12.0, 12.0, 12.0, 13.5], birth_date=puppy_birth)
    assert trend.is_growing
    assert trend.tier is None
    assert score_with(trend).override is None


def test_managed_loss_does_not_alarm_or_deduct():
    """An owner successfully slimming an overweight dog must not be alerted."""
    kgs = [40.0, 40.0, 40.0, 37.6]                        # ~6%/4wk, within the safe rate
    unmanaged = trend_for(kgs, plan=False)
    managed = trend_for(kgs, plan=True)

    assert unmanaged.tier is None and weight_penalty(unmanaged, CHECKIN_DAY) > 0
    assert managed.managed is True
    assert weight_penalty(managed, CHECKIN_DAY) == 0.0
    assert score_with(managed).score == 100


def test_loss_faster_than_the_plan_allows_still_escalates():
    trend = trend_for([40.0, 40.0, 40.0, 35.0], plan=True)   # ~12.5%/4wk
    assert trend.managed is False
    assert trend.tier == "urgent"


# --------------------------------------------------------------------------- #
# 14. Weight: weighting profiles stay normalised                               #
# --------------------------------------------------------------------------- #
def test_every_profile_sums_to_one():
    for name, profile in BASE_PROFILES.items():
        total = profile.appetite + profile.energy + profile.sleep + profile.activity
        assert abs(total - 1.0) < 1e-9, name


def test_body_status_bump_renormalises():
    """Shifting emphasis to activity must not raise the total deduction capacity."""
    pet = make_pet()
    heavy = trend_for([44.0, 44.0, 44.0, 44.0])          # well above the Labrador range
    assert heavy.body_status in ("above_reference", "well_above_reference")

    w = VitalityScoreEngine(pet, [], weight_trend=heavy)._select_weights()
    total = w.appetite + w.energy + w.sleep + w.activity
    assert abs(total - 1.0) < 1e-9
    assert w.activity > BASE_PROFILES["standard"].activity


def test_above_reference_amplifies_an_activity_drop():
    pet = make_pet()
    in_range = trend_for([32.0, 32.0, 32.0, 32.0])
    heavy = trend_for([44.0, 44.0, 44.0, 44.0])
    assert in_range.body_status == "in_reference"

    normal = score_with(in_range, pet=pet, activity_minutes=20)
    above = score_with(heavy, pet=pet, activity_minutes=20)
    assert above.score < normal.score


def test_unknown_breed_has_no_reference():
    trend = trend_for([30.0, 30.0, 30.0, 30.0], breed="Labrador cross")
    assert trend.body_status == "no_reference"


# --------------------------------------------------------------------------- #
# Output contract                                                              #
# --------------------------------------------------------------------------- #
def test_weight_trend_is_carried_on_every_path():
    trend = trend_for([30.0, 30.0, 30.0, 28.2])
    scored = score_with(trend)                                   # scored path
    override = score_with(trend, collapse=True)                  # emergency path
    assert scored.weight_trend is trend
    assert override.weight_trend is trend
    assert override.score is None


# =========================================================================== #
# 15. System analysis                                                         #
#                                                                             #
# These 20 probe the engine's behaviour rather than its product states:       #
# band boundaries, monotonicity, what the baseline is and is not sensitive    #
# to, red-flag precedence, and how the weight signal interacts with the       #
# existing math. Several of them pin down behaviour that is currently only    #
# implicit, so a future tuning change fails loudly instead of drifting.       #
# =========================================================================== #

# --- Band boundaries and clamping ------------------------------------------ #
def test_band_boundaries_are_exact():
    """The published cut-offs are 85 / 70 / 50 - inclusive at the lower edge."""
    band = VitalityScoreEngine._band
    assert band(100) == "Bright Green"
    assert band(85) == "Bright Green"
    assert band(84) == "Medium Green"
    assert band(70) == "Medium Green"
    assert band(69) == "Watch"
    assert band(50) == "Watch"
    assert band(49) == "Action Needed"
    assert band(0) == "Action Needed"


def test_score_is_clamped_to_zero_under_extreme_decline():
    """Deductions far exceeding 100 must floor at 0, never go negative."""
    pet = make_pet(worming=False)
    hist = make_history(pet.pet_id, 4, appetite=5, energy=5, sleep=5, activity=60)
    current = mk_checkin(pet.pet_id, appetite_score=1, energy_score=1,
                         sleep_quality_score=1, activity_minutes=0)
    r = process_checkin(pet, hist, current)
    assert r.score == 0
    assert r.band == "Action Needed"


def test_improvement_above_baseline_never_exceeds_100():
    """Only downward deviations count; a great week cannot bank credit."""
    pet = make_pet()
    hist = make_history(pet.pet_id, 4, appetite=2, energy=2, sleep=2, activity=20)
    current = mk_checkin(pet.pet_id, appetite_score=5, energy_score=5,
                         sleep_quality_score=5, activity_minutes=200)
    r = process_checkin(pet, hist, current)
    assert r.score == 100


# --- Monotonicity ---------------------------------------------------------- #
def test_score_decreases_monotonically_with_appetite():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    scores = [
        process_checkin(pet, hist, mk_checkin(pet.pet_id, appetite_score=a)).score
        for a in (4, 3, 2, 1)
    ]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == len(scores), "each further drop must cost something"


def test_weight_penalty_is_monotonic_in_loss_rate():
    penalties = [
        weight_penalty(trend_for([30.0, 30.0, 30.0, kg]), CHECKIN_DAY)
        for kg in (29.1, 28.5, 27.9, 27.3)      # 3%, 5%, 7%, 9% down
    ]
    assert penalties == sorted(penalties)
    assert len(set(penalties)) == len(penalties)


def test_weight_penalty_caps_at_the_escalation_boundary():
    """Past the urgent line the deduction stops growing - Layer 2 takes over."""
    at_line = weight_penalty(trend_for([30.0, 30.0, 30.0, 27.0]), CHECKIN_DAY)   # 10%
    far_past = weight_penalty(trend_for([30.0, 30.0, 30.0, 24.0]), CHECKIN_DAY)  # 20%
    assert at_line == far_past == 15.0


# --- What the baseline is (and is not) sensitive to ------------------------ #
def test_current_checkin_is_excluded_from_its_own_baseline():
    """
    WS2 boundary guard. Baseline is PREVIOUS check-ins only; folding the current
    one in would soften every drop against itself.
    """
    pet = make_pet()
    hist = make_history(pet.pet_id, 4, appetite=4)
    r = process_checkin(pet, hist, mk_checkin(pet.pet_id, appetite_score=1))
    # Baseline 4, drop 3 -> 3 * 0.30 * 60 = 54. Including current would give 2.4.
    assert r.score == 46


def test_confidence_upgrades_with_history_length():
    pet = make_pet()
    assert process_checkin(pet, make_history(pet.pet_id, 3), mk_checkin(pet.pet_id)).confidence == "moderate"
    assert process_checkin(pet, make_history(pet.pet_id, 4), mk_checkin(pet.pet_id)).confidence == "moderate"
    assert process_checkin(pet, make_history(pet.pet_id, 5), mk_checkin(pet.pet_id)).confidence == "high"


def test_baseline_mean_is_pulled_by_a_single_bad_week():
    """
    Documents a real asymmetry: the wellbeing baseline is a MEAN over history,
    so one bad week lowers the bar and flatters the next score. The weight
    module deliberately uses a median instead.
    """
    pet = make_pet()
    clean = make_history(pet.pet_id, 4, appetite=4)
    with_dip = make_history(pet.pet_id, 3, appetite=4) + make_history(pet.pet_id, 1, appetite=2)
    current = mk_checkin(pet.pet_id, appetite_score=3)
    assert process_checkin(pet, with_dip, current).score > process_checkin(pet, clean, current).score


# --- Red-flag precedence --------------------------------------------------- #
def test_emergency_outranks_urgent():
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 4),
                        mk_checkin(pet.pet_id, collapse=True, blood_in_stool=True, energy_score=2))
    assert r.override.severity_tier == "emergency"
    assert r.override.trigger == "collapse"


def test_emergency_outranks_weight_loss():
    r = score_with(trend_for([30.0, 30.0, 30.0, 26.4]), collapse=True)   # 12% loss
    assert r.override.severity_tier == "emergency"
    assert r.override.trigger == "collapse"


def test_blood_in_stool_outranks_weight_loss():
    """Both are urgent; the acute sign is the one the owner is told about."""
    r = score_with(trend_for([30.0, 30.0, 30.0, 26.4]), blood_in_stool=True)
    assert r.override.trigger == "blood_in_stool"


def test_urgent_outranks_monitor():
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 4),
                        mk_checkin(pet.pet_id, blood_in_stool=True, tick_found=True))
    assert r.override.severity_tier == "urgent"
    assert r.score is None


# --- Weight interacting with the existing math ----------------------------- #
def test_weight_loss_with_activity_drop_trips_multi_decline():
    """Weight counts towards the signal-vs-noise tally alongside the vitals."""
    r = score_with(trend_for([30.0, 30.0, 30.0, 28.2]), activity_minutes=20)  # 6% down
    assert any("several indicators declining together" in d for d in r.drivers)
    assert any("weight below usual" in d for d in r.drivers)


def test_sub_notable_loss_deducts_but_does_not_count_as_declining():
    """A 4% loss is worth points but is not yet a 'declining indicator'."""
    r = score_with(trend_for([30.0, 30.0, 30.0, 28.8]), activity_minutes=20)  # 4% down
    assert any("weight below usual" in d for d in r.drivers)
    assert not any("several indicators declining together" in d for d in r.drivers)


def test_body_status_still_applies_when_loss_is_managed():
    """
    Suppressing the deduction must not suppress the weighting shift: a pet on a
    diet is still carrying the weight that makes activity matter more.
    """
    pet = make_pet()
    managed = trend_for([44.0, 44.0, 44.0, 42.0], plan=True)
    assert managed.managed is True
    assert weight_penalty(managed, CHECKIN_DAY) == 0.0
    assert managed.body_status == "above_reference"

    w = VitalityScoreEngine(pet, [], weight_trend=managed)._select_weights()
    assert w.activity > BASE_PROFILES["standard"].activity


def test_cat_and_dog_managed_ceilings_differ():
    """Cats are held to a slower safe loss rate than dogs."""
    rate_6pct_dog = trend_for([30.0, 30.0, 30.0, 28.2], plan=True)
    rate_6pct_cat = trend_for([5.0, 5.0, 5.0, 4.7], species="cat",
                              breed="Domestic Shorthair", plan=True)
    assert rate_6pct_dog.managed is True     # within the 8%/4wk dog ceiling
    assert rate_6pct_cat.managed is False    # over the 4%/4wk cat ceiling


def test_growing_pet_uses_tightened_loss_threshold():
    """The same 8% loss escalates for a growing pet but not for an adult."""
    series = [12.0, 12.0, 12.0, 11.04]
    puppy = trend_for(series, birth_date=date(2026, 2, 1))
    adult = trend_for(series, birth_date=date(2020, 1, 1))
    assert puppy.is_growing and puppy.tier == "urgent"
    assert adult.is_growing is False and adult.tier is None


# --- Staleness and reading hygiene ----------------------------------------- #
def test_staleness_boundaries_are_exact():
    trend = trend_for([30.0, 30.0, 30.0, 28.2], last_on=date(2026, 1, 10))
    on = lambda weeks: datetime(2026, 1, 10) + timedelta(weeks=weeks)
    assert staleness_factor(trend, on(8)) == 1.0     # still fresh at the edge
    assert staleness_factor(trend, on(10)) == 0.5    # halfway through the fade
    assert staleness_factor(trend, on(12)) == 0.0    # fully expired at the edge


def test_readings_are_sorted_and_deduplicated():
    """Out-of-order input and a same-day correction must not change the answer."""
    ordered = compute_weight_trend(
        [WeightReading(30.0, date(2026, 6, 20)), WeightReading(28.2, date(2026, 7, 18))],
        species="dog", breed="Labrador", sex="male", birth_date=date(2020, 1, 1),
    )
    messy = compute_weight_trend(
        [WeightReading(30.0, date(2026, 7, 18)),      # superseded same-day entry
         WeightReading(30.0, date(2026, 6, 20)),      # out of order
         WeightReading(28.2, date(2026, 7, 18))],     # the correction
        species="dog", breed="Labrador", sex="male", birth_date=date(2020, 1, 1),
    )
    assert messy.status == "ok"
    assert messy.rate_per_4w == ordered.rate_per_4w
    assert messy.current_kg == 28.2


# =========================================================================== #
# 16. Core engine coverage (non-weight)                                       #
#                                                                             #
# The rules the weight work plugs into: every emergency sign, the four        #
# red-flag rules that previously never fired in any test, the repeated-sign   #
# look-back window, and the score/output contract.                            #
# =========================================================================== #

# --- Tier 1: every safety rule actually fires ------------------------------ #
def test_every_emergency_sign_suppresses_the_score():
    """
    Driven off EMERGENCY_SIGNS itself, so a newly added sign is covered
    automatically instead of silently going untested.
    """
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    assert len(EMERGENCY_SIGNS) == 6, "emergency list changed - review this test"

    for field_name, reason in EMERGENCY_SIGNS.items():
        r = process_checkin(pet, hist, mk_checkin(pet.pet_id, **{field_name: True}))
        assert r.score is None, field_name
        assert r.band == "Action Needed", field_name
        assert r.baseline_status == "override", field_name
        assert r.override.severity_tier == "emergency", field_name
        assert r.override.trigger == field_name, field_name
        assert r.override.clinical_reason_for_escalation == reason, field_name
        assert r.override.vet_validation_required is True, field_name
        _assert_no_disease_terms(r.explanation)


def test_repeated_vomiting_escalates_to_urgent():
    pet = make_pet()
    hist = history_with(pet.pet_id, 3, vomiting=True)      # vomited last check-in too
    r = process_checkin(pet, hist, mk_checkin(pet.pet_id, vomiting=True))
    assert r.score is None
    assert r.override.severity_tier == "urgent"
    assert r.override.trigger == "repeated_vomiting"


def test_persistent_increased_thirst_escalates_to_urgent():
    pet = make_pet()
    hist = history_with(pet.pet_id, 3, water_intake_status="increased")
    r = process_checkin(pet, hist, mk_checkin(pet.pet_id, water_intake_status="increased"))
    assert r.score is None
    assert r.override.trigger == "persistent_increased_thirst"
    _assert_no_disease_terms(r.explanation)


def test_pain_signs_escalate_to_urgent():
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 4),
                        mk_checkin(pet.pet_id, pain_or_discomfort_signs=True))
    assert r.score is None
    assert r.override.severity_tier == "urgent"
    assert r.override.trigger == "pain_signs"


def test_tick_found_is_monitor_and_keeps_the_score():
    """Previously only set alongside blood in stool, so this rule never ran."""
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 4),
                        mk_checkin(pet.pet_id, tick_found=True))
    assert r.score is not None                      # monitor never hides the score
    assert r.override.severity_tier == "monitor"
    assert r.override.trigger == "tick_found"


# --- Tier 2: branches inside rules that were only half-covered ------------- #
def test_lookback_window_stops_counting_after_three_checkins():
    """
    "Repeated" means within the last three check-ins. A sign older than that is
    stale and must fall back to the single-occurrence monitor tier.
    """
    pet = make_pet()
    # Vomiting four check-ins back: outside the window.
    stale = [mk_checkin(pet.pet_id, vomiting=True)] + make_history(pet.pet_id, 3)
    r = process_checkin(pet, stale, mk_checkin(pet.pet_id, vomiting=True))
    assert r.override.trigger == "single_gi_upset"
    assert r.override.severity_tier == "monitor"
    assert r.score is not None

    # Same sign one check-in back: inside the window, escalates.
    fresh = history_with(pet.pet_id, 3, vomiting=True)
    r2 = process_checkin(pet, fresh, mk_checkin(pet.pet_id, vomiting=True))
    assert r2.override.trigger == "repeated_vomiting"


def test_blood_in_stool_reason_reflects_energy_level():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    with_lethargy = process_checkin(pet, hist,
                                    mk_checkin(pet.pet_id, blood_in_stool=True, energy_score=2))
    alone = process_checkin(pet, hist,
                            mk_checkin(pet.pet_id, blood_in_stool=True, energy_score=4))
    assert "low energy" in with_lethargy.override.clinical_reason_for_escalation
    assert "low energy" not in alone.override.clinical_reason_for_escalation
    assert alone.override.severity_tier == "urgent"      # still urgent on its own


def test_single_diarrhoea_is_monitor():
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 4),
                        mk_checkin(pet.pet_id, diarrhoea=True))
    assert r.override.trigger == "single_gi_upset"
    assert "Diarrhoea" in r.override.clinical_reason_for_escalation
    assert r.score is not None


# --- Tier 3: score math ---------------------------------------------------- #
def test_sleep_drop_registers_a_driver():
    """Sleep was the only vital with no driver coverage."""
    pet = make_pet()
    hist = make_history(pet.pet_id, 4, sleep=4)
    r = process_checkin(pet, hist, mk_checkin(pet.pet_id, sleep_quality_score=2))
    assert any("sleep quality below usual" in d for d in r.drivers)
    assert r.score == 76                            # 2 points * 0.20 * 60 = 24


def test_worming_penalty_is_eight_points():
    hist = make_history("pet_w", 4)
    current = mk_checkin("pet_w")
    compliant = process_checkin(make_pet("pet_w", worming=True), hist, current)
    overdue = process_checkin(make_pet("pet_w", worming=False), hist, current)
    assert compliant.score - overdue.score == 8
    assert any("worming treatment overdue" in d for d in overdue.drivers)


def test_trend_field_reflects_state():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    assert process_checkin(pet, hist, mk_checkin(pet.pet_id)).trend == "stable"

    declining = mk_checkin(pet.pet_id, appetite_score=2, energy_score=2, activity_minutes=20)
    assert process_checkin(pet, hist, declining).trend == "declining vs baseline"

    building = process_checkin(pet, make_history(pet.pet_id, 2), mk_checkin(pet.pet_id))
    assert building.trend == "n/a"

    override = process_checkin(pet, hist, mk_checkin(pet.pet_id, collapse=True))
    assert override.trend == "override"


def test_zero_activity_baseline_does_not_divide_by_zero():
    """An indoor pet with no logged activity must not blow up the maths."""
    pet = make_pet()
    hist = make_history(pet.pet_id, 4, activity=0)
    assert process_checkin(pet, hist, mk_checkin(pet.pet_id, activity_minutes=0)).score == 100
    # Activity above a zero baseline is an improvement, never a penalty.
    assert process_checkin(pet, hist, mk_checkin(pet.pet_id, activity_minutes=30)).score == 100


# --- Tier 4: output contract ----------------------------------------------- #
def test_monitor_advisory_prepends_to_drivers():
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 4), mk_checkin(pet.pet_id, vomiting=True))
    assert r.drivers[0] == r.override.clinical_reason_for_escalation
    assert len(r.drivers) > 1, "the score's own drivers must be preserved beneath it"


def test_override_explanation_wording_differs_by_tier():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    emergency = process_checkin(pet, hist, mk_checkin(pet.pet_id, collapse=True))
    urgent = process_checkin(pet, hist, mk_checkin(pet.pet_id, pain_or_discomfort_signs=True))
    assert "safety alert" in emergency.explanation
    assert "safety prompt" in urgent.explanation
    for r in (emergency, urgent):
        assert "not a diagnosis" in r.explanation


def test_pet_id_propagates_on_every_path():
    pet = make_pet("pet_abc")
    hist = make_history(pet.pet_id, 4)
    paths = [
        process_checkin(pet, hist, mk_checkin(pet.pet_id)),                      # scored
        process_checkin(pet, hist, mk_checkin(pet.pet_id, collapse=True)),       # override
        process_checkin(pet, make_history(pet.pet_id, 1), mk_checkin(pet.pet_id)),  # building
    ]
    assert all(r.pet_id == "pet_abc" for r in paths)


def test_engine_is_deterministic():
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    current = mk_checkin(pet.pet_id, appetite_score=3, sleep_quality_score=2)
    a = process_checkin(pet, hist, current)
    b = process_checkin(pet, hist, current)
    assert (a.score, a.band, a.drivers, a.explanation, a.trend) == \
           (b.score, b.band, b.drivers, b.explanation, b.trend)


def test_building_baseline_result_contents():
    pet = make_pet()
    r = process_checkin(pet, make_history(pet.pet_id, 2), mk_checkin(pet.pet_id))
    assert r.drivers == ["3 of 4 check-ins collected"]
    assert "still building a baseline" in r.explanation
    assert "4th weekly check-in" in r.explanation
    assert pet.name in r.explanation
    _assert_no_disease_terms(r.explanation)


def test_every_result_carries_an_explanation_and_a_driver():
    """No product surface should ever receive an empty reason."""
    pet = make_pet()
    hist = make_history(pet.pet_id, 4)
    cases = [
        mk_checkin(pet.pet_id),                                        # nothing wrong
        mk_checkin(pet.pet_id, appetite_score=2),                      # a dip
        mk_checkin(pet.pet_id, vomiting=True),                         # monitor
        mk_checkin(pet.pet_id, pain_or_discomfort_signs=True),         # urgent
        mk_checkin(pet.pet_id, seizure=True),                          # emergency
    ]
    for current in cases:
        for history in (hist, make_history(pet.pet_id, 1)):            # scored and building
            r = process_checkin(pet, history, current)
            assert r.explanation.strip(), (current, len(history))
            assert r.drivers and all(d.strip() for d in r.drivers), (current, len(history))
            _assert_no_disease_terms(r.explanation)


# --------------------------------------------------------------------------- #
# Standalone runner (works without pytest installed)                           #
# --------------------------------------------------------------------------- #
def _run_standalone() -> int:
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            failures += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
