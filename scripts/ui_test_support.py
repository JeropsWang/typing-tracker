"""Windows 离屏 Qt 不自动发现系统字体，为预览加载现有中文字体。"""
from __future__ import annotations

import os
from pathlib import Path


def prepare_fonts():
    if os.name == 'nt' and os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        folder = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        if folder.is_dir():
            os.environ.setdefault('QT_QPA_FONTDIR', str(folder))


def load_fonts():
    if os.name == 'nt' and os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        from PySide6.QtGui import QFontDatabase
        path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
