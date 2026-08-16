"""TSF 组字监听：精确中文上屏检测（微软拼音等 TSF 输入法）。

原理：
- 本线程创建并激活 ITfThreadMgr，注册 ITfThreadMgrEventSink 跟踪全局键盘焦点；
  OnSetFocus 回调里拿到焦点文档管理器 → 顶层上下文（ITfContext）。
- 轮询（150ms）焦点上下文的 ITfContextComposition：
  * 存在组字视图 → 组字中：读取组字串（拼音），报告 composing
  * 组字消失/切换 → 上一轮缓存的 ITfRange 是持久锚点，提交后其内容
    已变为结果文本（汉字）→ 读取即得**精确上屏内容**
- 组字内退格/取消（Esc）不产生提交（final 文本与拼音快照相同或为空）

线程模型：独立 COM STA 线程（消息泵 + 轮询），与键盘钩子线程并行。
"""
from __future__ import annotations

import ctypes
import threading
import time

try:
    from comtypes import COMObject, CoCreateInstance, CoInitialize, CoUninitialize, cast
    from comtypes import c_ulong as _comtypes_c_ulong  # noqa: F401  (确保 comtypes 可导入)

    from . import tsf_bind as T
    HAS_COMTYPES = True
except Exception:
    HAS_COMTYPES = False

if HAS_COMTYPES:
    from ctypes import byref, c_ulong, c_void_p, c_wchar, create_unicode_buffer, POINTER

    P_UNK = POINTER(c_void_p)
    MAX_TEXT = 512

    class _ThreadMgrEventSink(COMObject):
        """ITfThreadMgrEventSink 实现：跟踪焦点文档管理器。"""

        _com_interfaces_ = [T.ITfThreadMgrEventSink]

        def __init__(self, hook):
            super().__init__()
            self._hook = hook

        def OnInitDocumentMgr(self, pdim):
            return 0

        def OnUninitDocumentMgr(self, pdim):
            return 0

        def OnSetFocus(self, pdimFocus, pdimPrevFocus):
            self._hook._set_focus_doc(pdimFocus)
            return 0

        def OnPushContext(self, pic):
            return 0

        def OnPopContext(self, pic):
            return 0

    class _EditSession(COMObject):
        """ITfEditSession 实现：在编辑会话中读取 range 文本（异步锁）。"""

        _com_interfaces_ = [T.ITfEditSession]

        def __init__(self, rng):
            super().__init__()
            self.text = ''
            self.event = threading.Event()
            self._rng = rng

        def DoEditSession(self, ec):
            self.text = _range_text(self._rng, ec)
            self.event.set()
            return 0


def _range_text(rng, ec=0):
    """读取 ITfRange 文本（ec=0 快速路径）。"""
    buf = (c_wchar * MAX_TEXT)()
    n = c_ulong(0)
    try:
        hr = rng.GetText(ec, 0, buf, MAX_TEXT - 1, byref(n))
        if hr == 0 and n.value:
            return ''.join(buf[:n.value])
    except Exception:
        pass
    return ''


def _release_com(ptr):
    """释放 comtypes 包装的 COM 接口指针（GetRange/Enum 等返回的裸指针）。

    曾从不 Release，每 150ms 泄漏 2-3 个引用（长时间运行累积，v0.8.9 修复）。
    """
    try:
        if ptr is not None:
            ptr.Release()
    except Exception:
        pass


