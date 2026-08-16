"""键盘钩子诊断工具：运行 N 秒，实时打印捕获到的所有输入事件。

用法：python scripts/hook_probe.py [--seconds 15] [--inject]

--inject：自动注入一个 F24 功能键（对前台窗口无影响），用于验证
          钩子链路是否通畅——若 RAW 里出现 0x87 说明钩子本身正常。

输出解读：
- RAW 行 = 钩子收到的原始按键（无论是否被计数逻辑过滤）
- CHAR/DEL/IME 行 = 实际计入统计的事件
- 若 RAW 有输出但 CHAR/DEL/IME 全 0 → 计数过滤逻辑问题
- 若 RAW 也全 0 → 钩子没收到事件，多半是：
  1) 打字的窗口以管理员身份运行（UIPI 隔离，普通权限钩子收不到）
     → 换普通窗口打字，或以管理员身份运行本程序/打字管家
  2) 杀毒软件拦截了低层键盘钩子
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.keyboard_hook import KeyboardHook  # noqa: E402

STATS = {'char': 0, 'del': 0, 'ime_chars': 0}
RAW_COUNT = 0
VK_F24 = 0x87


def is_admin() -> bool:
    try:
        return bool(ctypes.WinDLL('shell32').IsUserAnAdmin())
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=15)
    ap.add_argument('--inject', action='store_true', help='自动注入 F24 验证链路')
    args = ap.parse_args()

    def on_raw(vk, down, flags):
        global RAW_COUNT
        RAW_COUNT += 1
        if down:
            print(f'  RAW vk=0x{vk:02X} down')

    def on_char(kind):
        STATS['char'] += 1
        print(f'  CHAR {kind}')

    def on_delete():
        STATS['del'] += 1
        print('  DEL')

    def on_ime(text):
        STATS['ime_chars'] += len(text)
        print(f'  IME {text!r}')

    hook = KeyboardHook(on_raw=on_raw, on_char=on_char,
                        on_delete=on_delete, on_ime=on_ime)
    ok = hook.start()
    print(f'钩子安装: {"成功" if ok else "失败!"}')
    if not ok:
        return 1
    print(f'当前进程管理员: {"是" if is_admin() else "否"}'
          '（普通权限收不到管理员窗口的按键，UIPI 隔离）')

    # TSF 组字监听（微软拼音等 TSF 输入法的精确中文上屏）
    tsf = None
    try:
        from app.core.tsf_hook import TsfHook

        def on_tsf(text):
            STATS['ime_chars'] += len(text)
            print(f'  IME[TSF] {text!r}')

        tsf = TsfHook(on_commit=on_tsf)
        if tsf.start():
            print('TSF 组字监听: 可用（在 TSF 感知窗口如 Edge/Office 打中文时生效）')
        else:
            print('TSF 组字监听: 不可用（中文将按 IMM/按键近似计数）')
    except Exception as e:
        print(f'TSF 组字监听: 初始化失败（{e}）')
    if args.inject:
        time.sleep(1)
        u = ctypes.WinDLL('user32')
        print('注入 F24 验证钩子链路...')
        u.keybd_event(VK_F24, 0, 0, 0)
        u.keybd_event(VK_F24, 0, 2, 0)   # KEYEVENTF_KEYUP
        time.sleep(1.5)
    else:
        print(f'请在 {args.seconds} 秒内到其他窗口打字（中英文各试几个字）...')
        time.sleep(args.seconds)
    hook.stop()
    if tsf is not None:
        tsf.stop()
    if hook.errors:
        print('\n[诊断] 钩子回调捕获到异常（这是计数失败的直接原因）：')
        for e in hook.errors[:3]:
            print(e)
    print(f'\n汇总: RAW {RAW_COUNT} 条 | 按键 {STATS["char"]} 次 | 删除 {STATS["del"]} 次 | '
          f'IME 上屏 {STATS["ime_chars"]} 字符')
    print(f'输入法组字状态读取: {"可用" if hook.ime_readable else "不可用（TSF 输入法？中文将按按键近似计数）"}')
    if RAW_COUNT == 0:
        print('RAW 为 0 → 钩子没收到任何事件：请检查打字窗口是否管理员权限（UIPI），'
              '或杀毒软件是否拦截。')
    elif args.inject:
        print('注入测试完成：钩子链路正常（F24 非可打印键，统计为 0 属正常）。')
    elif STATS['char'] == 0 and STATS['del'] == 0 and STATS['ime_chars'] == 0:
        print('RAW 有事件但统计为 0 → 计数过滤逻辑问题，请把上面输出发给开发者。')
    else:
        print('钩子工作正常。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
