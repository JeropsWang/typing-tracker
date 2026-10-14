"""AI 范文的纸张工作区。仅管理呈现与输入，资格和生成由页面服务处理。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPolygonF
from PySide6.QtWidgets import (
    QBoxLayout, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..palette import P
from .design import PaperSurface, asset_path, paper_texture
from .responsive import StageLayout
from .ai_usage import TokenUsageLabel


class _WashPaper(PaperSurface):
    """保留纸纹，以薄色罩染区分两张纸，不给业务控件加滤镜。"""

    def __init__(self, rose=False, parent=None):
        """建立AI 训练话题输入组件的依赖与初始状态。"""
        self.rose = rose
        super().__init__(parent)

    def paintEvent(self, event):
        """在 Qt 主线程按当前状态绘制AI 训练话题输入的可见内容，不在绘制回调执行业务提交。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0, 0, -3, -4)
        path = self._paper_path(rect)
        painter.setClipPath(path)
        if not paper_texture().draw(painter, rect):
            painter.fillRect(rect, QColor(P.paper))
        wash = QLinearGradient(rect.topLeft(), rect.bottomRight())
        wash.setColorAt(0, QColor('#DFC9CF' if self.rose else '#F5ECDE'))
        wash.setColorAt(.6, QColor('#DCD2E2' if self.rose else '#EEE4D3'))
        wash.setColorAt(1, QColor('#D6BBC5' if self.rose else '#E3D6CC'))
        painter.setOpacity(.68 if self.rose else .22)
        painter.fillPath(path, wash)
        painter.end()


