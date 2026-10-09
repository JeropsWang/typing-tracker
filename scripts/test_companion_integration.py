"""Real service results and settings drive the companion, not preview fixtures."""
import uuid
from unittest.mock import patch
from test_ui_workflow import UIFixture, APP


class CompanionIntegrationTests(UIFixture):
    def test_main_window_owns_one_controller_and_settings_cancel_has_no_effect(self):
        window = self.window()
        original = window._companion
        dialog = self.dialog()
        dialog._companion_settings.mode.setCurrentIndex(1)
        dialog.reject()
        self.assertEqual(self.repo.get_setting('companion_mode', 'window'), 'window')
        dialog = self.dialog()
        dialog._companion_settings.mode.setCurrentIndex(1)
        dialog.accept()
        original.sync_settings()
        self.assertEqual(original.mode, 'desktop')
        self.assertIs(window._companion, original)
        self.assertEqual(self.repo.get_setting('companion_mode'), 'desktop')

    def test_challenge_saved_record_emits_single_companion_event(self):
        window = self.window()
        page = window._challenge_page
        window._tabs.setCurrentWidget(page)
        page._start()
        page._finish(page._current_text(), page._current_text())
        self.assertEqual(window._companion.runtime.sample().state, 'proud')
        self.assertGreater(len(page._svc.recent(5)), 0)

    def test_failed_challenge_save_does_not_celebrate(self):
        window = self.window()
        page = window._challenge_page
        window._tabs.setCurrentWidget(page)
        page._start()
        before = window._companion.runtime.sample().token
        with patch.object(page._svc, 'record', side_effect=OSError('save failed')):
            with self.assertRaises(OSError):
                page._finish(page._current_text(), page._current_text())
        self.assertEqual(window._companion.runtime.sample().token, before)

    def test_english_sentence_save_drives_reaction_once(self):
        window = self.window()
        page = window._english_page
        window._tabs.setCurrentWidget(page)
        page._set_mode('sentence')
        page.sentences.set_history([{'id': 1, 'topic': 'test', 'created_at': '2026-10-09',
                                     'words': ['hello'], 'sentences': [{'text': 'Hello world.', 'translation': '你好，世界。'}]}])
        page._start_sentence()
        page.sentences.input.setPlainText('Hello world.')
        page._finish_sentence()
        self.assertEqual(window._companion.runtime.sample().state, 'happy')
        token = window._companion.runtime.sample().token
        page._finish_sentence()
        self.assertEqual(window._companion.runtime.sample().token, token)

    def test_app_hidden_desktop_receives_real_achievement(self):
        window = self.window()
        window._companion.switch_mode('desktop')
        window.hide()
        APP.processEvents()
        window.notify('成就', '解锁了新成就', 'achievement')
        self.assertEqual(window._companion.runtime.sample().state, 'celebrating')
