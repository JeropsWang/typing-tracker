"""生成应用图标 app.ico（多尺寸，供 PyInstaller --icon 使用）。

用法：python scripts/make_icon.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_DEPS = ROOT / '.deps'
if _DEPS.is_dir():
    sys.path.insert(0, str(_DEPS))

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from app.ui.assets.app_icon import SIZES, save_ico  # noqa: E402


def main() -> int:
    _app = QGuiApplication([])
    target = ROOT / 'app.ico'
    save_ico(target)
    # 校验：ICO 头 + 读回图像
    data = target.read_bytes()
    assert data[:4] == b'\x00\x00\x01\x00', 'ICO 头错误'
    count = int.from_bytes(data[4:6], 'little')
    assert count == len(SIZES), f'图标页数错误: {count}'
    img = QImage(str(target))
    assert not img.isNull(), 'ICO 读取失败'
    print(f'已生成 {target}（{count} 个尺寸 {SIZES}），'
          f'校验 256px 图像 {img.width()}x{img.height()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
