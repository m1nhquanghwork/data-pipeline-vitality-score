from dataclass_layout import PetProfile, CheckInData, OutputData
from typing import  List

class VitalityScoreEngine:
    """
    Layer 1: Calculates the 0-100 wellness score based on comparative baseline logic and dynamic breed weighting.
    """
    def __init__(self, pet: PetProfile, history: list[CheckInData]):
        self.pet = pet
        self.history = history # Previous 4 weeks for baseline (should use only 4 previous week)

    def calculate_score(self, current: CheckInData) -> OutputData:
        
        # Acute Overrides
        is_sudden_collapse = (current.energy <= 2 and current.appetite <= 2)

        if current.toileting.blood_present or current.water_intake == "Increased" or is_sudden_collapse:
            return self._generate_action_needed_override(current)
        
        # Checking if meet the requirement length of the length is met
        if len(self.history) < 4:
            return OutputData(
                vitality_score=None,
                zone="Building Baseline",
                trend="N/A",
                confidence="Low",
                top_drivers=["Establishing normal patterns"],
                red_flag=False,
                recommended_next_step="Continue completing weekly check-ins.",
                owner_summary="Evie is still learning what is normal for your pet during these first four weeks."
            )
        
        # Average history baseline
        avg_energy = sum(h.energy for h in self.history) / 4.0
        avg_appetite = sum(h.appetite for h in self.history) / 4.0
        avg_sleep = sum(h.sleep_quality for h in self.history) / 4.0
        avg_act = max(1, sum(h.activity_minutes for h in self.history) / 4.0)

        # Calculate Negative Deviations
        drop_energy = max(0, avg_energy - current.energy)        # Energy
        drop_appetite = max(0, avg_appetite - current.appetite)    # Appetite
        drop_sleep = max(0, avg_sleep - current.sleep_quality)  # Sleep
        drop_act = max(0, (avg_act - current.activity_minutes) / avg_act) # Activity minute

        # Weighting (Normal breed v.s High Energy breed)
        w_act, w_sleep, w_energy, w_appetite = 0.25, 0.25, 0.25, 0.25
        if self.pet.is_high_energy:
            w_act = 0.40
            w_sleep = 0.10

        raw_score = 100.0
        drivers = []

        # Sighal v.s Noise
        if drop_act >= 1.0 and (drop_energy >= 1.0 or drop_sleep >= 1.0):
            raw_score -= 25.0
            drivers.append("Combined drop in appetite and energy/sleep")
        else:
            raw_score -= (drop_appetite * 10 * w_appetite)
            raw_score -= (drop_energy * 10 * w_energy)
            raw_score -= (drop_sleep * 10 * w_sleep)
            if drop_act  >= 1: drivers.append("Slightly lower appetite")
            if drop_energy >= 1: drivers.append("Slightly lower energy")

        # Activity Penalty
        if drop_act > 0.15:
            raw_score -= (drop_act * 30 * w_act)
            drivers.append("Lower activity than usual")

        # Medium weight vitals, platform data
        if current.social_behaviour in ["Withdrawn", "Aggressive", "Clingy"]:
            raw_score -= 10.0
            drivers.append(f"Social behaviour shift ({current.social_behaviour})")
            
        if not self.pet.worming_compliant:
            raw_score -= 10.0
            drivers.append("Overdue for worming treatment")

        final_score = max(0, min(100, int(raw_score)))
        zone_name = self._get_zone(final_score)
        
        if not drivers:
            drivers = ["Vitals are stable and consistent"]

        return OutputData(
            vitality_score=final_score,
            zone=zone_name,
            trend="Stable" if final_score >= 85 else "Slightly down", 
            confidence=self.pet.consistency,
            top_drivers=drivers,
            red_flag=False,
            recommended_next_step=self._get_next_step(zone_name),
            owner_summary=self._generate_summary(zone_name, drivers)
        )
    
    def _get_zone(self, score: int) -> str:
        if score >= 85: return "Bright Green"
        if score >= 70: return "Medium Green"
        if score >= 50: return "Watch Zone"
        return "Action Needed"

    def _get_next_step(self, zone: str) -> str:
        if zone in ["Bright Green", "Medium Green"]: return "Keep up the great routine."
        if zone == "Watch Zone": return "Monitor closely; consider reviewing our vet directory."
        return "Contact your veterinarian for advice." 

    def _generate_summary(self, zone: str, drivers: List[str]) -> str:
        if zone == "Bright Green":
            return "Your pet is doing wonderfully and tracking perfectly with their normal baseline."
        return f"Your pet seems a little below their usual pattern this week, mainly due to {drivers[0].lower()}."

        
        
        