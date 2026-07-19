"""Load settings.yaml and spots.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("RWA_ROOT", Path(__file__).resolve().parents[2]))


@dataclass
class Spot:
    id: str
    name: str
    latitude: float
    longitude: float
    phenomena: list[str] = field(default_factory=list)


@dataclass
class Settings:
    raw: dict

    @property
    def timezone(self) -> str:
        return self.raw["timezone"]

    @property
    def tiers(self) -> dict:
        return self.raw["tiers"]

    @property
    def merge_gap_hours(self) -> int:
        return self.raw["merge_gap_hours"]

    @property
    def coalesce_gap_hours(self) -> int:
        return self.raw["coalesce_gap_hours"]

    @property
    def forecast_days(self) -> int:
        return self.raw["forecast_days"]

    def path(self, key: str) -> Path:
        p = Path(self.raw["paths"][key])
        return p if p.is_absolute() else ROOT / p


def load_settings() -> Settings:
    with open(ROOT / "config" / "settings.yaml") as f:
        return Settings(yaml.safe_load(f))


def load_spots() -> list[Spot]:
    with open(ROOT / "config" / "spots.yaml") as f:
        data = yaml.safe_load(f)
    return [Spot(**s) for s in data["spots"]]
