"""拼写卡：语义操作信号与有限作答反馈。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget
from ..palette import P
from ..widgets.motion import FeedbackSpark


class SpellingPanel(QWidget):
    start_requested = Signal()
    submit_requested = Signal()
    hint_requested = Signal()
    reveal_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        top = QHBoxLayout()
        self.progress = QLabel('看中文，敲出英文。')
        self.progress.setProperty('textRole', 'paperField')
        top.addWidget(self.progress, 1)
        self.spark = FeedbackSpark()
        top.addWidget(self.spark)
        layout.addLayout(top)
        self.meaning = QTextBrowser()
        self.meaning.setAccessibleName('中文释义')
        self.meaning.setFixedHeight(126)
        self.meaning.setPlainText('从右侧选一本词库，再开始这一轮。\n答错或借助提示完成的词会进入待复习。')
        layout.addWidget(self.meaning)
        self.answer = QLineEdit()
        self.answer.setPlaceholderText('在这里拼写 · Enter 提交 / 下一词')
        self.answer.setAccessibleName('英文单词拼写')
        self.answer.setInputMethodHints(Qt.ImhLatinOnly | Qt.ImhNoPredictiveText)
        self.answer.setFixedHeight(58)
        self.answer.returnPressed.connect(self.submit_requested.emit)
        layout.addWidget(self.answer)
        row = QHBoxLayout()
        self.hint_button = QPushButton('偷看首字母')
        self.reveal_button = QPushButton('看看答案')
        self.submit_button = QPushButton('提交 →')
        self.submit_button.setProperty('buttonRole', 'primary')
        self.hint_button.clicked.connect(self.hint_requested.emit)
        self.reveal_button.clicked.connect(self.reveal_requested.emit)
        self.submit_button.clicked.connect(self.submit_requested.emit)
        for button in (self.hint_button, self.reveal_button):
            button.setProperty('buttonRole', 'quiet')
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self.submit_button)
        layout.addLayout(row)
        self.feedback = QLabel('提示也算练习；独立答对会单独记录。')
        self.feedback.setWordWrap(True)
        self.feedback.setMinimumHeight(60)
        layout.addWidget(self.feedback)
        layout.addStretch()
        self.start_button = QPushButton('开始这一轮 →')
        self.start_button.setProperty('buttonRole', 'primary')
        self.start_button.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.start_button, 0, Qt.AlignLeft)
        self.set_active(False)
        self.apply_theme()

    def set_active(self, active, judged=False):
        self.answer.setEnabled(active)
        self.answer.setReadOnly(judged)
        self.submit_button.setEnabled(active)
        self.hint_button.setEnabled(active and not judged)
        self.reveal_button.setEnabled(active and not judged)
        self.submit_button.setText('下一词 →' if judged else '提交 →')

    def show_word(self, word, index, total):
        self.progress.setText(f'单词 {index + 1:02d} / {total:02d}')
        self.meaning.setPlainText(word.meaning)
        self.answer.clear()
        self.feedback.setText('可以慢一点，让这个词留在记忆里。')
        self.set_active(True)
        self.answer.setFocus()

    def show_result(self, word, result):
        self.set_active(True, judged=True)
        phonetic = f'  /{word.phonetic}/' if word.phonetic else ''
        if result['independent']:
            prefix = '漂亮，独立答对！'
            self.spark.flash()
        elif result['correct']:
            prefix = '借助提示完成，已加入待复习。'
        else:
            prefix = '这个词先收进待复习，下次再见。'
        self.feedback.setText(f'{prefix}\n{word.word}{phonetic}')
        self.answer.setFocus()

    def set_motion_enabled(self, enabled):
        self.spark.set_motion_enabled(enabled)

    def apply_theme(self):
        for button in (self.submit_button, self.start_button):
            button.setStyleSheet('QPushButton {min-height:44px;max-height:44px;padding:0 18px;}')
        self.meaning.setStyleSheet(f'QTextBrowser {{background:transparent; color:{P.paper_text}; border:none; font-size:21px;}}')
        self.answer.setStyleSheet(f'QLineEdit {{background:{P.surface};color:{P.surface_text};border:1px solid {P.primary};border-radius:14px;min-height:52px;max-height:52px;padding:0 16px;font:22px Consolas;}}')
        self.feedback.setStyleSheet(f'color:{P.paper_muted}; background:transparent;')
