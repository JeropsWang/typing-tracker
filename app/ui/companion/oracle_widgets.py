"""Qt主线程的占卜纸张卡片和三段占比图；只展示已校验结果。"""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from .agent_visuals import AgentBubble, agent_style, colors
from .agent_widgets import label


class OracleChart(QWidget):
    """使用实际百分数绘制三段圆环，无结果时不显示虚构概率。"""
    def __init__(self, parent=None):
        """初始化空结果及紧凑固定图形区域。"""
        super().__init__(parent)
        self.result = None
        self.setFixedSize(116, 116)
        self.setAccessibleName('是、不确定、否的占比图')

    def paintEvent(self, event):
        """绘制已验证的三项扇段，中间保留纸面和中文结论。"""
        if self.result is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = colors()
        rect = QRectF(11, 11, 94, 94)
        start = 90 * 16
        for value, color in zip((self.result.yes, self.result.uncertain, self.result.no),
                                (c.accent, '#78adba', '#cf8e85')):
            painter.setPen(QPen(QColor(color), 12, Qt.SolidLine, Qt.FlatCap))
            span = round(value / 100 * 360 * 16)
            painter.drawArc(rect, start, -span)
            start -= span
        painter.setPen(QColor(c.ink))
        painter.drawText(self.rect(), Qt.AlignCenter, self.result.verdict)


class OracleCard(AgentBubble):
    """占卜结果和请求状态卡片，不接收未验证的模型正文或思考文本。"""
    cancel_requested = Signal()
    dismissed = Signal()

    def __init__(self):
        """组合原生标签、占比图、取消和收起按钮，保留键盘可达性。"""
        super().__init__()
        self.setWindowTitle('Sariana · 占卜')
        self.setStyleSheet(agent_style())
        self.resize(376, 300)
        self.result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 30, 32, 35)
        self.question = label('想问星星一个什么问题？', heading=True)
        layout.addWidget(self.question)
        row = QHBoxLayout()
        self.chart = OracleChart(self)
        row.addWidget(self.chart)
        self.percentages = label('')
        row.addWidget(self.percentages, 1)
        layout.addLayout(row)
        self.status = label('')
        layout.addWidget(self.status)
        layout.addWidget(label('娱乐性估计，仅供参考；不代表现实事件的真实发生概率。', muted=True))
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton('取消判断')
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.close_button = QPushButton('收起')
        self.close_button.clicked.connect(self.hide)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def hideEvent(self, event):
        """统一通知按钮、Escape 和系统关闭导致的收起，禁止迟到结果重弹。"""
        super().hideEvent(event)
        self.dismissed.emit()

    def show_status(self, text, *, busy=False):
        """新请求或失败时清除旧概率，避免旧结果被误认为当前判断。"""
        self.result = self.chart.result = None
        self.chart.update()
        self.percentages.clear()
        self.status.setText(text)
        self.cancel_button.setVisible(busy)

    def show_result(self, result):
        """仅显示业务层已校验的不可变概率，与文字标签提供同一数据。"""
        self.result = self.chart.result = result
        self.question.setText(result.question)
        self.percentages.setText(f'是  {result.yes}%\n不确定  {result.uncertain}%\n否  {result.no}%')
        self.status.setText('星星给出的回答：' + result.verdict)
        self.cancel_button.hide()
        self.chart.update()
