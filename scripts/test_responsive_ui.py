"""固定窗口内的页面布局回归，使用内存数据，不启动键盘钩子。"""
import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui_test_support import prepare_fonts, load_fonts
prepare_fonts()
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication
from app.core.engine import StatsEngine
from app.services.ai_service import AIService
from app.services.challenge_service import ChallengeService
from app.storage.db import connect_db, init_schema
from app.storage.repository import Repository
from app.theme.theme_manager import ThemeManager
from app.ui.main_window import MainWindow


class ResponsiveUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        load_fonts()

    def setUp(self):
        self.conn = connect_db(':memory:')
        init_schema(self.conn)
        repo = Repository(self.conn)
        balance = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
        theme = ThemeManager(self.app, ROOT / '.local/ui-night-stage/preview-data',
                             repo.get_setting, repo.set_setting)
        self.window = MainWindow(StatsEngine(repo, repo.get_setting, balance), repo, balance,
                                 challenge=ChallengeService(repo), ai_service=AIService(repo),
                                 theme_manager=theme)
        theme.register_window(self.window)
        theme.apply('arknights_endfield_lino')
        self.page = self.window._challenge_page
        self.window._tabs.setCurrentWidget(self.page)
        self.window.show()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.conn.close()

    def resize(self, width, height):
        self.window.resize(width, height)
        for _ in range(12):
            self.app.processEvents()

    def assert_visible(self, control, container):
        point = control.mapTo(container, control.rect().topLeft())
        self.assertGreaterEqual(point.x(), 0)
        self.assertGreaterEqual(point.y(), 0)
        self.assertLessEqual(point.x() + control.width(), container.width())
        self.assertLessEqual(point.y() + control.height(), container.height())

    def test_rejected_enlargement_keeps_paper_size_and_illustration_space(self):
        original_width = self.page._paper.width()
        self.resize(2560, 1440)
        self.assertEqual(self.window.size(), QSize(1440, 1024))
        self.assertEqual(self.page._paper.width(), original_width)
        self.assertLess(self.page._paper.width(), self.window.width() * .80)
        end = self.page._secondary.mapTo(self.page, self.page._secondary.rect().bottomLeft()).y()
        self.assertLess(self.page.height() - end, 180)
        self.assertLessEqual(self.page._input.height(), 280, '避免靠无限拉高空输入框填屏')

    def test_rejected_resizes_keep_training_and_secondary_entries_in_view(self):
        for size in [(900, 640), (1100, 720), (1440, 900), (900, 640)]:
            self.resize(*size)
            self.assertEqual(self.window.size(), QSize(1440, 1024))
            viewport = self.page._page_scroll.viewport()
            for control in (self.page._input, self.page._start_btn,
                            self.page._ai_section.toggle, self.page._recent_disclosure.toggle):
                self.assert_visible(control, viewport)
            self.assertGreaterEqual(self.page._ai_section.toggle.height(), 44)
            self.assertGreaterEqual(self.page._recent_disclosure.toggle.height(), 44)
            self.assertEqual(self.page._page_scroll.horizontalScrollBar().maximum(), 0)
            self.assertEqual(self.page._secondary.verticalScrollBar().maximum(), 0)

    def test_navigation_docks_without_excessive_spacing_and_preserves_selection(self):
        for size in [(900, 640), (1440, 1024), (2560, 1440), (900, 640)]:
            self.resize(*size)
            nav = self.window._nav
            self.assertLessEqual(nav.width(), 1400)
            center = nav.mapTo(self.window, nav.rect().center()).x()
            self.assertLessEqual(abs(center - self.window.width() / 2), 3)
            for button in nav.buttons.values():
                self.assert_visible(button, nav)
                self.assertGreaterEqual(button.height(), 44)
            self.assertTrue(nav.buttons['训练'].isChecked())

    def test_ai_controls_stay_visible_after_rejected_resizes(self):
        self.page._ai_section.toggle.setChecked(True)
        for size in [(2560, 1440), (1200, 800), (900, 640)]:
            self.resize(*size)
            self.assertEqual(self.window.size(), QSize(1440, 1024))
            for control in (self.page._topic_edit, self.page._lang_combo, self.page._ai_btn,
                            self.page._ai_composer.back_button):
                self.assert_visible(control, self.page._page_scroll.viewport())
        self.page._ai_composer.back_button.click()
        self.assertTrue(self.page._paper.isVisible())

    def test_repeated_window_requests_do_not_change_density_or_paper_position(self):
        before = (self.page._paper.size(), self.page._input.size(), self.window._nav.size(),
                  self.page._paper.mapTo(self.page, self.page._paper.rect().topLeft()))
        for size in [(1100, 800), (1100, 920), (2560, 1440)]:
            self.resize(*size)
            self.assertEqual(self.window._compact, self.page._compact,
                             '页面与导航必须使用同一个稳定的窗口预算')
            after = (self.page._paper.size(), self.page._input.size(), self.window._nav.size(),
                     self.page._paper.mapTo(self.page, self.page._paper.rect().topLeft()))
            self.assertEqual(before, after)

    def test_blocked_maximize_preserves_running_practice_and_input(self):
        self.page._start()
        text = self.page._current_text()[:1]
        self.page._input.setPlainText(text)
        self.window.setWindowState(Qt.WindowMaximized)
        for _ in range(4):
            self.app.processEvents()
        self.assertTrue(self.page._running)
        self.assertEqual(self.page._input.toPlainText(), text)
        self.assertFalse(self.window.isMaximized())
        self.assertTrue(self.window._nav.buttons['训练'].isChecked())


if __name__ == '__main__':
    unittest.main()
