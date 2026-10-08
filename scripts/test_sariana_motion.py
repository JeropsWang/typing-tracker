"""角色待机动效只改变局部，并服从训练、静态设置和窗口生命周期。"""
import hashlib
import json
import unittest

from PySide6.QtCore import QRect, QTimer
from PySide6.QtTest import QTest
from test_ui_workflow import APP, UIFixture, ROOT, pump_until


def pixels(image, rect=None):
    if rect is not None:
        image = image.copy(rect)
    return hashlib.sha256(image.constBits()).digest()


class CharacterMotionTests(UIFixture):
    def test_hand_drawn_strands_move_without_warping_source_hair_texture(self):
        from app.ui.widgets.character_motion import IdlePose
        window = self.window()
        backdrop = window._backdrop
        backdrop.set_motion_enabled(False)
        backdrop._motion.pose = IdlePose(time=1.6)
        first = backdrop.grab().toImage()
        backdrop._motion.pose = IdlePose(time=4.8)
        second = backdrop.grab().toImage()
        # 原插画的纹理保持固定；只有少量细线 SVG 笔触改变。
        for rect in (QRect(1020, 197, 22, 28), QRect(1358, 315, 22, 28)):
            changed = sum(first.pixel(x, y) != second.pixel(x, y)
                          for y in range(rect.top(), rect.top() + rect.height())
                          for x in range(rect.left(), rect.left() + rect.width()))
            # 细线和抗锯齿边缘可覆盖局部；大部分纹理必须保持原位。
            self.assertLess(changed, rect.width() * rect.height() * .5, '整片头发纹理不应被拉扯')
        for rect in (QRect(965, 125, 100, 145), QRect(1305, 115, 130, 385)):
            changed = sum(first.pixel(x, y) != second.pixel(x, y)
                          for y in range(rect.top(), rect.top() + rect.height())
                          for x in range(rect.left(), rect.left() + rect.width()))
            self.assertGreater(changed, 20, '两侧应各有手绘发丝笔触在轻摆')

    def test_closed_eye_overlay_preserves_scene_and_rest_of_face(self):
        from app.ui.widgets.character_motion import IdlePose
        window = self.window()
        backdrop = window._backdrop
        backdrop.set_motion_enabled(False)
        backdrop._motion.pose = IdlePose(blink=0, time=2)
        original = backdrop.grab().toImage()
        backdrop._motion.pose = IdlePose(blink=1, time=2)
        closed = backdrop.grab().toImage()
        for rect in (QRect(100, 100, 300, 300), QRect(1195, 240, 20, 20),
                     QRect(1250, 370, 100, 120)):
            self.assertEqual(pixels(original, rect), pixels(closed, rect), '闭眼只应覆盖眼部')
        self.assertNotEqual(pixels(original, QRect(1108, 140, 173, 82)),
                            pixels(closed, QRect(1108, 140, 173, 82)))

    def test_idle_blinks_locally_then_returns_to_open_eyes(self):
        window = self.window()
        backdrop = window._backdrop
        eye_area = QRect(1108, 140, 173, 82)
        open_eyes = pixels(backdrop.grab(eye_area).toImage())
        self.assertTrue(pump_until(
            lambda: pixels(backdrop.grab(eye_area).toImage()) != open_eyes, timeout=7.3),
            '4–7 秒内应出现一次眼部动作')
        QTest.qWait(350)
        self.assertEqual(pixels(backdrop.grab(eye_area).toImage()), open_eyes)

    def test_idle_changes_hair_without_moving_background_or_face(self):
        window = self.window()
        backdrop = window._backdrop
        first = backdrop.grab().toImage()
        QTest.qWait(700)
        second = backdrop.grab().toImage()
        self.assertNotEqual(pixels(first), pixels(second), 'Sariana 应有局部待机动作')
        self.assertEqual(pixels(first, QRect(100, 100, 300, 300)),
                         pixels(second, QRect(100, 100, 300, 300)))
        self.assertEqual(pixels(first, QRect(1195, 240, 20, 20)),
                         pixels(second, QRect(1195, 240, 20, 20)))

    def test_character_timers_pause_for_disabled_hidden_and_training(self):
        window = self.window()
        backdrop = window._backdrop
        active = lambda: any(timer.isActive() for timer in backdrop.findChildren(QTimer))
        self.assertTrue(active(), '角色待机应启动自己的定时器')
        self.repo.set_setting('reduced_motion', '1')
        window._sync_motion()
        self.assertFalse(active())
        first = backdrop.grab().toImage()
        QTest.qWait(150)
        self.assertEqual(pixels(first), pixels(backdrop.grab().toImage()))
        self.repo.set_setting('reduced_motion', '0')
        window._sync_motion()
        self.assertTrue(active())
        window._nav_buttons['英语'].click()
        window._english_page.spelling.start_button.click()
        self.assertFalse(active())
        window._nav_buttons['今日'].click()
        self.assertTrue(active())
        window.hide()
        self.assertFalse(active())
        window.show()
        APP.processEvents()
        self.assertTrue(active())
        window.showMinimized()
        APP.processEvents()
        self.assertFalse(active())
        window.showNormal()
        APP.processEvents()
        self.assertTrue(active())

    def test_undeclared_or_missing_motion_asset_falls_back_to_static(self):
        window = self.window()
        backdrop = window._backdrop
        active = lambda: any(timer.isActive() for timer in backdrop.findChildren(QTimer))
        window.apply_effects({'backdrop': 'background.png'})
        self.assertTrue(backdrop.has_artwork())
        self.assertFalse(active())
        before = pixels(backdrop.grab().toImage())
        QTest.qWait(100)
        self.assertEqual(pixels(backdrop.grab().toImage()), before)
        window.apply_effects({'backdrop': 'background.png', 'character_motion': 'sariana/absent.json'})
        self.assertTrue(backdrop.has_artwork())
        self.assertFalse(active())

    def test_malformed_or_nonfinite_svg_keeps_static_artwork(self):
        from app.ui.widgets.starfield import BackdropImage
        source = ROOT / 'app/ui/assets/background.png'
        base = json.loads((ROOT / 'app/ui/assets/sariana/idle.json').read_text(encoding='utf-8'))
        base['closed_eyes'] = str(ROOT / 'app/ui/assets/sariana/blink-closed-v1.png')
        cases = [
            ('svg', '<path d="M 1000 100"/>'),
            ('svg', '<path d="M 1000 100 C 1020 120 1040 140 1060 160" data-period="inf"/>'),
            ('svg', '<path d="M 1000 100 C 1020 120 1040 140 1060 nan"/>'),
            ('svg', '<path'),
            ('svg', '<path d="M 1000 100 C 1020 120 1040 140 1060 160" data-period="1e-320"/>'),
            ('not-svg', '<path d="M 1000 100 C 1020 120 1040 140 1060 160"/>'),
        ]
        for index, (root_tag, path_data) in enumerate(cases):
            with self.subTest(index=index):
                svg = self.data / f'invalid-hair-{index}.svg'
                svg.write_text(f'<{root_tag} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1487 1058">'
                               + path_data + f'</{root_tag}>', encoding='utf-8')
                data = dict(base, hair_svg=str(svg))
                metadata = self.data / f'invalid-motion-{index}.json'
                metadata.write_text(json.dumps(data), encoding='utf-8')
                backdrop = BackdropImage()
                self.widgets.append(backdrop)
                backdrop.resize(800, 560)
                backdrop.set_source(source, metadata)
                backdrop.set_motion_enabled(True)
                backdrop.show()
                APP.processEvents()
                self.assertTrue(backdrop.has_artwork())
                self.assertFalse(any(t.isActive() for t in backdrop.findChildren(QTimer)))


if __name__ == '__main__':
    unittest.main()
