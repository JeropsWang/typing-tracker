"""固定窗口回归：尺寸约束、放大入口、最小化与恢复。"""
import unittest

from PySide6.QtCore import Qt, QSize
from PySide6.QtTest import QTest

from test_ui_workflow import APP, UIFixture


class FixedWindowTests(UIFixture):
    def test_window_uses_design_size_and_rejects_resize(self):
        window = self.window()
        expected = QSize(1440, 1024)
        self.assertEqual(window.size(), expected)
        self.assertEqual(window.minimumSize(), expected)
        self.assertEqual(window.maximumSize(), expected)
        for size in (QSize(900, 640), QSize(2560, 1440)):
            window.resize(size)
            APP.processEvents()
            self.assertEqual(window.size(), expected)

    def test_titlebar_has_no_maximize_control_or_double_click_action(self):
        window = self.window()
        self.assertFalse(window.windowFlags() & Qt.WindowMaximizeButtonHint)
        self.assertFalse(hasattr(window._titlebar, '_btn_max'))
        QTest.mouseDClick(window._titlebar, Qt.LeftButton)
        APP.processEvents()
        self.assertFalse(window.isMaximized())
        self.assertEqual(window.size(), QSize(1440, 1024))

    def test_native_state_changes_cannot_enlarge_window(self):
        window = self.window()
        for state in (Qt.WindowMaximized, Qt.WindowFullScreen):
            window.setWindowState(state)
            APP.processEvents()
            self.assertFalse(window.isMaximized())
            self.assertFalse(window.isFullScreen())
            self.assertEqual(window.size(), QSize(1440, 1024))
        for show in (window.showMaximized, window.showFullScreen):
            show()
            APP.processEvents()
            self.assertTrue(window.isVisible())
            self.assertFalse(window.isMaximized())
            self.assertFalse(window.isFullScreen())
            self.assertEqual(window.size(), QSize(1440, 1024))

    def test_minimize_restore_keeps_size_page_selection_and_movement(self):
        window = self.window()
        window.open_training()
        window.move(80, 60)
        self.assertEqual(window.pos().x(), 80)
        QTest.mouseClick(window._titlebar._btn_min, Qt.LeftButton)
        APP.processEvents()
        self.assertTrue(window.isMinimized())
        window.show_and_raise()
        APP.processEvents()
        self.assertTrue(window.isVisible())
        self.assertFalse(window.isMinimized())
        self.assertEqual(window.size(), QSize(1440, 1024))
        self.assertIs(window._tabs.currentWidget(), window._challenge_page)
        self.assertTrue(window._nav.buttons['训练'].isChecked())

    def test_settings_dialog_keeps_its_form_size_without_resize_grip(self):
        dialog = self.dialog()
        expected = QSize(820, 640)
        self.assertEqual(dialog.minimumSize(), expected)
        self.assertEqual(dialog.maximumSize(), expected)
        self.assertFalse(dialog.isSizeGripEnabled())
        dialog.show()
        dialog.resize(1200, 900)
        dialog.setWindowState(Qt.WindowMaximized)
        APP.processEvents()
        self.assertFalse(dialog.isMaximized())
        self.assertEqual(dialog.size(), expected)


if __name__ == '__main__':
    unittest.main()
