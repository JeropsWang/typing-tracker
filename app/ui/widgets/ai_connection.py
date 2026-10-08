"""短连接测试使用独立配置和守护线程，关闭弹窗不销毁正在运行的 QThread。"""
from __future__ import annotations

import threading
from PySide6.QtCore import QObject, Signal


class ConnectionTest(QObject):
    done = Signal(bool, str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            ok, message = self._service.test_connection()
        except Exception:
            ok, message = False, '连接测试失败，请检查服务地址与模型配置。'
        try:
            self.done.emit(ok, message)
        except RuntimeError:
            pass  # 应用已退出；守护线程不再访问 UI 或数据库。
