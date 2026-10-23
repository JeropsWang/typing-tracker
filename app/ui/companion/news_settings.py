"""独立来信配置组件：只编辑草稿与发出操作信号，不联网、不访问数据库。"""
from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QCheckBox, QTimeEdit, QPlainTextEdit, QPushButton
from ...modules.companion.api import NewsConfig, normalize_interests, news_status
from .agent_settings_art import SettingsSheet
from .agent_widgets import label


class NewsSettingsPanel(QWidget):
    """复用切角纸张和原生输入，展示已保存状态；草稿在外层统一提交。"""
    run_requested = Signal()
    retry_requested = Signal(str)
    memory_requested = Signal()

    def __init__(self, config, snapshot, parent=None, *, now_local=None,
                 agent_enabled=True, companion_enabled=True):
        """从冻结配置及已保存总开关建立表单，用户操作不直接写库。"""
        super().__init__(parent)
        from datetime import datetime
        self.now_local = now_local or datetime.now
        self.agent_enabled, self.companion_enabled = agent_enabled, companion_enabled
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(20)
        body.addWidget(label('把喜欢的事，写进下一封来信', heading=True))
        body.addWidget(label('应用驻留后台时按本机时间准备，每天一封。关闭应用后不会运行。', muted=True))
        sheet = SettingsSheet('blue')
        grid = QGridLayout(sheet)
        grid.setContentsMargins(24, 22, 24, 28)
        grid.setVerticalSpacing(12)
        self.enabled = QCheckBox('开启定时来信')
        self.enabled.setChecked(config.enabled)
        grid.addWidget(self.enabled, 0, 0, 1, 2)
        self.interests = QPlainTextEdit('\n'.join(config.interests))
        self.interests.setAccessibleName('明确填写的兴趣')
        self.interests.setPlaceholderText('每行一个兴趣，最多 5 个，每个不超过 40 字')
        self.interests.setMaximumHeight(110)
        grid.addWidget(label('想让她留意什么？'), 1, 0, 1, 2)
        grid.addWidget(self.interests, 2, 0, 1, 2)
        self.time = self._time(config.time, '每天来信时间')
        grid.addWidget(label('每天几点出发'), 3, 0)
        grid.addWidget(self.time, 3, 1)
        self.quiet_enabled = QCheckBox('安静时段不打扰')
        self.quiet_enabled.setChecked(config.quiet_enabled)
        grid.addWidget(self.quiet_enabled, 4, 0, 1, 2)
        self.quiet_start = self._time(config.quiet_start, '安静时段开始')
        self.quiet_end = self._time(config.quiet_end, '安静时段结束')
        grid.addWidget(self.quiet_start, 5, 0)
        grid.addWidget(self.quiet_end, 5, 1)
        body.addWidget(sheet)
        aside = SettingsSheet('coral')
        note = QVBoxLayout(aside)
        note.setContentsMargins(22, 18, 22, 24)
        self.schedule = label('', muted=True)
        note.addWidget(self.schedule)
        self.status = label('', muted=True)
        note.addWidget(self.status)
        self.run = QPushButton('现在联网准备一封')
        self.run.setAutoDefault(False)
        self.run.clicked.connect(self.run_requested)
        note.addWidget(self.run)
        self.retry_button = QPushButton('重试最近未完成来信')
        self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(self._retry)
        note.addWidget(self.retry_button)
        memory = QPushButton('去记忆里翻一翻')
        memory.setAutoDefault(False)
        memory.clicked.connect(self.memory_requested)
        note.addWidget(memory)
        note.addWidget(label('现在汇报使用已保存配置，可能产生模型／搜索费用。失败不会自动重复请求。占卜仍在第三期准备中。', muted=True))
        body.addWidget(aside, 0, Qt.AlignRight)
        body.addStretch()
        self.set_snapshot(snapshot)

    @staticmethod
    def _time(value, accessible):
        """使用原生时间控件保留键盘编辑能力，统一显示 24 小时制。"""
        widget = QTimeEdit(QTime.fromString(value, 'HH:mm'))
        widget.setDisplayFormat('HH:mm')
        widget.setAccessibleName(accessible)
        return widget

    def values(self):
        """校验草稿并返回统一设置键；错误由外层显示，原草稿仍保留。"""
        return NewsConfig(enabled=self.enabled.isChecked(), interests=normalize_interests(self.interests.toPlainText()),
                          time=self.time.time().toString('HH:mm'), quiet_enabled=self.quiet_enabled.isChecked(),
                          quiet_start=self.quiet_start.time().toString('HH:mm'),
                          quiet_end=self.quiet_end.time().toString('HH:mm')).settings_values()

    def set_snapshot(self, snapshot, *, status='', busy=False, agent_enabled=None, companion_enabled=None):
        """用已保存总开关刷新只读排期与状态，不覆盖当前兴趣和时间草稿。"""
        if agent_enabled is not None:
            self.agent_enabled = agent_enabled
        if companion_enabled is not None:
            self.companion_enabled = companion_enabled
        view = news_status(snapshot, self.now_local(), agent_enabled=self.agent_enabled,
                           companion_enabled=self.companion_enabled)
        self.schedule.setText(view.schedule)
        self.status.setText('\n'.join(item for item in (snapshot.error or status or view.current, view.last_failure) if item))
        self.run.setEnabled(not busy)
        self._retry_id = view.retry_task_id
        self.retry_button.setEnabled(bool(self._retry_id) and not busy)

    def _retry(self):
        """明确选择最近终态任务后发布稳定 ID，组件不自行重跑模型。"""
        self.retry_requested.emit(self._retry_id)
