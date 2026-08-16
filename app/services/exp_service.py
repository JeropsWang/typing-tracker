"""经验与等级。

等级曲线（config/balance.json）：
cost(n) = cost_base + cost_growth * n        # 从 n 级升到 n+1 级所需经验
cumulative(k) = Σ cost(n), n=1..k
              = cost_base*k + cost_growth*k*(k+1)/2
满级 100；用户可开启「无限等级之路」→ 同一公式继续累加，无上限。
"""
from __future__ import annotations

import math


def cumulative_cost(k: int, balance: dict) -> int:
    """升到第 k+1 级所需的累计经验（level 1 起点为 0）。"""
    base = balance['level']['cost_base']
    growth = balance['level']['cost_growth']
    return base * k + growth * k * (k + 1) // 2


def level_from_exp(exp: int, balance: dict) -> int:
    """由总经验反解等级（公式累加，可解一元二次方程）。

    k = 已完成的升级次数；等级 = k+1（cum(1)=42 时 42 exp 应升 Lv.2）。
    曾返回 k 导致全员低一级（v0.8.9 修复）。
    """
    base = balance['level']['cost_base']
    growth = balance['level']['cost_growth']
    if growth == 0:
        k = exp // base if base else exp
    else:
        a = growth / 2.0
        b = base + growth / 2.0
        k = int((math.sqrt(b * b + 4 * a * exp) - b) / (2 * a))
    return max(1, k + 1)


def level_and_progress(exp: int, balance: dict):
    """返回 (等级, 升级进度 0~1, 距下一级所需经验 or None)。"""
    raw = level_from_exp(exp, balance)
    infinite = balance['level'].get('infinite_levels', False)
    max_level = balance['level']['max_level']
    if not infinite:
        level = min(raw, max_level)
    else:
        level = raw
    cur = cumulative_cost(level - 1, balance)
    if not infinite and level >= max_level:
        return level, 1.0, None
    nxt = cumulative_cost(level, balance)
    span = max(1, nxt - cur)
    progress = max(0.0, min(1.0, (exp - cur) / span))
    return level, progress, nxt - exp


def band_title(level: int, balance: dict, bands=None) -> str:
    """返回等级段称号；超出所有段（无限之路）返回 infinite_title。"""
    bands = bands or balance['level'].get('bands', [])
    for b in bands:
        if b['from'] <= level <= b['to']:
            return b['title']
    return balance['level'].get('infinite_title', '无限之路')
