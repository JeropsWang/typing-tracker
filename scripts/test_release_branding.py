"""Brand rename: visible surfaces, historical builds, and stable data identity."""
import subprocess
import sys
import tempfile
from pathlib import Path

from test_ui_workflow import UIFixture, ROOT
import build_release


class ReleaseBrandTests(UIFixture):
    def source(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'app').mkdir()
        (root / 'app/__init__.py').write_text(text, encoding='utf-8')
        return root

    def test_historical_tag_retains_typingtracker_brand(self):
        source = self.source("__version__ = '0.9.2'\n")
        self.assertEqual(build_release.read_brand(source), 'TypingTracker')

    def test_source_brand_is_read_without_importing_application(self):
        source = self.source("raise RuntimeError('must not import')\nAPP_NAME = 'Sariana'\n")
        self.assertEqual(build_release.read_brand(source), 'Sariana')

    def test_brand_cannot_escape_package_paths(self):
        source = self.source("APP_NAME = '../unexpected'\n")
        with self.assertRaises(ValueError):
            build_release.read_brand(source)

    def test_window_and_tray_show_the_new_brand(self):
        from app.ui.tray import TrayIcon
        from PySide6.QtWidgets import QLabel
        window = self.window()
        self.assertEqual(window.windowTitle(), 'Sariana · 伴你成长 v0.9.3')
        labels = [label.text() for label in window._titlebar.findChildren(QLabel)]
        self.assertIn('Sariana · 伴你成长', labels)
        tray = TrayIcon()
        self.addCleanup(tray.deleteLater)
        self.assertEqual(tray.toolTip(), 'Sariana · 伴你成长')
        tray.update_summary('123 字')
        self.assertEqual(tray.toolTip(), 'Sariana\n今日：123 字')

    def test_help_uses_sariana_and_keeps_the_existing_data_directory(self):
        import main
        self.assertEqual(main.DEFAULT_DATA_DIR.name, 'TypingTracker')
        result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--help'],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Sariana', result.stdout)
        self.assertIn('陪你打字，陪你成长。', result.stdout)
        self.assertIn('TypingTracker', result.stdout)
