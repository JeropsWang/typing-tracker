"""Deterministic checks of visible motion continuity and bounded displacement."""
import unittest


class MotionTests(unittest.TestCase):
    def test_emotions_have_distinct_motion_and_never_clip_stage_padding(self):
        from app.ui.companion.motion import CharacterMotion
        samples = {}
        for state in ('idle', 'focused', 'shy', 'happy', 'celebrating', 'surprised'):
            motion = CharacterMotion(clock=lambda: 0)
            motion.set_state(state, token=1, now=0)
            frames = [motion.sample(i / 60) for i in range(1, 361)]
            samples[state] = tuple(round(max(abs(getattr(f, key)) for f in frames), 2)
                                   for key in ('x', 'y', 'angle'))
            for frame in frames:
                self.assertLessEqual(abs(frame.x), 6)
                self.assertLessEqual(abs(frame.y), 8)
                self.assertLessEqual(abs(frame.angle), 8)
                self.assertTrue(.94 <= frame.scale_x <= 1.06)
                self.assertTrue(.94 <= frame.scale_y <= 1.06)
        self.assertGreater(len(set(samples.values())), 4)
        self.assertGreater(samples['celebrating'][1], samples['focused'][1])

    def test_interrupted_action_continues_from_current_frame(self):
        from app.ui.companion.motion import CharacterMotion
        motion = CharacterMotion(clock=lambda: 0)
        motion.set_state('celebrating', token=1, now=0)
        before = motion.sample(.27)
        motion.set_state('shy', token=2, now=.27)
        self.assertEqual(motion.sample(.27), before)
        after = motion.sample(.28)
        self.assertLess(abs(after.y - before.y), 2)
        self.assertLess(abs(after.angle - before.angle), 2)

    def test_drag_lean_and_release_settle_without_reset_jump(self):
        from app.ui.companion.motion import CharacterMotion
        motion = CharacterMotion(clock=lambda: 0)
        motion.set_drag(50, now=0)
        frame = motion.sample(.08)
        self.assertGreater(frame.angle, 0)
        motion.release(now=.08)
        self.assertEqual(motion.sample(.08), frame)
        settled = motion.sample(3)
        self.assertLess(abs(settled.angle), 1)
        motion.reset(now=3)
        still = motion.sample(3)
        self.assertEqual((still.x, still.y, still.angle, still.scale_x, still.scale_y),
                         (0, 0, 0, 1, 1))
