"""三处 AI 反馈共用的用量显示。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from ...services.ai_protocol import usage_text
from ..palette import P


class TokenUsageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName('本次 AI token 用量')
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setToolTip('接口报告的本次用量；思考 token 包含在输出中，不额外加入总计。')
        self.hide()
        self.apply_theme()

    def begin_request(self):
        self.setText('本次 token · 等待接口返回用量')
        self.show()

    def set_usage(self, usage):
        self.setText(usage_text(usage))
        self.show()

    def apply_theme(self):
        self.setStyleSheet(f'background:transparent;color:{P.paper_muted};font-size:13px;')
