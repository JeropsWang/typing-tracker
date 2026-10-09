"""Short surreal AI output with asynchronous, invalidatable requests."""
import threading
import uuid
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser
from .design import PaperPage
from .ai_usage import TokenUsageLabel
from ..palette import P


class ChaosRequest(QObject):
    done = Signal(str, bool, str)

    def __init__(self, ai, topic, parent):
        super().__init__(parent)
        self.id = uuid.uuid4().hex
        self.service = ai.snapshot()
        self.topic = topic
        self.usage = None
        self._valid = True
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._valid = False

    def _run(self):
        ok, result = self.service.generate_chaos(self.topic)
        self.usage = self.service.last_usage
        if self._valid:
            try:
                self.done.emit(self.id, ok, result)
            except RuntimeError:
                pass


class ChaosPanel(PaperPage):
    settings_requested = Signal()

    def __init__(self, ai, parent=None):
        super().__init__(parent)
        self.ai = ai
        self.request = None
        title = QLabel('混乱模块 · 让脑洞放个假')
        title.setProperty('textRole', 'paperTitle')
        self.body.addWidget(title)
        intro = QLabel('让模型胡言乱语，越荒诞越好。每段最多 60 字，标点和空格也计入。')
        intro.setProperty('textRole', 'paperMuted')
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.topic = QLineEdit()
        self.topic.setMaxLength(80)
        self.topic.setPlaceholderText('可选灵感词：退休的月亮、会煮面的键盘……')
        self.topic.setAccessibleName('混乱短文灵感词')
        self.body.addWidget(self.topic)
        actions = QHBoxLayout()
        self.generate_button = QPushButton('放飞一次 →')
        self.generate_button.setProperty('buttonRole', 'primary')
        self.generate_button.setMinimumHeight(44)
        self.generate_button.clicked.connect(self.generate)
        settings = QPushButton('AI 配置 ›')
        settings.setProperty('buttonRole', 'quiet')
        settings.clicked.connect(self.settings_requested.emit)
        actions.addWidget(self.generate_button)
        actions.addWidget(settings)
        actions.addStretch()
        self.body.addLayout(actions)
        self.output = QTextBrowser()
        self.output.setAccessibleName('混乱短文正文')
        self.output.setOpenExternalLinks(False)
        self.output.setFixedHeight(230)
        self.body.addWidget(self.output)
        self.count = QLabel('正文 0 / 60 字')
        self.count.setProperty('textRole', 'paperField')
        self.body.addWidget(self.count, 0, Qt.AlignRight)
        self.usage_label = TokenUsageLabel()
        self.body.addWidget(self.usage_label)
        self.status = QLabel('复用设置中的 AI 服务，输入灵感词或直接放飞。')
        self.status.setProperty('textRole', 'paperMuted')
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.apply_theme()

    def generate(self):
        if self.request:
            return
        if self.ai is None or not self.ai.enabled():
            self.status.setText('AI 未启用，请打开 AI 配置连接模型。')
            return
        request = ChaosRequest(self.ai, self.topic.text().strip(), self)
        self.request = request
        request.done.connect(self._done)
        self.generate_button.setEnabled(False)
        self.topic.setEnabled(False)
        self.generate_button.setText('脑洞正在转弯…')
        self.status.setText('正在生成一段最多 60 字的胡言乱语。')
        self.usage_label.begin_request()
        request.start()

    def _done(self, request_id, ok, result):
        if self.request is None or self.request.id != request_id:
            return
        self.usage_label.set_usage(self.request.usage)
        request = self.request
        self.request = None
        self._idle()
        request.deleteLater()
        if ok:
            self.output.setPlainText(result)
            self.count.setText(f'正文 {len(result)} / 60 字')
            self.status.setText('脑洞已抵达。再放飞一次，看看会落在哪。')
        else:
            self.status.setText(result)

    def _idle(self):
        self.generate_button.setEnabled(True)
        self.topic.setEnabled(True)
        self.generate_button.setText('放飞一次 →')

    def hideEvent(self, event):
        if self.request:
            self.request.cancel()
            self.usage_label.set_usage(self.request.usage)
            self.request.deleteLater()
            self.request = None
            self._idle()
            self.status.setText('本次生成已取消。')
        super().hideEvent(event)

    def apply_theme(self):
        self.output.setStyleSheet(f'QTextBrowser {{background:transparent;color:{P.paper_text};border:none;padding:12px;font-size:24px;}}')
        self.usage_label.apply_theme()
        self.paper.update()
