"""Keyboard warrior: cumulative manually entered characters in 15 seconds."""
from ...bootstrap.features import keyboard_presenter
from ..tasks import TaskBridge
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem,
)
from ...modules.practice.api import KeyboardSession
from .design import PaperPage
from .training_workspace import PracticeInput
from ..palette import P


class KeyboardInput(PracticeInput):
    """键盘侠主动输入控件，仅实际改变文档的普通/IME 上屏文字进入计数。"""
    text_entered = Signal(str)

    def keyPressEvent(self, event):
        """原输入处理后核对文档版本，实际新增可打印文本才发布输入信号。"""
        revision = self.document().revision()
        super().keyPressEvent(event)
        text = event.text().replace('\r', '\n')
        if self.document().revision() != revision and text and all(ch.isprintable() or ch in '\n\t' for ch in text):
            self.text_entered.emit(text)

    def inputMethodEvent(self, event):
        """只对实际插入的 IME commitString 发布上屏信号，组字不计数。"""
        revision = self.document().revision()
        super().inputMethodEvent(event)
        if event.commitString() and self.document().revision() != revision:
            self.text_entered.emit(event.commitString())


class KeyboardWarriorPanel(PaperPage):
    """十五秒键盘侠的 Qt 页面，纯会话计数、异步记录、失败原结果重试。"""
    running_changed = Signal(bool)

    def __init__(self, repo, balance, parent=None):
        """建立十五秒键盘侠训练组件的依赖与初始状态。"""
        super().__init__(parent)
        self.service = keyboard_presenter(repo)
        self._tasks = TaskBridge(self)
        self._saving = False
        self.balance = balance
        self.session = None
        self._pending = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        title = QLabel('键盘侠 · 15 秒放飞手指')
        title.setProperty('textRole', 'paperTitle')
        self.body.addWidget(title)
        rules = QLabel('随意乱敲，不比正确率。汉字 2tw，其他字符 1tw；速度 = 本轮累计 tw × 4。\n'
                       '删除不扣已输入量，重新输入继续累计；仅记录本机成绩，不保存输入内容。')
        rules.setProperty('textRole', 'paperMuted')
        rules.setWordWrap(True)
        self.body.addWidget(rules)
        metrics = QHBoxLayout()
        self.countdown = QLabel('剩余 15.0 秒')
        self.countdown.setProperty('textRole', 'paperMetric')
        self.speed = QLabel('本轮累计 0 tw · 速度 — tw/分')
        self.speed.setProperty('textRole', 'paperField')
        self.speed.setToolTip('以固定 15 秒为分母，速度为累计 tw × 60 / 15；未结束时显示实时速度。')
        metrics.addWidget(self.countdown)
        metrics.addWidget(self.speed, 1, Qt.AlignRight)
        self.body.addLayout(metrics)
        self.input = KeyboardInput()
        self.input.setAccessibleName('键盘侠随意输入区')
        self.input.setPlaceholderText('点击开始，在这里随意输入。')
        self.input.setFixedHeight(150)
        self.input.setEnabled(False)
        self.input.setUndoRedoEnabled(False)
        self.input.text_entered.connect(self._text_changed)
        self.input.paste_blocked.connect(lambda: self.status.setText('请手动乱敲，粘贴不会计分。'))
        self.body.addWidget(self.input)
        self.start_button = QPushButton('开始 15 秒挑战 →')
        self.start_button.setProperty('buttonRole', 'primary')
        self.start_button.setMinimumHeight(44)
        self.start_button.clicked.connect(self._action)
        self.body.addWidget(self.start_button, 0, Qt.AlignLeft)
        self.status = QLabel('准备好了就开始。切换模块或离开页面会取消本轮。')
        self.status.setProperty('textRole', 'paperMuted')
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        heading = QLabel('本机历史榜 · 按 tw/分钟排名')
        heading.setProperty('textRole', 'paperField')
        self.body.addWidget(heading)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['名次', '速度 tw/分', '累计 tw', '记录时间'])
        self.table.setAccessibleName('键盘侠本机历史排行榜')
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(210)
        self.body.addWidget(self.table)
        self.empty = QLabel('还没有成绩，完成第一轮 15 秒挑战就会上榜。')
        self.empty.setProperty('textRole', 'paperMuted')
        self.empty.setWordWrap(True)
        self.body.addWidget(self.empty)
        self.refresh()
        self.apply_theme()

    def _action(self):
        """按待保存/进行/空闲状态执行保存重试、取消或新建十五秒会话。"""
        if self._pending:
            self._save()
        elif self.session:
            self.cancel()
        else:
            self.input.clear()
            self.session = KeyboardSession(self.balance)
            self.input.setEnabled(True)
            self.input.setFocus()
            self.start_button.setText('取消本轮')
            self.status.setText('随意输入，15 秒后自动结算。')
            self.timer.start(50)
            self.running_changed.emit(True)
            self._tick()

    def _text_changed(self, text):
        """有效会话把主动文字交纯计数器，再更新临时速度展示。"""
        if self.session and not self._pending:
            self.session.add_text(text)
            self._tick()

    def _tick(self):
        """显示真实剩余秒数和 tw 速度，到期冻结输入并启动保存。"""
        if self.session is None or self._pending:
            return
        remaining = self.session.remaining
        self.countdown.setText(f'剩余 {remaining:.1f} 秒')
        elapsed = 15 - remaining
        speed = self.session.tw * 60 / elapsed if elapsed > 0 else 0
        self.speed.setText(f'本轮累计 {self.session.tw:g} tw · 速度 {speed:.1f} tw/分')
        if remaining <= 0:
            self.timer.stop()
            self.input.setEnabled(False)
            self.running_changed.emit(False)
            self._pending = True
            self._save()

    def _save(self):
        """只提交一次已结束会话，Future 完成前禁重复操作，失败保留原会话 ID。"""
        if self._saving:
            return
        result = self.session.result()
        try:
            saved = self.service.record(self.session)
        except Exception as error:
            self._save_failed(error)
            return
        self._saving=True
        self.start_button.setEnabled(False)
        self._tasks.resolve(saved,lambda value:self._saved(value,result),self._save_failed)

    def _save_failed(self,error):
        """恢复保存重试操作并保留成绩，不把失败记录当已完成。"""
        self._saving=False
        self.start_button.setEnabled(True)
        self.status.setText('成绩保存失败，本轮结果已保留，点击重试保存。')
        self.start_button.setText('重试保存')

    def _saved(self,saved,result):
        """提交成功后展示本轮数值并刷新排行榜，空输入不产生记录。"""
        self._saving=False
        self.start_button.setEnabled(True)
        self.speed.setText(f"本轮累计 {result['tw']:g} tw · 速度 {result['speed']:.1f} tw/分")
        self.status.setText('15 秒完成，成绩已加入本机历史榜。' if saved else '本轮没有输入，未生成成绩。')
        self.session = None
        self._pending = False
        self.start_button.setText('再来一轮 →')
        self.refresh()

    def cancel(self):
        """取消未完成会话，但已到期待保存结果保留供重试。"""
        self.timer.stop()
        if self._pending:
            return  # Retain a finished result until the user can retry saving it.
        if self.session:
            self.session = None
            self.input.setEnabled(False)
            self.start_button.setText('开始 15 秒挑战 →')
            self.countdown.setText('剩余 15.0 秒')
            self.status.setText('本轮已取消，未生成成绩。')
            self.running_changed.emit(False)

    def refresh(self):
        """从只读服务刷新已提交排行榜和空状态。"""
        rows = self.service.leaderboard()
        self.table.setRowCount(len(rows))
        self.empty.setVisible(not rows)
        for index, row in enumerate(rows):
            for column, value in enumerate((str(row['rank']), f"{row['speed']:.1f}", f"{row['tw']:g}", row['created_at'])):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter if column < 3 else Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(index, column, item)

    def hideEvent(self, event):
        """页面隐藏时复用会话取消语义，待保存成绩不丢弃。"""
        self.cancel()
        super().hideEvent(event)

    def apply_theme(self):
        """将当前主题颜色、字号和图标同步到十五秒键盘侠训练，保持现有业务状态。"""
        self.input.setStyleSheet(f'QPlainTextEdit {{background:{P.surface};color:{P.surface_text};border:1px solid {P.primary};border-radius:14px;padding:12px;font:18px Consolas;}}')
        self.table.setStyleSheet(f'QTableWidget {{background:transparent;color:{P.paper_text};border:none;}} QHeaderView::section {{background:transparent;color:{P.paper_muted};border:none;padding:6px;}}')
        self.paper.update()
