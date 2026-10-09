"""Real image and ZIP fixtures exercise the local portable pack boundary."""
import copy
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path
from PySide6.QtGui import QImage, QColor


class PackTests(unittest.TestCase):
    def setUp(self):
        from app.companion.packs import PackStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'image.png'
        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(QColor('#bca4d1'))
        image.save(str(self.image))
        self.manifest = dict(schema_version=1, id='sample', name='作品', author='我',
                             description='说明', version='1.0', memes=[],
                             states={'idle': {'asset': 'assets/idle.png', 'lines': ['你好，{nickname}'], 'duration_ms': 6000}})
        self.store = PackStore(self.root / 'data', self.root / 'builtin')

    def save(self, manifest=None):
        return self.store.save(manifest or self.manifest, {'assets/idle.png': self.image})

    def test_save_import_export_roundtrip_assigns_new_identity(self):
        pack = self.save()
        archive = self.root / 'creation.zip'
        self.store.export_zip(pack.id, archive)
        imported = self.store.import_zip(archive)
        self.assertNotEqual(imported.id, pack.id)
        self.assertEqual(imported.manifest['name'], '作品')
        self.assertTrue(imported.asset_for('shy').path.is_file())
        self.assertEqual(len(self.store.list_packs()), 2)

    def test_rejects_missing_idle_unknown_fields_and_template_expression(self):
        for change in ('no_idle', 'expression', 'secret'):
            manifest = copy.deepcopy(self.manifest)
            if change == 'no_idle':
                manifest['states'] = {}
            elif change == 'expression':
                manifest['states']['idle']['lines'] = ['{nickname.__class__}']
            else:
                manifest['api_key'] = 'secret'
            with self.assertRaises(ValueError):
                self.save(manifest)
        self.assertEqual(self.store.list_packs(), [])

    def test_optional_bad_asset_falls_back_to_idle(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['states']['shy'] = {'asset': 'assets/missing.png', 'lines': ['害羞']}
        pack = self.save(manifest)
        self.assertEqual(pack.asset_for('shy').path, pack.asset_for('idle').path)

    def test_bad_save_preserves_previous_revision(self):
        old = self.save()
        manifest = copy.deepcopy(old.manifest)
        manifest['name'] = '新版本'
        self.store.save(manifest, {'assets/idle.png': old.asset_for('idle').path})
        self.assertEqual(old.manifest['name'], '作品')
        self.assertTrue(old.asset_for('idle').path.is_file())
        self.image.write_bytes(b'broken image')
        with self.assertRaises(ValueError):
            self.store.save(manifest, {'assets/idle.png': self.image})
        self.assertEqual(self.store.load(old.id).manifest['name'], '新版本')

    def test_final_revision_read_failure_preserves_old_pointer(self):
        old = self.save()
        pointer = self.store.user_dir / old.id / 'current.json'
        previous = pointer.read_bytes()
        changed = copy.deepcopy(old.manifest)
        changed['name'] = '未能读取的新版本'
        with patch.object(self.store, 'load', side_effect=OSError('final revision unreadable')):
            with self.assertRaises(OSError):
                self.store.save(changed, {'assets/idle.png': old.asset_for('idle').path})
        self.assertEqual(pointer.read_bytes(), previous)
        self.assertEqual(self.store.load(old.id).revision, old.revision)

    def test_zip_rejects_windows_paths_and_case_collisions(self):
        for names in (['../escape.png'], ['C:/outside.png'], ['assets/A.png', 'assets/a.png'],
                      ['assets/../escape.png'], ['assets/CON.png'], ['assets/a.png:stream']):
            archive = self.root / 'unsafe.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('manifest.json', json.dumps(self.manifest))
                for name in names:
                    z.writestr(name, b'x')
            with self.assertRaises(ValueError, msg=str(names)):
                self.store.import_zip(archive)
        self.assertEqual(self.store.list_packs(), [])

    def test_export_contains_only_creation_files(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['states']['idle']['lines'] = ['Lv.{level}，{accuracy}']
        pack = self.save(manifest)
        archive = self.root / 'safe.zip'
        self.store.export_zip(pack.id, archive)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), {'manifest.json', 'assets/idle.png'})
        self.assertEqual(pack.id, self.store.load(pack.id).id)


if __name__ == '__main__':
    unittest.main()
