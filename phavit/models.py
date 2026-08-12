"""
Typed data models for the PHAIVIT scoring engine.

These are plain dataclasses so the engine can be imported, tested and called
from check-in completion flows without any notebook or framework dependency.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional
import statistics


@dataclass
class PetProfile:
    """Static information about a pet. Drives breed-aware weighting only."""
    pet_id: str
    name: str
    species: str                   # "dog" | "cat"
    breed: str
    sex: str                       # "male" | "female"
    post_code: int
    birth_date: date
    is_high_energy: bool           # e.g. Vizsla, Border Collie -> activity weighted higher
    worming_compliant: bool        # provisional, non-clinical care-compliance nudge
    vaccination_current: bool

    # Owner has recorded a deliberate weight-management plan. Suppresses the
    # weight-loss escalation while the loss stays within a safe rate, so owners
    # doing the right thing are not alarmed for succeeding.
    weight_management_plan: bool = False


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
    weight_kg: Optional[float] = None            # weight changes may later be a signal
    owner_concern_level: Optional[int] = None    # 1-5 owner subjective worry, advisory only


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
    def from_history(cls, history: List["CheckInData"], min_checkins: int = 4) -> "BaselineSummary":
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
class WeightReading:
    """
    A single recorded body weight. Weight is logged MONTHLY, on its own cadence,
    not once per weekly check-in - so it is kept apart from CheckInData.
    """
    kg: float
    at: date


@dataclass
class WeightTrendResult:
    """
    Output of the weight subsystem (weight.py). Computed when a new weight is
    recorded, stored, then read by the weekly pipeline - it is never recomputed
    from scratch inside a check-in.

    `rate_per_4w` is the headline number: percent body weight LOST per 4 weeks
    (negative means gain). Normalising to a 4-week rate makes readings taken at
    irregular intervals comparable.
    """
    status: str                        # "ok" | "insufficient" | "implausible"
    direction: str = "unknown"         # "loss" | "gain" | "stable" | "unknown"
    pct_change: float = 0.0            # % change over the window (positive = loss)
    rate_per_4w: float = 0.0           # % per 4 weeks (positive = loss)
    baseline_kg: Optional[float] = None
    current_kg: Optional[float] = None
    as_of: Optional[date] = None       # date of the LATEST valid reading
    weeks_span: float = 0.0
    body_status: str = "no_reference"  # vs breed reference; see weight.body_status()
    is_growing: bool = False           # under the breed's adult age - growth expected
    managed: bool = False              # loss is within a recorded weight plan
    tier: Optional[str] = None         # "urgent" | "monitor" | None (trend-only rules)
    notes: List[str] = field(default_factory=list)


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
    # Latest weight signal, carried through for Pawport display and the WS9
    # referral hooks. None whenever no weight has been recorded.
    weight_trend: Optional["WeightTrendResult"] = None
