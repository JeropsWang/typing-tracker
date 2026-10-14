"""三处 AI 反馈共用的用量显示。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from ...integrations.ai.protocol import usage_text
from ..palette import P


class TokenUsageLabel(QLabel):
    """只显示本次请求用量的标签，接口未返回时明确显示未知。"""
    def __init__(self, parent=None):
        """建立单次请求 token 用量组件的依赖与初始状态。"""
        super().__init__(parent)
        self.setAccessibleName('本次 AI token 用量')
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setToolTip('接口报告的本次用量；思考 token 包含在输出中，不额外加入总计。')
        self.hide()
        self.apply_theme()

    def begin_request(self):
        """清除上次用量并显示等待状态，避免把旧 token 当成本次费用。"""
        self.setText('本次 token · 等待接口返回用量')
        self.show()

    def set_usage(self, usage):
        """按实际 TokenUsage 刷新文字，不估算缺失计数。"""
        self.setText(usage_text(usage))
        self.show()

    def apply_theme(self):
        """将当前主题颜色、字号和图标同步到单次请求 token 用量，保持现有业务状态。"""
        self.setStyleSheet(f'background:transparent;color:{P.paper_muted};font-size:13px;')
