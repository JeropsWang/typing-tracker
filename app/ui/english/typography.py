"""English-only logical pixel sizes; never shrink text for a compact window."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EnglishType:
    body: int
    meaning: int
    answer: int
    sentence: int
    helper: int


SIZES = {
    'standard': EnglishType(16, 22, 24, 22, 14),
    'large': EnglishType(18, 24, 28, 24, 16),
    'extra': EnglishType(20, 28, 32, 28, 18),
}


def english_type(key):
    return SIZES.get(key, SIZES['large'])
