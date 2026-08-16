"""Windows 全局键盘钩子（ctypes WH_KEYBOARD_LL）+ IME 上屏精确计数。

计数口径（v0.3 修复版）：
- 非组字状态：每个可打印按键记 1 字符、1 tw（字母/数字/符号/空格）。
- 输入法组字：按键不直接计数；上屏（commit）时按实际字符计数，
  汉字 = 2 tw、字母/符号 = 1 tw（classifier 判定）。
- 上屏检测（ImeCommitTracker，修复连续打字丢失问题）：
  * GCS_RESULTSTR 结果串优先（IME 提交后通常保留到下一轮组字开始）；
  * 组字串"前缀丢失"兜底：选字后立即开始新组字、拿不到结果串时，
    把上一轮组字近似计入（拼音字母数 ≈ 汉字 tw 数，误差小）；
  * 组字内退格（旧串以新串开头）与 Esc 取消不计数；
  * 非组字直接提交（中文标点等）按结果串计数。
- 组字中的退格/删除不记删除；非组字状态 Backspace/Delete 记 1 次删除。
- 按住 Ctrl/Alt/Win 的组合键忽略；排除程序列表中的程序完全忽略。
- 鼠标选字等非按键提交由 1 秒轮询兜底。

隐私：只产生计数回调，绝不记录/落盘任何字符内容。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading
import time
import traceback

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
imm32 = ctypes.WinDLL('imm32', use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

VK_BACK, VK_DELETE = 0x08, 0x2E
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_PROCESSKEY = 0xE5
MODIFIER_VKS = {VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN}

GCS_COMPSTR, GCS_RESULTSTR = 0x0008, 0x0800

PRINTABLE_VKS = (
    set(range(0x30, 0x3A))      # 0-9
    | set(range(0x41, 0x5B))    # A-Z
    | set(range(0x60, 0x6A))    # 小键盘数字
    | set(range(0xBA, 0xE3))    # OEM 键区
    | {0x20}                    # 空格
)
LETTER_VKS = set(range(0x41, 0x5B))
DIGIT_VKS = set(range(0x30, 0x3A)) | set(range(0x60, 0x6A))


class ImeCommitTracker:
    """根据 IME 组字串/结果串的事件序列推断上屏提交（纯逻辑，可单测）。

    关键时序背景：LL 键盘钩子在消息分发**之前**触发，因此看到按键时
    IME 的组字状态可能还是旧值；连续打字时"上一轮提交"往往在下一轮
    组字已经开始后才被观察到。旧实现的"组字串变空才提交"会漏掉这种
    情况，本实现用"结果串 + 前缀丢失"双通道保证不丢失、不重复。
    """

    def __init__(self):
        self._comp = ''
        self._last_result = ''

    @property
    def comp(self) -> str:
        """当前组字串（非空表示正在组字，调用方据此跳过按键计数）。"""
        return self._comp

    def update(self, open_, comp, result) -> str:
        """喂入一次 IME 状态快照，返回本次推断出的上屏文本（可能为空串）。"""
        if not open_:
            self._comp = ''
            self._last_result = ''
            return ''

        committed = ''
        if not comp:
            # 组字结束：提交（有结果串）/ 取消或删空（无结果串，不计数）
            if self._comp:
                # 结果串保留期间轮询会重复读到同一串：与 _last_result 去重
                # （曾漏更新导致停顿 >1s 时二次提交，v0.8.9 修复）
                if result and result != self._last_result:
                    committed = result
                self._last_result = result
            elif result and result != self._last_result:
                # 非组字状态的直接提交（中文标点等）
                committed = result
                self._last_result = result
        elif comp != self._comp:
            if self._comp and comp.startswith(self._comp):
                pass                    # 拼音继续增长
            elif self._comp and self._comp.startswith(comp):
                pass                    # 组字内退格（旧串以新串开头）
            else:
                # 上一轮已结束（提交/取消），新组字已开始：
                # result 是权威结果串；若与上一轮相同（保留串）则用拼音
                # 近似兜底；_last_result 随 result 更新——新组字开始时
                # result 为空即清除标记，同内容二次提交不会被误吞
                if result and result != self._last_result:
                    committed = result  # 权威结果串
                else:
                    committed = self._comp  # 兜底：近似计入（拼音字母数）
                self._last_result = result

        self._comp = comp
        return committed


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', wt.DWORD), ('scanCode', wt.DWORD), ('flags', wt.DWORD),
        ('time', wt.DWORD), ('dwExtraInfo', ctypes.POINTER(wt.ULONG)),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ('hwnd', wt.HWND), ('message', wt.UINT), ('wParam', wt.WPARAM),
        ('lParam', wt.LPARAM), ('time', wt.DWORD), ('pt', wt.POINT),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t  # LRESULT 是 LONG_PTR（x64 为 64 位）
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL

imm32.ImmGetContext.argtypes = [wt.HWND]
imm32.ImmGetContext.restype = wt.HANDLE
imm32.ImmReleaseContext.argtypes = [wt.HWND, wt.HANDLE]
imm32.ImmReleaseContext.restype = wt.BOOL
imm32.ImmGetOpenStatus.argtypes = [wt.HANDLE]
imm32.ImmGetOpenStatus.restype = wt.BOOL
imm32.ImmGetCompositionStringW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPVOID, wt.DWORD]
imm32.ImmGetCompositionStringW.restype = wt.LONG


class KeyboardHook:
    """全局键盘钩子。回调：on_char(kind) / on_delete() / on_ime(text)。"""

    def __init__(self, on_char=None, on_delete=None, on_ime=None,
                 excluded_apps=None, on_raw=None):
        """excluded_apps：排除统计的程序名集合（小写 exe 名）。

        注意：钩子线程的回调绝不访问 SQLite/文件等非线程安全资源，
        排除列表以快照方式传入，设置变更时调用 set_excluded_apps() 刷新。
        """
        self._on_char = on_char or (lambda kind: None)
        self._on_delete = on_delete or (lambda: None)
        self._on_ime = on_ime or (lambda text: None)
        self._on_raw = on_raw or (lambda vk, down, flags: None)
        self._excluded_apps = set(excluded_apps or ())
        self._proc_ref = None
        self._hook = None
        self._thread = None
        self._poller = None
        self._ready = threading.Event()
        self._running = False
        self._lock = threading.Lock()
        self._ime = ImeCommitTracker()
        self._proc_cache = ('', 0.0)
        self._mod_down = {}         # vk -> bool：修饰键按下状态（StickyKeys 安全）
        self.errors: list = []      # 诊断：采集回调中的异常堆栈（不再静默）
        self.event_count = 0        # 收到的原始按键事件数（keydown+keyup，诊断用）
        self.ime_readable = True    # IMM 组字状态是否可读（TSF 输入法可能读不到）
        self._tsf = None            # TSF 组字监听器（可选，精确中文计数）
        self.tsf_ok = False         # TSF 监听是否已接入

    def attach_tsf(self, tsf) -> None:
        """接入 TSF 组字监听（主线程调用）；提交经 on_tsf_commit 回调计入。"""
        self._tsf = tsf
        self.tsf_ok = True

    def on_tsf_commit(self, text: str) -> None:
        """TSF 组字提交回调（tsf 线程）→ 按上屏文本计入统计。"""
        if text:
            self._on_ime(text)

    # ---------- 生命周期 ----------
    def start(self) -> bool:
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, name='kb-hook', daemon=True)
        self._thread.start()
        self._ready.wait(5)
        self._poller = threading.Thread(target=self._poll_loop, name='kb-ime-poll', daemon=True)
        self._poller.start()
        return self._hook is not None

    def stop(self) -> None:
        self._running = False
        tid = self._thread.ident if self._thread else None
        if tid:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=3)

    def _thread_main(self):
        self._proc_ref = HOOKPROC(self._callback)
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc_ref, kernel32.GetModuleHandleW(None), 0)
        msg = MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)  # 建立消息队列
        self._ready.set()
        if not self._hook:
            return
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    # ---------- 钩子回调 ----------
    def _callback(self, nCode, wParam, lParam):
        if nCode >= 0 and self._running:
            self.event_count += 1
            try:
                kb = KBDLLHOOKSTRUCT.from_address(lParam)
                down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                # 维护修饰键按下状态（替代 GetAsyncKeyState，防 StickyKeys 丢键）
                if kb.vkCode in MODIFIER_VKS:
                    if down:
                        self._mod_down[kb.vkCode] = True
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        self._mod_down[kb.vkCode] = False
                self._on_raw(kb.vkCode, down, kb.flags)
                self._process(wParam, lParam)
            except Exception:
                # 采集绝不影响系统，但异常必须可见（存入 errors 供诊断）
                try:
                    if len(self.errors) < 50:
                        self.errors.append(traceback.format_exc())
                except Exception:
                    pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _process(self, wParam, lParam):
        kb = KBDLLHOOKSTRUCT.from_address(lParam)
        vk = kb.vkCode
        down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        if not down or vk in MODIFIER_VKS:
            return
        if self._modifiers_held():
            return
        if self._excluded():
            return

        # IME 状态同步（任何按键都可能结束/开始一轮组字）
        if self._tsf is not None and self._tsf.available and self._tsf.active:
            # TSF 路径（微软拼音等 TSF 输入法 + TSF 感知窗口）：
            # 组字状态由 TSF 监听精确提供，提交经 on_tsf_commit 回调。
            # composing 由 150ms 轮询更新，新词首字母按下时必为 False——
            # 若 IME 开启且键是字母（拼音），不直接计数，等 TSF 提交；
            # 否则首字母会被双计（曾系统性膨胀中文 tw/字数，v0.8.9 修复）
            if self._tsf.composing:
                return          # 组字中：按键交给输入法，不直接计数
            if vk in (VK_BACK, VK_DELETE):
                self._on_delete()
                return
            if vk in PRINTABLE_VKS:
                if vk in LETTER_VKS and self._ime_open():
                    return      # 中文模式：字母=拼音，交给 TSF 提交
                self._on_char(self._vk_kind(vk))
            return

        # IMM 路径（传统输入法 / 无 TSF 上下文的窗口）
        open_, comp, result = self._read_ime_state()
        with self._lock:
            committed = self._ime.update(open_, comp, result)
            composing = bool(self._ime.comp)
        if committed:
            self._on_ime(committed)
        if vk == VK_PROCESSKEY:
            if not open_:
                # IMM 读取失败（前台窗口无输入上下文等）：无法检测上屏，
                # 退化为按键近似计数（1 键 1 tw），保证不漏记
                self._on_char('other')
            return
        if composing:
            return  # 组字中：按键交给 IME，不直接计数

        if vk in (VK_BACK, VK_DELETE):
            self._on_delete()
            return
        if vk in PRINTABLE_VKS:
            self._on_char(self._vk_kind(vk))

    def _vk_kind(self, vk) -> str:
        if vk in LETTER_VKS:
            return 'letter'
        if vk in DIGIT_VKS:
            return 'digit'
        if vk == 0x20:
            return 'space'
        return 'symbol'

    # ---------- IME 轮询（兜底鼠标选字等非按键提交） ----------
    def _poll_loop(self):
        while self._running:
            time.sleep(1.0)
            try:
                # TSF 接入后 IMM 轮询跳过：TSF 线程自带 150ms 组字轮询，
                # 这里再喂 IMM 状态机会造成双计（v0.8.9 修复）
                if self._tsf is not None and self._tsf.available and self._tsf.active:
                    continue
                if self._excluded():
                    continue  # 排除程序中的 IME 上屏也不计数（曾绕过，v0.8.9）
                open_, comp, result = self._read_ime_state()
                with self._lock:
                    committed = self._ime.update(open_, comp, result)
                if committed:
                    self._on_ime(committed)
            except Exception:
                pass

    # ---------- 辅助 ----------
    def _modifiers_held(self) -> bool:
        """修饰键是否处于按下状态。

        用钩子自维护的 down/up 状态机，而非 GetAsyncKeyState：
        后者会被 StickyKeys 闩住（粘滞键锁存 Ctrl/Alt/Win 后，下一个
        真实击键被误判为组合键而丢弃，v0.8.9 修复）。
        """
        return any(self._mod_down.get(vk) for vk in MODIFIER_VKS)

    def _excluded(self) -> bool:
        if not self._excluded_apps:
            return False  # 空列表短路：省掉 OpenProcess 开销（v0.8.9）
        proc = self._foreground_process()
        return bool(proc) and proc.lower() in self._excluded_apps

    def set_excluded_apps(self, names) -> None:
        """设置中修改排除程序后调用（主线程），刷新快照。"""
        self._excluded_apps = set(names or ())

    def _foreground_process(self) -> str:
        """返回前台窗口进程名（带 0.5s 缓存）。"""
        now = time.monotonic()
        name, ts = self._proc_cache
        if now - ts < 0.5:
            return name
        name = ''
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
                if h:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wt.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                            name = os.path.basename(buf.value)
                    finally:
                        kernel32.CloseHandle(h)
        self._proc_cache = (name, now)
        return name

    def _ime_open(self) -> bool:
        """前台窗口 IME 是否开启（TSF 输入法也维护 IMM 兼容状态）。

        中文模式下返回 True（字母键=拼音，不直接计数）；
        英文模式/无 IME 返回 False（字母键正常计数）。
        """
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            himc = imm32.ImmGetContext(hwnd)
            if not himc:
                return False
            try:
                return bool(imm32.ImmGetOpenStatus(himc))
            finally:
                imm32.ImmReleaseContext(hwnd, himc)
        except Exception:
            return False

    def _read_ime_state(self):
        """读取前台窗口输入法的 (是否开启, 组字串, 结果串)。

        TSF 输入法（新版微软拼音等）可能不通过 IMM 暴露组字状态：
        此时返回 open_=False 且 comp/result 为空，中文上屏无法精确
        检测，只能按键近似计数（ime_readable=False 供界面提示）。
        """
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False, '', ''
            himc = imm32.ImmGetContext(hwnd)
            if not himc:
                self.ime_readable = False
                return False, '', ''
            try:
                open_ = bool(imm32.ImmGetOpenStatus(himc))
                comp = self._get_composition(himc, GCS_COMPSTR)
                result = self._get_composition(himc, GCS_RESULTSTR)
                return open_, comp, result
            finally:
                imm32.ImmReleaseContext(hwnd, himc)
        except Exception:
            return False, '', ''

    @staticmethod
    def _get_composition(himc, index) -> str:
        n = imm32.ImmGetCompositionStringW(himc, index, None, 0)
        if n <= 0:
            return ''
        buf = ctypes.create_unicode_buffer(n // 2 + 1)
        imm32.ImmGetCompositionStringW(himc, index, buf, ctypes.sizeof(buf))
        return buf.value
