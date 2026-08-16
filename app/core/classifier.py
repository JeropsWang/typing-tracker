"""字符分类与 tw 换算（统一度量衡）。

规则（可在 config/balance.json 调整）:
- 汉字 = 2 tw
- 字母 = 1 tw
- 数字 / 标点 / 空格 / 其他符号 = 1 tw
"""
from __future__ import annotations

HANZI_RANGES = (
    (0x3400, 0x4DBF),    # 扩展 A
    (0x4E00, 0x9FFF),    # 基本区
    (0xF900, 0xFAFF),    # 兼容表意文字
    (0x20000, 0x2A6DF),  # 扩展 B
    (0x2A700, 0x2B73F),  # 扩展 C
    (0x2B740, 0x2B81F),  # 扩展 D
    (0x2B820, 0x2CEAF),  # 扩展 E
)


def is_hanzi(ch: str) -> bool:
    """判断单个字符是否为汉字（CJK 表意文字）。"""
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in HANZI_RANGES)


def classify_char(ch: str) -> str:
    """返回 'hanzi' | 'letter' | 'other'。"""
    if is_hanzi(ch):
        return 'hanzi'
    if len(ch) == 1 and ch.isascii() and ch.isalpha():
        return 'letter'
    return 'other'


def char_tw(ch: str, balance=None) -> int:
    kind = classify_char(ch)
    if kind == 'hanzi':
        return 2 if balance is None else balance.get('unit', {}).get('hanzi_tw', 2)
    return 1


def text_tw(text: str, balance=None) -> int:
    return sum(char_tw(ch, balance) for ch in text)


# ---- 三个预测换算（平均 tw/分 → 汉字/分、字母/分） ----

def tw_to_hanzi_per_min(tw_per_min: float) -> float:
    """预测平均汉字数/分 = 平均tw/分 ÷ 2（假设全部输入为汉字）。"""
    return tw_per_min / 2.0


def tw_to_letters_per_min(tw_per_min: float) -> float:
    """预测平均字母数/分 = 平均tw/分 × 1（假设全部输入为字母）。"""
    return tw_per_min
