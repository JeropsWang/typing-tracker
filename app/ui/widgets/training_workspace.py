"""训练纸张的呈现组件：输入、范文选择与指标，不读数据库、不计分。

页面通过语义信号响应操作，再写回范文和指标；尺寸由 StageLayout 决定。
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QTextBrowser, QVBoxLayout, QWidget,
)
from .design import PaperField, PaperSurface, paper_texture
from .responsive import StageLayout
from ..palette import P


class PracticeInput(QPlainTextEdit):
    """手动练习输入：禁止粘贴，IME 上屏仍由 Qt 正常处理。"""
    paste_blocked = Signal()

    def insertFromMimeData(self, source):
        self.paste_blocked.emit()


class TrainingWorkspace(PaperSurface):
    source_changed = Signal(int)
    restart_requested = Signal()
    next_requested = Signal()
    start_requested = Signal()
    input_changed = Signal()
    paste_blocked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage = None
        self.content = QVBoxLayout(self)
        self.content.setSpacing(0)
        self.source_combo = QComboBox()
        self.source_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source_combo.view().setTextElideMode(Qt.ElideRight)
        self.source_combo.currentTextChanged.connect(self.source_combo.setToolTip)
        self.source_combo.currentIndexChanged.connect(self.source_changed.emit)
        self.source_field = PaperField('练习范文', self.source_combo)
        self.restart_button = QPushButton('重新开始')
        self.restart_button.setProperty('buttonRole', 'secondary')
        self.restart_button.setEnabled(False)
        self.restart_button.clicked.connect(self.restart_requested.emit)
        self.source_row = QHBoxLayout()
        self.source_row.setContentsMargins(0, 0, 0, 0)
        self.source_row.addWidget(self.source_field)
        self.source_row.addWidget(self.restart_button, 0, Qt.AlignBottom)
        self.source_row.addStretch(1)
        self.content.addLayout(self.source_row)
        self.source_gap = QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.content.addSpacerItem(self.source_gap)

        reference_block = QWidget()
        reference_layout = QVBoxLayout(reference_block)
        reference_layout.setContentsMargins(0, 0, 0, 0)
        reference_layout.setSpacing(6)
        reference_header = QHBoxLayout()
        reference_header.setContentsMargins(0, 0, 0, 0)
        self.reference_hint = QLabel('照着范文输入，跟上自己的节奏')
        self.reference_hint.setProperty('textRole', 'paperMuted')
        reference_header.addWidget(self.reference_hint)
        reference_header.addStretch(1)
        self.next_button = QPushButton('换一篇')
        self.next_button.setProperty('buttonRole', 'quiet')
        self.next_button.setAccessibleName('换一篇范文')
        self.next_button.clicked.connect(self.next_requested.emit)
        reference_header.addWidget(self.next_button)
        reference_layout.addLayout(reference_header)
        self.reference = QTextBrowser()
        self.reference.setAccessibleName('练习范文')
        self.reference.setOpenExternalLinks(False)
        self.reference.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.reference.setFrameShape(QFrame.NoFrame)
        reference_layout.addWidget(self.reference)
        self.content.addWidget(reference_block)
        self.reference_gap = QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.content.addSpacerItem(self.reference_gap)

        self.input = PracticeInput()
        self.input.setPlaceholderText('点「开始练习」后，在这里输入。')
        self.input.setEnabled(False)
        self.input.textChanged.connect(self.input_changed.emit)
        self.input.paste_blocked.connect(self.paste_blocked.emit)
        self.content.addWidget(PaperField('你的输入', self.input))
        self.content.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.metrics = QWidget()
        self.metrics.setObjectName('practiceMetrics')
        self.metrics.setStyleSheet('QWidget#practiceMetrics {background:rgba(181,164,191,45); border-radius:18px;}')
        self.metrics_layout = QHBoxLayout(self.metrics)
        self.metrics_layout.setContentsMargins(12, 0, 12, 0)
        self.metrics_layout.setSpacing(0)
        self.metric_labels = []
        for title, value in [('用时', '用时 —'), ('速度', '速度 — tw/分'),
                             ('正确率', '正确率 —'), ('进度', '进度 0%')]:
            label = QLabel(value)
            label.setProperty('textRole', 'paperField')
            label.setMinimumHeight(36)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            label.setAccessibleName(title)
            self.metrics_layout.addWidget(label, 1)
            self.metric_labels.append(label)
        self.metric_labels[2].setToolTip('与当前范文逐字对比，区别于首页的删除按键估算。')
        self.actions.addWidget(self.metrics, 1)
        self.start_button = QPushButton('开始练习 →')
        self.start_button.setProperty('buttonRole', 'primary')
        self.start_button.setAccessibleName('开始练习')
        self.start_button.clicked.connect(self.start_requested.emit)
        self.actions.addWidget(self.start_button, 0, Qt.AlignBottom)
        self.content.addLayout(self.actions)
        self.apply_layout(StageLayout(900, 526), force=True)

    def apply_layout(self, stage, *, force=False):
        if self._stage == stage and not force:
            return
        self._stage = stage
        pad = stage.paper_padding
        self.content.setContentsMargins(pad, stage.blend(6, 14), pad, stage.blend(14, 22))
        self.setFixedWidth(stage.content_width)
        self.input.setFixedHeight(stage.input_height)
        self.reference.setMinimumHeight(stage.reference_height)
        self.reference.setMaximumHeight(stage.blend(57, 220))
        self.start_button.setFixedSize(stage.blend(164, 192), stage.blend(44, 52))
        self.restart_button.setFixedSize(stage.blend(150, 186), 44)
        self.source_combo.setFixedHeight(stage.blend(42, 46))
        self.source_row.setSpacing(stage.blend(12, 16))
        available = stage.content_width - 2 * pad
        source_width = min(round(available * .70), available - self.restart_button.width() - self.source_row.spacing())
        self.source_field.setFixedWidth(max(160, source_width))
        self.source_combo.setMaximumWidth(self.source_field.width())
        self.actions.setSpacing(stage.blend(18, 24))
        self.source_gap.changeSize(0, stage.blend(4, 12))
        self.reference_gap.changeSize(0, stage.blend(4, 12))
        self.content.invalidate()
        self.content.activate()
        height = max(stage.training_height, self.content.minimumSize().height())
        self.setFixedHeight(height)

    def paintEvent(self, event):
        """玫瑰灰背纸斜向露边；交互内容保持水平，不受装饰旋转影响。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        front = QRectF(self.rect()).adjusted(0, 0, -8, -9)
        backing = QPolygonF([
            QPointF(9, 9), QPointF(front.right() + 7, 2),
            QPointF(self.width() - 1, self.height() - 6),
            QPointF(17, self.height() - 1),
        ])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#BFA7B2'))
        painter.drawPolygon(backing)
        if not paper_texture().draw(painter, front):
            painter.fillPath(self._paper_path(front), QColor(P.paper))
        painter.setClipPath(self._paper_path(front))
        wash = QLinearGradient(front.topLeft(), front.bottomRight())
        wash.setColorAt(0, QColor(243, 231, 215, 12))
        wash.setColorAt(.7, QColor(209, 194, 218, 20))
        wash.setColorAt(1, QColor(195, 154, 169, 58))
        painter.fillRect(front, wash)
        painter.end()
