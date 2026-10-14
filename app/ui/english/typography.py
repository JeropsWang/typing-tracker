"""English-only logical pixel sizes; never shrink text for a compact window."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EnglishType:
    """不可变英语字号角色，分别定义正文、辅助、释义、答案和句子尺寸。"""
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
    """按档位取得字号方案，未知值回退到 large。"""
    return SIZES.get(key, SIZES['large'])
