"""固定窗口策略：统一尺寸约束与系统放大拦截，不处理页面业务。"""
from PySide6.QtCore import QEvent, QObject, Qt


class FixedWindowPolicy(QObject):
    def __init__(self, window, size):
        super().__init__(window)
        self._window = window
        window.setFixedSize(*size)
        window.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self._window and event.type() == QEvent.WindowStateChange:
            # 标题栏之外也可能收到系统放大请求；清除放大状态，保留最小化状态。
            expanded = Qt.WindowMaximized | Qt.WindowFullScreen
            state = self._window.windowState()
            if state & expanded:
                self._window.setWindowState(state & ~expanded)
        return False
