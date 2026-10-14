"""Windows 离屏 Qt 不自动发现系统字体，为预览加载现有中文字体。"""
from __future__ import annotations

import os
from pathlib import Path


def prepare_fonts():
    """Windows 离屏 Qt 初始化前设置系统字体目录，减少缺字与字体查找失败；不覆盖已有环境设置。"""
    if os.name == 'nt' and os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        folder = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        if folder.is_dir():
            os.environ.setdefault('QT_QPA_FONTDIR', str(folder))


def load_fonts():
    """Windows 离屏 QApplication 创建后加载微软雅黑字体文件，稳定中文 UI 测试与截图。"""
    if os.name == 'nt' and os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        from PySide6.QtGui import QFontDatabase
        path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
