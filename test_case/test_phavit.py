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

Runs two ways:
  * with pytest:   python -m pytest test_case/test_phavit.py
  * standalone:    python test_case/test_phavit.py   (no pytest needed)
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List

# Allow standalone execution (`python test_case/test_phavit.py`) by putting the
# repo root on sys.path. Under pytest the root conftest.py already handles this.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phavit.models import CheckInData, PetProfile, VitalityScoreResult
from phavit.pipeline import process_checkin
from phavit.scoring import VitalityScoreEngine

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


def make_pet(pet_id="pet_1", name="Rex", high_energy=False, worming=True) -> PetProfile:
    return PetProfile(
        pet_id=pet_id, name=name, species="dog", breed="Labrador", sex="male",
        post_code=4217, birth_date=date(2020, 1, 1), is_high_energy=high_energy,
        worming_compliant=worming, vaccination_current=True,
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
        data = json.loads(path.read_text(encoding="utf-8"))
        pet = load_pet_profile(data["pet_profile"])
        current = load_checkin(data["check_in_data"])
        r = process_checkin(pet, make_history(pet.pet_id, 4), current)
        assert r.band in VALID_BANDS, path.name
        assert r.score is None or 0 <= r.score <= 100, path.name
        assert r.baseline_status in {"established", "building", "override"}, path.name
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
