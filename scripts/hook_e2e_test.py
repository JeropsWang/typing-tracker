"""钩子端到端自测（v2）：连接真实统计引擎，注入 'A' 与 Backspace，验证计数。

覆盖钩子线程 → engine（含 SQLite 跨线程防护）全链路。
注意：会向当前前台窗口注入一个 'A' 和一个退格（A 会被退格删除，无净效果）。
用法：python scripts/hook_e2e_test.py
"""
from __future__ import annotations

import ctypes
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.engine import StatsEngine  # noqa: E402
from app.core.keyboard_hook import KeyboardHook  # noqa: E402
from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402


def main() -> int:
    tmp = ROOT / '.tmptest'
    tmp.mkdir(exist_ok=True)
    td = tmp / ('tt_' + uuid.uuid4().hex)
    td.mkdir()
    balance = json.loads((ROOT / 'config' / 'balance.json').read_text(encoding='utf-8'))
    conn = connect_db(td / 't.db')
    init_schema(conn)
    repo = Repository(conn)

    engine = StatsEngine(repo, lambda k, d=None: repo.get_setting(k, d), balance)
    hk = KeyboardHook(on_char=engine.handle_char, on_delete=engine.handle_delete,
                      on_ime=engine.handle_ime)
    ok = hk.start()
    print(f'钩子安装: {"成功" if ok else "失败!"}')
    if not ok:
        return 1

    u = ctypes.WinDLL('user32')
    u.keybd_event(0x41, 0, 0, 0)   # A down
    u.keybd_event(0x41, 0, 2, 0)   # A up
    time.sleep(0.3)
    u.keybd_event(0x08, 0, 0, 0)   # Backspace down
    u.keybd_event(0x08, 0, 2, 0)   # Backspace up
    time.sleep(1.5)
    hk.stop()

    if hk.errors:
        print('钩子回调异常（统计中断的直接原因）:')
        for e in hk.errors[:3]:
            print(e)
    snap = engine.snapshot()
    print(f'stats: typed={snap["typed"]} deleted={snap["deleted"]} tw={snap["tw"]}')
    passed = snap['typed'] >= 1 and snap['deleted'] >= 1 and not hk.errors
    print('result:', 'PASS (hook->engine full chain ok)' if passed else 'FAIL')
    shutil.rmtree(td, ignore_errors=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
