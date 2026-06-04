"""Pump.fun bonding-curve graduation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

GraduationStatus = Literal["graduated", "near-graduation", "bonding-curve", "unknown"]


@dataclass(frozen=True)
class PumpfunGraduation:
    status: GraduationStatus
    progress_pct: float | None = None
    reason: str = ""

    @property
    def eligible(self) -> bool:
        return self.status in {"graduated", "near-graduation"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _progress_from(info: dict[str, Any]) -> float | None:
    for key in (
        "progress_pct",
        "bonding_curve_progress",
        "graduation_progress",
        "completion_pct",
        "progress",
    ):
        pct = _as_float(info.get(key))
        if pct is None:
            continue
        if 0 <= pct <= 1:
            pct *= 100
        return max(0.0, min(100.0, pct))
    return None


def classify_pumpfun_graduation(
    info: dict[str, Any] | None,
    *,
    near_progress_pct: float = 90.0,
) -> PumpfunGraduation:
    """Classify a Pump.fun token without inferring private trading thresholds."""

    if not info:
        return PumpfunGraduation("unknown", reason="No Pump.fun response")
    if bool(info.get("complete") or info.get("graduated")):
        return PumpfunGraduation("graduated", 100.0, "Pump.fun marks the coin complete")

    progress_pct = _progress_from(info)
    if progress_pct is None:
        return PumpfunGraduation("unknown", reason="No bonding-curve progress field")
    if progress_pct >= near_progress_pct:
        return PumpfunGraduation(
            "near-graduation",
            progress_pct,
            f"Bonding-curve progress is {progress_pct:.1f}%",
        )
    return PumpfunGraduation(
        "bonding-curve",
        progress_pct,
        f"Bonding-curve progress is {progress_pct:.1f}%",
    )
