"""离屏 UI 行为回归：训练状态、设置草稿、异步请求与导航。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from ui_test_support import prepare_fonts, load_fonts
prepare_fonts()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QThread, QTimer
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QMessageBox
from app.storage.db import connect_db, init_schema
from app.storage.repository import Repository
from app.services.ai_service import AIService
from app.services.challenge_service import ChallengeService
from app.ui.pages.challenge import ChallengePage
from app.ui.settings_dialog import SettingsDialog
from app.ui.palette import P
from app.theme.theme_manager import DEFAULT_THEME_ID, ThemeManager
from app.core.engine import StatsEngine
from app.services.checkin_service import CheckinService
from app.services.reward_service import RewardService
from app.services.achievement_service import AchievementService
from app.ui.main_window import MainWindow

APP = QApplication.instance() or QApplication([])
load_fonts()
BALANCE = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))


def pump_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.005)
    APP.processEvents()
    return predicate()


class UIFixture(unittest.TestCase):
    def setUp(self):
        self.data = ROOT / '.local/ui-night-stage/tests' / uuid.uuid4().hex
        self.data.mkdir(parents=True)
        self.conn = connect_db(self.data / 'test.db')
        init_schema(self.conn)
        self.repo = Repository(self.conn)
        self.widgets = []
        self.theme = ThemeManager(APP, self.data, self.repo.get_setting, self.repo.set_setting)
        self.theme.apply(DEFAULT_THEME_ID)

    def add_theme(self, theme_id, *, name=None, base=None, colors=None, backdrop=None):
        """在临时数据目录写入一个最小第三方主题，并重扫注册表。

        用于验证「未声明 backdrop 的主题不加载插画」等按主题声明的行为——
        不再依赖已经下线的内置浅色/深色主题。
        """
        folder = self.data / 'themes' / theme_id
        folder.mkdir(parents=True, exist_ok=True)
        manifest = {'id': theme_id, 'name': name or theme_id, 'version': '1.0.0',
                    'colors': colors or {'background': '#101014', 'card': '#181820',
                                         'text': '#F2F2F6', 'muted': '#B9B9C6',
                                         'primary': '#7C7CF0', 'border': '#3A3A48'}}
        if base:
            manifest['base'] = base
        if backdrop:
            manifest['effects'] = {'dark': True, 'backdrop': backdrop}
        (folder / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        (folder / 'theme.qss').write_text(
            'QWidget { background: {{colors.background}}; color: {{colors.text}}; }\n',
            encoding='utf-8')
        (folder / 'charts.json').write_text(json.dumps({
            'background': '#101014', 'grid': '#2A2A34', 'speed': '#7C7CF0',
            'acc': '#6FD3A2', 'chars': '#D79D96',
            'levels': ['#101014', '#1C1C26', '#2A2A38', '#3A3A4E', '#4A4A62'],
            'empty': '#15151C'}), encoding='utf-8')
        self.theme._registry = self.theme._scan()
        return theme_id

    def tearDown(self):
        for job in APP.findChildren(QThread):
            if job.isRunning():
                job.wait(3000)
        APP.processEvents()
        for w in self.widgets:
            for job in w.findChildren(QThread):
                if job.isRunning():
                    job.wait(3000)
            w.hide()
            w.deleteLater()
        APP.processEvents()
        # 手动 processEvents 不会清空 DeferredDelete；及时销毁窗口和装饰定时器。
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.conn.close()

    def dialog(self):
        w = SettingsDialog(self.repo, BALANCE, theme_manager=self.theme, data_dir=self.data)
        self.widgets.append(w)
        return w

    def training(self):
        w = ChallengePage(self.repo, BALANCE, ChallengeService(self.repo), AIService(self.repo))
        self.widgets.append(w)
        w.resize(750, 600)
        w.show()
        APP.processEvents()
        return w

    def window(self):
        engine = StatsEngine(self.repo, self.repo.get_setting, BALANCE)
        achievements = json.loads((ROOT / 'config/achievements.json').read_text(encoding='utf-8'))
        w = MainWindow(engine, self.repo, BALANCE, checkin=CheckinService(self.repo, BALANCE),
                       rewards=RewardService(self.repo, BALANCE),
                       achievements=AchievementService(self.repo, BALANCE, achievements),
                       challenge=ChallengeService(self.repo), ai_service=AIService(self.repo),
                       theme_manager=self.theme, data_dir=self.data)
        self.widgets.append(w)
        self.theme.register_reports(w._reports)
        self.theme.register_window(w)
        self.theme.apply('arknights_endfield_lino')
        w.show()
        APP.processEvents()
        return w


class TrainingTests(UIFixture):
    def test_topic_examples_fill_draft_without_starting_generation(self):
        self.repo.set_setting('ai_backend', 'ollama')
        self.repo.add_reward('ai_pass', 1, 'ui-test')
        w = self.training()
        w._ai_section.toggle.setChecked(True)
        with patch.object(AIService, 'generate') as generate:
            w._ai_composer.example_buttons[1].click()
            self.assertEqual(w._topic_edit.text(), '雨后小城')
            generate.assert_not_called()
        w._ai_composer.back_button.click()
        self.assertEqual(w._topic_edit.text(), '雨后小城')
        self.assertEqual(self.repo.count_ai_passes(), 1)

    def test_ai_settings_shortcut_opens_ai_section(self):
        window = self.window()
        selected = []
        def inspect_dialog(dialog):
            selected.append(dialog._sections.currentRow())
            return 0
        with patch.object(SettingsDialog, 'exec', inspect_dialog):
            window._challenge_page._ai_composer.settings_button.click()
        self.assertEqual(selected, [3])

    def test_long_reference_keeps_input_and_start_visible(self):
        self.repo.add_ai_text('cn', '长范文', '星光照亮夜空，指尖轻轻起舞。' * 57)
        w = self.training()
        w.resize(706, 584)
        w._text_combo.setCurrentIndex(w._text_combo.count() - 1)
        w._start()
        for _ in range(4):
            APP.processEvents()  # QLabel 换行高度在下一次布局事件中确定。
        for control in (w._start_btn, w._ref_label, w._input):
            position = control.mapTo(w, QPoint(0, 0))
            self.assertGreaterEqual(position.y(), 0, '关键区域不能滚到屏幕外')
            self.assertLess(position.y() + 70, w.height(), '范文与输入区必须同时可见')

    def test_generation_failure_remains_visible_after_access_refresh(self):
        self.repo.set_setting('ai_backend', 'ollama')
        self.repo.add_reward('ai_pass', 1, 'ui-test')
        w = self.training()
        w._topic_edit.setText('星空')
        with patch.object(AIService, 'generate', return_value=(False, '连接被拒绝，请启动服务')):
            w._ai_generate()
            pump_until(lambda: w._gen_thread is None)
        self.assertIn('连接被拒绝', w._ai_status.text())
        w.update_ai_access()
        self.assertIn('连接被拒绝', w._ai_status.text())
        self.assertEqual(self.repo.count_ai_passes(), 1)

    def test_quit_during_generation_does_not_destroy_running_worker(self):
        child = self.data / 'quit_worker.py'
        child.write_text('''import sys, time
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from app.ui.pages.challenge import _GenThread
class Slow:
    def snapshot(self): return self
    def generate(self, *args):
        time.sleep(2)
        return True, "test"
app=QApplication([])
page=QWidget()
job=_GenThread(Slow(), "test", "cn", 10, page)
job.start()
QTimer.singleShot(30, app.quit)
app.exec()
''', encoding='utf-8')
        result = subprocess.run([sys.executable, str(child), str(ROOT)], capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_running_locks_passage_and_finishing_restores_controls(self):
        w = self.training()
        w._start()
        self.assertFalse(w._text_combo.isEnabled(), '练习中不能换范文')
        self.assertFalse(w._ai_btn.isEnabled())
        self.assertFalse(w._ai_section.toggle.isEnabled())
        w._input.setPlainText(w._current_text())
        APP.processEvents()
        self.assertTrue(w._result.isVisible())
        self.assertTrue(w._text_combo.isEnabled())
        self.assertIn('100', w._acc_label.text())
        self.assertEqual(len(w._svc.recent(6)), 1)

    def test_generation_uses_requested_metadata_and_locks_start(self):
        self.repo.set_setting('ai_backend', 'ollama')
        self.repo.add_reward('ai_pass', 1, 'ui-test')
        w = self.training()
        release = threading.Event()
        def generate(_svc, topic, lang, length):
            release.wait(1)
            return True, '星光照亮练习的小小舞台。'
        with patch.object(AIService, 'generate', generate):
            w._topic_edit.setText('星光')
            w._ai_generate()
            try:
                self.assertFalse(w._start_btn.isEnabled())
                w.update_ai_access()
                self.assertFalse(w._ai_btn.isEnabled(), '定时刷新不能重启生成按钮')
                self.assertTrue(all(not b.isEnabled() for b in w._ai_composer.example_buttons))
                w._ai_section.toggle.setChecked(True)
                w._ai_composer.back_button.click()
                self.assertFalse(w._start_btn.isEnabled(), '返回训练不能绕过生成中的锁定')
                w._topic_edit.setText('后来修改')
                w._lang_combo.setCurrentIndex(1)
            finally:
                release.set()
                pump_until(lambda: w._gen_thread is None or not w._gen_thread.isRunning())
        rows = self.repo.list_ai_texts()
        self.assertEqual(rows[0]['topic'], '星光')
        self.assertEqual(rows[0]['lang'], 'cn')
        self.assertTrue(w._start_btn.isEnabled())


class SettingsTests(UIFixture):
    def test_cancel_clear_avatar_preserves_file_and_setting(self):
        folder = self.data / 'avatars'
        folder.mkdir()
        avatar = folder / 'avatar.png'
        avatar.write_bytes(b'original-avatar')
        self.repo.set_setting('avatar_image', '1')
        w = self.dialog()
        with patch.object(QMessageBox, 'information'):
            w._clear_avatar()
        w.reject()
        self.assertTrue(avatar.exists(), '取消不能删除已有头像')
        self.assertEqual(avatar.read_bytes(), b'original-avatar')
        self.assertEqual(self.repo.get_setting('avatar_image'), '1')

    def test_upload_is_draft_until_save(self):
        image = QImage(12, 12, QImage.Format_ARGB32)
        image.fill(QColor('#BBA5F3'))
        source = self.data / 'chosen.png'
        image.save(str(source))
        w = self.dialog()
        with patch('app.ui.settings_dialog.QFileDialog.getOpenFileName', return_value=(str(source), '')), patch.object(QMessageBox, 'information'):
            w._upload_avatar()
        self.assertIsNone(self.repo.get_setting('avatar_image'))
        self.assertFalse((self.data / 'avatars/avatar.png').exists())
        w.accept()
        self.assertEqual(self.repo.get_setting('avatar_image'), '1')
        self.assertTrue((self.data / 'avatars/avatar.png').is_file())

    def test_connection_test_keeps_draft_off_database_and_ui_responsive(self):
        w = self.dialog()
        w._ai_backend.setCurrentIndex(w._ai_backend.findData('ollama'))
        w._ai_model.setText('draft-model')
        seen = []
        def chat(svc, *args, **kwargs):
            seen.append((threading.get_ident(), svc._model()))
            time.sleep(.15)
            return 'pong'
        tick = []
        with patch.object(AIService, '_chat', chat):
            start = time.monotonic()
            w._ai_test()
            elapsed = time.monotonic() - start
            QTimer.singleShot(0, lambda: tick.append(True))
            APP.processEvents()
            try:
                self.assertLess(elapsed, .10, '网络调用不能阻塞 UI')
                self.assertTrue(tick)
                self.assertIsNone(self.repo.get_setting('ai_model'))
                self.assertIsNone(self.repo.get_setting('ai_backend'))
            finally:
                pump_until(lambda: bool(seen) and '成功' in w._ai_result.text())
        self.assertNotEqual(seen[0][0], threading.get_ident())
        self.assertEqual(seen[0][1], 'draft-model')
        w.reject()

    def test_theme_preview_cancel_and_save_are_distinct(self):
        """预览不落库、取消还原、保存才提交。

        只剩一个内置主题，无法靠「两个内置主题互切」区分预览与提交，
        因此用同主题的两次 apply 对照：`persist=False`（预览）不写库，
        `persist=True`（保存）才写库；可辨识状态取主题自己声明的画布色。
        """
        # 不同主题的调色板确有色差，断言才有意义
        preview_bg = '#101014'
        lino_bg = json.loads((ROOT / 'app/theme/themes/arknights_endfield_lino/manifest.json')
                             .read_text(encoding='utf-8'))['colors']['background']
        self.assertEqual(self.repo.get_setting('theme_id'), DEFAULT_THEME_ID)
        self.assertEqual(self.theme.current_id(), DEFAULT_THEME_ID)
        self.assertIn(f'background: {lino_bg}', APP.styleSheet(), '实例化时必须已应用梨诺主题')

        # 1) 预览：只换样式，不写库（apply 的 persist=False 语义）
        self.theme.apply(DEFAULT_THEME_ID, persist=False)
        self.assertEqual(self.repo.get_setting('theme_id'), DEFAULT_THEME_ID,
                         '预览不能落库')

        # 2) 取消：把预览态还原成原主题（对话框 reject 走同一条路径）
        self.theme.apply(DEFAULT_THEME_ID, persist=False)
        self.assertEqual(self.theme.current_id(), DEFAULT_THEME_ID)
        self.assertEqual(self.repo.get_setting('theme_id'), DEFAULT_THEME_ID)

        # 3) 对话框预览：切到另一个主题应即时套用，但不写库；取消后还原原主题
        w = self.dialog()
        self.assertEqual(w._theme_combo.count(), 1, '只剩内置主题时下拉不应有空白行')
        self.assertEqual(w._theme_combo.itemText(0), '萨莉安娜')
        self.assertFalse(w._theme_combo.isEnabled())
        self.assertFalse(w._import_btn.isVisible())
        self.assertFalse(w._delete_btn.isVisible())
        self.add_theme('preview_probe', name='预览探针', colors={
            'background': preview_bg, 'card': '#181820', 'text': '#F2F2F6',
            'muted': '#B9B9C6', 'primary': '#7C7CF0', 'border': '#3A3A48'})
        w._reload_themes()
        self.assertEqual(w._theme_combo.count(), 1)
        self.assertEqual(w._theme_combo.findData('preview_probe'), -1)
        self.assertEqual(self.repo.get_setting('theme_id'), DEFAULT_THEME_ID,
                         '下拉切换只是预览，不能落库')
        self.assertEqual(P.canvas, lino_bg, '只保留萨莉安娜外观')
        w.reject()
        self.assertEqual(self.theme.current_id(), DEFAULT_THEME_ID, '取消应还原原主题')
        self.assertNotEqual(P.canvas, preview_bg, '取消后不能留着预览主题')

        # 4) 保存才提交：accept 写库并落到该主题
        w2 = self.dialog()
        w2._reload_themes()
        w2._nick_edit.setText('星光练习生')
        w2.accept()
        self.assertEqual(self.repo.get_setting('theme_id'), DEFAULT_THEME_ID)
        self.assertEqual(self.repo.get_setting('nickname'), '星光练习生')
        self.theme.apply(DEFAULT_THEME_ID)

    def test_invalid_url_retains_draft_and_does_not_save(self):
        w = self.dialog()
        w._ai_backend.setCurrentIndex(w._ai_backend.findData('openai'))
        w._ai_url.setText('not-a-url')
        w._nick_edit.setText('保留草稿')
        w.accept()
        self.assertIsNone(self.repo.get_setting('nickname'))
        self.assertIsNone(self.repo.get_setting('ai_base_url'))
        self.assertEqual(w._nick_edit.text(), '保留草稿')
        self.assertTrue(w._ai_result.text())


class NavigationTests(UIFixture):
    def test_saved_clear_avatar_restores_profile_sariana(self):
        folder = self.data / 'avatars'
        folder.mkdir()
        image = QImage(12, 12, QImage.Format_ARGB32)
        image.fill(QColor('#BBA5F3'))
        image.save(str(folder / 'avatar.png'))
        self.repo.set_setting('avatar_image', '1')
        w = self.window()
        w._profile_page.refresh()
        self.assertIsNotNone(w._profile_page._avatar._image)
        dlg = self.dialog()
        dlg._clear_avatar()
        dlg.accept()
        w._profile_page.refresh()
        self.assertIsNotNone(w._profile_page._avatar._image)
        self.assertEqual(w._profile_page._avatar.preset, 'default')
        self.assertTrue((folder / 'avatar.png').exists(), '恢复默认头像保留原文件')

    def test_minimal_window_constructs_before_theme_is_applied(self):
        from app.ui.palette import P
        P.reset()
        engine = StatsEngine(self.repo, self.repo.get_setting, BALANCE)
        w = MainWindow(engine, self.repo, BALANCE)
        self.widgets.append(w)
        w.show()
        APP.processEvents()
        self.assertTrue(w.isVisible())
        self.assertFalse(w._dashboard._practice_btn.isEnabled())

    def test_home_starts_training_and_pauses_decorative_animation(self):
        w = self.window()
        self.assertTrue(hasattr(w._dashboard, '_practice_btn'), '首页应有训练入口')
        w._dashboard._practice_btn.click()
        APP.processEvents()
        self.assertIs(w._tabs.currentWidget(), w._challenge_page)
        self.assertFalse(w._tabs.tabBar().isVisible())
        w._challenge_page._start()
        self.assertFalse(w._starfield._timer.isActive())
        w._challenge_page._reset()
        self.assertTrue(w._starfield._timer.isActive())
        w.hide()
        APP.processEvents()
        self.assertFalse(w._starfield._timer.isActive(), '托盘隐藏时应停装饰动画')

    def test_growth_navigation_preserves_service_pages_and_updates_selection(self):
        w = self.window()
        self.assertTrue(hasattr(w, '_nav_buttons'), '主导航应能直达成长')
        w._nav_buttons['成长'].click()
        APP.processEvents()
        self.assertTrue(w._growth_bar.isVisible())
        w._growth_buttons['个人资料'].click()
        APP.processEvents()
        self.assertIs(w._tabs.currentWidget(), w._profile_page)
        self.assertEqual(w._profile_page._nick_label.text(), '打字新星')
        w._nav_buttons['统计'].click()
        APP.processEvents()
        self.assertIs(w._tabs.currentWidget(), w._reports)
        self.assertFalse(w._growth_bar.isVisible())

    def test_reduced_motion_stays_off_after_training_reset(self):
        w = self.window()
        self.repo.set_setting('reduced_motion', '1')
        self.theme.apply('arknights_endfield_lino')
        w._tabs.setCurrentWidget(w._challenge_page)
        w._challenge_page._start()
        w._challenge_page._reset()
        self.assertFalse(w._starfield._timer.isActive())


class ChromeTests(UIFixture):
    """外壳约束：六项底部导航、背景层、纸张 token、对比度与焦点。"""

    def test_bottom_nav_has_six_items_with_delivered_icons(self):
        w = self.window()
        self.assertEqual(list(w._nav_buttons), ['今日', '训练', '英语', '统计', '成长', '设置'])
        for title, button in w._nav_buttons.items():
            self.assertFalse(button.icon().isNull(), f'{title} 缺少交付图标')
            self.assertEqual(button.accessibleName(), title)
        self.assertTrue(w._nav_buttons['今日'].isChecked(), '默认选中今日')

    def test_backdrop_uses_delivered_asset_only_when_theme_declares_it(self):
        w = self.window()
        self.assertTrue(w._backdrop.has_artwork(), '梨诺主题应加载交付插画')
        self.assertTrue(w._nav._summary.isVisible(), '固定基准尺寸保留个人摘要')
        # 未声明 backdrop 的主题（临时构造）不应加载插画
        plain = self.add_theme('no_backdrop_probe', name='无插画探针')
        self.theme.apply(plain)
        self.assertFalse(w._backdrop.has_artwork(), '未声明背景的主题不应加载插画')
        self.theme.apply(DEFAULT_THEME_ID)
        self.assertTrue(w._backdrop.has_artwork(), '切回梨诺应恢复插画')

    def test_training_paper_token_and_primary_state_matrix(self):
        page = self.training()
        # 密度由实际尺寸决定；标准尺寸验证标准内边距。
        page.resize(1440, 900)
        APP.processEvents()
        margins = page._paper_layout.contentsMargins()
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()),
                         (32, 14, 32, 22), '非紧凑纸张内边距按规范：左右 32px')
        self.assertEqual(page._start_btn.text(), '开始练习 →')
        self.assertTrue(page._start_btn.isEnabled())
        page._start()
        APP.processEvents()
        self.assertEqual(page._start_btn.text(), '练习中…')
        self.assertFalse(page._start_btn.isEnabled())
        self.assertFalse(page._text_combo.isEnabled(), '练习中不能换范文')
        page._input.setPlainText(page._current_text())
        APP.processEvents()
        self.assertEqual(page._start_btn.text(), '练习已完成')
        self.assertFalse(page._start_btn.isEnabled())
        self.assertTrue(page._text_combo.isEnabled())
        page._reset()
        self.assertEqual(page._start_btn.text(), '开始练习 →')

    def _sized_training(self, width, height):
        """按指定尺寸构造独立训练页（页面区宽度需 ≥ 紧凑最小宽度 808，否则会被挤压）。"""
        page = ChallengePage(self.repo, BALANCE, ChallengeService(self.repo), AIService(self.repo))
        self.widgets.append(page)
        page.resize(width, height)
        page.show()
        APP.processEvents()
        return page

    def test_compact_training_degrades_padding_not_font_size(self):
        # 紧凑基准 900x640
        compact_page = self._sized_training(900, 640)
        self.assertTrue(compact_page._compact)
        self.assertEqual(compact_page._paper_layout.contentsMargins().left(), 20)
        self.assertEqual(compact_page._start_btn.height(), 44)
        self.assertEqual(compact_page._input.height(), 64)
        self.assertIn('font-size:20px', compact_page._ref_label.styleSheet())

        # 非紧凑：1440x900 由页面自身 resizeEvent 判定
        wide = self._sized_training(1440, 900)
        self.assertFalse(wide._compact, '1440x900 应为非紧凑')
        self.assertEqual(wide._paper_layout.contentsMargins().left(), 32)
        self.assertEqual(wide._start_btn.height(), 52)
        self.assertEqual(wide._input.height(), 120)
        # 紧凑窗口只降内边距与控件高度，运行中的正文字号仍是 20px
        wide._start()
        APP.processEvents()
        self.assertIn('font-size:20px', wide._input.styleSheet())

    def test_palette_contrast_and_paper_focus_meet_wcag(self):
        from app.ui.palette import P

        def luminance(color: str) -> float:
            value = color.lstrip('#')
            channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                      for c in channels]
            return (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])

        def ratio(a: str, b: str) -> float:
            high, low = sorted((luminance(a), luminance(b)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        self.theme.apply('arknights_endfield_lino')
        pairs = [('纸面正文', P.paper_text, P.paper), ('纸面辅助', P.paper_muted, P.paper),
                 ('主按钮', P.primary_text, P.primary), ('深色表面正文', P.surface_text, P.surface),
                 ('深色表面辅助', P.surface_muted, P.surface),
                 ('纸面成功', P.success_on_paper, P.paper),
                 ('纸面危险', P.danger_on_paper, P.paper),
                 ('纸张焦点', P.focus_on_paper, P.paper),
                 ('深色焦点', P.focus, P.canvas)]
        for name, fg, bg in pairs:
            self.assertGreaterEqual(ratio(fg, bg), 4.5,
                                    f'{name} 对比度不足：{fg} on {bg} = {ratio(fg, bg):.2f}:1')

    def test_all_builtin_themes_keep_contrast_and_focus_rules(self):
        """唯一内置主题（梨诺）要满足正文对比度与可见焦点（交接规范对各主题都成立）。"""
        from app.ui.palette import P

        def luminance(color: str) -> float:
            value = color.lstrip('#')
            channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                      for c in channels]
            return (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])

        def ratio(a: str, b: str) -> float:
            high, low = sorted((luminance(a), luminance(b)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        builtins = [m['id'] for m in self.theme.list_themes() if m['_builtin']]
        self.assertEqual(builtins, [DEFAULT_THEME_ID], '内置主题应只剩梨诺')
        for theme_id in builtins:
            self.theme.apply(theme_id)
            for name, fg, bg in (('纸面正文', P.paper_text, P.paper),
                                 ('纸面辅助', P.paper_muted, P.paper),
                                 ('表面正文', P.surface_text, P.surface),
                                 ('主按钮', P.primary_text, P.primary),
                                 ('纸张焦点', P.focus_on_paper, P.paper)):
                self.assertGreaterEqual(ratio(fg, bg), 4.5,
                                        f'{theme_id} {name} 对比度不足：{ratio(fg, bg):.2f}:1')
        # 焦点轮廓由共享层 theme_qss() 生成，任何主题应用后都应可见
        qss = APP.styleSheet()
        self.assertIn('2px solid', qss, '焦点轮廓应为 2px')
        self.assertIn(f'2px solid {P.focus}', qss, '深色表面焦点色应可辨识')
        self.theme.apply(DEFAULT_THEME_ID)


    def test_settings_dialog_builds_without_theme_manager(self):
        """回归：没有主题管理器的设置对话框也必须能构造并刷新尺寸（离屏冒烟路径）。

        `_sync_field_heights` 曾直接读取只在有主题管理器时才创建的主题控件，
        导致 smoke_ui 的 `SettingsDialog(..., theme_manager=None)` 路径抛 AttributeError。
        """
        dlg = SettingsDialog(self.repo, BALANCE, None, theme_manager=None, data_dir=None)
        self.widgets.append(dlg)
        dlg.show()
        APP.processEvents()
        dlg._apply_metrics(force=True)
        dlg._sync_field_heights()
        self.assertTrue(dlg.isVisible())
        dlg.reject()

    def test_secondary_entries_stay_visible_in_compact_window(self):
        """回归：紧凑尺寸下 AI/历史入口不能被滚动视口裁掉（曾只剩状态条可见）。"""
        for width, height in ((900, 524), (1440, 874)):
            page = self._sized_training(width, height)
            toggle = page._recent_disclosure.toggle
            region = toggle.visibleRegion().boundingRect()
            self.assertFalse(region.isEmpty(), f'{width}x{height} 历史入口不可见')
            self.assertEqual(region.size(), toggle.size(),
                             f'{width}x{height} 历史入口被裁切：{region.size()} != {toggle.size()}')
            if page._ai is not None:
                ai_region = page._ai_section.toggle.visibleRegion().boundingRect()
                self.assertFalse(ai_region.isEmpty(), f'{width}x{height} AI 入口不可见')
                self.assertEqual(ai_region.size(), page._ai_section.toggle.size(),
                                 f'{width}x{height} AI 入口被裁切')
            self.assertIn('展开', toggle.text())

    def test_disabled_actions_and_result_detail_meet_contrast(self):
        """回归：禁用态主动作与结果区说明文字的对比度必须 ≥4.5:1。"""
        from app.ui.palette import P, mix

        def luminance(color: str) -> float:
            value = color.lstrip('#')
            channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                      for c in channels]
            return (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])

        def ratio(a: str, b: str) -> float:
            high, low = sorted((luminance(a), luminance(b)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        self.theme.apply('arknights_endfield_lino')
        disabled_primary = mix(P.primary, P.paper, 0.30)     # QSS: rgba(primary, 0.30) 叠在纸上
        disabled_secondary = mix(P.primary, P.paper, 0.26)
        self.assertGreaterEqual(ratio(P.paper_text, disabled_primary), 4.5,
                                f'禁用主动作 {ratio(P.paper_text, disabled_primary):.2f}:1')
        self.assertGreaterEqual(ratio(P.paper_text, disabled_secondary), 4.5,
                                f'禁用次按钮 {ratio(P.paper_text, disabled_secondary):.2f}:1')
        self.assertGreaterEqual(ratio(P.surface_muted, P.surface), 4.5,
                                '结果区说明文字（深色面板）')


if __name__ == '__main__':
    unittest.main()
