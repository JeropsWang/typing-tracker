"""应用内记忆双视角：同一记录选中态、纯文本阅读与提交后删除反馈。"""
import json
import uuid
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QListWidget,
                              QPlainTextEdit, QPushButton, QMessageBox)
from ...modules.companion.api import encode_report
from ..tasks import TaskBridge
from .agent_widgets import label


class MemoryPage(QWidget):
    """只持有 Presenter 和安全索引展示值；两个视角共享一份冻结快照。"""
    report_requested = Signal(object)
    interests_saved = Signal(object)

    def __init__(self, presenter, development_index, parent=None):
        """建立普通／开发者页、异步操作和固定代码入口，默认不读取任意源码文件。"""
        super().__init__(parent)
        self.presenter, self.index_service = presenter, development_index
        self.tasks = TaskBridge(self)
        self._saving = False
        self._delete_ids = {}
        self._interest_id = None
        self._interest_draft = None
        self._code_entries = ()
        self._saving_interests = False
        self.selected_id = ''
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(label('她记得的，都在这里', heading=True))
        body.addWidget(label('兴趣由你填写；来信只保存主动安排的报告。键盘输入正文不会成为记忆。', muted=True))
        self.status = label('', muted=True)
        body.addWidget(self.status)
        self.views = QTabWidget()
        self.views.setAccessibleName('记忆查看视角')
        user = QWidget()
        user_body = QVBoxLayout(user)
        self.interest_summary = label('我的兴趣 · 本人填写')
        user_body.addWidget(self.interest_summary)
        edit = QPushButton('修改兴趣')
        edit.setAutoDefault(False)
        edit.setCheckable(True)
        user_body.addWidget(edit, 0, Qt.AlignLeft)
        self.interests = QPlainTextEdit()
        self.interests.setAccessibleName('我的兴趣草稿')
        self.interests.setMaximumHeight(82)
        self.interests.hide()
        edit.toggled.connect(self.interests.setVisible)
        user_body.addWidget(self.interests)
        self.save_interests_button = QPushButton('保存兴趣修改')
        self.save_interests_button.setAutoDefault(False)
        self.save_interests_button.clicked.connect(self.save_interests)
        self.save_interests_button.hide()
        edit.toggled.connect(self.save_interests_button.setVisible)
        user_body.addWidget(self.save_interests_button, 0, Qt.AlignLeft)
        self.records = QListWidget()
        self.records.setAccessibleName('已保存的来信')
        self.records.setMaximumHeight(110)
        self.records.currentRowChanged.connect(self._select)
        user_body.addWidget(self.records)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setMinimumHeight(150)
        self.content.setAccessibleName('已保存来信的正文与来源')
        user_body.addWidget(self.content)
        controls = QHBoxLayout()
        self.read = QPushButton('用来信卡片阅读')
        self.read.setAutoDefault(False)
        self.read.clicked.connect(self._read_selected)
        self.forget = QPushButton('忘掉这封来信')
        self.forget.setAutoDefault(False)
        self.forget.clicked.connect(self.forget_selected)
        controls.addWidget(self.read)
        controls.addWidget(self.forget)
        user_body.addLayout(controls)
        self.views.addTab(user, '我的记忆')
        developer = QWidget()
        developer_body = QVBoxLayout(developer)
        developer_body.addWidget(label('同一份记录 · 来源、结构与代码'))
        self.developer_text = QPlainTextEdit()
        self.developer_text.setReadOnly(True)
        self.developer_text.setAccessibleName('当前记忆的来源和结构')
        developer_body.addWidget(self.developer_text)
        self.index_status = label('可选本地索引尚未加载。', muted=True)
        developer_body.addWidget(self.index_status)
        self.codes = QListWidget()
        self.codes.setAccessibleName('固定代码入口')
        self.codes.setMaximumHeight(110)
        self.codes.currentRowChanged.connect(self._select_code)
        developer_body.addWidget(self.codes)
        self.code_text = QPlainTextEdit()
        self.code_text.setReadOnly(True)
        self.code_text.setMaximumHeight(145)
        developer_body.addWidget(self.code_text)
        self.open_code = QPushButton('打开所选源码')
        self.open_code.setAutoDefault(False)
        self.open_code.setEnabled(False)
        self.open_code.clicked.connect(self._open_code)
        developer_body.addWidget(self.open_code, 0, Qt.AlignLeft)
        self.views.addTab(developer, '开发者')
        body.addWidget(self.views)
        body.addStretch()
        self.refresh(reset_draft=True)
        if self.index_service is not None:
            self.tasks.resolve(self.index_service.snapshot(), self._index_loaded, self._index_failed)

    def refresh(self, *, reset_draft=False):
        """重读已提交快照并保留草稿与选中 ID；未保存内存报告不出现在记录列表。"""
        self.snapshot = self.presenter.snapshot()
        self.interest_summary.setText('本人填写的兴趣 · ' + ('、'.join(self.snapshot.config.interests) or '还没有填写'))
        if reset_draft:
            self.interests.setPlainText('\n'.join(self.snapshot.config.interests))
        self.status.setText(self.snapshot.error or f'已保存 {len(self.snapshot.reports)} 封来信 · 兴趣版本 {self.snapshot.revision}'
                            + (f' · 更新于 {self.snapshot.updated_at}' if self.snapshot.updated_at else ' · 尚未保存兴趣'))
        selected = self.selected_id
        self.records.blockSignals(True)
        self.records.clear()
        for task in self.snapshot.reports:
            self.records.addItem(task.planned_date + ' · ' + ('定时来信' if task.kind == 'auto' else '主动来信'))
        self.records.blockSignals(False)
        row = next((i for i, task in enumerate(self.snapshot.reports) if task.task_id == selected), 0)
        self.records.setCurrentRow(row if self.snapshot.reports else -1)
        self._select(self.records.currentRow())

    def _selected(self):
        """从同一冻结快照按稳定 ID 查找，不使用界面标题冒充对象身份。"""
        return next((task for task in self.snapshot.reports if task.task_id == self.selected_id), None)

    def _select(self, row):
        """普通阅读和开发者结构同时指向同一封报告，所有外部文本保持字面显示。"""
        task = self.snapshot.reports[row] if 0 <= row < len(self.snapshot.reports) else None
        self.selected_id = task.task_id if task else ''
        self.read.setEnabled(task is not None)
        self.forget.setEnabled(task is not None and not self._saving)
        if task is None:
            self.content.setPlainText('这里还没有保存的来信。到定时来信页填写兴趣，再明确准备一封吧。')
            details = {'interest_source': '本人填写', 'revision': self.snapshot.revision,
                       'updated_at': self.snapshot.updated_at,
                       'tasks': [{'id': item.task_id, 'state': item.state, 'error': item.error_code,
                                  'deleted': bool(item.deleted_at)} for item in self.snapshot.tasks]}
        else:
            report = task.report
            sources = '\n\n'.join(f'[{i}] {source.title}\n{source.url}\n{source.snippet}'
                                    for i, source in enumerate(report.sources, 1))
            self.content.setPlainText(report.topic + '\n\n' + report.summary + '\n\n' + report.warning + '\n\n' + sources)
            details = {'task_id': task.task_id, 'kind': task.kind, 'state': task.state,
                       'attempt': task.attempt, 'source': '用户明确兴趣 → 搜索工具 → 模型整理',
                       'created_at': task.created_at, 'finished_at': task.finished_at,
                       'notified_at': task.notified_at, 'revision': self.snapshot.revision,
                       'report': json.loads(encode_report(report))}
        self.developer_text.setPlainText(json.dumps(details, ensure_ascii=False, indent=2))

    def _read_selected(self):
        """点击后发布已保存任务供桌宠复用阅读卡，不启动模型。"""
        task = self._selected()
        if task:
            self.report_requested.emit(task)

    def forget_selected(self):
        """明确确认后沿用稳定删除 ID；取消不写，提交失败仍保留可读内容。"""
        task = self._selected()
        if task is None or self._saving or getattr(self.window(), 'saving', False):
            return
        answer = QMessageBox.question(self, '忘掉这封来信？',
                                       '正文和来源将从本机记忆删除。今日定时名额仍保留，不会自动重新生成。',
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        operation = self._delete_ids.setdefault(task.task_id, uuid.uuid4().hex)
        self._saving = True
        self.forget.setEnabled(False)
        self.tasks.resolve(self.presenter.forget(task.task_id, operation), self._saved, self._failed)

    def save_interests(self):
        """兴趣保存成功才更新记忆版本，清空兴趣的排期关闭由业务用例处理。"""
        if self._saving or getattr(self.window(), 'saving', False):
            return
        text = self.interests.toPlainText()
        if text != self._interest_draft:
            self._interest_id, self._interest_draft = uuid.uuid4().hex, text
        try:
            future = self.presenter.save_interests(text, self._interest_id)
        except ValueError as error:
            self.status.setText(str(error))
            return
        self._saving = True
        self._saving_interests = True
        self.save_interests_button.setEnabled(False)
        self.tasks.resolve(future, self._saved, self._failed)

    def _saved(self, value):
        """提交成功后刷新两个视角，保留尚未提交的草稿文本。"""
        self._saving = False
        self.save_interests_button.setEnabled(True)
        self.refresh()
        if self._saving_interests:
            self._saving_interests = False
            self.interests_saved.emit(self.snapshot.config)

    def _failed(self, error):
        """失败保留同一内容与操作 ID，不展示异常原文或提前移除来信。"""
        self._saving = False
        self._saving_interests = False
        self.save_interests_button.setEnabled(True)
        self.forget.setEnabled(self._selected() is not None)
        self.status.setText('保存失败，内容与草稿仍在，请重试。')

    def _index_loaded(self, snapshot):
        """后台仅交付白名单对象，UI 显示纯文本且不按索引文字生成外链。"""
        self._code_entries = snapshot.entries
        self.index_status.setText(snapshot.status)
        self.codes.clear()
        self.codes.addItems([entry.title for entry in snapshot.entries])
        self.codes.setCurrentRow(0)

    def _index_failed(self, error):
        """索引不可用不阻塞兴趣和历史阅读，错误不泄露本机路径或凭据。"""
        self.index_status.setText('本地索引不可用，记忆仍可正常查看。')

    def _select_code(self, row):
        """展示固定模块入口和原始语义，缺源码时保留可读定位。"""
        entry = self._code_entries[row] if 0 <= row < len(self._code_entries) else None
        self.open_code.setEnabled(bool(entry and entry.local_path))
        self.code_text.setPlainText('\n'.join((entry.module, entry.path, entry.state, entry.semantics)) if entry else '')

    def _open_code(self):
        """只打开适配器核准的固定本仓库源码路径，不解析索引提供的 URL。"""
        row = self.codes.currentRow()
        if 0 <= row < len(self._code_entries) and self._code_entries[row].local_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._code_entries[row].local_path))
