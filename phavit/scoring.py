"""
Layer 1 - the 0-100 wellness trend score.

Compares the current check-in against the pet's OWN recent baseline rather than
using fixed deductions. Pure wellbeing math: acute red flags are handled
separately by RedFlagEngine (red_flags.py) and must not be folded in here.
"""

from dataclasses import dataclass, replace
from typing import List, Optional

from .models import (
    BaselineSummary,
    CheckInData,
    PetProfile,
    VitalityScoreResult,
    WeightTrendResult,
)
from .weight import declining_strength, signal_quality, weight_penalty


BAND_BRIGHT = 85
BAND_MEDIUM = 70
BAND_WATCH = 50

# How many score points a full deviation can remove (tuning constant, provisional).
DEVIATION_WEIGHT = 60

# Fraction of baseline activity that must be lost before it counts as a drop.
# Tightened for pets carrying weight above their breed reference, for whom
# sustained low activity matters more.
ACTIVITY_DROP_THRESHOLD = 0.25
ACTIVITY_DROP_THRESHOLD_HEAVY = 0.20

# Placeholder driver used when nothing moved the score. Kept as a constant so
# the explanation layer can tell "nothing to report" from a real driver.
NO_DRIVERS = "all tracked indicators in line with usual baseline"

# A data-quality driver, not a wellbeing one. Listed for the owner and for WS9,
# but excluded from the "compared with their usual baseline" copy - it describes
# the recording, not the pet.
WEIGHT_RECHECK_DRIVER = "last recorded weight needs re-checking"
WEIGHT_STALE_DRIVER = "weight not recorded recently"

# Neither describes the pet, so both are kept out of the "compared with their
# usual baseline" copy and carried as their own sentence instead.
DATA_QUALITY_DRIVERS = (WEIGHT_RECHECK_DRIVER, WEIGHT_STALE_DRIVER)

# Extra activity weight for a pet above / well above their breed reference.
# Applied then renormalised - see Weights.normalised().
BODY_STATUS_ACTIVITY_BUMP = {
    "above_reference": 0.05,
    "well_above_reference": 0.10,
}

# The mirror of the activity bump. For a pet BELOW their breed reference the
# lever is intake rather than exercise, so a fall in appetite counts for more.
# Still never a deduction in itself - only a shift in emphasis.
BODY_STATUS_APPETITE_BUMP = {
    "below_reference": 0.10,
}

# Most points the multiple-indicators-declining rule can remove.
COMPOUND_DECLINE_DEDUCTION = 12.0


@dataclass(frozen=True)
class Weights:
    """
    One breed-aware weighting profile. The four indicator weights always sum to
    1.0 so profiles stay directly comparable (report section 8.2).
    """
    appetite: float
    energy: float
    sleep: float
    activity: float
    activity_drop_threshold: float = ACTIVITY_DROP_THRESHOLD

    def normalised(self) -> "Weights":
        """
        Rescale the four indicator weights back to a sum of 1.0.

        This is load-bearing. Bumping activity without renormalising raises the
        total above 1.0, which makes the score uniformly harsher rather than
        simply re-prioritising activity - a different, and worse, behaviour.
        """
        total = self.appetite + self.energy + self.sleep + self.activity
        if total <= 0:
            return self
        return replace(
            self,
            appetite=self.appetite / total,
            energy=self.energy / total,
            sleep=self.sleep / total,
            activity=self.activity / total,
        )


BASE_PROFILES = {
    "high_energy": Weights(0.20, 0.25, 0.10, 0.45),
    "standard": Weights(0.30, 0.30, 0.20, 0.20),
}


