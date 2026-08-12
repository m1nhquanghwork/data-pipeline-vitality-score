"""
Orchestration layer.

`process_checkin()` runs the red-flag safety net FIRST, then the 0-100 wellbeing
score. This is the single entry point the check-in completion flow should call.
"""

from typing import List, Optional

from .models import (
    CheckInData,
    PetProfile,
    RedFlagResult,
    VitalityScoreResult,
    WeightTrendResult,
)
from .red_flags import RedFlagEngine
from .scoring import VitalityScoreEngine


def _override_explanation(pet: PetProfile, rf: RedFlagResult) -> str:
    if rf.severity_tier == "emergency":
        return (
            f"{rf.clinical_reason_for_escalation} for {pet.name}. {rf.recommended_user_pathway} "
            f"This is a safety alert based on reported signs, not a diagnosis."
        )
    return (
        f"{rf.clinical_reason_for_escalation} for {pet.name}. {rf.recommended_user_pathway} "
        f"This is a safety prompt based on reported signs, not a diagnosis."
    )


def process_checkin(
    pet: PetProfile,
    previous_checkins: List[CheckInData],
    current_checkin: CheckInData,
    weight_trend: Optional[WeightTrendResult] = None,
) -> VitalityScoreResult:
    """
    Full pipeline:
      1. The red-flag override layer runs FIRST (safety net).
      2. An EMERGENCY or URGENT flag replaces the reassuring score with a safety pathway.
      3. Otherwise the 0-100 baseline score is calculated; a MONITOR flag is attached
         as advisory context without hiding the score.

    `previous_checkins` and `current_checkin` are passed separately (WS2). The
    current completed check-in is part of the scoreable set, so the first score
    unlocks at 4 total (3 previous + current), not the 5th event.

    `weight_trend` is the LATEST STORED result from the monthly weight subsystem
    (see weight.py). It is read here, never recomputed - weight runs on its own
    cadence. Passing None makes the engine behave exactly as it did before weight
    was introduced.
    """
    history = previous_checkins
    current = current_checkin

    rf = RedFlagEngine(history=history, weight_trend=weight_trend).evaluate(current)

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
            weight_trend=weight_trend,
        )

    result = VitalityScoreEngine(pet, history, weight_trend=weight_trend).calculate(current)
    # Carried on every path so Pawport and the WS9 referral hooks always see it.
    result.weight_trend = weight_trend

    # Attach a monitor-tier advisory if present (does not hide the wellbeing score).
    if rf.triggered and rf.severity_tier == "monitor":
        result.override = rf
        result.drivers = [rf.clinical_reason_for_escalation] + result.drivers
        result.explanation = f"{result.explanation} {rf.recommended_user_pathway}"

    return result