class TsfHook:
    """TSF 组字监听器。回调：on_commit(text) / on_composing(bool)（可选）。"""

    def __init__(self, on_commit=None, on_composing=None):
        self._on_commit = on_commit or (lambda text: None)
        self._on_composing = on_composing or (lambda flag: None)
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        self.available = False      # Activate 成功且线程存活
        self.active = False         # 有焦点 TSF 上下文（可检测组字）
        self.composing = False      # 当前是否组字中
        self._comp = ''
        self._pending = False
        self._pending_text = ''
        self._pending_rng = None
        self._ctx = None            # 焦点 ITfContext
        self._tid = 0               # TfClientId

    # ---------- 生命周期 ----------
    def start(self) -> bool:
        if not HAS_COMTYPES:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, name='tsf', daemon=True)
        self._thread.start()
        for _ in range(50):
            if self.available:
                break
            time.sleep(0.1)
        return self.available

    def stop(self):
        self._running = False
        # 反注册事件接收器并停用线程管理器（曾缺失，COM 引用悬挂，v0.8.9）
        try:
            if getattr(self, '_sink_cookie', None) is not None and hasattr(self, '_sink'):
                mgr = getattr(self, '_mgr', None)
                if mgr is not None:
                    source = mgr.QueryInterface(T.ITfSource)
                    source.UnadviseSink(self._sink_cookie)
        except Exception:
            pass
        try:
            mgr = getattr(self, '_mgr', None)
            if mgr is not None:
                mgr.Deactivate()
        except Exception:
            pass
        self.available = False
        if self._thread is not None:
            self._thread.join(timeout=3)

    # ---------- 线程主循环 ----------
    def _thread_main(self):
        try:
            CoInitialize()
            mgr = CoCreateInstance(T.CLSID_TF_ThreadMgr, interface=T.ITfThreadMgr)
            self._mgr = mgr
            tid = c_ulong()
            if mgr.Activate(byref(tid)) != 0:
                CoUninitialize()
                return
            self._tid = tid.value
            self.available = True

            # 注册线程管理器事件接收器（焦点跟踪）
            try:
                source = mgr.QueryInterface(T.ITfSource)
                self._sink = _ThreadMgrEventSink(self)
                cookie = c_ulong()
                source.AdviseSink(byref(T.IID_ITfThreadMgrEventSink),
                                  ctypes.cast(self._sink, P_UNK), byref(cookie))
                self._sink_cookie = cookie.value
            except Exception:
                pass

            # 初始焦点
            try:
                dim = c_void_p()
                if mgr.GetFocus(byref(dim)) == 0 and dim.value:
                    self._set_focus_doc(dim)
            except Exception:
                pass

            # 消息泵 + 轮询
            msg = ctypes.wintypes.MSG()
            while self._running:
                while ctypes.windll.user32.PeekMessageW(
                        byref(msg), None, 0, 0, 1):   # PM_REMOVE
                    ctypes.windll.user32.TranslateMessage(byref(msg))
                    ctypes.windll.user32.DispatchMessageW(byref(msg))
                try:
                    self._poll()
                except Exception:
                    pass
                time.sleep(0.15)
        finally:
            self.available = False
            try:
                CoUninitialize()
            except Exception:
                pass

    # ---------- 焦点 ----------
    def _set_focus_doc(self, pdimFocus):
        """OnSetFocus / 初始焦点：更新当前焦点上下文。"""
        try:
            if not pdimFocus:
                with self._lock:
                    self._ctx = None
                    self.active = False
                    self.composing = False
                return
            dim = ctypes.cast(pdimFocus, POINTER(T.ITfDocumentMgr))
            pp = c_void_p()
            if dim.GetTop(byref(pp)) == 0 and pp.value:
                ctx = ctypes.cast(pp, POINTER(T.ITfContext))
                with self._lock:
                    self._ctx = ctx
                    self.active = True
        except Exception:
            pass

    # ---------- 组字轮询 ----------
    def _poll(self):
        with self._lock:
            ctx = self._ctx
            composing = False
            text = ''
            rng = None
            if ctx is not None:
                try:
                    comp_iface = ctx.QueryInterface(T.ITfContextComposition)
                    pp_enum = c_void_p()
                    if comp_iface.EnumCompositions(byref(pp_enum)) == 0 and pp_enum.value:
                        enum = ctypes.cast(pp_enum, POINTER(T.IEnumITfCompositionView))
                        arr = (P_UNK * 1)()
                        n = c_ulong(0)
                        if enum.Next(1, arr, byref(n)) == 0 and n.value and arr[0]:
                            view = ctypes.cast(arr[0], POINTER(T.ITfCompositionView))
                            pp_rng = c_void_p()
                            if view.GetRange(byref(pp_rng)) == 0 and pp_rng.value:
                                rng = ctypes.cast(pp_rng, POINTER(T.ITfRange))
                                text = _range_text(rng)
                                composing = True
                            else:
                                _release_com(view)
                        else:
                            _release_com(enum)
                except Exception:
                    pass
            # 防假提交：组字中且拼音串与上一轮互为前缀（同词增长/退格）时，
            # range 内容仍是拼音，读 final 会把它误判为上屏（曾致单字计
            # 10+ tw，v0.8.9 修复）。仅在组字消失或新词开始（互不为前缀）
            # 时读取上一轮 range 的最终文本。
            changed = (not composing) or not self._comp or (
                not text.startswith(self._comp)
                and not self._comp.startswith(text))
            final = ''
            if changed and self._pending and self._pending_rng is not None:
                final = self._final_text(self._pending_rng)
                _release_com(self._pending_rng)
                self._pending_rng = None
            commits = self._update_state(composing, text, final)
            self._pending_rng = rng if composing else None
            self._comp = text
            self.composing = composing
        for c in commits:
            self._on_commit(c)
        self._on_composing(composing)

    def _update_state(self, composing, text, final_text):
        """状态机（纯逻辑，可单测）：组字结束/切换时提交上一轮最终文本。

        - 组字中：记录当前组字串
        - 组字消失/切换：final_text 为上一轮 range 提交后的文本（汉字）
          - final_text 非空且 ≠ 上一轮拼音快照 → 提交（精确上屏内容）
          - 否则视为取消（Esc）/删空，不提交
        """
        commits = []
        if composing:
            if self._pending:
                if final_text and final_text != self._pending_text:
                    commits.append(final_text)
            self._pending = True
            self._pending_text = text
        else:
            if self._pending:
                if final_text and final_text != self._pending_text:
                    commits.append(final_text)
            self._pending = False
            self._pending_text = ''
        return commits

    @staticmethod
    def _final_text(rng):
        """提交后的 range 文本（汉字）。"""
        if rng is None:
            return ''
        return _range_text(rng)
