from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class PetProfile:
    """
    Pet data
    """
    pet_id: str
    pet_name: Optional[str] = None
    breed: str                      # for searching any special attribute of the breed
    birth_date: datetime
    is_high_energy: bool            # e.g., Vizsla 
    postcode: str                   # For seasonal/geographic tick risk 
    streak: int                     # auto calculate number of checkin in (consecutive), reset if hasn't checkin more than 1 week (7 days)
    consistency: float               # Automatic check if has owner has checkin regularly
    worming_compliant: bool         # Non-compliance moves score to Action Needed 
    vaccination_current: bool       # Treatment currency feeds score 
    days_since_last_vet_visit: int  # Auto-calculated metric 
    
@dataclass
class VetInteractionLog:
    visited_vet: bool
    reason_for_visit: Optional[str] = None # Categorized reason informs score 

@dataclass
class DentalHealthLog:
    """Periodic check-in (Puppy teething, 6-month baseline, and 6-monthly ongoing)"""
    breath_odour: str             # e.g., "Noticeably worse", "Normal" 
    chewing_changes: str          # e.g., "Less interested", "Favouring one side" 
    gum_redness_bleeding: str     # e.g., "Noticed buildup/redness", "Normal" 
    professional_clean_due: bool  # True/False
    
@dataclass
class ToiletingLog:
    """Tracks bowel habits, frequency, and acute overrides"""
    frequency_changes: str    # e.g., "Normal", "More frequent", "Less frequent"
    consistency_changes: str  # e.g., "Normal", "Runny", "Hard" 
    indoor_accidents: bool    # True/False 
    blood_present: bool


@dataclass
class CheckInData:
    """The Weekly Check-in Data payload"""
    pet_id: str
    timestamp: datetime
    
    # Pre-Moment 1 Context
    vet_interaction: VetInteractionLog 
    
    # Core Weekly Vitals (Moment 1 & 2)
    energy: int                  # 1-10 scale (comparative to baseline) 
    appetite: int                # 1-10 scale 
    sleep_quality: int           # 1-10 scale 
    water_intake: str            # "Normal", "Increased", "Decreased" (Increased = High Risk) 
    activity_minutes: int        # Aggregated from Strava-style quick-logs 
    
    # Behaviour & Changes
    diet_changed: bool           # Elevated if coincides with health signal 
    social_behaviour: str        # e.g., "Normal", "Withdrawn", "Clingy", "Aggressive" 
    
    # Physical & Specific Logs
    physical_health: Dict[str, int] # e.g., {"eyes": 10, "ears": 8, "coat": 9} 
    toileting: ToiletingLog         # Modular sub-class 
    
    # Parasite & Pain Checks (Moment 1 Additions)
    tick_check_completed: bool      # Passive score contributor if consistently done 
    skin_or_lump_issue_found: bool  # True/False 
    is_in_pain: bool                # Triggers quarterly or from combined flags 
    
    # Periodic & Monthly Inputs (Can be None/Null on standard weeks)
    weight: Optional[float] = None              # First check-in of each month [cite: 310]
    dental_log: Optional[DentalHealthLog] = None # Periodic (weeks 12-24, or 6-monthly) [cite: 213]
    
    # Closing Question (Breeder / Owner Support)
    owner_wellbeing_status: str     # Flags breeder dashboard if struggling 2+ weeks 

class OutputData:
    """Output"""
    vitality_score: Optional[int]
    zone: str
    trend: str
    confidence: str
    top_drivers: List[str]
    red_flag: bool
    recommended_next_step: str
    owner_summary: str
    