"""离屏截图工具：把主窗口各 Tab 渲染为 PNG，便于开发检查界面与图表。

用法：python scripts/screenshot.py --data-dir DIR [--tab 0|1] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_DEPS = ROOT / '.deps'
if _DEPS.is_dir():
    sys.path.insert(0, str(_DEPS))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.engine import StatsEngine  # noqa: E402
from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--tab', type=int, default=1, choices=[0, 1])
    ap.add_argument('--out', default=str(ROOT / '.shots'))
    args = ap.parse_args()

    balance = json.loads((ROOT / 'config' / 'balance.json').read_text(encoding='utf-8'))
    app = QApplication([])
    conn = connect_db(Path(args.data_dir) / 'app.db')
    init_schema(conn)
    repo = Repository(conn)
    engine = StatsEngine(repo, lambda k, d=None: repo.get_setting(k, d), balance)

    win = MainWindow(engine, repo, balance, tray=None)
    win.show()
    win._tabs.setCurrentIndex(args.tab)
    app.processEvents()
    win._reports.refresh()
    app.processEvents()

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    f = out / f'tab{args.tab}.png'
    win.grab().save(str(f))
    print(f'saved: {f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
