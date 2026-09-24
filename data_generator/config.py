"""Explicit, reproducible generation profiles."""

from dataclasses import asdict, dataclass
from datetime import date

VERSION = "1.0.0"
PROFILES = {
    "small": dict(customers=600, orders=3500, items=36, categories=12, locations=4, ratings=1200, wastage=750, promotions=8),
    "medium": dict(customers=6000, orders=35000, items=72, categories=12, locations=8, ratings=12000, wastage=7500, promotions=20),
    "full": dict(customers=60000, orders=350000, items=180, categories=12, locations=24, ratings=120000, wastage=75000, promotions=40),
}


@dataclass(frozen=True)
class Config:
    profile: str = "small"
    seed: int = 42
    start: str = "2025-01-01"
    end: str = "2026-07-01"  # Exclusive boundary, never inferred from today's date.
    corruption_rate: float = 0.01

    def __post_init__(self):
        if self.profile not in PROFILES:
            raise ValueError("Unknown profile")
        if (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days < 120:
            raise ValueError("History must contain at least 120 days")
        if not 0 <= self.corruption_rate <= 0.1:
            raise ValueError("Corruption rate must be between 0 and 0.1")

    @property
    def sizes(self):
        return PROFILES[self.profile]

    def manifest(self):
        return asdict(self) | {"sizes": self.sizes, "generator_version": VERSION}
