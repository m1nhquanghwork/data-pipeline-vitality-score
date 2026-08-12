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
    WeightReading,
    WeightTrendResult,
)
from .red_flags import RedFlagEngine, EMERGENCY_SIGNS
from .scoring import VitalityScoreEngine, Weights, BASE_PROFILES
from .weight import compute_weight_trend, validate_readings, body_status
from .pipeline import process_checkin

__all__ = [
    "PetProfile",
    "CheckInData",
    "BaselineSummary",
    "RedFlagResult",
    "VitalityScoreResult",
    "WeightReading",
    "WeightTrendResult",
    "RedFlagEngine",
    "EMERGENCY_SIGNS",
    "VitalityScoreEngine",
    "Weights",
    "BASE_PROFILES",
    "compute_weight_trend",
    "validate_readings",
    "body_status",
    "process_checkin",
]
