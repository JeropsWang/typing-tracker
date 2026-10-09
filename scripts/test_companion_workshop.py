"""Creation drafts and active packs remain separate across save/cancel failures."""
import copy
from unittest.mock import patch
from test_ui_workflow import UIFixture, APP


class WorkshopTests(UIFixture):
    def workshop(self):
        from app.ui.companion.controller import CompanionController
        from app.ui.companion.workshop import Workshop
        window = self.window()
        controller = window._companion
        controller.start()
        workshop = Workshop(controller.store, controller, window)
        self.widgets.append(workshop)
        workshop.show()
        APP.processEvents()
        return controller, workshop

    def test_builtin_copy_save_and_apply_are_separate(self):
        controller, workshop = self.workshop()
        workshop.load_pack('starlight')
        workshop.copy_draft()
        workshop.name_edit.setText('我的星光')
        workshop.editor.lines.setPlainText('你好，{nickname}\n慢慢来，我陪你')
        pack = workshop.save_draft()
        self.assertIsNotNone(pack)
        self.assertFalse(pack.builtin)
        self.assertEqual(pack.manifest['name'], '我的星光')
        self.assertEqual(controller.pack.id, 'starlight')
        workshop.apply_pack()
        self.assertEqual(controller.pack.id, pack.id)
        self.assertEqual(self.repo.get_setting('companion_pack'), pack.id)

    def test_cancel_draft_and_invalid_save_leave_original_intact(self):
        controller, workshop = self.workshop()
        workshop.copy_draft()
        workshop.name_edit.setText('未保存的作品')
        workshop.discard_draft()
        self.assertEqual(workshop.draft['name'], controller.pack.manifest['name'])
        workshop.copy_draft()
        workshop.editor.lines.setPlainText('{nickname.__class__}')
        self.assertIsNone(workshop.save_draft())
        self.assertIn('话术', workshop.feedback.text())
        self.assertEqual(len(controller.store.list_packs()), 3)
        self.assertEqual(controller.pack.id, 'starlight')

    def test_write_failure_keeps_draft_and_previous_saved_creation(self):
        controller, workshop = self.workshop()
        workshop.copy_draft()
        saved = workshop.save_draft()
        workshop.name_edit.setText('不要丢掉这个草稿')
        with patch.object(controller.store, 'save', side_effect=OSError('disk unavailable')):
            self.assertIsNone(workshop.save_draft())
        self.assertEqual(workshop.name_edit.text(), '不要丢掉这个草稿')
        self.assertEqual(controller.store.load(saved.id).manifest['name'], saved.manifest['name'])

    def test_replacement_asset_and_meme_edits_persist(self):
        controller, workshop = self.workshop()
        workshop.copy_draft()
        workshop.import_asset(controller.pack.asset_for('idle').path)
        self.assertNotIn('rect', workshop.editor.current_entry())
        before = len(workshop.draft['memes'])
        workshop.editor.add_meme()
        self.assertEqual(len(workshop.draft['memes']), before + 1)
        self.assertEqual(workshop.editor.selection.currentData(), ('meme', before))
        workshop.editor.lines.setPlainText('这是我自己的表情包')
        pack = workshop.save_draft()
        self.assertEqual(pack.manifest['memes'][-1]['lines'], ['这是我自己的表情包'])

    def test_preview_never_changes_real_statistics(self):
        controller, workshop = self.workshop()
        before = self.repo.get_exp(), self.repo.get_lifetime()
        workshop.preview.simulate('record')
        self.assertEqual(before, (self.repo.get_exp(), self.repo.get_lifetime()))
        self.assertIn('示例数据', workshop.preview.note.text())

    def test_resizing_restores_all_wide_panels(self):
        controller, workshop = self.workshop()
        workshop.resize(820, 650)
        APP.processEvents()
        workshop.resize(1120, 760)
        APP.processEvents()
        self.assertTrue(workshop.gallery.isVisible())
        self.assertTrue(workshop.name_edit.isVisible())
        self.assertTrue(workshop.preview.isVisible())
        self.assertTrue(workshop.wide.isVisible())

    def test_builtin_can_preview_states_without_editing(self):
        controller, workshop = self.workshop()
        self.assertTrue(workshop.editor.selection.isEnabled())
        workshop.editor.selection.setCurrentIndex(4)
        self.assertEqual(workshop.editor.current_entry(), workshop.draft['states']['shy'])
        self.assertTrue(workshop.editor.lines.isReadOnly())
        self.assertFalse(workshop.editor.replace.isEnabled())

    def test_saved_but_unapplied_revision_stays_unapplied_after_restart(self):
        controller, workshop = self.workshop()
        workshop.copy_draft()
        workshop.name_edit.setText('已应用版本 A')
        saved = workshop.save_draft()
        workshop.apply_pack()
        workshop.name_edit.setText('仅保存版本 B')
        workshop.save_draft()
        controller.shutdown()
        second = self.window()._companion
        self.assertEqual(second.pack.manifest['name'], '已应用版本 A')
        self.assertEqual(second.store.load(saved.id).manifest['name'], '仅保存版本 B')
        second.apply_pack(saved.id)
        second.shutdown()
        third = self.window()._companion
        self.assertEqual(third.pack.manifest['name'], '仅保存版本 B')

    def test_state_buttons_and_preview_keep_each_dialogue_draft(self):
        controller, workshop = self.workshop()
        workshop.copy_draft()
        workshop.editor.state_buttons['shy'].click()
        workshop.editor.lines.setPlainText('这是害羞时的话术')
        workshop.preview.state_buttons['happy'].click()
        self.assertEqual(workshop.editor.selection.currentData(), ('state', 'happy'))
        self.assertTrue(workshop.editor.state_buttons['happy'].isChecked())
        self.assertTrue(workshop.preview.state_buttons['happy'].isChecked())
        workshop.editor.lines.setPlainText('这是开心时的话术')
        workshop.editor.state_buttons['shy'].click()
        self.assertEqual(workshop.editor.lines.toPlainText(), '这是害羞时的话术')
        pack = workshop.save_draft()
        self.assertEqual(pack.manifest['states']['happy']['lines'], ['这是开心时的话术'])
        self.assertEqual(pack.manifest['states']['shy']['lines'], ['这是害羞时的话术'])
        self.assertEqual(controller.pack.id, 'starlight')

    def test_thumbnail_updates_after_replacing_its_state_asset(self):
        from PySide6.QtGui import QImage, QColor
        controller, workshop = self.workshop()
        workshop.copy_draft()
        workshop.editor.state_buttons['shy'].click()
        original = workshop.preview.state_buttons['shy'].icon().cacheKey()
        path = self.data / 'replacement.png'
        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(QColor('#4f405d'))
        self.assertTrue(image.save(str(path)))
        self.assertTrue(workshop.import_asset(path))
        self.assertNotEqual(workshop.preview.state_buttons['shy'].icon().cacheKey(), original)
        self.assertTrue(workshop.preview.state_buttons['shy'].isChecked())
