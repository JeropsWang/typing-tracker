"""离屏检查标题与导航的布局回归，不接触用户数据。"""
import os
import json
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app.ui.widgets.design import ArtHeading, BottomNav


class LayoutRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_heading_stays_in_left_decoration_region(self):
        heading = ArtHeading('today', '每一次敲击')
        heading.resize(1100, 180)
        heading.show()
        self.app.processEvents()
        self.assertLessEqual(heading.art.width(), 650)
        self.assertLessEqual(heading.art.height(), 130)
        self.assertEqual(heading.art.x(), 0)
        heading.close()

    def test_nav_uses_available_width(self):
        nav = BottomNav(compact=True)
        for title, icon in [('今日', 'today'), ('训练', 'training'),
                            ('统计', 'stats'), ('成长', 'growth'), ('设置', 'settings')]:
            nav.add_item(title, icon)
        nav.show()
        buttons = list(nav.buttons.values())
        for width in (868, 1376, 2495):
            nav.resize(width, 62)
            self.app.processEvents()
            self.assertGreater(buttons[-1].geometry().center().x(), nav.width() * .8)
            self.assertLessEqual(max(b.width() for b in buttons) - min(b.width() for b in buttons), 2)
        nav.close()

    def test_business_pages_keep_header_and_compact_actions_visible(self):
        from app.core.engine import StatsEngine
        from app.services.checkin_service import CheckinService
        from app.services.reward_service import RewardService
        from app.storage.db import connect_db, init_schema
        from app.storage.repository import Repository
        from app.theme.theme_manager import ThemeManager
        from app.ui.main_window import MainWindow
        root = Path(__file__).resolve().parents[1]
        conn = connect_db(':memory:')
        init_schema(conn)
        repo = Repository(conn)
        balance = json.loads((root / 'config/balance.json').read_text(encoding='utf-8'))
        theme = ThemeManager(self.app, root / '.local/ui-night-stage/preview-data',
                             repo.get_setting, repo.set_setting)
        window = MainWindow(StatsEngine(repo, repo.get_setting, balance), repo, balance,
                            checkin=CheckinService(repo, balance),
                            rewards=RewardService(repo, balance), theme_manager=theme)
        theme.register_window(window)
        theme.apply('arknights_endfield_lino')
        window.show()
        try:
            for width, height in [(1440, 1024), (900, 640), (1440, 1024)]:
                window.resize(width, height)
                page = window._checkin_page
                window._tabs.setCurrentWidget(page)
                window.refresh()
                for _ in range(4):
                    self.app.processEvents()
                viewport = page._page.scroll.viewport()
                for button in (page._repair_btn, page._boost_btn):
                    top = button.mapTo(viewport, button.rect().topLeft())
                    self.assertGreaterEqual(top.y(), 0)
                    self.assertLessEqual(top.y() + button.height(), viewport.height())
                    self.assertGreaterEqual(button.height(), 44)
                stats = window._reports
                window._tabs.setCurrentWidget(stats)
                for _ in range(4):
                    self.app.processEvents()
                art_bottom = stats._heading.mapTo(window, stats._heading.rect().bottomLeft()).y()
                paper_top = stats._paper.mapTo(window, stats._paper.rect().topLeft()).y()
                self.assertLess(art_bottom, paper_top)
        finally:
            window.hide()
            window.deleteLater()
            self.app.processEvents()
            conn.close()

    def test_ai_workspace_preserves_draft_and_keeps_actions_visible(self):
        from app.services.ai_service import AIService
        from app.services.challenge_service import ChallengeService
        from app.storage.db import connect_db, init_schema
        from app.storage.repository import Repository
        from app.theme.theme_manager import ThemeManager
        from app.ui.pages.challenge import ChallengePage
        conn = connect_db(':memory:')
        init_schema(conn)
        repo = Repository(conn)
        root = Path(__file__).resolve().parents[1]
        balance = json.loads((root / 'config/balance.json').read_text(encoding='utf-8'))
        theme = ThemeManager(self.app, root / '.local/ui-night-stage/preview-data',
                             repo.get_setting, repo.set_setting)
        theme.apply('arknights_endfield_lino')
        page = ChallengePage(repo, balance, ChallengeService(repo), AIService(repo))
        try:
            page.show()
            page._topic_edit.setText('雨后的小城')
            page._lang_combo.setCurrentIndex(1)
            for size in [(1440, 874), (900, 526), (750, 600)]:
                page.resize(*size)
                page._ai_section.toggle.setChecked(True)
                for _ in range(8):
                    self.app.processEvents()
                self.assertFalse(page._paper.isVisible())
                self.assertTrue(page._ai_composer.isVisible())
                viewport = page._page_scroll.viewport()
                page._page_scroll.ensureWidgetVisible(page._ai_btn, 0, 0)
                for _ in range(4):
                    self.app.processEvents()
                for control in (page._topic_edit, page._lang_combo, page._ai_btn,
                                page._ai_composer.back_button):
                    top = control.mapTo(viewport, control.rect().topLeft())
                    self.assertGreaterEqual(top.y(), 0)
                    self.assertLessEqual(top.y() + control.height(), viewport.height())
                    self.assertGreaterEqual(top.x(), 0)
                    self.assertLessEqual(top.x() + control.width(), viewport.width())
                    self.assertGreaterEqual(control.height(), 44)
                page._ai_composer.back_button.click()
                for _ in range(8):
                    self.app.processEvents()
                self.assertTrue(page._paper.isVisible())
                self.assertFalse(page._ai_composer.isVisible())
                self.assertEqual(page._topic_edit.text(), '雨后的小城')
                self.assertEqual(page._lang_combo.currentData(), 'en')
                self.assertLessEqual(page._secondary.height(), 62)
        finally:
            page.hide()
            page.deleteLater()
            self.app.processEvents()
            conn.close()


if __name__ == '__main__':
    unittest.main()
