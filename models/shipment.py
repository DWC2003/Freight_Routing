"""One shipment that must travel together from its origin to its destination."""

from dataclasses import dataclass
from math import isfinite
from typing import Optional


@dataclass
class Shipment:
    shipment_id: str
    origin: str
    destination: str
    volume: float
    start_time: float
    deadline: float
    priority: int = 1  # A larger number means a higher priority.
    allowed_modes: Optional[set[str]] = None  # None allows every mode.

    def __post_init__(self):
        if not self.shipment_id or not self.origin or not self.destination:
            raise ValueError("Shipment ID, origin and destination are required.")
        if not isfinite(self.volume) or self.volume <= 0:
            raise ValueError("Shipment volume must be a positive finite number.")
        if not isfinite(self.start_time) or self.start_time < 0:
            raise ValueError("Start time must be a nonnegative finite number.")
        if not isfinite(self.deadline) or self.deadline < self.start_time:
            raise ValueError("Deadline must be finite and at or after start time.")
        if not isinstance(self.priority, int) or self.priority < 0:
            raise ValueError("Priority must be a nonnegative integer.")
