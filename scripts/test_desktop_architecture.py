"""Real desktop worker + Qt: saves are acknowledged before UI state advances."""
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from test_ui_workflow import APP, BALANCE, pump_until
from app.bootstrap.application import DesktopApplication
from app.bootstrap.features import DesktopQueries
from app.integrations.ai.api import AIService
from app.theme.theme_manager import ThemeManager
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog
from app.ui.presenters import PracticeState

ROOT=Path(__file__).resolve().parents[1]

class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.local').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.local')
        self.application=DesktopApplication(self.temp.name,BALANCE,{})
        self.queries=DesktopQueries(self.application)
        self.application.set_settings(dict(ai_backend='openai',ai_base_url='http://unused',ai_model='test')).result(5)
        self.theme=ThemeManager(APP,Path(self.temp.name),self.queries.get_setting,self.queries.set_setting)
        self.theme.apply(self.theme.current_id(),persist=False)
        self.window=MainWindow(self.application.counter,self.queries,BALANCE,
            checkin=self.application.checkin,rewards=self.application.rewards,
            achievements=self.application.achievements,challenge=self.application.practice,
            ai_service=AIService(self.queries),theme_manager=self.theme,
            data_dir=Path(self.temp.name),application=self.application)
        self.theme.register_window(self.window)
        self.window.show();APP.processEvents()
    def tearDown(self):
        self.window._challenge_page._cancel_generation()
        self.window._english_page._cancel_request()
        self.window._companion.shutdown()
        self.application.close()
        self.window.hide();self.window.deleteLater()
        APP.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        self.temp.cleanup()
    def grant_pass(self):
        self.application.worker.submit(lambda context:context['repo'].add_reward('ai_pass',1,'test')).result(5)
        APP.processEvents()
    def test_practice_result_is_committed_before_completion_and_reaction(self):
        page=self.window._challenge_page
        self.window._tabs.setCurrentWidget(page)
        page._start();page._finish(page._current_text(),page._current_text())
        self.assertTrue(pump_until(lambda:page._presenter.state==PracticeState.COMPLETED))
        self.assertEqual(len(self.application.models.get_recent_challenges()),1)
        self.assertEqual(self.window._companion.runtime.sample().state,'proud')
    def test_english_attempt_is_confirmed_after_async_save(self):
        page=self.window._english_page
        self.window._tabs.setCurrentWidget(page)
        page._start_spelling()
        session=page.service.session
        page.spelling.answer.setText(session.current.word)
        page._submit_spelling()
        self.assertTrue(pump_until(lambda:session.result is not None))
        self.assertEqual(page.service.summary(page.library.deck)['attempts'],1)
        self.assertTrue(session.result['independent'])

    def test_english_schedule_failure_retries_same_attempt_before_correction(self):
        page = self.window._english_page
        self.window._tabs.setCurrentWidget(page)
        page._start_spelling()
        session = page.service.session
        self.application.worker.submit(lambda context: context['repo']._conn.execute(
            "CREATE TRIGGER reject_review BEFORE INSERT ON english_review_schedule BEGIN SELECT RAISE(FAIL,'test'); END;"
        )).result(5)
        page.spelling.answer.setText('incorrect')
        page._submit_spelling()
        prepared = dict(session._prepared)
        self.assertFalse(page.library.deck_combo.isEnabled())
        self.assertTrue(pump_until(lambda: not page._spelling_saving))
        self.assertIsNone(session.result)
        self.assertFalse(session.correcting)
        self.assertEqual(page.service.summary(page.library.deck)['attempts'], 0)
        self.assertEqual(page.service.review_plan(page.library.deck)['due_count'], 0)
        self.application.worker.submit(lambda context: context['repo']._conn.execute('DROP TRIGGER reject_review')).result(5)
        page._submit_spelling()
        self.assertTrue(pump_until(lambda: session.result is not None))
        self.assertEqual(session.result, prepared)
        self.assertTrue(session.correcting)
        self.assertEqual(page.service.summary(page.library.deck)['attempts'], 1)
        self.assertEqual(page.service.review_plan(page.library.deck)['due_count'], 1)
        page.spelling.answer.setText(session.current.word)
        page._correct()
        self.assertEqual(page.service.summary(page.library.deck)['attempts'], 1)
    def test_settings_commit_updates_cached_profile(self):
        dialog=SettingsDialog(self.queries,BALANCE,theme_manager=self.theme,data_dir=self.temp.name)
        dialog._nick_edit.setText('异步保存')
        dialog.accept()
        self.assertTrue(pump_until(lambda:dialog._closed))
        self.assertEqual(self.queries.get_setting('nickname'),'异步保存')
        dialog.deleteLater()
    def test_cancelled_passage_holds_gate_until_network_ends(self):
        self.grant_pass()
        started=threading.Event();release=threading.Event()
        def generate(*_):
            started.set();release.wait(5)
            return True,'不会保存的正文'
        page=self.window._challenge_page
        self.window._tabs.setCurrentWidget(page);page._topic_edit.setText('test')
        with patch.object(AIService,'generate',side_effect=generate):
            page._ai_generate();self.assertTrue(started.wait(2))
            self.window._tabs.setCurrentWidget(self.window._english_page)
            english=self.window._english_page
            english._generate()
            self.assertIn('已有 AI',english.sentences.status.text())
            release.set()
            self.assertTrue(pump_until(lambda:page._gen_thread is None))
        self.assertEqual(self.queries.list_ai_texts(),[])
        self.assertEqual(self.queries.count_ai_passes(),1)
    def test_failed_material_save_retries_without_second_model_call(self):
        self.grant_pass()
        self.application.worker.submit(lambda context:context['repo']._conn.execute(
            "CREATE TRIGGER fail_material BEFORE INSERT ON ai_texts BEGIN SELECT RAISE(ABORT,'disk full'); END")).result(5)
        page=self.window._challenge_page
        self.window._tabs.setCurrentWidget(page);page._topic_edit.setText('test')
        with patch.object(AIService,'generate',return_value=(True,'有效的测试正文')) as generate:
            page._ai_generate()
            self.assertTrue(pump_until(lambda:page._pending_material is not None and not page._material_saving))
            self.assertEqual(self.queries.count_ai_passes(),1)
            self.application.worker.submit(lambda context:context['repo']._conn.execute('DROP TRIGGER fail_material')).result(5)
            page._ai_generate()
            self.assertTrue(pump_until(lambda:len(self.queries.list_ai_texts())==1))
            APP.processEvents()
            self.assertEqual(generate.call_count,1)
        self.assertEqual(self.queries.count_ai_passes(),0)
    def test_refreshes_use_no_sql_and_save_failure_is_visible(self):
        traces=[]
        self.application.worker.submit(lambda context:context['repo']._conn.set_trace_callback(traces.append)).result(5)
        for _ in range(5):
            self.window.refresh();self.window._companion._tick()
        self.assertEqual(traces,[])
        self.application.counter.handle_char('letter')
        def fail(context):
            context['repo']._conn.execute("CREATE TRIGGER fail_stats BEFORE INSERT ON daily_stats BEGIN SELECT RAISE(ABORT,'full'); END")
        self.application.worker.submit(fail).result(5)
        future=self.application.flush()
        with self.assertRaises(Exception):future.result(5)
        self.assertTrue(pump_until(lambda:self.window._dashboard._save_status.text()=='保存失败'))
        self.application.worker.submit(lambda context:context['repo']._conn.execute('DROP TRIGGER fail_stats')).result(5)
        self.application.flush().result(5)
        self.assertTrue(pump_until(lambda:self.window._dashboard._save_status.text().startswith('已保存')))

if __name__=='__main__':unittest.main()
