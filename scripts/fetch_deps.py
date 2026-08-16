"""下载并解包 Python 依赖到 .deps（沙箱环境下 pip 的临时文件操作被拦截时的替代路径）。

只用标准库的普通文件操作（urllib + zipfile）。幂等：已存在的 wheel 跳过下载。
用法：python scripts/fetch_deps.py [包名...]   # 不传包名则下载全部（PKGS）
"""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / '.deps'
DL = ROOT / '.dl'
PKGS = ['PySide6', 'shiboken6', 'PySide6_Essentials', 'PySide6_Addons', 'pyqtgraph']


def pypi_json(name: str) -> dict:
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/json', timeout=60) as r:
        return json.load(r)


def pick_wheel(data: dict):
    """依次尝试：win_amd64 二进制 / 纯 Python any / win_amd64 纯 Python。"""
    urls = data['urls']
    for f in urls:
        fn = f['filename']
        if (fn.endswith('.whl') and 'win_amd64' in fn and 'cp310-abi3' in fn
                and 'musllinux' not in fn and 'manylinux' not in fn):
            return f['url'], fn
    for f in urls:
        fn = f['filename']
        if fn.endswith('.whl') and 'py3-none-any' in fn:
            return f['url'], fn
    for f in urls:
        fn = f['filename']
        if fn.endswith('.whl') and 'win_amd64' in fn and 'py3-none' in fn:
            return f['url'], fn
    raise RuntimeError(f'未找到可用轮子: {data["info"]["name"]}')


def main() -> int:
    DEPS.mkdir(exist_ok=True)
    DL.mkdir(exist_ok=True)
    packages = sys.argv[1:] or PKGS
    for name in packages:
        url, fn = pick_wheel(pypi_json(name))
        target = DL / fn
        if not target.exists():
            print(f'下载 {fn}')
            urllib.request.urlretrieve(url, target)
        print(f'解包 {fn}')
        with zipfile.ZipFile(target) as z:
            z.extractall(DEPS)
    print(f'完成 → {DEPS}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
