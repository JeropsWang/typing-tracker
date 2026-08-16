"""数据备份导出（M4）：daily_stats CSV + 全量 JSON 包。"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path


def export_all(repo, out_dir) -> str:
    """导出到 out_dir/typing_backup_时间戳/；返回导出目录路径。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    folder = out / f'typing_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    folder.mkdir()

    rows = repo.get_daily_range('0000-01-01', '9999-12-31')
    with open(folder / 'daily_stats.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['date', 'typed_chars', 'deleted_chars', 'valid_chars',
                    'total_tw', 'active_minutes', 'avg_tw', 'accuracy', 'exp_gained'])
        for r in rows:
            w.writerow([r['date'], r['typed_chars'], r['deleted_chars'],
                        r['valid_chars'], r['total_tw'], r['active_minutes'],
                        r['avg_tw'], r['accuracy'], r['exp_gained']])

    bundle = {
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'lifetime': repo.get_lifetime(),
        'settings': {r['key']: r['value'] for r in
                     repo._conn.execute('SELECT key, value FROM settings')},
        'achievements': repo.get_achievements(),
        'rewards': repo.list_rewards(),
        'checkins': repo.get_checkins('0000-01-01', '9999-12-31'),
    }
    (folder / 'data.json').write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(folder)
