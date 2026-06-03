"""
PawHealthAI Vitality Score Engine v0.2
======================================
Validation-ready, rules-based, *non-diagnostic* wellness scoring + safety
override harness for the PawHealthAI app.

SAFETY NOTICE (read before using):
- This engine is PROVISIONAL and NOT clinically validated.
- It does NOT diagnose disease and must never output disease names to users.
- All thresholds, weights and bands are placeholders pending veterinary review.
- Red flags trigger a separate safety pathway; they never simply "lower a score".

The module is intentionally dependency-free (standard library only) so it can be
imported by the notebook test harness and reviewed line-by-line by clinicians.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional
import statistics


# ---------------------------------------------------------------------------
# 1. DATA MODELS  (section 4.1 / 4.2 of the task brief)
# ---------------------------------------------------------------------------

@dataclass
class PetProfile:
    """Static information about a pet. Drives breed-aware weighting only."""
    pet_id: str
    name: str
    species: str                      # "dog" | "cat"
    breed: str
    birth_date: date
    is_high_energy: bool = False      # e.g. Vizsla, Border Collie -> activity weighted higher
    worming_compliant: bool = True    # provisional, non-clinical care-compliance nudge
    vaccination_current: bool = True


@dataclass
class CheckInData:
    """
    A single weekly check-in payload.

    Wellbeing scores use a 1-5 scale (1 = very poor, 5 = excellent).
    Acute signals are booleans and feed ONLY the red-flag override layer.
    """
    pet_id: str
    timestamp: datetime

    # --- Core wellbeing vitals (1-5) ---
    appetite_score: int
    energy_score: int
    sleep_quality_score: int
    activity_minutes: int                 # raw activity, compared against baseline

    # --- Toileting / hydration context ---
    toileting_status: str = "normal"      # "normal" | "more_frequent" | "less_frequent"
    water_intake_status: str = "normal"   # "normal" | "increased" | "decreased"

    # --- Acute / red-flag signals (booleans) ---
    blood_in_stool: bool = False
    vomiting: bool = False
    diarrhoea: bool = False
    breathing_difficulty: bool = False
    collapse: bool = False
    seizure: bool = False
    suspected_toxin_ingestion: bool = False
    unable_to_urinate: bool = False
    severe_bleeding: bool = False
    tick_found: bool = False
    pain_or_discomfort_signs: bool = False

    # --- Optional context (NOT direct health-score drivers) ---
    weight_kg: Optional[float] = None
    owner_concern_level: Optional[int] = None   # 1-5 owner subjective worry, advisory only


@dataclass
class BaselineSummary:
    """The pet's own recent normal, computed from history. Section 4.3."""
    n_checkins: int
    has_baseline: bool
    avg_appetite: Optional[float] = None
    avg_energy: Optional[float] = None
    avg_sleep: Optional[float] = None
    avg_activity: Optional[float] = None

    @classmethod
    def from_history(cls, history: List[CheckInData], min_checkins: int = 4) -> "BaselineSummary":
        n = len(history)
        if n == 0:
            return cls(n_checkins=0, has_baseline=False)
        return cls(
            n_checkins=n,
            has_baseline=n >= min_checkins,
            avg_appetite=statistics.mean(h.appetite_score for h in history),
            avg_energy=statistics.mean(h.energy_score for h in history),
            avg_sleep=statistics.mean(h.sleep_quality_score for h in history),
            avg_activity=statistics.mean(h.activity_minutes for h in history),
        )


@dataclass
class RedFlagResult:
    """
    Output of the safety override layer. Replaces the old, unsafe
    `potential_diseases` field with safe, internal-only escalation fields. Section 4.5.
    """
    triggered: bool
    trigger: Optional[str] = None                      # short machine label, e.g. "collapse"
    severity_tier: Optional[str] = None                # "emergency" | "urgent" | "monitor"
    clinical_reason_for_escalation: Optional[str] = None
    recommended_user_pathway: Optional[str] = None
    vet_validation_required: bool = False


@dataclass
class VitalityScoreResult:
    """Unified, product-facing result. Never contains a disease name."""
    pet_id: str
    score: Optional[int]               # 0-100, or None while building baseline / on override
    band: str                          # Bright Green | Medium Green | Watch | Action Needed | Building Baseline
    baseline_status: str               # "established" | "building" | "override"
    confidence: str                    # "high" | "moderate" | "low"
    override: Optional[RedFlagResult]  # populated whenever a red flag fired
    drivers: List[str] = field(default_factory=list)
    explanation: str = ""              # plain-English, safe, non-diagnostic
    trend: str = "n/a"


# ---------------------------------------------------------------------------
# 2. RED-FLAG OVERRIDE LAYER  (section 4.4)  -- runs SEPARATELY from the score
# ---------------------------------------------------------------------------

