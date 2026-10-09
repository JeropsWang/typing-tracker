"""Companion host switches and visibility tested against real Qt windows."""
from PySide6.QtCore import Qt, QPoint, QPointF, QRect, QTimer, QEvent
from test_ui_workflow import UIFixture, APP


class CompanionUITests(UIFixture):
    def drag_to(self, view, global_target):
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        anchor = QPoint(view.width() // 2, view.height() - 70)
        QTest.mousePress(view, Qt.LeftButton, pos=anchor)
        APP.sendEvent(view, QMouseEvent(QEvent.MouseMove,
                      QPointF(view.mapFromGlobal(global_target)), QPointF(global_target),
                      Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        APP.sendEvent(view, QMouseEvent(QEvent.MouseButtonRelease,
                      QPointF(view.mapFromGlobal(global_target)), QPointF(global_target),
                      Qt.LeftButton, Qt.NoButton, Qt.NoModifier))

    def companion(self):
        from app.ui.companion.controller import CompanionController
        window = self.window()
        controller = window._companion
        self.addCleanup(controller.shutdown)
        controller.start()
        return window, controller

    def test_switch_keeps_single_view_and_current_reaction(self):
        from app.companion.models import CompanionEvent
        window, c = self.companion()
        original = c.view
        c.handle_event(CompanionEvent('pet'))
        token = c.runtime.sample().token
        for mode in ('desktop', 'window') * 5:
            c.switch_mode(mode)
            APP.processEvents()
            self.assertIs(c.view, original)
            self.assertEqual(c.runtime.sample().token, token)
        self.assertEqual(self.repo.get_setting('companion_mode'), 'window')
        self.assertIs(c.view.parentWidget(), window)

    def test_window_hidden_desktop_continues_and_shutdown_stops(self):
        window, c = self.companion()
        window.hide()
        c.sync_visibility()
        self.assertFalse(c.view.isVisible())
        c.switch_mode('desktop')
        APP.processEvents()
        self.assertTrue(c.view.isVisible())
        self.assertTrue(c.view.testAttribute(Qt.WA_ShowWithoutActivating))
        self.assertTrue(c.view.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        c.shutdown()
        self.assertFalse(c.view.isVisible())
        self.assertFalse(c._timer.isActive())
        self.assertFalse(c.view._animation.isActive())

    def test_reduced_motion_and_practice_disable_animation(self):
        window, c = self.companion()
        self.repo.set_setting('reduced_motion', '1')
        c.sync_settings()
        self.assertFalse(c.view._animation.isActive())
        self.repo.set_setting('reduced_motion', '0')
        window._challenge_page._set_running(True)
        c.sync_visibility()
        self.assertFalse(c.view._animation.isActive())
        self.assertEqual(c.runtime.sample().state, 'focused')

    def test_screen_clamping_handles_negative_and_removed_screen(self):
        from app.ui.companion.desktop import clamp_position
        screens = [QRect(-1920, 0, 1920, 1040), QRect(0, 0, 1920, 1040)]
        self.assertEqual(clamp_position(QPoint(-1000, 100), 200, 280, screens), QPoint(-1000, 100))
        recovered = clamp_position(QPoint(-5000, 2000), 200, 280, screens[1:])
        self.assertTrue(screens[1].contains(QRect(recovered.x(), recovered.y(), 200, 280)))

    def test_hide_cancels_scheduled_click(self):
        from PySide6.QtTest import QTest
        window, c = self.companion()
        before = c.runtime.sample().token
        QTest.mouseClick(c.view, Qt.LeftButton, pos=QPoint(c.view.width() // 2, c.view.height() - 70))
        c.hide_companion()
        QTest.qWait(APP.doubleClickInterval() + 20)
        self.assertEqual(c.runtime.sample().token, before)

    def test_gif_is_static_when_motion_disabled_and_releases_source(self):
        from app.companion.packs import Sprite
        from PySide6.QtGui import QMovie
        from PySide6.QtTest import QTest
        window, c = self.companion()
        path = self.data / 'two-frames.gif'
        path.write_bytes(bytes.fromhex(
            '47494638396101000100800000000000ffffff'
            '21ff0b4e45545343415045322e300301000000'
            '21f90400050000002c0000000001000100000202440100'
            '21f90400050000002c00000000010001000002024c01003b'))
        c._timer.stop()
        c.view.set_content(Sprite(path), '测试动画', True)
        QTest.qWait(150)
        self.assertEqual(c.view._movie.state(), QMovie.Running)
        c.view.set_motion_enabled(False)
        self.assertEqual(c.view._movie.state(), QMovie.NotRunning)
        self.assertEqual(c.view._movie.currentFrameNumber(), 0)
        # Windows must allow replacement of a draft source while it is being previewed.
        path.unlink()
        self.assertFalse(path.exists())

    def test_double_click_is_one_reaction(self):
        from PySide6.QtTest import QTest
        window, c = self.companion()
        before = c.runtime.sample().token
        QTest.mouseDClick(c.view, Qt.LeftButton, pos=QPoint(c.view.width() // 2, c.view.height() - 70))
        QTest.qWait(APP.doubleClickInterval() + 20)
        self.assertEqual(c.runtime.sample().token, before + 1)
        self.assertEqual(c.runtime.sample().state, 'surprised')

    def test_desktop_resizing_keeps_character_inside_available_screen(self):
        from app.ui.companion.desktop import available_screens
        window, c = self.companion()
        c.switch_mode('desktop')
        self.repo.set_setting('companion_size', '100')
        c.sync_settings()
        area = available_screens()[0]
        c.view.move(area.right() - c.view.width() + 1, area.bottom() - c.view.height() + 1)
        self.repo.set_setting('companion_size', '220')
        c.sync_settings()
        self.assertTrue(area.contains(c.view.geometry()))

    def test_event_metrics_never_fall_back_to_daily_metrics(self):
        from app.companion.models import CompanionEvent
        import copy
        window, c = self.companion()
        manifest = copy.deepcopy(c.pack.manifest)
        manifest['states']['happy']['lines'] = ['本次速度 {speed}，正确率 {accuracy}']
        manifest['memes'][0]['duration_ms'] = 30000
        manifest['memes'][1]['duration_ms'] = 30000
        saved = c.store.save(manifest, {'assets/atlas-v1.png': c.pack.asset_for('idle').path})
        c.apply_pack(saved.id)
        c._values.update(speed='123.4', accuracy='11%')
        c.handle_event(CompanionEvent('finished', {'accuracy': '96%'}, 'english-result'))
        self.assertEqual(c.view._text, '本次速度 暂无数据，正确率 96%')

    def test_available_geometry_signal_recovers_desktop_position(self):
        from app.ui.companion.desktop import available_screens
        window, c = self.companion()
        c.switch_mode('desktop')
        area = available_screens()[0]
        c.view.move(area.right() + 200, area.bottom() + 200)
        APP.primaryScreen().availableGeometryChanged.emit(area)
        self.assertTrue(area.contains(c.view.geometry()))

    def test_selected_random_meme_uses_custom_duration(self):
        from app.companion.runtime import Runtime
        import copy
        window, c = self.companion()
        manifest = copy.deepcopy(c.pack.manifest)
        for entry in manifest['memes']:
            entry['duration_ms'] = 30000
        saved = c.store.save(manifest, {'assets/atlas-v1.png': c.pack.asset_for('idle').path})
        c.apply_pack(saved.id)
        now = [0.0]
        c.runtime = Runtime(clock=lambda: now[0])
        c.runtime.set_visible(True)
        c.runtime.set_frequency('lively')
        now[0] = 241
        c._render()
        self.assertEqual(c.runtime.sample().kind, 'meme')
        now[0] += 20
        self.assertEqual(c.runtime.sample().kind, 'meme')

    def test_window_drag_stays_where_placed_across_refresh_and_mode_switch(self):
        window, c = self.companion()
        target = window.mapToGlobal(QPoint(360, 350))
        self.drag_to(c.view, target)
        placed = QPoint(c.view.pos())
        self.assertEqual(c.mode, 'window')
        self.assertLess(placed.x(), 400)
        c.sync_visibility()
        self.assertEqual(c.view.pos(), placed)
        c.switch_mode('desktop')
        c.switch_mode('window')
        self.assertEqual(c.view.pos(), placed)
        self.assertEqual(self.repo.get_setting('companion_window_position'),
                         __import__('json').dumps([placed.x(), placed.y()]))

    def test_drag_out_of_window_detaches_and_continues_same_gesture(self):
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        window, c = self.companion()
        c._timer.stop()
        before = c.runtime.sample().token
        anchor = QPoint(c.view.width() // 2, c.view.height() - 70)
        QTest.mousePress(c.view, Qt.LeftButton, pos=anchor)
        target = window.mapToGlobal(QPoint(-40, window.height() // 2))
        APP.sendEvent(c.view, QMouseEvent(QEvent.MouseMove,
                      QPointF(c.view.mapFromGlobal(target)), QPointF(target),
                      Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(c.mode, 'desktop')
        self.assertIsNone(c.view.parentWidget())
        self.assertTrue(c.view._dragging)
        second = QPoint(500, 400)
        APP.sendEvent(c.view, QMouseEvent(QEvent.MouseMove,
                      QPointF(c.view.mapFromGlobal(second)), QPointF(second),
                      Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        self.assertLess((c.view.mapToGlobal(anchor) - second).manhattanLength(), 3)
        APP.sendEvent(c.view, QMouseEvent(QEvent.MouseButtonRelease,
                      QPointF(anchor), QPointF(second), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        QTest.qWait(APP.doubleClickInterval() + 20)
        self.assertEqual(c.runtime.sample().token, before)
        self.assertEqual(self.repo.get_setting('companion_mode'), 'desktop')
        self.assertTrue(self.repo.get_setting('companion_position'))
        window.hide()
        c.sync_visibility()
        self.assertTrue(c.view.isVisible())

    def test_restored_window_position_is_clamped_when_window_changes(self):
        window, c = self.companion()
        self.repo.set_setting('companion_window_position', '[99999, -99999]')
        c.sync_settings()
        self.assertTrue(window.rect().contains(c.view.geometry()))
        self.repo.set_setting('companion_window_position', 'invalid')
        c.sync_settings()
        self.assertTrue(window.rect().contains(c.view.geometry()))

    def test_pose_transition_is_smooth_and_reduced_motion_is_immediate(self):
        from app.companion.models import CompanionEvent
        window, c = self.companion()
        c._timer.stop()
        self.repo.set_setting('reduced_motion', '0')
        c.sync_settings()
        c.handle_event(CompanionEvent('pet'))
        self.assertIsNotNone(c.view._previous_image)
        self.assertLess(c.view._blend, 1)
        self.repo.set_setting('reduced_motion', '1')
        c.sync_settings()
        self.assertEqual(c.view._blend, 1)
        self.assertIsNone(c.view._previous_image)
        self.assertFalse(c.view._animation.isActive())

    def test_invalid_gif_static_frame_falls_back_after_animation(self):
        from app.companion.packs import Sprite
        window, c = self.companion()
        c._timer.stop()
        path = self.data / 'static-frame-fallback.gif'
        path.write_bytes(bytes.fromhex(
            '47494638396101000100800000000000ffffff'
            '21ff0b4e45545343415045322e300301000000'
            '21f90400050000002c0000000001000100000202440100'
            '21f90400050000002c00000000010001000002024c01003b'))
        c.view.set_content(Sprite(path, frame=100), '', True)
        self.assertTrue(c.view._movie.jumpToFrame(1))
        self.assertEqual(c.view._movie.currentFrameNumber(), 1)
        c.view.set_motion_enabled(False)
        self.assertEqual(c.view._movie.currentFrameNumber(), 0)
