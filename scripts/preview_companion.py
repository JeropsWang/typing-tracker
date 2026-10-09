"""Isolated Sariana companion/workshop preview: no global hooks or user database."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--capture', default=str(ROOT / '.local/0.9.3/preview'))
    args = parser.parse_args()
    if not args.interactive:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ui_test_support import prepare_fonts, load_fonts
    prepare_fonts()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from app.core.engine import StatsEngine
    from app.services.checkin_service import CheckinService
    from app.services.reward_service import RewardService
    from app.services.achievement_service import AchievementService
    from app.services.challenge_service import ChallengeService
    from app.services.ai_service import AIService
    from app.storage.db import connect_db, init_schema
    from app.storage.repository import Repository
    from app.theme.theme_manager import ThemeManager
    from app.ui.main_window import MainWindow
    from app.companion.models import CompanionEvent
    from app.ui.companion.workshop import Workshop
    app = QApplication([])
    load_fonts()
    from PySide6.QtGui import QFontDatabase
    serif = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/simsun.ttc'
    if serif.is_file():
        QFontDatabase.addApplicationFont(str(serif))
    out = Path(args.capture)
    out.mkdir(parents=True, exist_ok=True)
    data = out / ('data-' + uuid.uuid4().hex)
    data.mkdir()
    conn = connect_db(data / 'preview.db')
    init_schema(conn)
    repo = Repository(conn)
    repo.set_settings({'nickname': '星光练习生', 'reduced_motion': '1', 'companion_frequency': 'off'})
    balance = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
    definitions = json.loads((ROOT / 'config/achievements.json').read_text(encoding='utf-8'))
    theme = ThemeManager(app, data, repo.get_setting, repo.set_setting)
    window = MainWindow(StatsEngine(repo, repo.get_setting, balance), repo, balance,
                        checkin=CheckinService(repo, balance), rewards=RewardService(repo, balance),
                        achievements=AchievementService(repo, balance, definitions),
                        challenge=ChallengeService(repo), ai_service=AIService(repo),
                        theme_manager=theme, data_dir=data)
    window.setWindowTitle('Sariana 0.9.3 隔离预览 · 示例数据')
    theme.register_reports(window._reports)
    theme.register_window(window)
    theme.apply('arknights_endfield_lino')
    window.show()
    app.processEvents()
    companion = window._companion
    companion.handle_event(CompanionEvent('pet'))
    QTest.qWait(100)
    window.grab().save(str(out / 'companion-window.png'))
    window._tabs.setCurrentWidget(window._challenge_page)
    QTest.qWait(100)
    window.grab().save(str(out / 'companion-training.png'))
    companion.switch_mode('desktop')
    companion.handle_event(CompanionEvent('record'))
    QTest.qWait(100)
    companion.view.grab().save(str(out / 'companion-desktop.png'))
    if not args.desktop:
        companion.switch_mode('window')
    workshop = Workshop(companion.store, companion, window)
    workshop.show()
    workshop.resize(1120, 760)
    workshop.load_pack('starlight')
    workshop.copy_draft()
    workshop.name_edit.setText('星光陪伴')
    workshop.editor.selection.setCurrentIndex(4)
    QTest.qWait(100)
    workshop.grab().save(str(out / 'workshop-wide.png'))
    workshop.resize(820, 650)
    workshop.tabs.setCurrentIndex(1)
    QTest.qWait(100)
    workshop.grab().save(str(out / 'workshop-narrow.png'))
    workshop.resize(1120, 760)
    print(json.dumps({'preview': str(out), 'data_dir': str(data), 'keyboard_hook': False}, ensure_ascii=False))
    if args.interactive:
        repo.set_setting('reduced_motion', '0')
        companion.sync_settings()
        if args.desktop:
            companion.switch_mode('desktop')
        return app.exec()
    workshop.preview.view.shutdown()
    companion.shutdown()
    window.hide()
    workshop.hide()
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
