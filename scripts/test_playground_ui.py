"""Real Qt flows for 0.9.4 modules; only network responses are stubbed."""
import threading
from unittest.mock import patch
from test_ui_workflow import UIFixture, APP, pump_until
from app.services.ai_service import AIService
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QClipboard


class PlaygroundUITests(UIFixture):
    def playground(self, mode):
        window = self.window()
        window._nav_buttons['训练'].click()
        page = window._challenge_page
        page.mode_buttons[mode].click()
        APP.processEvents()
        return window, page

    def test_keyboard_deadline_and_saved_local_ranking(self):
        _, page = self.playground('keyboard')
        panel = page.keyboard_panel
        panel.start_button.click()
        now = [0.0]
        panel.session._started = 0
        panel.session._clock = lambda: now[0]
        QTest.keyClicks(panel.input, 'abcd')
        QTest.keyClick(panel.input, Qt.Key_Backspace)
        QTest.keyClicks(panel.input, 'e')
        now[0] = 15
        panel._tick()
        self.assertFalse(panel.input.isEnabled())
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertIn('20', panel.table.item(0, 1).text())
        panel._tick()
        self.assertEqual(len(panel.service.leaderboard()), 1)

    def test_keyboard_paste_and_mode_switch_cannot_create_score(self):
        _, page = self.playground('keyboard')
        panel = page.keyboard_panel
        panel.start_button.click()
        APP.clipboard().setText('fake score', QClipboard.Clipboard)
        QTest.keyClick(panel.input, Qt.Key_V, Qt.ControlModifier)
        self.assertEqual(panel.session.tw, 0)
        page.mode_buttons['chaos'].click()
        self.assertIsNone(panel.session)
        self.assertFalse(panel.service.leaderboard())
        self.assertFalse(page._running)

    def test_keyboard_same_text_replacement_and_unicode_count_actual_insertions(self):
        _, page = self.playground('keyboard')
        panel = page.keyboard_panel
        panel.start_button.click()
        QTest.keyClicks(panel.input, 'a')
        panel.input.selectAll()
        QTest.keyClicks(panel.input, 'a')
        self.assertEqual(panel.session.tw, 2)
        from PySide6.QtGui import QInputMethodEvent
        event = QInputMethodEvent()
        event.setCommitString('中😀')
        APP.sendEvent(panel.input, event)
        self.assertEqual(panel.session.tw, 5)
        self.assertEqual(panel.session.typed_chars, 4)
        QTest.keyClick(panel.input, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(panel.input, Qt.Key_Y, Qt.ControlModifier)
        self.assertEqual(panel.session.tw, 5)
        QTest.keyClick(panel.input, Qt.Key_Tab)
        self.assertEqual(panel.session.tw, 6)

    def test_keyboard_failed_save_is_retryable_without_duplicate_score(self):
        _, page = self.playground('keyboard')
        panel = page.keyboard_panel
        panel.start_button.click()
        QTest.keyClicks(panel.input, 'a')
        panel.session._clock = lambda: panel.session._started + 15
        self.conn.execute("CREATE TRIGGER fail_keyboard BEFORE INSERT ON keyboard_warrior_history BEGIN SELECT RAISE(FAIL, 'test'); END;")
        self.conn.commit()
        panel._tick()
        self.assertIsNotNone(panel.session)
        self.assertFalse(panel.input.isEnabled())
        page.mode_buttons['practice'].click()
        page.mode_buttons['keyboard'].click()
        self.conn.execute('DROP TRIGGER fail_keyboard')
        self.conn.commit()
        panel.start_button.click()
        self.assertIsNone(panel.session)
        self.assertEqual(len(panel.service.leaderboard()), 1)

    def test_chaos_generates_short_plain_text_and_recovers_from_error(self):
        self.repo.set_setting('ai_backend', 'openai')
        _, page = self.playground('chaos')
        panel = page.chaos_panel
        with patch.object(AIService, '_chat', return_value='<云朵>今天辞职去当键盘。' * 10):
            panel.generate_button.click()
            self.assertTrue(pump_until(lambda: panel.request is None))
        self.assertEqual(len(panel.output.toPlainText()), 60)
        previous = panel.output.toPlainText()
        with patch.object(AIService, '_chat', side_effect=TimeoutError()):
            panel.generate_button.click()
            self.assertTrue(pump_until(lambda: panel.request is None))
        self.assertEqual(panel.output.toPlainText(), previous)
        self.assertTrue(panel.generate_button.isEnabled())

    def test_chaos_stale_result_is_ignored_on_mode_switch(self):
        self.repo.set_setting('ai_backend', 'openai')
        _, page = self.playground('chaos')
        panel = page.chaos_panel
        release = threading.Event()
        def delayed(*args, **kwargs):
            release.wait(2)
            return '月亮在煮键盘。'
        with patch.object(AIService, '_chat', side_effect=delayed):
            panel.generate_button.click()
            request = panel.request
            page.mode_buttons['practice'].click()
            release.set()
            self.assertTrue(pump_until(lambda: not request._thread.is_alive()))
        self.assertEqual(panel.output.toPlainText(), '')

    def test_background_passage_completion_does_not_end_keyboard_running_state(self):
        self.repo.set_setting('ai_backend', 'openai')
        self.repo.add_reward('ai_pass', 1, 'test')
        window, page = self.playground('practice')
        page._topic_edit.setText('星星')
        release = threading.Event()
        def delayed(*args, **kwargs):
            release.wait(2)
            return '星星在天空中闪烁。'
        with patch.object(AIService, '_chat', side_effect=delayed):
            page._ai_btn.click()
            self.assertIsNotNone(page._gen_thread)
            page.mode_buttons['keyboard'].click()
            page.keyboard_panel.start_button.click()
            release.set()
            self.assertTrue(pump_until(lambda: page._gen_thread is None))
        self.assertIsNotNone(page.keyboard_panel.session)
        self.assertTrue(page._running)
        self.assertFalse(window._motion_active())
        page.mode_buttons['practice'].click()
        self.assertTrue(page._start_btn.isEnabled())
        self.assertTrue(page._ai_section.toggle.isEnabled())