class _PaperPair(QWidget):
    """纸张背衬和一段胶带；装饰不拦截输入。"""

    def __init__(self, parent=None):
        """建立AI 训练话题输入组件的依赖与初始状态。"""
        super().__init__(parent)
        self.left_paper = _WashPaper(parent=self)
        self.right_paper = _WashPaper(rose=True, parent=self)
        self.row = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.row.setContentsMargins(12, 14, 8, 12)
        self.row.setSpacing(24)
        self.row.addWidget(self.left_paper, 7, Qt.AlignTop)
        right_wrap = QWidget(self)
        self.right_layout = QVBoxLayout(right_wrap)
        self.right_layout.setContentsMargins(0, 58, 0, 0)
        self.right_layout.addWidget(self.right_paper)
        self.right_layout.addStretch(1)
        self.row.addWidget(right_wrap, 3)

    def set_compact(self, compact):
        """更新AI 训练话题输入的紧凑布局、间距和尺寸约束。"""
        self.set_stage_layout(StageLayout(900, 526) if compact else StageLayout(1440, 874))

    def set_stage_layout(self, stage):
        """将响应式模型同步给装饰纸面尺寸，保留原表单控件。"""
        self.row.setSpacing(stage.blend(12, 24))
        self.right_layout.setContentsMargins(0, stage.blend(26, 58), 0, 0)
        self.row.setContentsMargins(stage.blend(8, 12), stage.blend(10, 14),
                                   stage.blend(4, 8), stage.blend(8, 12))
        self.update()

    def paintEvent(self, event):
        """在 Qt 主线程按当前状态绘制AI 训练话题输入的可见内容，不在绘制回调执行业务提交。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        paper = QRectF(self.left_paper.geometry())
        if paper.isEmpty():
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#A9828F'))
        backing = QPolygonF([
            QPointF(paper.left() - 8, paper.top() + 12),
            QPointF(paper.right() - 4, paper.top() - 6),
            QPointF(paper.right() + 7, paper.bottom() - 8),
            QPointF(paper.left() + 4, paper.bottom() + 7),
        ])
        painter.drawPolygon(backing)
        painter.setBrush(QColor('#C6AC89'))
        painter.setOpacity(.78)
        painter.drawPolygon(QPolygonF([
            QPointF(paper.left() + 35, paper.top() - 7),
            QPointF(paper.left() + 133, paper.top() - 3),
            QPointF(paper.left() + 131, paper.top() + 10),
            QPointF(paper.left() + 32, paper.top() + 6),
        ]))
        painter.end()


class AIPassageComposer(QWidget):
    """AI 训练主题/语言草稿与生成状态面板，动作通过信号交业务页面处理。"""
    generate_requested = Signal()
    back_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        """建立AI 训练话题输入组件的依赖与初始状态。"""
        super().__init__(parent)
        self.setObjectName('aiPassageComposer')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._compact = False
        self._stage = None
        self._status_kind = ''
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.back_button = QPushButton('‹  返回训练')
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)
        outer.addWidget(self.back_button, 0, Qt.AlignLeft)
        self._papers = _PaperPair(self)
        self.topic_paper = self._papers.left_paper
        self.options_paper = self._papers.right_paper
        outer.addWidget(self._papers)

        self._topic_layout = QVBoxLayout(self.topic_paper)
        self._topic_layout.setSpacing(12)
        self.eyebrow = QLabel('AI 范文  /  灵感手札')
        self.heading = QLabel('想练习什么？')
        self._topic_layout.addWidget(self.eyebrow)
        self._topic_layout.addWidget(self.heading)
        self.topic_edit = QLineEdit()
        self.topic_edit.setAccessibleName('练习主题')
        self.topic_edit.setPlaceholderText('例如：雨后的小城，或今晚的星空')
        self.topic_edit.returnPressed.connect(self.generate_requested.emit)
        self._topic_layout.addWidget(self.topic_edit)
        self.example_buttons = []
        examples = QHBoxLayout()
        examples.setSpacing(8)
        for topic in ('星空', '雨后小城', '日常碎碎念'):
            button = QPushButton(topic)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName('使用主题：' + topic)
            button.clicked.connect(lambda checked=False, text=topic: self._choose_topic(text))
            examples.addWidget(button)
            self.example_buttons.append(button)
        examples.addStretch(1)
        self._topic_layout.addLayout(examples)
        self.note = QLabel('写一点喜欢的故事。生成后会加入范文库。')
        self.note.setWordWrap(True)
        self._topic_layout.addWidget(self.note)
        self._topic_layout.addStretch(1)
        self.access_label = QLabel('')
        self.access_label.setWordWrap(True)
        self.access_label.setTextFormat(Qt.PlainText)
        self._topic_layout.addWidget(self.access_label)
        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._topic_layout.addWidget(self.status_label)
        self.usage_label = TokenUsageLabel()
        self._topic_layout.addWidget(self.usage_label)

        self._options_layout = QVBoxLayout(self.options_paper)
        self._options_layout.setSpacing(12)
        self.options_heading = QLabel('生成选项')
        self._options_layout.addWidget(self.options_heading)
        self.language_label = QLabel('范文语言')
        self._options_layout.addWidget(self.language_label)
        self.language_combo = QComboBox()
        self.language_combo.setAccessibleName('范文语言')
        self.language_combo.addItem('中文', 'cn')
        self.language_combo.addItem('English', 'en')
        self._options_layout.addWidget(self.language_combo)
        self.settings_button = QPushButton('AI 配置  ↗')
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self._options_layout.addWidget(self.settings_button, 0, Qt.AlignLeft)
        self._options_layout.addStretch(1)
        self.generate_button = QPushButton('生成范文  →')
        self.generate_button.setCursor(Qt.PointingHandCursor)
        self.generate_button.clicked.connect(self.generate_requested.emit)
        self._options_layout.addWidget(self.generate_button)
        self.topic_edit.installEventFilter(self)
        self.set_compact(False)
        self.apply_theme()

    def _choose_topic(self, topic):
        """输入可用时用示例主题预填并聚焦，不自动生成。"""
        if self.topic_edit.isEnabled():
            self.topic_edit.setText(topic)
            self.topic_edit.setFocus()

    def _sync_examples(self, enabled):
        """同步示例按钮资格，生成期间不能改动请求主题。"""
        for button in self.example_buttons:
            button.setEnabled(enabled)

    def set_status(self, text, kind=''):
        """设置生成状态文字和状态类别，再更新对比色。"""
        self._status_kind = kind
        self.status_label.setText(text)
        self._style_status()

    def _style_status(self):
        """按成功/错误/普通状态设置反馈颜色。"""
        color = {'error': P.danger_on_paper, 'success': P.success_on_paper}.get(self._status_kind, P.paper_text)
        self.status_label.setStyleSheet(f'background:transparent; color:{color}; font-size:14px;')

    def eventFilter(self, obj, event):
        """主题输入启用状态变化时同步示例操作，不绕过原事件处理。"""
        if obj is self.topic_edit and event.type() == QEvent.EnabledChange:
            self._sync_examples(self.topic_edit.isEnabled())
        return super().eventFilter(obj, event)

    def set_compact(self, compact):
        """更新AI 训练话题输入的紧凑布局、间距和尺寸约束。"""
        self._compact = bool(compact)
        stage = self._stage or (StageLayout(900, 526) if compact else StageLayout(1440, 874))
        self._papers.set_stage_layout(stage)
        self._topic_layout.setContentsMargins(stage.blend(20, 32), stage.blend(16, 28),
                                             stage.blend(20, 32), stage.blend(14, 26))
        self._topic_layout.setSpacing(stage.blend(6, 12))
        self._options_layout.setContentsMargins(stage.blend(18, 28), stage.blend(18, 30),
                                               stage.blend(18, 28), stage.blend(18, 28))
        self._options_layout.setSpacing(stage.blend(8, 14))
        extra = max(0, stage.height - 874)
        self._input_height = stage.blend(60, 94) + min(80, round(extra * .18))
        self.topic_paper.setMinimumHeight(stage.blend(276, 416) + min(140, round(extra * .28)))
        self.options_paper.setMinimumHeight(stage.blend(244, 344) + min(110, round(extra * .24)))
        self.back_button.setFixedHeight(44)
        self.topic_edit.setFixedHeight(self._input_height)
        self._language_height = stage.blend(44, 52)
        self.language_combo.setFixedHeight(self._language_height)
        self.generate_button.setFixedHeight(stage.blend(48, 62))
        self.settings_button.setFixedHeight(44)
        for button in self.example_buttons:
            button.setFixedHeight(44)
        self.apply_theme()
        self.updateGeometry()

    def set_stage_layout(self, stage):
        """响应式模型改变时同步开放度/紧凑布局，不清除话题草稿。"""
        if self._stage != stage:
            self._stage = stage
            self.set_compact(stage.compact)

    def apply_theme(self):
        """将当前主题颜色、字号和图标同步到AI 训练话题输入，保持现有业务状态。"""
        self.usage_label.apply_theme()
        ink = P.paper_text
        muted = P.paper_muted
        stage = self._stage or (StageLayout(900, 526) if self._compact else StageLayout(1440, 874))
        self.setStyleSheet('QWidget#aiPassageComposer {background:transparent;}')
        for label in (self.eyebrow, self.language_label, self.note, self.access_label):
            label.setStyleSheet(f'background:transparent; color:{muted}; font-size:14px;')
        self.heading.setStyleSheet(
            f'background:transparent; color:{ink}; font-family:"KaiTi"; '
            f'font-size:{stage.blend(30, 42)}px;')
        self.options_heading.setStyleSheet(
            f'background:transparent; color:{ink}; font-family:"KaiTi"; '
            f'font-size:{stage.blend(26, 32)}px;')
        self._style_status()
        input_content = self._input_height - 28
        self.topic_edit.setStyleSheet(
            f'QLineEdit {{background:{P.surface}; color:{P.surface_text}; '
            f'font-size:20px; padding:12px 16px; '
            f'min-height:{input_content}px; max-height:{input_content}px; '
            f'border:2px solid #B5A1BC; border-radius:12px; selection-background-color:#776181;}}'
            f'QLineEdit:focus {{border:2px solid {P.accent_rose};}}'
            f'QLineEdit:disabled {{color:{P.surface_muted}; border-color:#A89BAE;}}')
        self.language_combo.setStyleSheet(
            f'QComboBox {{background:rgba(255,250,244,170); color:{ink}; font-size:16px; '
            f'min-height:{self._language_height - 18}px; max-height:{self._language_height - 18}px; '
            f'padding:8px 12px; border:1px solid #9A859C; border-radius:7px;}}'
            f'QComboBox:focus {{border:2px solid {P.focus_on_paper};}}'
            'QComboBox::drop-down {border:none; width:26px;}'
            f'QComboBox::down-arrow {{image:url("{asset_path("nav", "chevron-ink.svg").as_posix()}"); width:12px; height:12px;}}'
            f'QComboBox QAbstractItemView {{background:{P.paper}; color:{ink}; selection-background-color:#C6ACBA; selection-color:{ink};}}')
        quiet = (
            f'QPushButton {{background:transparent; color:{muted}; border:none; '
            f'font-size:14px; padding:4px 8px; min-height:36px; max-height:36px; text-align:left;}}'
            f'QPushButton:hover {{color:{ink};}}'
            f'QPushButton:focus {{border:1px solid {P.focus_on_paper}; border-radius:6px;}}')
        self.settings_button.setStyleSheet(quiet)
        self.back_button.setStyleSheet(quiet.replace(muted, P.surface_text).replace(ink, P.surface_text))
        for button in self.example_buttons:
            button.setStyleSheet(
                f'QPushButton {{color:{ink}; background:#DFD3D5; border:none; '
                f'border-radius:18px; padding:4px 12px; min-height:36px; max-height:36px; font-size:14px;}}'
                f'QPushButton:hover {{background:#D2BED0;}}'
                f'QPushButton:focus {{border:2px solid {P.focus_on_paper};}}'
                f'QPushButton:disabled {{color:{muted}; background:#E3DAD4;}}')
        self.generate_button.setStyleSheet(
            'QPushButton {color:#FFF5EB; background:#87566D; border:none; '
            f'min-height:{32 if self._compact else 46}px; max-height:{32 if self._compact else 46}px; '
            'border-radius:20px; font-size:20px; padding:8px 12px;}'
            'QPushButton:hover {background:#75455D;}'
            'QPushButton:pressed {background:#65394F;}'
            f'QPushButton:focus {{border:2px solid {P.focus_on_paper};}}'
            'QPushButton:disabled {color:#4D3A4B; background:#C6ACBA;}')
        self._papers.update()
        self.topic_paper.update()
        self.options_paper.update()
