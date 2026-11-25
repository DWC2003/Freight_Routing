"""An indivisible shipment with hard mode restrictions and a soft preference."""
from dataclasses import dataclass
from typing import Optional
from models.common import identifier, integer, mode, number


@dataclass
class Shipment:
    shipment_id: str
    origin: str
    destination: str
    volume: float
    start_time: float
    deadline: float
    priority: int = 1
    allowed_modes: Optional[set[str]] = None
    preferred_mode: Optional[str] = None

    def __post_init__(self):
        for name in ("shipment_id", "origin", "destination"):
            identifier(name, getattr(self, name))
        number("volume", self.volume, positive=True)
        number("start_time", self.start_time)
        number("deadline", self.deadline, minimum=self.start_time)
        integer("priority", self.priority, minimum=0)
        if self.allowed_modes is not None:
            if not isinstance(self.allowed_modes, (set, frozenset, list, tuple)):
                raise TypeError("allowed_modes must be a collection of modes or None.")
            self.allowed_modes = {mode(value) for value in self.allowed_modes}
        if self.preferred_mode is not None:
            self.preferred_mode = mode(self.preferred_mode)

            if self.allowed_modes is not None and self.preferred_mode not in self.allowed_modes:
                raise ValueError("preferred_mode must be included in allowed_modes")
