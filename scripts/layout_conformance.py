"""训练页基准尺寸核对：把实际控件几何与交接 spec.json 的 frames 比对。

容差按 UI_SPEC：纸张位置误差 ≤12px，主要控件边界误差 ≤8px。
只读隔离内存库、离屏渲染，不安装键盘钩子、不触碰用户数据。

用法：.venv\\Scripts\\python.exe -B scripts/layout_conformance.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from ui_test_support import prepare_fonts, load_fonts  # noqa: E402

prepare_fonts()

from PySide6.QtWidgets import QApplication  # noqa: E402
from app.core.engine import StatsEngine  # noqa: E402
from app.services.achievement_service import AchievementService  # noqa: E402
from app.services.ai_service import AIService  # noqa: E402
from app.services.challenge_service import ChallengeService  # noqa: E402
from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402
from app.theme.theme_manager import ThemeManager  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

SPEC = json.loads((ROOT / '.local/ui-night-stage/deepseek-handoff/v1/design/spec.json')
                  .read_text(encoding='utf-8'))
PAPER_TOLERANCE = 12
CONTROL_TOLERANCE = 8


def main() -> int:
    app = QApplication([])
    load_fonts()
    conn = connect_db(':memory:')
    init_schema(conn)
    repo = Repository(conn)
    balance = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
    definitions = json.loads((ROOT / 'config/achievements.json').read_text(encoding='utf-8'))
    data = ROOT / '.local/ui-night-stage/preview-data'
    theme = ThemeManager(app, data, repo.get_setting, repo.set_setting)

    class CheckWindow(MainWindow):
        def closeEvent(self, event):
            event.accept()

    window = CheckWindow(StatsEngine(repo, repo.get_setting, balance), repo, balance,
                         achievements=AchievementService(repo, balance, definitions),
                         challenge=ChallengeService(repo), ai_service=AIService(repo),
                         theme_manager=theme, data_dir=data)
    theme.register_reports(window._reports)
    theme.register_window(window)
    theme.apply('arknights_endfield_lino')
    window.show()
    page = window._challenge_page

    failures = []
    for frame_name, frame in SPEC['frames'].items():
        width, height = (int(part) for part in frame_name.split('x'))
        window.resize(width, height)
        window._tabs.setCurrentWidget(page)
        window.refresh()
        app.processEvents()
        app.processEvents()

        widgets = {
            'paper': page._paper,
            'source': page._text_combo,
            'reference': page._ref_label,
            'input': page._input,
            'metrics': page._metrics_box,
            'primary': page._start_btn,
            'secondary': page._secondary,
            'nav': window._nav,
            'lettering': page._art,
        }
        print(f'== window {frame_name}（页面区 {page.width()}x{page.height()}，'
              f'紧凑={page._compact}）==')
        for key, widget in widgets.items():
            expected = frame.get(key)
            if expected is None:
                continue
            top_left = widget.mapTo(window, widget.rect().topLeft())
            actual = (top_left.x(), top_left.y(), widget.width(), widget.height())
            dx = actual[0] - expected[0]
            dy = actual[1] - expected[1]
            dw = actual[2] - expected[2]
            dh = actual[3] - expected[3]
            tolerance = PAPER_TOLERANCE if key in ('paper', 'nav', 'lettering') else CONTROL_TOLERANCE
            worst = max(abs(dx), abs(dy))
            ok = worst <= tolerance
            # 高度允许按内容增长（纸张/次级区），只卡左上角位置与宽度
            if key in ('paper', 'secondary'):
                ok = ok and abs(dw) <= tolerance
            else:
                ok = ok and abs(dw) <= tolerance and abs(dh) <= tolerance
            status = 'OK  ' if ok else 'FAIL'
            print(f'  {status} {key:10s} 实际={actual} 基准={tuple(expected)} '
                  f'dx={dx:+d} dy={dy:+d} dw={dw:+d} dh={dh:+d}（容差 {tolerance}）')
            if not ok:
                failures.append(f'{frame_name}/{key}: dx={dx:+d} dy={dy:+d} '
                                f'dw={dw:+d} dh={dh:+d}（容差 {tolerance}）')
        print()

    window.hide()
    conn.close()
    if failures:
        print('基准核对未通过：')
        for item in failures:
            print(' -', item)
        return 1
    print('基准核对通过：纸张 ≤12px、控件 ≤8px 全部满足。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
