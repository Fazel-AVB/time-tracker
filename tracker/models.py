from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Subject:
    name: str
    low_level_label: str
    high_level_label: str
    id: Optional[int] = None


@dataclass
class TimeEntry:
    date: date
    subject_id: int
    duration_hours: float
    notes: str = ""
    id: Optional[int] = None
    # Populated by JOIN queries:
    subject_name: Optional[str] = None
    low_level_label: Optional[str] = None
    high_level_label: Optional[str] = None


@dataclass
class Reflection:
    week_start: date
    strengths: str = ""
    weaknesses: str = ""
    next_week_plan: str = ""
    id: Optional[int] = None


@dataclass
class Goal:
    week_start: date          # the week this goal is intended FOR
    description: str
    target_hours: Optional[float] = None
    subject_id: Optional[int] = None   # optional link to a subject for auto-evaluation
    notes: str = ""
    id: Optional[int] = None
    subject_name: Optional[str] = None  # populated by JOIN


@dataclass
class GoalOutcome:
    goal_id: int
    actual_hours: Optional[float] = None
    met: int = 0              # 0 = not met, 1 = met, 2 = partial
    notes: str = ""
    id: Optional[int] = None
