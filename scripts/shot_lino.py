"""梨诺主题效果截图：星空背景 + 等级条 + 弹窗，离屏渲染 PNG。"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_DEPS = ROOT / '.deps'
if _DEPS.is_dir():
    sys.path.insert(0, str(_DEPS))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.engine import StatsEngine  # noqa: E402
from app.services.checkin_service import CheckinService  # noqa: E402
from app.services.reward_service import RewardService  # noqa: E402
from app.services.achievement_service import AchievementService  # noqa: E402
from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402
from app.theme.theme_manager import ThemeManager  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

BALANCE = json.loads((ROOT / 'config' / 'balance.json').read_text(encoding='utf-8'))
ACH = json.loads((ROOT / 'config' / 'achievements.json').read_text(encoding='utf-8'))


def main() -> int:
    tmp = ROOT / '.tmptest'
    tmp.mkdir(exist_ok=True)
    import uuid
    td = tmp / ('tt_' + uuid.uuid4().hex)
    td.mkdir()

    app = QApplication([])
    conn = connect_db(td / 't.db')
    init_schema(conn)
    repo = Repository(conn)

    def gs(key, default=None):
        return repo.get_setting(key, default)

    engine = StatsEngine(repo, gs, BALANCE)
    checkin = CheckinService(repo, BALANCE)
    checkin.checkin_if_needed(engine.current_day())
    for _ in range(120):
        engine.handle_char('letter')
        engine.handle_ime('梨诺')
    ach = AchievementService(repo, BALANCE, ACH)

    win = MainWindow(engine, repo, BALANCE, tray=None,
                     checkin=checkin, rewards=RewardService(repo, BALANCE),
                     achievements=ach)
    win.show()
    tm = ThemeManager(app, td, gs, repo.set_setting)
    tm.register_reports(win._reports)
    tm.register_window(win)
    tm.apply('arknights_endfield_lino')

    # 弹窗 + 等级条推进
    win._dashboard._level_bar.set_progress(0.68)
    win.show_toast('🏆 成就解锁', '「初窥门径」到成就页领取奖励', 'achievement')
    win.show_toast('🎉 升级！', 'Lv.2 → Lv.3 称号「初露锋芒」', 'level')

    for _ in range(8):
        app.processEvents()
        time.sleep(0.05)

    out = ROOT / '.shots'
    out.mkdir(exist_ok=True)
    f = out / 'lino_dashboard.png'
    win.grab().save(str(f))
    print('saved:', f)

    # 像素多样性检查（紫色星空应远多于纯色界面）
    from PySide6.QtGui import QImage
    img = QImage(str(f))
    colors = set()
    for x in range(0, img.width(), 6):
        for y in range(0, img.height(), 6):
            colors.add(img.pixelColor(x, y).name())
    print('distinct sampled colors:', len(colors))
    win.close()
    import shutil
    shutil.rmtree(td, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