# Tier 1 emergency signs: any one triggers an emergency pathway immediately.
EMERGENCY_SIGNS = {
    "collapse": "Collapse reported",
    "breathing_difficulty": "Breathing difficulty reported",
    "seizure": "Seizure reported",
    "severe_bleeding": "Severe bleeding reported",
    "suspected_toxin_ingestion": "Suspected toxin ingestion reported",
    "unable_to_urinate": "Inability to urinate reported",
}


class RedFlagEngine:
    """
    Layer 2 - the safety net. Three escalation tiers:
      * emergency : seek emergency care now (no reassuring score is shown)
      * urgent    : action needed / urgent vet review pathway
      * monitor   : watch band with a safe explanation
    Acute signs are NEVER reassured away by the wellbeing math.
    """

    def __init__(self, history: Optional[List[CheckInData]] = None):
        # Recent history lets us spot *repeated* signs (e.g. thirst over weeks).
        self.history = history or []

    def evaluate(self, current: CheckInData) -> RedFlagResult:
        # ---------- TIER 1: EMERGENCY ----------
        for field_name, reason in EMERGENCY_SIGNS.items():
            if getattr(current, field_name):
                return RedFlagResult(
                    triggered=True,
                    trigger=field_name,
                    severity_tier="emergency",
                    clinical_reason_for_escalation=reason,
                    recommended_user_pathway=(
                        "Seek emergency veterinary care now. Reported signs may be serious "
                        "and need urgent professional assessment."
                    ),
                    vet_validation_required=True,
                )

        recent = self.history[-3:]   # look back a few check-ins for "repeated" patterns

        # ---------- TIER 2: URGENT VET ----------
        low_energy = current.energy_score <= 2

        # Blood in stool, especially alongside lethargy.
        if current.blood_in_stool:
            reason = "Blood in stool reported"
            if low_energy:
                reason += " together with low energy"
            return RedFlagResult(
                True, "blood_in_stool", "urgent", reason,
                "Reported signs may be concerning. Veterinary review is recommended soon.",
                True,
            )

        # Repeated vomiting across recent check-ins.
        if current.vomiting and any(h.vomiting for h in recent):
            return RedFlagResult(
                True, "repeated_vomiting", "urgent",
                "Repeated vomiting across recent check-ins",
                "Repeated vomiting may need veterinary review, especially if it continues.",
                True,
            )

        # Increased thirst across repeated check-ins.
        if current.water_intake_status == "increased" and any(
            h.water_intake_status == "increased" for h in recent
        ):
            return RedFlagResult(
                True, "persistent_increased_thirst", "urgent",
                "Increased thirst across repeated check-ins",
                "Increased thirst may require veterinary review, especially if it persists or "
                "appears with changes in appetite, weight, urination, or energy.",
                True,
            )

        # Persistent appetite loss across repeated check-ins.
        if current.appetite_score <= 2 and any(h.appetite_score <= 2 for h in recent):
            return RedFlagResult(
                True, "persistent_appetite_loss", "urgent",
                "Persistent low appetite across repeated check-ins",
                "Ongoing reduced appetite may need veterinary review if it continues.",
                True,
            )

        # Signs of pain / painful movement.
        if current.pain_or_discomfort_signs:
            return RedFlagResult(
                True, "pain_signs", "urgent",
                "Signs of pain or discomfort reported",
                "Reported signs of pain may need veterinary review.",
                True,
            )

        # ---------- TIER 3: MONITOR & REVIEW ----------
        if current.tick_found:
            return RedFlagResult(
                True, "tick_found", "monitor",
                "Tick found",
                "Remove the tick safely and monitor the area. Seek veterinary advice if you "
                "are unsure or your pet seems unwell.",
                True,
            )

        if current.vomiting or current.diarrhoea:
            sign = "Vomiting" if current.vomiting else "Diarrhoea"
            return RedFlagResult(
                True, "single_gi_upset", "monitor",
                f"{sign} reported on a single check-in",
                "Monitor closely and ensure access to water. Seek veterinary advice if it "
                "continues beyond a day or worsens.",
                True,
            )

        # No red flags. Mild single-day dips are handled by the score's Watch band.
        return RedFlagResult(triggered=False)


# ---------------------------------------------------------------------------
# 3. WELLBEING SCORE LAYER  (section 4.3)  -- 0-100, baseline comparison
# ---------------------------------------------------------------------------

# Band thresholds (PROVISIONAL - pending veterinary review).
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

    MIN_BASELINE = 4

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


# ---------------------------------------------------------------------------
# 4. ORCHESTRATOR  -- safety net first, then the score (sections 4.4 / 4.8)
# ---------------------------------------------------------------------------

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
