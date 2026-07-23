from pipeline import VitalityScoreEngine
from models import PetProfile, CheckInData, VitalityScoreResult

def process_checkin(
    pet: PetProfile, history: List[CheckInData], current: CheckInData
) -> VitalityScoreResult:
    """
    Full pipeline:
      1. The red-flag override layer runs FIRST (safety net).
      2. An EMERGENCY or URGENT flag replaces the reassuring score with a safety pathway.
      3. Otherwise the 0-100 baseline score is calculated; a MONITOR flag is attached
         as advisory context without hiding the score.
    """
    rf = RedFlagEngine(history=history).evaluate(current)

    if rf.triggered and rf.severity_tier in ("emergency", "urgent"):
        return VitalityScoreResult(
            pet_id=pet.pet_id,
            score=None,                       # score withheld; safety pathway takes over
            band="Action Needed",
            baseline_status="override",
            confidence="high",
            override=rf,
            drivers=[rf.clinical_reason_for_escalation],
            explanation=_override_explanation(pet, rf),
            trend="override",
        )

    result = VitalityScoreEngine(pet, history).calculate(current)

    # Attach a monitor-tier advisory if present (does not hide the wellbeing score).
    if rf.triggered and rf.severity_tier == "monitor":
        result.override = rf
        result.drivers = [rf.clinical_reason_for_escalation] + result.drivers
        result.explanation = f"{result.explanation} {rf.recommended_user_pathway}"

    return result
