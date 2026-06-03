from dataclass_layout import PetProfile, CheckInData, OutputData
from typing import  List ,Optional

class RedFlagEngine:
    def evaluate(self, current: CheckInData) -> Optional[OutputData]:
        """
        Scans for acute overrides. Returns a critical OutputData object if a 
        red flag is found, otherwise returns None to allow Layer 1 to calculate normally.
        """
        acute_driver = None

        # Toileting Red Flags (Immediate bypass)
        if current.toileting.blood_present:
            acute_driver = "Blood present in stool"

        # Increased Water Intake (Chronic disease flag)
        elif current.water_intake == "Increased":
            acute_driver = "Significantly increased water intake"

        # Sudden Collapse (Combined lethargy and anorexia)
        # Using <= 2 on a 1-10 scale to represent "collapse"
        elif current.energy <= 2 and current.appetite <= 2:
            acute_driver = "Sudden collapse in appetite combined with lethargy"

        # Confirmed Tick / Parasite 
        elif current.skin_or_lump_issue_found and current.tick_check_completed:
            # Assuming the issue found during a tick check is a confirmed tick
            acute_driver = "Confirmed tick or parasite"

        # If any override was triggered, return the Action Needed object immediately
        if acute_driver:
            return OutputData(
                vitality_score=40,  # Forces the UI into the Below 50 zone
                zone="Action Needed",
                trend="Acute Drop",
                confidence="High",  # Acute signs are high confidence triggers
                top_drivers=[acute_driver],
                red_flag=True,
                recommended_next_step="Contact your veterinarian immediately.",
                owner_summary=f"We noticed {acute_driver.lower()}, which requires professional advice. Please contact your vet."
            )

        # No red flags detected; return None so the pipeline knows to proceed to Layer 1
        return None
    