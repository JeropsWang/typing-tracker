"""独立英语入口、作答交互、异步造句与持久化材料回归。"""
import json
import threading
import unittest
from unittest.mock import patch
from test_ui_workflow import UIFixture, APP, pump_until
from app.services.ai_service import AIService
from layout_audit import audit_window
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


class EnglishUITests(UIFixture):
    def page(self):
        window = self.window()
        window._nav_buttons['英语'].click()
        APP.processEvents()
        return window, window._english_page

    def test_english_navigation_and_fixed_layout(self):
        window, page = self.page()
        self.assertIs(window._tabs.currentWidget(), page)
        self.assertEqual(window.size().width(), 1440)
        self.assertEqual(list(window._nav_buttons), ['今日', '训练', '英语', '统计', '成长', '设置'])
        self.assertFalse(window._nav_buttons['英语'].icon().isNull())
        self.assertFalse(audit_window(window, '英语拼写'))

    def test_enter_submit_next_and_review_empty(self):
        _, page = self.page()
        page.mode_buttons['review'].click()
        page.spelling.start_button.click()
        self.assertIn('没有', page.spelling.feedback.text())
        page.mode_buttons['spelling'].click()
        page.spelling.start_button.click()
        answer = page.service.session.current.word
        page.spelling.answer.setText(answer)
        QTest.keyClick(page.spelling.answer, Qt.Key_Return)
        self.assertEqual(page.service.summary('cet4')['attempts'], 1)
        QTest.keyClick(page.spelling.answer, Qt.Key_Return)
        self.assertEqual(page.service.summary('cet4')['attempts'], 1)
        self.assertEqual(page.service.session.index, 1)

    def test_generation_stale_result_and_close(self):
        self.repo.set_setting('ai_backend', 'openai')
        self.repo.add_reward('ai_pass', 1, 'test')
        window, page = self.page()
        page.mode_buttons['sentence'].click()
        page._targets = ('government',)
        release = threading.Event()
        def delayed_chat(*args, **kwargs):
            release.wait(2)
            return json.dumps([{'text': 'The government supports a local school.', 'translation': '政府支持当地学校。'}])
        with patch.object(AIService, '_chat', side_effect=delayed_chat):
            page.sentences.generate_button.click()
            request = page._request
            page.library.deck_combo.setCurrentIndex(1)
            self.assertIsNone(page._request, '切换词库应立即取消旧请求')
            self.assertFalse(page.sentences.history_combo.count() > 1)
            release.set()
            self.assertTrue(pump_until(lambda: not request._thread.is_alive()))
        self.assertEqual(self.repo.count_ai_passes(), 1)
        self.assertFalse(self.repo.english.sentence_history('cet4'))
        page.library.deck_combo.setCurrentIndex(0)
        page._targets = ('government',)
        release.clear()
        with patch.object(AIService, '_chat', side_effect=delayed_chat):
            page.sentences.generate_button.click()
            request = page._request
            window.hide()
            release.set()
            self.assertTrue(pump_until(lambda: not request._thread.is_alive()))
        self.assertEqual(self.repo.count_ai_passes(), 1)

    def test_saved_generation_can_be_practised(self):
        self.repo.set_setting('ai_backend', 'openai')
        self.repo.add_reward('ai_pass', 1, 'test')
        _, page = self.page()
        page.mode_buttons['sentence'].click()
        page._targets = ('government',)
        response = [{'text': 'The government supports a local school.', 'translation': '政府支持当地学校。'}]
        with patch.object(AIService, '_chat', return_value=json.dumps(response)):
            page.sentences.generate_button.click()
            self.assertTrue(pump_until(lambda: page._request is None))
        self.assertEqual(self.repo.count_ai_passes(), 0)
        self.assertEqual(len(self.repo.english.sentence_history('cet4')), 1)
        panel = page.sentences
        from PySide6.QtGui import QFont
        marked = panel.reference.document().find('government')
        self.assertGreaterEqual(marked.charFormat().fontWeight(), QFont.Bold)
        panel.start_button.click()
        panel.input.setPlainText(response[0]['text'])
        panel.finish_button.click()
        attempts = self.repo.english.export()['attempts']
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]['accuracy'], 1)
        self.assertNotIn('answer', attempts[0])

    def test_long_translation_keeps_input_and_actions_in_view(self):
        window, page = self.page()
        page.mode_buttons['sentence'].click()
        page.sentences.set_history([dict(id=1, topic='长释义', created_at='2026-10-08', words=['government'],
            sentences=[dict(text='The government supports a local school.', translation='这是较长的中文解释。' * 30)])])
        APP.processEvents()
        translation = page.sentences.translation
        self.assertLessEqual(translation.heightForWidth(translation.width()), translation.height(),
                             '长释义需要完整展示或提供滚动，不应被固定行高裁切')
        input_bottom = page.sentences.input.mapTo(window, page.sentences.input.rect().bottomLeft()).y()
        action_bottom = page.sentences.finish_button.mapTo(window, page.sentences.finish_button.rect().bottomLeft()).y()
        nav_top = window._nav.mapTo(window, window._nav.rect().topLeft()).y()
        self.assertLess(input_bottom, nav_top)
        self.assertLess(action_bottom, nav_top)

    def test_minimize_and_tray_restore_preserve_active_practice(self):
        window, page = self.page()
        page.spelling.start_button.click()
        session = page.service.session
        page.spelling.answer.setText('draft')
        for hide, show in ((window.showMinimized, window.showNormal), (window.hide, window.show)):
            hide()
            APP.processEvents()
            self.assertIs(page.service.session, session)
            show()
            APP.processEvents()
            self.assertTrue(page.spelling.answer.isEnabled())
            self.assertEqual(page.spelling.answer.text(), 'draft')
            self.assertTrue(page._running)
        page.mode_buttons['sentence'].click()
        text = 'The government supports a local school.'
        page.sentences.set_history([dict(id=1, topic='恢复', created_at='2026-10-08', words=['government'],
            sentences=[dict(text=text, translation='政府支持当地学校。')])])
        page.sentences.start_button.click()
        run = page._sentence_run
        page.sentences.input.setPlainText('The government')
        for hide, show in ((window.showMinimized, window.showNormal), (window.hide, window.show)):
            hide()
            APP.processEvents()
            self.assertEqual(page._sentence_run, run)
            show()
            APP.processEvents()
            self.assertTrue(page.sentences.finish_button.isEnabled())
            self.assertEqual(page.sentences.input.toPlainText(), 'The government')
            self.assertTrue(page._running)
        page.sentences.input.setPlainText(text)
        page.sentences.finish_button.click()
        self.assertEqual(len(self.repo.english.export()['attempts']), 1)

    def test_storage_failure_has_feedback_and_can_retry(self):
        _, page = self.page()
        page.spelling.start_button.click()
        word = page.service.session.current.word
        page.spelling.answer.setText(word)
        self.conn.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON english_attempts BEGIN SELECT RAISE(FAIL, 'test write error'); END;")
        self.conn.commit()
        page.spelling.submit_button.click()
        self.assertIn('未保存', page.spelling.feedback.text())
        self.assertIsNone(page.service.session.result)
        self.conn.execute('DROP TRIGGER fail_attempt')
        self.conn.commit()
        page.spelling.submit_button.click()
        self.assertEqual(page.service.summary('cet4')['attempts'], 1)
        page.spelling.submit_button.click()
        self.conn.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON english_attempts BEGIN SELECT RAISE(FAIL, 'test write error'); END;")
        self.conn.commit()
        page.spelling.reveal_button.click()
        self.assertIn('未保存', page.spelling.feedback.text())
        self.assertIsNone(page.service.session.result)
        self.conn.execute('DROP TRIGGER fail_attempt')
        self.conn.commit()
        page.spelling.reveal_button.click()
        self.assertTrue(page.service.session.result['assisted'])
        self.assertEqual(page.service.summary('cet4')['attempts'], 2)
        page.mode_buttons['sentence'].click()
        text = 'The government supports a local school.'
        page.sentences.set_history([dict(id=1, topic='重试', created_at='2026-10-08', words=['government'],
            sentences=[dict(text=text, translation='政府支持当地学校。')])])
        page.sentences.start_button.click()
        page.sentences.input.setPlainText(text)
        run = page._sentence_run
        self.conn.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON english_attempts BEGIN SELECT RAISE(FAIL, 'test write error'); END;")
        self.conn.commit()
        page.sentences.finish_button.click()
        self.assertIn('未保存', page.sentences.status.text())
        self.assertEqual(page._sentence_run, run)
        self.conn.execute('DROP TRIGGER fail_attempt')
        self.conn.commit()
        page.sentences.finish_button.click()
        self.assertEqual(len(self.repo.english.export()['attempts']), 3)
        page.sentences.finish_button.click()
        self.assertEqual(len(self.repo.english.export()['attempts']), 3)


class FixtureCleanupTests(unittest.TestCase):
    def test_fixture_releases_deferred_widgets(self):
        from shiboken6 import isValid
        fixture = UIFixture()
        fixture.setUp()
        try:
            window = fixture.window()
        finally:
            fixture.tearDown()
        self.assertFalse(isValid(window), '每个隔离用例结束后应释放 Qt 窗口，防止跨用例定时器残留')


if __name__ == '__main__':
    unittest.main()
