"""
Layer 2 - the red-flag safety net.

Acute or serious signs are handled here, separately from the 0-100 math, so a
serious sign can never be averaged away by otherwise good vitals.
"""

from typing import List, Optional

from .models import CheckInData, RedFlagResult


# Emergency signs: any one of these hides the reassuring score and routes the
# owner to emergency care. Field name on CheckInData -> safe escalation reason.
EMERGENCY_SIGNS = {
    "collapse": "Collapse or loss of consciousness reported",
    "breathing_difficulty": "Difficulty breathing reported",
    "seizure": "Seizure activity reported",
    "severe_bleeding": "Severe or uncontrolled bleeding reported",
    "suspected_toxin_ingestion": "Suspected ingestion of a toxic substance",
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

        low_energy = current.energy_score <= 2

        # ---------- TIER 2: URGENT ----------
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

        # ---------- TIER 3: MONITOR ----------
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
