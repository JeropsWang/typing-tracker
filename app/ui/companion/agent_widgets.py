"""Reusable input, scrolling dialogue card and report detail for companion tools."""
from datetime import datetime
from html import escape
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QDesktopServices, QRegion, QTextCursor, QTextBlockFormat,
                          QPainter, QPainterPath, QPainterPathStroker, QPen, QColor)
from PySide6.QtWidgets import (QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QToolButton, QPlainTextEdit, QTextBrowser, QWidget)
from ..assets.icons import icon
from .agent_visuals import AgentBubble, agent_style, colors
from .agent_controls import OrbitButton, AgentJourney


def label(text, *, heading=False, muted=False):
    """建立纯文本、自动换行的共用标签，并设置标题或辅助文字颜色角色。"""
    item = QLabel(text)
    item.setTextFormat(Qt.PlainText)
    item.setWordWrap(True)
    item.setProperty('agentHeading', heading)
    item.setProperty('agentMuted', muted)
    return item


class AgentActions(QWidget):
    """Qt 主线程的浮动轮盘；仅按钮和轨道命中，中心保留桌宠摸头与拖动。"""
    search_requested = Signal()
    news_requested = Signal()
    settings_requested = Signal()

    def __init__(self):
        """创建搜索及后续占位入口，设置透明命中遮罩和搜索信号。"""
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName('companionAgentActions')
        self.setStyleSheet(agent_style())
        self.setFixedSize(286, 154)
        self.buttons = []
        for caption, title, name, tone, available, point in (
                ('占卜', '占卜 · 第三期筹备中', 'agent-oracle', 'lavender', False, (8, 80)),
                ('来信', '查看来信与定时配置', 'agent-report', 'coral', True, (102, 6)),
                ('搜索', '联网搜索', 'agent-search', 'blue', True, (206, 68))):
            button = OrbitButton(caption, name, tone, self)
            side = 72 if available else 60 if caption == '来信' else 56
            button.setFixedSize(side, side)
            button.setAccessibleName(title)
            button.setToolTip(title)
            button.setEnabled(available)
            button.setCursor(Qt.PointingHandCursor if available else Qt.ArrowCursor)
            button.move(*point)
            self.buttons.append(button)
        self.buttons[-1].clicked.connect(self.search_requested)
        self.buttons[1].clicked.connect(self.news_requested)
        # A transparent centre must remain clickable for petting and dragging.
        region = QRegion()
        for button in self.buttons:
            region |= QRegion(button.geometry(), QRegion.Ellipse)
        self._orbit = QPainterPath()
        self._orbit.moveTo(36, 108)
        self._orbit.cubicTo(70, 8, 212, 6, 242, 104)
        stroke = QPainterPathStroker()
        stroke.setWidth(3)
        region |= QRegion(stroke.createStroke(self._orbit).toFillPolygon().toPolygon())
        self.setMask(region)

    def paintEvent(self, event):
        """绘制呼应圆形入口的轨道连接线，不绘制额外不透明底板。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(colors().line), 1.5, Qt.DashLine))
        painter.drawPath(self._orbit)

    def set_motion_enabled(self, enabled):
        """把减弱动态效果传给全部入口，关闭时停止现有悬停动画。"""
        for button in self.buttons:
            button.motion = bool(enabled)
            if not enabled:
                button._animation.stop()

    def set_busy(self, busy):
        """切换搜索入口的思考标题和提示；点击仍用于查看当前任务。"""
        button = self.buttons[-1]
        button.caption = '思考' if busy else '搜索'
        button.setToolTip('查看正在整理的情报' if busy else '联网搜索')
        button.update()


class AgentInputDialog(AgentBubble):
    """可复用的话题输入浮层；限制字符数，以信号交出主动输入，不请求网络。"""
    submitted = Signal(str)

    def __init__(self, *, title='今天，想一起探索什么？', limit=200):
        """创建话题、计数、校验反馈与确认/取消控件，确认时发布原始话题。"""
        super().__init__()
        self.setWindowTitle('Sariana · 联网搜索')
        self.setStyleSheet(agent_style())
        self.resize(420, 286)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 32, 36, 40)
        layout.setSpacing(10)
        eyebrow = label('SARIANA / 一起去看看')
        eyebrow.setProperty('agentEyebrow', True)
        layout.addWidget(eyebrow)
        layout.addWidget(label(title, heading=True))
        self.topic = QLineEdit()
        self.topic.setMaxLength(limit)
        self.topic.setPlaceholderText('最近的天文发现，或你的一个小好奇…')
        self.topic.setAccessibleName('搜索话题')
        layout.addWidget(self.topic)
        hint = QHBoxLayout()
        hint.addWidget(label('你来提问，我把线索带回来。', muted=True), 1)
        self.count = label(f'0 / {limit}', muted=True)
        self.count.setWordWrap(False)
        self.topic.textChanged.connect(lambda text: self.count.setText(f'{len(text)} / {limit}'))
        hint.addWidget(self.count)
        layout.addLayout(hint)
        self.feedback = label('', muted=True)
        self.feedback.setMaximumHeight(40)
        layout.addWidget(self.feedback)
        row = QHBoxLayout()
        self.cancel = QPushButton('稍后再聊')
        self.cancel.setProperty('agentQuiet', True)
        self.cancel.clicked.connect(self.hide)
        self.submit = QPushButton('一起找找  →')
        self.submit.setProperty('agentPrimary', True)
        self.submit.setCursor(Qt.PointingHandCursor)
        self.submit.setDefault(True)
        self.submit.clicked.connect(lambda: self.submitted.emit(self.topic.text()))
        row.addWidget(self.cancel)
        row.addStretch()
        row.addWidget(self.submit)
        layout.addLayout(row)


class AgentDialogueCard(AgentBubble):
    """只读搜索短卡片，显示真实进度/草稿/报告并发出取消、详情与重试信号。"""
    detail_requested = Signal()
    config_requested = Signal()
    cancel_requested = Signal()
    search_requested = Signal()

    def __init__(self):
        """创建被动显示的滚动正文卡片及阶段、详情、关闭控件。"""
        super().__init__(passive=True)
        self.setWindowTitle('Sariana · 小小情报')
        self.setStyleSheet(agent_style())
        self.resize(408, 344)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 30, 36, 40)
        layout.setSpacing(8)
        top = QHBoxLayout()
        eyebrow = label('SARIANA / 小小情报')
        eyebrow.setProperty('agentEyebrow', True)
        top.addWidget(eyebrow, 1)
        self.badge = label('探索中')
        self.badge.setProperty('agentBadge', True)
        self.badge.setWordWrap(False)
        top.addWidget(self.badge)
        close = QToolButton()
        close.setProperty('agentQuiet', True)
        close.setFixedSize(28, 28)
        close.setIcon(icon('close', colors().muted, 14))
        close.setAccessibleName('收起卡片')
        close.setToolTip('收起卡片')
        close.clicked.connect(self._dismiss)
        top.addWidget(close)
        layout.addLayout(top)
        self.title = label('小小情报', heading=True)
        layout.addWidget(self.title)
        self.status = label('', muted=True)
        self.status.setMaximumHeight(38)
        layout.addWidget(self.status)
        self.journey = AgentJourney()
        layout.addWidget(self.journey)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setAccessibleName('桌宠搜索摘要，可滚动阅读')
        layout.addWidget(self.body, 1)
        self.hint = label('滚轮翻阅 · 我会把来源一起带回来', muted=True)
        layout.addWidget(self.hint)
        footer = QHBoxLayout()
        self.detail = QPushButton('打开这封手信  ↗')
        self.detail.setProperty('agentPrimary', True)
        self.detail.setCursor(Qt.PointingHandCursor)
        self.detail.clicked.connect(lambda: (self.config_requested if self._error else self.detail_requested).emit())
        self.action = QPushButton('取消')
        self.action.setProperty('agentQuiet', True)
        self.action.clicked.connect(self._action)
        footer.addWidget(self.detail, 1)
        footer.addWidget(self.action)
        layout.addLayout(footer)
        self.busy = False
        self._error = False

    def _body_text(self, text, *, preserve=False):
        """替换纯文本正文并设置行距；流式更新时保留向上阅读位置。"""
        bar = self.body.verticalScrollBar()
        at_bottom, position = bar.value() == bar.maximum(), bar.value()
        self.body.setPlainText(text)
        cursor = QTextCursor(self.body.document())
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        block.setLineHeight(145, QTextBlockFormat.ProportionalHeight.value)
        cursor.mergeBlockFormat(block)
        bar.setValue(bar.maximum() if preserve and at_bottom else position if preserve else 0)

    def show_progress(self, text, stage='searching'):
        """切换到真实任务阶段和取消操作，暂不开放尚不存在的报告详情。"""
        self._error = False
        self.detail.setText('正在准备手信…')
        self.busy = True
        self.title.setText('让我找找看…' if stage == 'searching' else '把线索串成小星星…')
        self.status.setText('我在核对原文，稍等一下。' if stage == 'reading' else '好奇心已出发 · 随时可以取消')
        self.badge.setText('读一读' if stage == 'reading' else '思考中' if stage == 'summarizing' else '出发啦')
        self.journey.show()
        self.journey.set_stage({'searching': 0, 'reading': 1, 'summarizing': 2}.get(stage, 0), True)
        self._body_text(text)
        self.detail.setEnabled(False)
        self.action.setText('取消')
        self.hint.setText('滚轮翻阅 · 我会把来源一起带回来')

    def show_report(self, report):
        """展示最终只读摘要、来源数量与警告，并停止进度指示。"""
        self._error = False
        self.detail.setText('打开这封手信  ↗')
        self.busy = False
        self.journey.set_stage(2, False)
        self.journey.hide()
        self.title.setText('找到啦，给你看看' if not report.warning else '先带回这些线索')
        self.badge.setText(f'{len(report.sources)} 个来源')
        self.status.setText(report.topic)
        self._body_text(report.summary + (('\n\n' + report.warning) if report.warning else ''))
        self.detail.setEnabled(True)
        self.action.setText('再问一个')
        self.hint.setText('滚轮翻阅 · 点击手信核对原始来源')

    def show_partial(self, text):
        """展示模型可见草稿，保留用户滚动位置；草稿不等于已完成报告。"""
        self.title.setText('手信正在写给你…')
        self.status.setText('正文一点点送达 · 随时可以取消')
        self.badge.setText('整理中')
        self.journey.set_stage(2, True)
        self._body_text(text, preserve=True)

    def show_error(self, message):
        """展示错误并开放配置/重试入口，不把失败资料标成成功。"""
        self._error = True
        self.busy = False
        self.journey.set_stage(0, False)
        self.journey.hide()
        self.title.setText('线索暂时打了个结')
        self.badge.setText('稍等一下')
        self.status.setText('换个问法，或检查一下连接。')
        self._body_text(message)
        self.detail.setText('检查配置')
        self.detail.setEnabled(True)
        self.action.setText('重试')
        self.hint.setText('你的小好奇还在，可以再试一次。')

    def _action(self):
        """忙碌时发布取消信号，空闲时发布重新搜索信号。"""
        (self.cancel_requested if self.busy else self.search_requested).emit()

    def _dismiss(self):
        """收起卡片；若仍有任务先通知控制器取消。"""
        if self.busy:
            self.cancel_requested.emit()
        self.hide()

    def reject(self):
        """让 Escape/对话框拒绝操作复用收起与取消语义。"""
        self._dismiss()


class AgentReportDialog(QDialog):
    """只读报告详情窗口，对模型正文做转义，只有真实来源链接可打开。"""
    def __init__(self):
        """创建正文/来源阅读区与关闭操作，禁用富文本自动打开链接。"""
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('Sariana · 搜索详情')
        self.setStyleSheet(agent_style())
        self.resize(660, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        eyebrow = label('SARIANA / 给你的探索手信')
        eyebrow.setProperty('agentEyebrow', True)
        layout.addWidget(eyebrow)
        self.title = label('', heading=True)
        layout.addWidget(self.title)
        self.meta = label('', muted=True)
        layout.addWidget(self.meta)
        panel = QFrame()
        panel.setProperty('agentPanel', True)
        paper = QVBoxLayout(panel)
        paper.setContentsMargins(20, 16, 20, 16)
        self.body = QTextBrowser()
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(self._open_source)
        self.body.setAccessibleName('完整搜索报告及原始来源')
        paper.addWidget(self.body)
        layout.addWidget(panel, 1)
        close = QPushButton('读完啦')
        close.setProperty('agentPrimary', True)
        close.clicked.connect(self.hide)
        layout.addWidget(close)
        self._urls = set()

    def set_report(self, report):
        """转义报告文字并生成来源编号、摘录和本地时间展示，更新链接白名单。"""
        self.title.setText(report.topic)
        self._urls = {s.url for s in report.sources}
        def paragraph(text):
            """转义用户/模型/网页文字为保留换行的安全 HTML 段落。"""
            return '<p style="white-space:pre-wrap;line-height:1.6">' + escape(text) + '</p>'
        fetched = datetime.fromisoformat(report.fetched_at).astimezone().strftime('%Y-%m-%d %H:%M')
        self.meta.setText(f'{len(report.sources)} 个原始来源 / {fetched}')
        html = paragraph(report.summary)
        if report.warning:
            html += paragraph(report.warning)
        html += f'<h3 style="color:{colors().accent}">沿着这些线索，继续看看</h3>'
        html += paragraph('模型根据搜索资料整理，可点击来源核对原文。')
        for i, source in enumerate(report.sources, 1):
            html += f'<p><a style="color:{colors().accent}" href="{escape(source.url, quote=True)}">[{i}] {escape(source.title)}</a></p>'
            html += paragraph(source.snippet)
        self.body.setHtml(html)

    def _open_source(self, url):
        """只打开当前报告来源白名单中的 URL，拒绝模型自行构造的链接。"""
        if url.toString() in self._urls:
            QDesktopServices.openUrl(url)
