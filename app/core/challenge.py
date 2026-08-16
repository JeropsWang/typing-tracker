"""打字竞速挑战：范文库 + 逐字对比计分（真正的正确率，非按键近似）。

与全局统计的口径差异（诚实说明）：
- 全局正确率 = 有效字数/输入字数（删除按键计入失误，被动统计的近似）
- 挑战正确率 = 与原文逐字对比（主动练习的精确口径）
"""
from __future__ import annotations

from .classifier import text_tw

TEXTS = [
    {'id': 'cn_star', 'name': '中文·星空物语', 'lang': 'cn',
     'text': '夜空中最亮的星，请照亮我前行的路。每一颗星星都在诉说自己的故事，而我们的故事，才刚刚开始。'},
    {'id': 'cn_typing', 'name': '中文·打字练习', 'lang': 'cn',
     'text': '打字是一门艺术，也是日常生活的必备技能。坚持练习，你的手指会在键盘上起舞，速度与准确并存。'},
    {'id': 'cn_dream', 'name': '中文·追梦的人', 'lang': 'cn',
     'text': '梦想不会发光，发光的是追梦的你。在无数个平凡的夜晚，正是那些看似微小的坚持，悄悄改变着未来的方向。'},
    {'id': 'cn_fox', 'name': '中文·风与云', 'lang': 'cn',
     'text': '清风拂过山岗，白云飘向远方。我们在时间里行走，在键盘上书写，把每一个平凡的日子，都过成闪闪发光的样子。'},
    {'id': 'en_hello', 'name': 'English · Hello World', 'lang': 'en',
     'text': 'The quick brown fox jumps over the lazy dog. Practice makes perfect, and every keystroke brings you closer to mastery.'},
    {'id': 'en_star', 'name': 'English · A Starry Tale', 'lang': 'en',
     'text': 'Under the starry sky, every light tells a story. Keep typing, keep dreaming, and let your fingers dance across the keys.'},
    {'id': 'en_code', 'name': 'English · Think & Type', 'lang': 'en',
     'text': 'Good typing is not about speed alone. It is about rhythm, accuracy, and the quiet confidence that comes with practice.'},
]

TEXT_BY_ID = {t['id']: t for t in TEXTS}


def compare(input_text: str, reference: str):
    """逐字对比：相同位置字符一致计正确，其余（含长度差）计错误。

    返回 (正确数, 错误数)。
    """
    n = min(len(input_text), len(reference))
    correct = sum(1 for i in range(n) if input_text[i] == reference[i])
    errors = max(len(input_text), len(reference)) - correct
    return correct, errors


def score(input_text: str, reference: str, elapsed_seconds: float, balance=None):
    """计算挑战成绩。tw 用全局口径（汉字 2tw、字母 1tw）。"""
    correct, errors = compare(input_text, reference)
    total = len(reference) or 1
    accuracy = correct / total
    tw = text_tw(input_text, balance)
    speed = tw / (elapsed_seconds / 60.0) if elapsed_seconds > 0 else 0.0
    return {
        'typed_chars': len(input_text),
        'errors': errors,
        'accuracy': accuracy,
        'tw': tw,
        'speed': speed,
    }
