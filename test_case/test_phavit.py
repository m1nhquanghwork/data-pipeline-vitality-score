import json
from pathlib import Path
from models import PetProfile, CheckInData, VitalityScoreResult
from scoring import process_checkin

TEST_DIR = Path("test_case")

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
        # appetite_scorew is a typo in the JSON files; fall back gracefully
        appetite_score=c.get("appetite_score", c.get("appetite_scorew")),
        energy_score=c["energy_score"],
        sleep_quality_score=c["sleep_quality_score"],
        activity_minutes=c["activity_minutes"],
        toileting_status=c.get("toileting_status", "normal"),
        water_intake_status=c.get("water_intake_status", "normal"),
        blood_in_stool=c.get("blood_in_stool", False),
        vomiting=c.get("vomiting", False),
        # dỉarhea (non-ASCII) is a typo in the JSON files
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

def make_history(pet_id: str, n: int, appetite: int, energy: int, sleep: int, activity: int) -> List[CheckInData]:
    """Synthetic stable baseline — same scores repeated n times."""
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


def run_test(label: str, json_path: Path, history: List[CheckInData]) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    pet = load_pet_profile(data["pet_profile"])
    current = load_checkin(data["check_in_data"])
    result = process_checkin(pet, history, current)

    print(f"{'─' * 62}")
    print(f"  {label}  |  {pet.name} ({pet.breed})")
    print(f"{'─' * 62}")
    print(f"  Score           : {result.score if result.score is not None else 'N/A: override active'}")
    print(f"  Band            : {result.band}")
    print(f"  Baseline status : {result.baseline_status}")
    print(f"  Confidence      : {result.confidence}")
    print(f"  Trend           : {result.trend}")
    print(f"  Drivers         : {', '.join(result.drivers)}")
    if result.override:
        rf = result.override
        print(f"  Red Flag        : [{rf.severity_tier.upper()}] {rf.trigger}")
        print(f"  Pathway         : {rf.recommended_user_pathway}")
    print(f"  Explanation     : {result.explanation}")
    print()

# Test 1: Bonnie: Vizsla, high-energy, clean healthy check-in 
history_1 = make_history("pet_100495", n=4, appetite=4, energy=4, sleep=4, activity=65)
run_test("TEST 1", TEST_DIR / "test_1.json", history_1)

# Test 2: Minh: Scottish Fold, diarrhoea + worming overdue 
history_2 = make_history("pet_100000", n=4, appetite=3, energy=3, sleep=3, activity=40)
run_test("TEST 2", TEST_DIR / "test_2.json", history_2)

# Test 3: Bonnie same profile as test_1 
history_3 = make_history("pet_100495", n=4, appetite=4, energy=4, sleep=4, activity=65)
run_test("TEST 3", TEST_DIR / "test_3.json", history_3)