class VitalityScoreEngine:
    """
    Layer 1 - the 0-100 wellness trend score.

    Compares the current check-in against the pet's OWN recent baseline rather
    than using fixed deductions. Only downward deviations reduce the score.
    """

    # The first PHAIVIT score unlocks on the FOURTH completed weekly check-in.
    # This total counts the current check-in, i.e. 3 previous + current = 4.
    MIN_CHECKINS_FOR_SCORE = 4

    def __init__(
        self,
        pet: PetProfile,
        history: List[CheckInData],
        weight_trend: Optional[WeightTrendResult] = None,
    ):
        self.pet = pet
        self.history = history          # PREVIOUS check-ins only (excludes current)
        # Latest stored monthly weight signal. None -> the engine behaves
        # exactly as it did before weight existed.
        self.weight_trend = weight_trend

    def _select_weights(self) -> Weights:
        """
        Pick the weighting profile for this pet.

        Breed energy level chooses the base profile; body weight relative to the
        breed reference then shifts emphasis towards activity, because for a pet
        carrying extra weight sustained low activity is both more consequential
        and the lever an owner can actually pull.
        """
        profile = BASE_PROFILES["high_energy" if self.pet.is_high_energy else "standard"]

        body_status = self.weight_trend.body_status if self.weight_trend else None
        activity_bump = BODY_STATUS_ACTIVITY_BUMP.get(body_status, 0.0)
        appetite_bump = BODY_STATUS_APPETITE_BUMP.get(body_status, 0.0)
        if not activity_bump and not appetite_bump:
            return profile

        return replace(
            profile,
            activity=profile.activity + activity_bump,
            appetite=profile.appetite + appetite_bump,
            activity_drop_threshold=(
                ACTIVITY_DROP_THRESHOLD_HEAVY if activity_bump
                else profile.activity_drop_threshold
            ),
        ).normalised()

    def calculate(self, current: CheckInData) -> VitalityScoreResult:
        # Unlock boundary (WS2): the current completed check-in is part of the
        # scoreable set, so the total is previous + 1. The first score appears at
        # 4 total (3 previous + current); fewer than that stays Building Baseline.
        total_checkins = len(self.history) + 1

        if total_checkins < self.MIN_CHECKINS_FOR_SCORE:
            return VitalityScoreResult(
                pet_id=self.pet.pet_id,
                score=None,
                band="Building Baseline",
                baseline_status="building",
                confidence="low",
                override=None,
                drivers=[f"{total_checkins} of {self.MIN_CHECKINS_FOR_SCORE} check-ins collected"],
                explanation=(
                    f"{self.pet.name} is still building a baseline. The first PHAIVIT score "
                    f"unlocks on the {self.MIN_CHECKINS_FOR_SCORE}th weekly check-in, so no "
                    f"score is shown yet. Keep checking in each week."
                ),
                trend="n/a",
            )

        # Deviation baseline is the pet's OWN recent normal from the PREVIOUS
        # check-ins (min_checkins=1: any history is enough once the gate passes).
        baseline = BaselineSummary.from_history(self.history, min_checkins=1)

        # Negative deviations from baseline (only drops reduce wellbeing).
        drop_appetite = max(0.0, baseline.avg_appetite - current.appetite_score)
        drop_energy = max(0.0, baseline.avg_energy - current.energy_score)
        drop_sleep = max(0.0, baseline.avg_sleep - current.sleep_quality_score)
        drop_activity_frac = 0.0
        if baseline.avg_activity and baseline.avg_activity > 0:
            drop_activity_frac = max(
                0.0, (baseline.avg_activity - current.activity_minutes) / baseline.avg_activity
            )

        # Breed-aware weights (each set sums to 1.0), shifted towards activity when
        # the pet is above their breed weight reference.
        w = self._select_weights()

        score = 100.0
        drivers: List[str] = []

        score -= drop_appetite * w.appetite * DEVIATION_WEIGHT
        score -= drop_energy * w.energy * DEVIATION_WEIGHT
        score -= drop_sleep * w.sleep * DEVIATION_WEIGHT
        score -= drop_activity_frac * w.activity * DEVIATION_WEIGHT

        activity_dropped = drop_activity_frac >= w.activity_drop_threshold

        # Weight loss from the monthly weight subsystem. Carried forward between
        # weigh-ins and decayed once stale, so the score stays steady rather than
        # spiking on whichever week the weight happened to be logged.
        w_penalty = weight_penalty(self.weight_trend, current.timestamp)
        score -= w_penalty

        if drop_appetite >= 1:
            drivers.append("appetite below usual")
        if drop_energy >= 1:
            drivers.append("energy below usual")
        if drop_sleep >= 1:
            drivers.append("sleep quality below usual")
        if activity_dropped:
            drivers.append("activity below usual")
        if w_penalty > 0:
            drivers.append("weight below usual")

        # Weight data quality. Neither of these is a wellbeing judgement - they
        # tell the owner what the score could not see, rather than passing
        # silently on an entry we rejected or a reading that has aged out.
        weight_quality = signal_quality(self.weight_trend, current.timestamp)
        if weight_quality == "unreliable":
            drivers.append(WEIGHT_RECHECK_DRIVER)
        elif weight_quality == "stale":
            drivers.append(WEIGHT_STALE_DRIVER)

        # Signal vs noise: multiple indicators declining together is more concerning
        # than a single one-day dip (section 4.3 - "multiple indicators declining together").
        #
        # Summed as a float rather than counted, because weight contributes a
        # decaying strength rather than a yes/no. The deduction is the excess
        # over one declining indicator, capped: two solid indicators give the
        # full deduction and three or more still give the same, exactly as the
        # boolean count did, while a fading weight signal now tapers instead of
        # falling off a cliff.
        declining = (
            float(drop_appetite >= 1)
            + float(drop_energy >= 1)
            + float(drop_sleep >= 1)
            + float(activity_dropped)
            + declining_strength(self.weight_trend, current.timestamp)
        )
        if declining > 1.0:
            score -= COMPOUND_DECLINE_DEDUCTION * min(1.0, declining - 1.0)
            drivers.append("several indicators declining together")

        # Provisional, non-clinical care-compliance nudge.
        if not self.pet.worming_compliant:
            score -= 8.0
            drivers.append("worming treatment overdue")

        final = int(max(0, min(100, round(score))))
        band = self._band(final)
        confidence = "high" if total_checkins >= 6 else "moderate"
        # Weight can now move the score by real points, so a recorded-but-
        # untrustworthy weight signal must not be reported at full confidence.
        # "none" (never weighed, or too few readings) is left alone: with no
        # trend the engine behaves exactly as it did before weight existed.
        if confidence == "high" and weight_quality in ("stale", "unreliable"):
            confidence = "moderate"
        # A data-quality nudge is not a driver of the score, so on its own it must
        # not read as though something moved. Keep the "nothing changed" line.
        if not any(d not in DATA_QUALITY_DRIVERS for d in drivers):
            drivers.insert(0, NO_DRIVERS)
        trend = "stable" if final >= BAND_MEDIUM else "declining vs baseline"

        return VitalityScoreResult(
            pet_id=self.pet.pet_id,
            score=final,
            band=band,
            baseline_status="established",
            confidence=confidence,
            override=None,
            drivers=drivers,
            explanation=self._explain(
                band,
                drivers,
                weight_contributed=w_penalty > 0,
                weight_quality=weight_quality,
            ),
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

    def _weight_note(self) -> str:
        """
        Weight is recorded monthly, so any mention of it must carry the date of
        the reading. Never let the copy imply it was measured this week.
        """
        trend = self.weight_trend
        if trend is None or trend.as_of is None:
            return ""
        return (
            f" The weight comparison uses the reading recorded on "
            f"{trend.as_of.strftime('%d %b %Y')}."
        )

    def _data_quality_note(self, weight_quality: str) -> str:
        """
        Owner-facing prompt about the weight RECORDING rather than the pet.

        Deliberately plain, and never built from WeightTrendResult.notes - those
        are internal diagnostics and must not reach owner copy.

        The stale prompt matters because the score quietly RISES as an old weight
        signal decays. Without it an owner sees an improving number and has no
        way to know it reflects an expiring reading, not a recovering pet.
        """
        if weight_quality == "unreliable":
            return (
                """
                The most recent weight entry looks unusual, so it has not been used here - please check it and re-enter it if it was a typo."""
            )
        if weight_quality == "stale":
            trend = self.weight_trend
            when = (
                f" is from {trend.as_of.strftime('%d %b %Y')}"
                if trend is not None and trend.as_of is not None
                else " is getting old"
            )
            return (
                f" The last recorded weight{when}, so it is counting for less here - "
                f"a fresh weigh-in would keep this accurate."
            )
        return ""

    def _explain(
        self,
        band: str,
        drivers: List[str],
        weight_contributed: bool = False,
        weight_quality: str = "none",
    ) -> str:
        name = self.pet.name
        # The stale note already names the reading date, so the routine "which
        # reading was used" line would just repeat it back.
        dates_the_reading = weight_contributed and weight_quality != "stale"
        note = self._weight_note() if dates_the_reading else ""
        note += self._data_quality_note(weight_quality)
        real_drivers = [d for d in drivers if d != NO_DRIVERS and d not in DATA_QUALITY_DRIVERS]

        if band in ("Bright Green", "Medium Green"):
            # A green band can still carry a driver (a weight drop, an overdue
            # worming nudge). Reassuring copy must not contradict it.
            if real_drivers:
                driver_text = ", ".join(real_drivers[:2])
                return (
                    f"{name} is still tracking well overall this week, though {driver_text} "
                    f"compared with their usual baseline. No emergency red flags were "
                    f"reported. Keep an eye on it and keep up the regular check-ins.{note}"
                )
            return (
                f"{name}'s indicators are tracking in line with their usual baseline this week. "
                f"No emergency red flags were reported. Keep up the regular check-ins.{note}"
            )
        driver_text = ", ".join(real_drivers[:2]) if real_drivers else "small changes from baseline"
        return (
            f"{name}'s score is lower this week mainly because {driver_text} compared with their "
            f"usual baseline. This is a wellbeing trend, not a diagnosis. If it continues or "
            f"worsens, veterinary advice should be considered.{note}"
        )
