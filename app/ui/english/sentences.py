"""AI 语句组件：材料选择与跟打展示；网络、判分、存储在页面服务层。"""
import html
import re
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget
from ..widgets.training_workspace import PracticeInput
from ..widgets.ai_usage import TokenUsageLabel
from ..palette import P
from .typography import english_type


class SentencePanel(QWidget):
    """主动造句材料、句子训练输入和错误对齐的只读/信号展示面板。"""
    generate_requested = Signal()
    targets_requested = Signal()
    settings_requested = Signal()
    start_requested = Signal()
    finish_requested = Signal()
    material_changed = Signal()
    retry_requested = Signal()

    def __init__(self, parent=None):
        """创建目标词、主题、历史材料、句子输入和结果控件。"""
        super().__init__(parent)
        self._type = english_type('large')
        self._history = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        self.targets = QLabel()
        self.targets.setWordWrap(True)
        self.targets.setProperty('textRole', 'paperField')
        layout.addWidget(self.targets)
        row = QHBoxLayout()
        self.topic = QLineEdit()
        self.topic.setMaxLength(80)
        self.topic.setPlaceholderText('句子主题，如校园、旅行、星空')
        self.topic.setAccessibleName('AI 语句主题')
        self.generate_button = QPushButton('让词语相遇 →')
        self.generate_button.setProperty('buttonRole', 'primary')
        self.generate_button.clicked.connect(self.generate_requested.emit)
        row.addWidget(self.topic, 1)
        row.addWidget(self.generate_button)
        layout.addLayout(row)
        links = QHBoxLayout()
        self.shuffle_button = QPushButton('换一组词')
        settings = QPushButton('AI 配置 ›')
        for button in (self.shuffle_button, settings):
            button.setProperty('buttonRole', 'quiet')
            links.addWidget(button)
        links.addStretch()
        self.shuffle_button.clicked.connect(self.targets_requested.emit)
        settings.clicked.connect(self.settings_requested.emit)
        layout.addLayout(links)
        choices = QHBoxLayout()
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(160)
        self.history_combo.setAccessibleName('本机语句材料')
        self.sentence_combo = QComboBox()
        self.sentence_combo.setAccessibleName('选择跟打句子')
        self.history_combo.currentIndexChanged.connect(self._select_pack)
        self.sentence_combo.currentIndexChanged.connect(self._select_sentence)
        choices.addWidget(self.history_combo, 2)
        choices.addWidget(self.sentence_combo, 1)
        layout.addLayout(choices)
        self.reference = QTextBrowser()
        self.reference.setFixedHeight(82)
        self.reference.setAccessibleName('英文跟打原句')
        layout.addWidget(self.reference)
        self.translation = QTextBrowser()
        self.translation.setAccessibleName('语句中文解释')
        self.translation.setFixedHeight(50)
        layout.addWidget(self.translation)
        self.input = PracticeInput()
        self.input.setFixedHeight(86)
        self.input.setPlaceholderText('点「开始跟打」，手动输入上面的英文句子。')
        self.input.setEnabled(False)
        self.input.setAccessibleName('英文语句跟打')
        self.input.paste_blocked.connect(lambda: self.status.setText('这段练习需要手动输入。'))
        layout.addWidget(self.input)
        actions = QHBoxLayout()
        self.start_button = QPushButton('开始跟打 →')
        self.finish_button = QPushButton('完成并记录')
        self.start_button.setProperty('buttonRole', 'primary')
        self.start_button.clicked.connect(self.start_requested.emit)
        self.finish_button.clicked.connect(self.finish_requested.emit)
        self.finish_button.setEnabled(False)
        actions.addWidget(self.start_button)
        actions.addWidget(self.finish_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.usage_label = TokenUsageLabel()
        layout.addWidget(self.usage_label)
        rules = QLabel('单词正确率：忽略大小写、空白与句间标点；错词、漏词、多词分别扣分。')
        rules.setWordWrap(True)
        rules.setProperty('textRole', 'paperField')
        rules.setToolTip('按单词编辑距离对齐，正确率 = 1 − 错误词数 / 较长句子的词数。词内撇号和连字符仍属于拼写。')
        layout.addWidget(rules)
        self.status = QLabel('生成后的材料会保留在本机，可随时再次跟打。')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(40)
        layout.addWidget(self.status)
        self.errors = QLabel()
        self.errors.setTextFormat(Qt.RichText)
        self.errors.setWordWrap(True)
        self.errors.hide()
        layout.addWidget(self.errors)
        self.retry_button = QPushButton('再练这一句 →')
        self.retry_button.clicked.connect(self.retry_requested.emit)
        self.retry_button.hide()
        layout.addWidget(self.retry_button, 0)
        layout.addStretch()
        self.apply_theme()

    def set_history(self, packs):
        """刷新已保存材料列表，填充时屏蔽信号再统一选中材料。"""
        self._history = packs
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        for pack in packs:
            self.history_combo.addItem(f"{pack['topic'] or '自由主题'} · {pack['created_at'][:10]}", pack['id'])
        if not packs:
            self.history_combo.addItem('还没有本机语句材料')
        self.history_combo.blockSignals(False)
        self._select_pack()

    def _select_pack(self, *_):
        """按当前材料更新其中的句子选项，不重新调用模型。"""
        self.sentence_combo.blockSignals(True)
        self.sentence_combo.clear()
        index = self.history_combo.currentIndex()
        if 0 <= index < len(self._history):
            for n, sentence in enumerate(self._history[index]['sentences']):
                self.sentence_combo.addItem(f'第 {n + 1} 句', sentence)
        self.sentence_combo.blockSignals(False)
        self._select_sentence()

    def _select_sentence(self, *_):
        """显示所选原句/译文/目标词并清理旧对齐结果，通知训练上下文改变。"""
        self.errors.hide()
        self.retry_button.hide()
        sentence = self.sentence_combo.currentData() or {}
        text = sentence.get('text', '选好词，生成一段属于这一轮的英文。')
        pack_index = self.history_combo.currentIndex()
        words = self._history[pack_index]['words'] if 0 <= pack_index < len(self._history) else []
        self._show_reference(text, words)
        self.translation.setPlainText(sentence.get('translation', ''))
        self.start_button.setEnabled(bool(sentence))
        self.material_changed.emit()

    def _show_reference(self, text, words):
        """先转义文本，再按完整目标词高亮，网页/模型文字不能注入 HTML。"""
        pattern = r'(?<![A-Za-z])(?:' + '|'.join(re.escape(w) for w in words) + r')(?![A-Za-z])'
        parts, offset = [], 0
        for match in re.finditer(pattern, text, re.I) if words else []:
            parts.append(html.escape(text[offset:match.start()]))
            parts.append(f'<span style="background-color:{P.primary};color:{P.paper_text};font-weight:700;">{html.escape(match[0])}</span>')
            offset = match.end()
        parts.append(html.escape(text[offset:]))
        self.reference.setHtml(''.join(parts))

    @property
    def reference_text(self):
        """取得所选材料的纯英文参考句，无材料时为空串。"""
        return (self.sentence_combo.currentData() or {}).get('text', '')

    def set_busy(self, busy):
        """按生成忙碌状态限制生成/换词并显示等待文案。"""
        self.generate_button.setEnabled(not busy)
        self.shuffle_button.setEnabled(not busy)
        self.generate_button.setText('正在编织句子…' if busy else '让词语相遇 →')

    def set_running(self, running):
        """训练中锁定材料选择，启用输入/结算并清除旧反馈。"""
        self.input.setEnabled(running)
        self.finish_button.setEnabled(running)
        for control in (self.history_combo, self.sentence_combo):
            control.setEnabled(not running)
        self.start_button.setEnabled(not running and bool(self.reference_text))
        if running:
            self.errors.hide()
            self.retry_button.hide()
            self.input.clear()
            self.input.setFocus()

    def show_alignment(self, tokens):
        """将瞬时错词/漏词/多词对齐转为转义后的可见提示，不保存答案原文。"""
        parts = []
        for token in tokens:
            kind = token['kind']
            typed, expected = html.escape(token['typed']), html.escape(token['expected'])
            if kind == 'equal':
                parts.append(expected)
            elif kind == 'wrong':
                parts.append(f'<span style="color:{P.danger_on_paper}">错词 {typed} → {expected}</span>')
            elif kind == 'missing':
                parts.append(f'<span style="color:{P.danger_on_paper}">漏词 {expected}</span>')
            else:
                parts.append(f'<span style="color:{P.danger_on_paper}">多词 {typed}</span>')
        self.errors.setText('核对：' + ' · '.join(parts))
        self.errors.show()
        self.retry_button.show()

    def set_type(self, key):
        """设置句子区域字号档位并重新应用样式。"""
        self._type = english_type(key)
        self.apply_theme()

    def apply_theme(self):
        """同步句子、输入、译文和操作颜色/字号，重绘已有内容。"""
        t = self._type
        self.usage_label.apply_theme()
        for button in (self.generate_button, self.start_button, self.finish_button):
            button.setStyleSheet('QPushButton {min-height:44px;max-height:44px;padding:0 18px;}')
        self.reference.setFixedHeight(t.sentence * 3 + 24)
        self.input.setFixedHeight(t.sentence * 3 + 30)
        self.translation.setFixedHeight(t.body * 3 + 12)
        self.reference.setStyleSheet(f'QTextBrowser {{background:rgba(180,166,186,55);color:{P.paper_text};border:none;border-radius:12px;padding:8px;font:{t.sentence}px Georgia;}}')
        self.input.setStyleSheet(f'QPlainTextEdit {{background:{P.surface};color:{P.surface_text};border:1px solid {P.primary};border-radius:14px;padding:10px;font:{t.sentence}px Consolas;}}')
        self.translation.setStyleSheet(f'QTextBrowser {{color:{P.paper_muted};background:transparent;border:none;padding:0;font-size:{t.body}px;}}')
        self.status.setStyleSheet(f'color:{P.paper_muted};background:transparent;font-size:{t.helper}px;')
        for widget in self.findChildren(QLabel):
            if widget is not self.usage_label:
                widget.setStyleSheet(f'color:{P.paper_text};background:transparent;font-size:{t.helper}px;')
        for button in self.findChildren(QPushButton):
            button.setStyleSheet(f'QPushButton {{font-size:{t.body}px;min-height:44px;padding:0 16px;}}')
        for combo in self.findChildren(QComboBox):
            combo.setStyleSheet(f'QComboBox {{font-size:{t.body}px;min-height:40px;}}')
        self.topic.setStyleSheet(f'QLineEdit {{font-size:{t.body}px;min-height:40px;}}')
