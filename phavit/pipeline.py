from red_flags import RedFlagEngine, RedFlagResult
from models import PetProfile, CheckInData, VitalityScoreResult

BAND_BRIGHT = 85
BAND_MEDIUM = 70
BAND_WATCH = 50

# How many score points a full deviation can remove (tuning constant, provisional).
DEVIATION_WEIGHT = 60


class VitalityScoreEngine:
    """
    Layer 1 - the 0-100 wellness trend score.

    Compares the current check-in against the pet's OWN recent baseline rather
    than using fixed deductions. Pure wellbeing math: acute red flags are handled
    separately by RedFlagEngine and must not be folded in here.
    """

    MIN_BASELINE = 3

    def __init__(self, pet: PetProfile, history: List[CheckInData]):
        self.pet = pet
        self.history = history

    def calculate(self, current: CheckInData) -> VitalityScoreResult:
        baseline = BaselineSummary.from_history(self.history, self.MIN_BASELINE)

        # Not enough history -> honest "building baseline" state (section 4.3).
        if not baseline.has_baseline:
            return VitalityScoreResult(
                pet_id=self.pet.pet_id,
                score=None,
                band="Building Baseline",
                baseline_status="building",
                confidence="low",
                override=None,
                drivers=[f"only {baseline.n_checkins} of {self.MIN_BASELINE} check-ins collected"],
                explanation=(
                    f"{self.pet.name} is still building a baseline. With fewer than "
                    f"{self.MIN_BASELINE} recent check-ins we cannot yet tell what is normal "
                    f"for them, so no score is shown. Keep checking in each week."
                ),
                trend="n/a",
            )

        # Negative deviations from baseline (only drops reduce wellbeing).
        drop_appetite = max(0.0, baseline.avg_appetite - current.appetite_score)
        drop_energy = max(0.0, baseline.avg_energy - current.energy_score)
        drop_sleep = max(0.0, baseline.avg_sleep - current.sleep_quality_score)
        drop_activity_frac = 0.0
        if baseline.avg_activity and baseline.avg_activity > 0:
            drop_activity_frac = max(
                0.0, (baseline.avg_activity - current.activity_minutes) / baseline.avg_activity
            )

        # Breed-aware weights (each set sums to 1.0). High-energy breeds weight activity.
        if self.pet.is_high_energy:
            w_app, w_energy, w_sleep, w_act = 0.20, 0.25, 0.10, 0.45
        else:
            w_app, w_energy, w_sleep, w_act = 0.30, 0.30, 0.20, 0.20

        score = 100.0
        drivers: List[str] = []

        score -= drop_appetite * w_app * DEVIATION_WEIGHT
        score -= drop_energy * w_energy * DEVIATION_WEIGHT
        score -= drop_sleep * w_sleep * DEVIATION_WEIGHT
        score -= drop_activity_frac * w_act * DEVIATION_WEIGHT

        if drop_appetite >= 1:
            drivers.append("appetite below usual")
        if drop_energy >= 1:
            drivers.append("energy below usual")
        if drop_sleep >= 1:
            drivers.append("sleep quality below usual")
        if drop_activity_frac >= 0.25:
            drivers.append("activity below usual")

        # Signal vs noise: multiple indicators declining together is more concerning
        # than a single one-day dip (section 4.3 - "multiple indicators declining together").
        declining = sum([
            drop_appetite >= 1,
            drop_energy >= 1,
            drop_sleep >= 1,
            drop_activity_frac >= 0.25,
        ])
        if declining >= 2:
            score -= 12.0
            drivers.append("several indicators declining together")

        # Provisional, non-clinical care-compliance nudge.
        if not self.pet.worming_compliant:
            score -= 8.0
            drivers.append("worming treatment overdue")

        final = int(max(0, min(100, round(score))))
        band = self._band(final)
        confidence = "high" if baseline.n_checkins >= 6 else "moderate"
        if not drivers:
            drivers = ["all tracked indicators in line with usual baseline"]
        trend = "stable" if final >= BAND_MEDIUM else "declining vs baseline"

        return VitalityScoreResult(
            pet_id=self.pet.pet_id,
            score=final,
            band=band,
            baseline_status="established",
            confidence=confidence,
            override=None,
            drivers=drivers,
            explanation=self._explain(band, drivers),
            trend=trend,
        )

    @staticmethod
    def _band(score: int) -> str:
        if score >= BAND_BRIGHT:
            return "Bright Green"
        if score >= BAND_MEDIUM:
            return "Medium Green"
        if score >= BAND_WATCH:
            return "Watch"
        return "Action Needed"

    def _explain(self, band: str, drivers: List[str]) -> str:
        name = self.pet.name
        if band in ("Bright Green", "Medium Green"):
            return (
                f"{name}'s indicators are tracking in line with their usual baseline this week. "
                f"No emergency red flags were reported. Keep up the regular check-ins."
            )
        driver_text = ", ".join(drivers[:2]) if drivers else "small changes from baseline"
        return (
            f"{name}'s score is lower this week mainly because {driver_text} compared with their "
            f"usual baseline. This is a wellbeing trend, not a diagnosis. If it continues or "
            f"worsens, veterinary advice should be considered."
        )


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
