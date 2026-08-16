"""生成演示数据（近 N 天每日快照 + 分钟数据 + 打卡记录），方便预览报表。

不会修改今天的实时统计（今天的行由应用自己写）。
用法：python scripts/seed_demo.py [--data-dir DIR] [--days 120]
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402

DEFAULT_DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'TypingTracker'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR))
    ap.add_argument('--days', type=int, default=120)
    args = ap.parse_args()
    rng = random.Random(20260601)

    conn = connect_db(Path(args.data_dir) / 'app.db')
    init_schema(conn)
    repo = Repository(conn)

    today = date.today()
    streak = 0
    for i in range(args.days - 1, -1, -1):
        d = today - timedelta(days=i)
        if i == 0:
            continue  # 今天留给应用实时统计
        if rng.random() < 0.12:
            streak = 0
            continue  # 模拟断签，打卡日历会出现空缺
        typed = rng.randint(1800, 8200)
        deleted = rng.randint(60, 320)
        valid = max(0, typed - deleted)
        minutes = rng.randint(20, 90)
        hanzi = int(typed * rng.uniform(0.4, 0.9))     # 中英混合
        tw = hanzi * 2 + (typed - hanzi)
        repo.upsert_daily({
            'date': d.isoformat(), 'typed_chars': typed,
            'deleted_chars': deleted, 'valid_chars': valid,
            'total_tw': tw, 'active_minutes': minutes,
            'avg_tw': round(tw / minutes, 2), 'accuracy': round(valid / typed, 4),
        })
        n_min = rng.randint(2, 6)
        hour_pool = list(range(8, 23))
        rows = []
        for _ in range(n_min):
            hh = rng.choice(hour_pool)
            mm = rng.randint(0, 59)
            m_typed = rng.randint(20, 120)
            m_del = rng.randint(0, 8)
            m_hanzi = int(m_typed * rng.uniform(0.3, 0.9))
            m_tw = m_hanzi * 2 + (m_typed - m_hanzi)
            rows.append((d.isoformat(), f'{hh:02d}:{mm:02d}', m_typed, m_del, m_tw))
        if rows:
            repo.upsert_minutes(rows)
        streak += 1
        repo.add_checkin(d.isoformat(), streak, 20, 0)

    print(f'演示数据已写入 {args.data_dir}（{args.days - 1} 天，不含今天）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
