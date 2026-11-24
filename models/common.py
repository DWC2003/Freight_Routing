"""Shared input validation and the canonical transport-mode vocabulary."""
from math import isfinite
from numbers import Real

MODES = ("truck", "rail", "air", "ship")


def number(name, value, minimum=0, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number.")
    if not isfinite(value) or value < minimum or (positive and value <= 0):
        raise ValueError(f"{name} must be finite and in its permitted range.")
    return value


def integer(name, value, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer.")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def identifier(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string.")
    return value


def mode(value):
    if not isinstance(value, str):
        raise TypeError("Transport mode must be a string.")
    value = value.strip().lower()
    value = {"sea": "ship"}.get(value, value)
    if value not in MODES:
        raise ValueError(f"Unsupported mode: {value!r}")
    return value
