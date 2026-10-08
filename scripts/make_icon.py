"""生成应用图标 app.ico（多尺寸，供 PyInstaller --icon 使用）。

源图：交付资源 `app/ui/assets/app_icon.png`（与窗口/托盘同一份 PNG）；
读不出时回退 `app.ui.assets.app_icon.draw_app_icon()` 的程序化绘制。
输出：仓库根目录 `app.ico`（7 档 16/24/32/48/64/128/256，PNG 内嵌），
脚本可重复执行，每次整文件覆盖。

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

from app.ui.assets.app_icon import APP_ICON_PNG, SIZES, save_ico  # noqa: E402


def ico_entry_sizes(data: bytes) -> list:
    """从 ICO 目录项解析各档尺寸（0 表示 256）。"""
    out = []
    for i in range(int.from_bytes(data[4:6], 'little')):
        w = data[6 + 16 * i] or 256
        h = data[7 + 16 * i] or 256
        out.append((w, h))
    return out


def main() -> int:
    _app = QGuiApplication([])
    if not APP_ICON_PNG.is_file():
        print(f'[警告] 交付源图缺失，回退程序化绘制：{APP_ICON_PNG}')
    target = ROOT / 'app.ico'
    save_ico(target, APP_ICON_PNG)
    # 校验：ICO 头 + 页数 + 目录项尺寸 + 读回图像
    data = target.read_bytes()
    assert data[:4] == b'\x00\x00\x01\x00', 'ICO 头错误'
    count = int.from_bytes(data[4:6], 'little')
    assert count == len(SIZES), f'图标页数错误: {count}'
    entries = ico_entry_sizes(data)
    assert entries == [(s, s) for s in SIZES], f'ICO 目录项尺寸错误: {entries}'
    img = QImage(str(target))
    assert not img.isNull(), 'ICO 读取失败'
    size_b = APP_ICON_PNG.stat().st_size if APP_ICON_PNG.is_file() else 0
    print(f'源图 {APP_ICON_PNG} 存在={APP_ICON_PNG.is_file()} 大小={size_b} B')
    print(f'已生成 {target}（{count} 档 {SIZES}，{len(data)} B）')
    print(f'ICO 目录项尺寸：{["%dx%d" % e for e in entries]}，'
          f'读回图像 {img.width()}x{img.height()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
