"""Sariana 头像草稿与同篇范文个人练习榜回归，使用隔离数据库。"""
import unittest
from pathlib import Path

from test_ui_workflow import UIFixture, APP
from app.services.challenge_service import ChallengeService
from app.core.avatars import AVATAR_PRESETS, DEFAULT_AVATAR
from app.ui.widgets.avatar import avatar_path


class SarianaProfileTests(UIFixture):
    def test_avatar_tiles_show_full_portrait_and_label(self):
        w = self.dialog()
        w.show()
        for _ in range(5):
            APP.processEvents()
        for button in w._profile_editor.picker.buttons.values():
            self.assertGreaterEqual(button.height(), 110, '头像和名称不能被主题压成一条')
        self.assertGreaterEqual(w._sections.visualItemRect(w._sections.item(0)).height(), 44)
        self.assertIn('::item:selected', w._sections.styleSheet())

    def test_five_presets_are_valid_and_default_is_sariana(self):
        from PySide6.QtGui import QImage
        self.assertEqual(len(AVATAR_PRESETS), 5)
        self.assertEqual(DEFAULT_AVATAR, 'default')
        for key, _ in AVATAR_PRESETS:
            self.assertFalse(QImage(str(avatar_path(key))).isNull(), key)
        self.assertEqual(avatar_path('unknown'), avatar_path(DEFAULT_AVATAR))

    def test_selection_is_draft_until_save_and_cancel_preserves_upload(self):
        self.repo.set_settings({'avatar_image': '1', 'avatar_preset': 'front'})
        w = self.dialog()
        w._profile_editor.picker.buttons['chibi'].click()
        self.assertEqual(self.repo.get_setting('avatar_preset'), 'front')
        w.reject()
        self.assertEqual(self.repo.get_setting('avatar_image'), '1')
        saved = self.dialog()
        saved._profile_editor.picker.buttons['side'].click()
        saved.accept()
        self.assertEqual(self.repo.get_setting('avatar_preset'), 'side')
        self.assertEqual(self.repo.get_setting('avatar_image'), '')

    def test_saved_preset_appears_on_profile_and_clear_uses_default(self):
        w = self.window()
        dlg = self.dialog()
        dlg._profile_editor.picker.buttons['chibi'].click()
        dlg.accept()
        w._profile_page.refresh()
        self.assertEqual(w._profile_page._avatar.preset, 'chibi')
        self.assertIsNotNone(w._profile_page._avatar._image)
        reset = self.dialog()
        reset._clear_avatar()
        reset.accept()
        w._profile_page.refresh()
        self.assertEqual(w._profile_page._avatar.preset, 'default')

    def test_leaderboard_orders_actual_scores_within_passage(self):
        add = self.repo.add_challenge
        add('2026-10-08T10:00:00', 'cn_star', 30, 0, 50, 60, 1, 9999999, 100)
        add('2026-10-08T11:00:00', 'cn_star', 30, 0, 40, 60, .98, 9999999, 300)
        add('2026-10-08T12:00:00', 'cn_star', 30, 0, 30, 60, 1, 9999999, 300)
        add('2026-10-08T12:30:00', 'cn_star', 30, 0, 20, 60, 1, 9999999, 300)
        add('2026-10-08T13:00:00', 'cn_typing', 30, 0, 1, 60, 1, 9999999, 9000)
        svc = ChallengeService(self.repo)
        rows = svc.leaderboard('cn_star', 3)
        self.assertEqual([r['score'] for r in rows], [300, 300, 300])
        self.assertEqual([r['elapsed_seconds'] for r in rows], [20, 30, 40])
        self.assertEqual([r['rank'] for r in rows], [1, 2, 3])
        self.assertAlmostEqual(rows[0]['speed'], 180)
        self.assertFalse(svc.leaderboard('missing'))

    def test_leaderboard_refreshes_after_finish_and_passage_switch(self):
        page = self.training()
        self.repo.add_challenge('2026-10-08T10:00:00', 'cn_star', 20, 0, 20, 40, 1, 200, 200)
        page._refresh_recent()
        self.assertEqual(page._leaderboard.table.rowCount(), 1)
        page._text_combo.setCurrentIndex(1)
        APP.processEvents()
        self.assertEqual(page._leaderboard.table.rowCount(), 0)
        self.assertTrue(page._leaderboard.empty.isVisibleTo(page._leaderboard))
        page._start()
        page._input.setPlainText(page._current_text())
        APP.processEvents()
        self.assertEqual(page._leaderboard.table.rowCount(), 1)


if __name__ == '__main__':
    unittest.main()
