"""绘制层动效可取消、可关闭，并遵从窗口生命周期。"""
import unittest
from PySide6.QtCore import QAbstractAnimation
from test_ui_workflow import UIFixture, APP


class MotionValueTests(UIFixture):
    def test_cancel_motion_sets_stable_end(self):
        from app.ui.widgets.motion import MotionValue
        values = []
        motion = MotionValue(None, values.append)
        motion.animate_to(1)
        motion.set_enabled(False)
        self.assertEqual(motion.value, 1)
        self.assertEqual(motion.animation.state(), QAbstractAnimation.Stopped)
        motion.animate_to(0)
        self.assertEqual(motion.value, 0)
        self.assertEqual(motion.animation.state(), QAbstractAnimation.Stopped)

    def test_repeated_hover_reuses_one_animation(self):
        from app.ui.widgets.motion import MotionValue
        motion = MotionValue(None, lambda value: None)
        original = motion.animation
        for value in (1, 0, 1, .5, 0):
            motion.animate_to(value)
            self.assertIs(motion.animation, original)
        motion.stop()
        self.assertEqual(motion.animation.state(), QAbstractAnimation.Stopped)


class MotionLifecycleTests(UIFixture):
    def test_motion_toggle_persists_and_cancel_keeps_value(self):
        dlg = self.dialog()
        self.assertEqual(dlg._motion.text(), '动态效果')
        self.assertTrue(dlg._motion.isChecked())
        dlg._motion.setChecked(False)
        dlg.reject()
        self.assertEqual(self.repo.get_setting('reduced_motion', '0'), '0')
        saved = self.dialog()
        saved._motion.setChecked(False)
        saved.accept()
        self.assertEqual(self.repo.get_setting('reduced_motion'), '1')
        restored = self.dialog()
        self.assertFalse(restored._motion.isChecked())

    def test_disabled_confetti_and_hidden_window_do_not_tick(self):
        window = self.window()
        window.play_confetti()
        self.assertTrue(window._confetti._timer.isActive())
        self.repo.set_setting('reduced_motion', '1')
        window._sync_motion()
        self.assertFalse(window._confetti._timer.isActive())
        self.assertFalse(window._confetti._particles)
        self.assertFalse(window._starfield._timer.isActive())
        window.show_toast('提示', '动效关闭时仍应显示文本')
        popup = window._popups[-1]
        self.assertEqual(popup._anim.state(), QAbstractAnimation.Stopped)
        self.repo.set_setting('reduced_motion', '0')
        window._sync_motion()
        window.play_confetti()
        window.hide()
        self.assertFalse(window._confetti._timer.isActive())
        for button in window._nav_buttons.values():
            self.assertEqual(button._hover_motion.animation.state(), QAbstractAnimation.Stopped)
        window.show()
        window.showMinimized()
        APP.processEvents()
        self.assertFalse(window._starfield._timer.isActive())
        window.showNormal()
        APP.processEvents()
        self.assertTrue(window._starfield._timer.isActive())

    def test_training_reset_does_not_override_disabled_motion(self):
        window = self.window()
        window._nav_buttons['英语'].click()
        page = window._english_page
        self.repo.set_setting('reduced_motion', '1')
        window._sync_motion()
        page.spelling.start_button.click()
        page.spelling.answer.setText(page.service.session.current.word)
        page.spelling.answer.returnPressed.emit()
        page.spelling.answer.returnPressed.emit()
        self.assertFalse(window._starfield._timer.isActive())
        self.assertEqual(page.spelling.spark.motion.animation.state(), QAbstractAnimation.Stopped)
        window._nav_buttons['今日'].click()
        self.assertFalse(window._starfield._timer.isActive())


if __name__ == '__main__':
    unittest.main()
