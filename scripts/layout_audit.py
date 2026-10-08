"""布局体检：离屏构造主窗口，自动检测几何问题（重叠/越界/文本溢出）。

用法：python scripts/layout_audit.py [--theme arknights_endfield_lino]
输出问题清单，作为 UI 回归检查（selftest 可调用核心函数）。
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from ui_test_support import prepare_fonts, load_fonts
prepare_fonts()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_DEPS = ROOT / '.deps'
if _DEPS.is_dir():
    sys.path.insert(0, str(_DEPS))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QLabel, QTabWidget, QWidget,
)

from app.core.engine import StatsEngine  # noqa: E402
from app.services.achievement_service import AchievementService  # noqa: E402
from app.services.challenge_service import ChallengeService  # noqa: E402
from app.services.checkin_service import CheckinService  # noqa: E402
from app.services.reward_service import RewardService  # noqa: E402
from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402
from app.theme.theme_manager import ThemeManager  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

BALANCE = json.loads((ROOT / 'config' / 'balance.json').read_text(encoding='utf-8'))
ACH = json.loads((ROOT / 'config' / 'achievements.json').read_text(encoding='utf-8'))


def _inside_scroll(w: QWidget) -> bool:
    """是否位于任意滚动容器的后代链中（内容高度可超视口）。"""
    p = w.parentWidget()
    while p is not None:
        if p.inherits('QAbstractScrollArea'):
            return True
        p = p.parentWidget()
    return False


def audit_window(win: MainWindow, label: str) -> list:
    """遍历控件，检测：越界 / 文本溢出 / 与兄弟重叠。返回问题列表。"""
    issues = []
    w_widgets = win.findChildren(QWidget)

    for w in w_widgets:
        if not w.isVisible():
            continue
        g = w.geometry()
        parent = w.parentWidget()
        # 1) 越界（相对父控件；滚动容器内内容不算越界）
        if parent is not None and parent is not win and not _inside_scroll(w):
            if (g.right() > parent.width() + 4 or g.bottom() > parent.height() + 4
                    or g.left() < -4 or g.top() < -4):
                issues.append(f'[{label}] 越界: {type(w).__name__} '
                              f'geo=({g.x()},{g.y()},{g.width()}x{g.height()}) '
                              f'父={type(parent).__name__}({parent.width()}x{parent.height()})')
        # 2) 文本溢出（QLabel 内容宽 > 控件宽；自动换行标签跳过）
        if isinstance(w, QLabel) and w.text() and not w.wordWrap():
            try:
                hint = w.sizeHint()
                if hint.width() > w.width() + 24 and w.width() > 0:
                    issues.append(f'[{label}] 文本溢出: "{w.text()[:20]}..." '
                                  f'需要{hint.width()}px 实际{w.width()}px')
            except Exception:
                pass

    # 3) 同父重叠：仅统计"非父子关系"且均非布局容器的同级控件
    from collections import defaultdict
    buckets = defaultdict(list)
    for w in w_widgets:
        if not w.isVisible() or w.parentWidget() is None:
            continue
        if isinstance(w, (QFrame, QLabel)) and w.size().width() > 4:
            parent = w.parentWidget()
            if isinstance(parent, QLabel) or isinstance(parent, QFrame):
                continue   # 父子同几何属正常（cell 内填充）
            key = (id(parent), w.x() // 3, w.y() // 3)
            buckets[key].append(w)
    for key, items in buckets.items():
        if len(items) >= 2:
            sizes = {f'{i.geometry().width()}x{i.geometry().height()}' for i in items}
            if len(sizes) == 1:
                issues.append(f'[{label}] 疑似重叠 @({key[1] * 3},{key[2] * 3}): '
                              f'{len(items)} 个 {next(iter(sizes))}')
    return issues


def main() -> int:
    app = QApplication([])
    load_fonts()
    tmp = ROOT / '.tmptest'
    tmp.mkdir(exist_ok=True)
    td = tmp / ('tt_' + uuid.uuid4().hex)
    td.mkdir()
    conn = connect_db(td / 't.db')
    init_schema(conn)
    repo = Repository(conn)

    def gs(key, default=None):
        return repo.get_setting(key, default)

    engine = StatsEngine(repo, gs, BALANCE)
    checkin = CheckinService(repo, BALANCE)
    checkin.checkin_if_needed(engine.current_day())
    for _ in range(200):
        engine.handle_char('letter')
        engine.handle_ime('布局体检测试文本')
    ach = AchievementService(repo, BALANCE, ACH)
    win = MainWindow(engine, repo, BALANCE, tray=None,
                     checkin=checkin, rewards=RewardService(repo, BALANCE),
                     achievements=ach, challenge=ChallengeService(repo),
                     data_dir=td)
    win.show()
    tm = ThemeManager(app, td, gs, repo.set_setting)
    tm.register_reports(win._reports)
    tm.register_window(win)

    import sys as _sys
    theme_id = 'arknights_endfield_lino'
    if '--theme' in _sys.argv:
        theme_id = _sys.argv[_sys.argv.index('--theme') + 1]
    tm.apply(theme_id)
    app.processEvents()

    all_issues = []
    for i in range(win._tabs.count()):
        win._tabs.setCurrentIndex(i)
        app.processEvents()
        all_issues += audit_window(win, f'Tab{i}({win._tabs.tabText(i)})')

    if all_issues:
        print(f'发现 {len(all_issues)} 个布局问题：')
        for issue in all_issues[:40]:
            print(' -', issue)
    else:
        print('布局体检通过：无越界/溢出/重叠')
    win.close()
    import shutil
    shutil.rmtree(td, ignore_errors=True)
    return 1 if all_issues else 0


if __name__ == '__main__':
    sys.exit(main())
