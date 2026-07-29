"""
PHAIVIT scoring engine.

A validation-ready, rules-based, NON-DIAGNOSTIC wellbeing scoring engine plus a
red-flag safety net. Import the orchestrator and call it on each completed
weekly check-in:

    from phavit import process_checkin
    result = process_checkin(pet, previous_checkins, current_checkin)
"""

from .models import (
    PetProfile,
    CheckInData,
    BaselineSummary,
    RedFlagResult,
    VitalityScoreResult,
)
from .red_flags import RedFlagEngine, EMERGENCY_SIGNS
from .scoring import VitalityScoreEngine
from .pipeline import process_checkin

__all__ = [
    "PetProfile",
    "CheckInData",
    "BaselineSummary",
    "RedFlagResult",
    "VitalityScoreResult",
    "RedFlagEngine",
    "EMERGENCY_SIGNS",
    "VitalityScoreEngine",
    "process_checkin",
]
