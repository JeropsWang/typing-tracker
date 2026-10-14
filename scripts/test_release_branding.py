"""Brand rename: visible surfaces, historical builds, and stable data identity."""
import subprocess
import sys
import tempfile
from pathlib import Path

from test_ui_workflow import UIFixture, ROOT
import build_release


class ReleaseBrandTests(UIFixture):
    """品牌及发布命名兼容的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def source(self, text):
        """读取待测源码文本，不通过导入启动应用或访问数据库。"""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'app').mkdir()
        (root / 'app/__init__.py').write_text(text, encoding='utf-8')
        return root

    def test_historical_tag_retains_typingtracker_brand(self):
        """验证历史版本标签仍按旧品牌命名。"""
        source = self.source("__version__ = '0.9.2'\n")
        self.assertEqual(build_release.read_brand(source), 'TypingTracker')

    def test_source_brand_is_read_without_importing_application(self):
        """验证构建读取源码品牌无需启动或导入应用装配。"""
        source = self.source("raise RuntimeError('must not import')\nAPP_NAME = 'Sariana'\n")
        self.assertEqual(build_release.read_brand(source), 'Sariana')

    def test_brand_cannot_escape_package_paths(self):
        """验证品牌参数不能构造越出发布目录的路径。"""
        source = self.source("APP_NAME = '../unexpected'\n")
        with self.assertRaises(ValueError):
            build_release.read_brand(source)

    def test_window_and_tray_show_the_new_brand(self):
        """验证主窗口及托盘使用新品牌文字。"""
        from app.ui.tray import TrayIcon
        from PySide6.QtWidgets import QLabel
        window = self.window()
        from app import APP_DISPLAY_NAME, __version__
        self.assertEqual(window.windowTitle(), f'{APP_DISPLAY_NAME} v{__version__}')
        labels = [label.text() for label in window._titlebar.findChildren(QLabel)]
        self.assertIn('Sariana · 伴你成长', labels)
        tray = TrayIcon()
        self.addCleanup(tray.deleteLater)
        self.assertEqual(tray.toolTip(), 'Sariana · 伴你成长')
        tray.update_summary('123 字')
        self.assertEqual(tray.toolTip(), 'Sariana\n今日：123 字')

    def test_help_uses_sariana_and_keeps_the_existing_data_directory(self):
        """验证帮助采用新品牌但保留原数据目录行为。"""
        import main
        self.assertEqual(main.DEFAULT_DATA_DIR.name, 'TypingTracker')
        result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--help'],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Sariana', result.stdout)
        self.assertIn('陪你打字，陪你成长。', result.stdout)
        self.assertIn('TypingTracker', result.stdout)
