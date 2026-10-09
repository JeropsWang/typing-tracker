"""Builtin creations must be complete, independently illustrated and portable."""
import tempfile
import unittest
from PySide6.QtGui import QImage
from app.companion.models import STATES
from app.companion.packs import PackStore


class BuiltinAssetTests(unittest.TestCase):
    def test_all_three_packs_have_ten_states_and_two_memes(self):
        with tempfile.TemporaryDirectory() as data:
            packs = PackStore(data).list_packs()
            self.assertEqual({p.id for p in packs}, {'starlight', 'tsundere', 'slacker'})
            images = set()
            for pack in packs:
                self.assertEqual(set(pack.manifest['states']), set(STATES))
                for state in STATES:
                    self.assertGreaterEqual(len(pack.entry_for(state)['lines']), 3)
                self.assertEqual(len(pack.manifest['memes']), 2)
                sprites = {tuple(pack.asset_for(s).rect) for s in STATES}
                self.assertEqual(len(sprites), 10)
                path = pack.asset_for('idle').path
                image = QImage(str(path))
                self.assertTrue(image.hasAlphaChannel())
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                images.add(path.read_bytes())
            self.assertEqual(len(images), 3)


if __name__ == '__main__':
    unittest.main()
