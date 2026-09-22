from typing import List, Optional

from .models import CheckInData, RedFlagResult, WeightTrendResult
from .weight import declining_strength, staleness_factor


# Emergency signs: any one hides the reassuring score and routes to emergency
# care. Field name on CheckInData -> safe, non-diagnostic escalation reason.
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

    def __init__(
        self,
        history: Optional[List[CheckInData]] = None,
        weight_trend: Optional[WeightTrendResult] = None,
    ):
        # Recent history lets us spot *repeated* signs (e.g. thirst over weeks).
        self.history = history or []
        # Latest stored monthly weight signal; None -> no weight rules apply.
        self.weight_trend = weight_trend

    def _weight_loss_present(self, current: CheckInData) -> bool:
        """
        A usable, unmanaged loss at or past the notable threshold, not yet fully
        stale. Delegates to weight.py so the safety net and the score agree on
        what counts as a loss rather than each keeping their own copy of the rule.
        """
        return declining_strength(self.weight_trend, current.timestamp) > 0.0

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

        # Notable unintentional weight loss. The tier was decided by weight.py at
        # weigh-in; re-check freshness here so a long-stale reading cannot keep
        # firing an alert week after week.
        wt = self.weight_trend
        if (
            wt is not None
            and wt.tier == "urgent"
            and staleness_factor(wt, current.timestamp) > 0.0
        ):
            return RedFlagResult(
                True, "notable_weight_loss", "urgent",
                f"Recorded weight is about {abs(wt.pct_change):.0f}% lower than the "
                f"recent average - about {abs(wt.rate_per_4w):.0f}% per 4 weeks "
                f"(reading of {wt.as_of.strftime('%d %b %Y')})",
                "A drop in body weight of this size may need veterinary review, "
                "especially if it was not expected.",
                True,
            )

        # Weight loss alongside another sign on this check-in. Each of the signs
        # below needs REPETITION to escalate on its own, so a first occurrence
        # next to real weight loss would otherwise slip through entirely.
        if self._weight_loss_present(current):
            companion = None
            if current.appetite_score <= 2:
                companion = "reduced appetite"
            elif current.water_intake_status == "increased":
                companion = "increased thirst"
            elif low_energy:
                companion = "low energy"
            if companion:
                return RedFlagResult(
                    True, "weight_loss_with_signs", "urgent",
                    f"Weight loss since recent readings together with {companion}",
                    "This combination may need veterinary review, especially if it "
                    "continues.",
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

        # Rapid weight gain in an adult. The score deduction is applied by
        # scoring.py on the same ramp as loss; this is the advisory that goes
        # with it. Suppressed entirely while a pet is still growing.
        if (
            wt is not None
            and wt.tier == "monitor"
            and staleness_factor(wt, current.timestamp) > 0.0
        ):
            return RedFlagResult(
                True, "rapid_weight_gain", "monitor",
                f"Recorded weight is about {abs(wt.pct_change):.0f}% higher than the "
                f"recent average - about {abs(wt.rate_per_4w):.0f}% per 4 weeks "
                f"(reading of {wt.as_of.strftime('%d %b %Y')})",
                "Consider reviewing portions and treats, and seek veterinary advice "
                "if the gain was unexpected.",
                True,
            )

        # No red flags. Mild single-day dips are handled by the score's Watch band.
        return RedFlagResult(triggered=False)