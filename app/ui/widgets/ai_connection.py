"""短连接测试使用独立配置和守护线程，关闭弹窗不销毁正在运行的 QThread。"""
from __future__ import annotations

import threading
from PySide6.QtCore import QObject, Signal


class ConnectionTest(QObject):
    """短模型连接请求的 Qt 回传对象，后台使用配置快照不访问控件。"""
    done = Signal(bool, str)

    def __init__(self, service, parent=None):
        """建立模型连接检查组件的依赖与初始状态。"""
        super().__init__(parent)
        self._service = service
        self._thread = None

    def start(self):
        """启动独立连接检查线程，结果通过 done 信号回主线程。"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        """后台测试连接，将意外异常转为脱敏提示，UI 已销毁时忽略回传。"""
        try:
            ok, message = self._service.test_connection()
        except Exception:
            ok, message = False, '连接测试失败，请检查服务地址与模型配置。'
        try:
            self.done.emit(ok, message)
        except RuntimeError:
            pass  # 应用已退出；守护线程不再访问 UI 或数据库。
