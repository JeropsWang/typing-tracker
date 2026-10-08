"""思考配置、请求用量与开发者彩蛋；隔离用户数据与付费接口。"""
import json
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QCheckBox, QLabel
from test_ui_workflow import UIFixture, APP, BALANCE, pump_until
from test_ai_controls import FakeProvider
from app.ui.settings_dialog import SettingsDialog
from unittest.mock import patch
import threading


class AIUsageUITests(UIFixture):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        self.addCleanup(self.provider.close)
        self.repo.set_settings(dict(ai_backend='openai', ai_base_url=self.provider.base, ai_model='custom-model'))

    def test_thinking_defaults_off_and_warning_is_explicit(self):
        dialog = self.dialog()
        boxes = [b for b in dialog.findChildren(QCheckBox) if b.text() == '思考模式']
        self.assertEqual(len(boxes), 1)
        self.assertFalse(boxes[0].isChecked())
        self.assertTrue(any('极高' in label.text() and 'token' in label.text()
                            for label in dialog.findChildren(QLabel)))

    def test_thinking_and_protocol_are_drafts_until_saved(self):
        dialog = self.dialog()
        controls = getattr(dialog, '_ai_thinking_controls', None)
        self.assertIsNotNone(controls)
        controls.toggle.setChecked(True)
        controls.protocol.setCurrentIndex(controls.protocol.findData('thinking'))
        self.assertEqual(dialog._ai_config_values()['thinking'], '1')
        self.assertIsNone(self.repo.get_setting('ai_thinking'))
        dialog.reject()
        self.assertIsNone(self.repo.get_setting('ai_thinking'))
        saved = self.dialog()
        saved._ai_thinking_controls.toggle.setChecked(True)
        saved._ai_thinking_controls.protocol.setCurrentIndex(saved._ai_thinking_controls.protocol.findData('thinking'))
        saved.accept()
        self.assertEqual(self.repo.get_setting('ai_thinking'), '1')
        self.assertEqual(self.repo.get_setting('ai_thinking_protocol'), 'thinking')

    def test_connection_result_scrolls_to_show_usage(self):
        dialog = self.dialog()
        dialog._sections.setCurrentRow(3)
        dialog.show()
        APP.processEvents()
        dialog._ai_test()
        pump_until(lambda: dialog._test_job is None)
        viewport = dialog._pages.currentWidget().viewport()
        bottom = dialog._ai_result.mapTo(viewport, QPoint(0, dialog._ai_result.height())).y()
        self.assertIn('总计 100', dialog._ai_result.text())
        self.assertLessEqual(bottom, viewport.height())

    def test_passage_worker_displays_usage_on_success_and_truncation(self):
        window = self.window()
        self.repo.add_exp(4410)
        page = window._challenge_page
        usage = getattr(page._ai_composer, 'usage_label', None)
        self.assertIsNotNone(usage)
        page.update_ai_access()
        page._topic_edit.setText('星空')
        page._ai_generate()
        pump_until(lambda: page._gen_thread is None)
        self.assertIn('总计 100', usage.text())
        self.assertIn('思考 60', usage.text())
        self.assertEqual(len(self.repo.list_ai_texts()), 1)
        self.provider.reply['choices'][0] = {'finish_reason': 'length', 'message': {'content': ''}}
        page._ai_generate()
        pump_until(lambda: page._gen_thread is None)
        self.assertIn('上限', page._ai_composer.status_label.text())
        self.assertIn('总计 100', usage.text())
        self.assertEqual(len(self.repo.list_ai_texts()), 1)

    def test_english_worker_displays_usage_without_replacing_material_status(self):
        window = self.window()
        self.repo.add_exp(4410)
        page = window._english_page
        window._nav_buttons['英语'].click()
        page.mode_buttons['sentence'].click()
        usage = getattr(page.sentences, 'usage_label', None)
        self.assertIsNotNone(usage)
        sentence = 'We learn ' + ', '.join(page._targets) + ' at school.'
        self.provider.reply['choices'][0]['message']['content'] = json.dumps([
            dict(text=sentence, translation='我们在学校学习这些单词。')])
        page._generate()
        pump_until(lambda: page._request is None)
        self.assertIn('总计 100', usage.text())
        self.assertIn('已经收好', page.sentences.status.text())

    def test_cancelled_sentence_request_does_not_leave_usage_waiting_forever(self):
        window = self.window()
        self.repo.add_exp(4410)
        page = window._english_page
        window._nav_buttons['英语'].click()
        page.mode_buttons['sentence'].click()
        started, release = threading.Event(), threading.Event()

        def delayed(*args, **kwargs):
            started.set()
            release.wait(2)
            return 'invalid response'

        with patch('app.services.ai_service.AIService._chat', delayed):
            try:
                page._generate()
                pump_until(started.is_set)
                page._cancel_request()
                self.assertNotIn('等待', page.sentences.usage_label.text())
                self.assertIn('接口未返回', page.sentences.usage_label.text())
            finally:
                release.set()

    def test_developer_egg_unlocks_both_pages_without_persisting_levels_or_passes(self):
        window = self.window()
        session = getattr(window, '_ai_session', None)
        self.assertIsNotNone(session)
        self.assertFalse(session.enabled)
        self.assertEqual(self.repo.get_exp(), 0)
        dialog = SettingsDialog(self.repo, BALANCE, test_session=session)
        self.widgets.append(dialog)
        egg = dialog._ai_thinking_controls.egg_button
        egg.click()
        dialog.reject()
        self.assertTrue(session.enabled)
        page = window._challenge_page
        page.update_ai_access()
        self.assertTrue(page._ai_btn.isEnabled())
        page._topic_edit.setText('测试')
        page._ai_generate()
        pump_until(lambda: page._gen_thread is None)
        self.assertEqual(len(self.repo.list_ai_texts()), 1)
        self.assertTrue(window._english_page.service.ai_access(window._ai_service, BALANCE)[0])
        english = window._english_page
        window._nav_buttons['英语'].click()
        english.mode_buttons['sentence'].click()
        self.provider.reply['choices'][0]['message']['content'] = json.dumps([
            dict(text='We learn ' + ', '.join(english._targets) + ' at school.',
                 translation='我们在学校学习这些单词。')])
        english._generate()
        # 请求开始时捕获彩蛋状态；随后关闭不会让已经发出的测试请求扣券。
        egg.click()
        pump_until(lambda: english._request is None)
        self.assertIn('已经收好', english.sentences.status.text())
        self.assertEqual(len(english.service.sentence_history(english.library.deck)), 1)
        self.assertEqual(self.repo.get_exp(), 0)
        self.assertEqual(self.repo.count_ai_passes(), 0)
        fresh = self.window()
        self.assertFalse(fresh._ai_session.enabled)
        self.assertFalse(session.enabled)
        page.update_ai_access()
        self.assertFalse(page._ai_btn.isEnabled())


if __name__ == '__main__':
    import unittest
    unittest.main()
