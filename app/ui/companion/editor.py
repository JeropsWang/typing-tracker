"""State and meme editing against a workshop-owned JSON draft."""
import copy
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPlainTextEdit,
    QPushButton, QSpinBox, QFormLayout, QGridLayout, QButtonGroup, QFrame,
)
from ...companion.models import STATES


class StateEditor(QWidget):
    changed = Signal()
    selection_changed = Signal()
    replace_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.draft = None
        self.editable = False
        self._key = ('state', 'idle')
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title = QLabel('心情')
        title.setProperty('companionHeading', True)
        layout.addWidget(title)
        self.selection = QComboBox()
        self.selection.setAccessibleName('选择角色状态或表情包')
        self.selection.currentIndexChanged.connect(self._selected)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.state_buttons = {}
        self.state_group = QButtonGroup(self)
        for index, (key, name) in enumerate(STATES.items()):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setProperty('companionState', True)
            button.setAccessibleName(f'编辑{name}状态')
            self.state_group.addButton(button, index)
            self.state_buttons[key] = button
            grid.addWidget(button, index // 5, index % 5)
        self.state_group.idClicked.connect(self.selection.setCurrentIndex)
        layout.addLayout(grid)
        paper = QFrame()
        paper.setObjectName('companionDialoguePaper')
        paper.setMaximumHeight(235)
        page = QVBoxLayout(paper)
        page.setContentsMargins(16, 14, 16, 12)
        page.setSpacing(6)
        heading = QLabel('编辑话术')
        heading.setProperty('companionHeading', True)
        page.addWidget(heading)
        note = QLabel('每行一句，互动时随机出现')
        note.setProperty('companionHint', True)
        page.addWidget(note)
        self.lines = QPlainTextEdit()
        self.lines.setObjectName('companionDialogueLines')
        self.lines.setAccessibleName('当前心情的话术，每行一句')
        self.lines.setPlaceholderText('你好，{nickname}\n今天也一起加油吧。')
        self.lines.setMinimumHeight(110)
        page.addWidget(self.lines, 1)
        layout.addWidget(paper)
        layout.addWidget(QLabel('替换表情 / GIF'))
        self.replace = QPushButton('选择本地图片 / GIF…')
        self.replace.clicked.connect(self.replace_requested)
        layout.addWidget(self.replace)
        timing = QHBoxLayout()
        self.timing = timing
        timing.addWidget(QLabel('持续时间'))
        self.duration = QSpinBox()
        self.duration.setRange(1, 30)
        self.duration.setSuffix(' 秒')
        self.duration.setMaximumWidth(90)
        timing.addWidget(self.duration, 1)
        layout.addLayout(timing)
        self.more_button = QPushButton('表情包与更多设置')
        self.more_button.setCheckable(True)
        self.more_button.setProperty('companionQuiet', True)
        layout.addWidget(self.more_button)
        self.more = QWidget()
        more_layout = QVBoxLayout(self.more)
        more_layout.setContentsMargins(0, 0, 0, 0)
        more_layout.addWidget(self.selection)
        row = QHBoxLayout()
        self.add = QPushButton('添加表情包')
        self.remove = QPushButton('移除表情包')
        self.add.clicked.connect(self.add_meme)
        self.remove.clicked.connect(self.remove_meme)
        row.addWidget(self.add)
        row.addWidget(self.remove)
        more_layout.addLayout(row)
        form = QFormLayout()
        self.frame = QSpinBox()
        self.frame.setRange(0, 100)
        self.frame.setToolTip('关闭动效时显示 GIF 的这一帧；静态图片无需调整。')
        form.addRow('静态预览帧', self.frame)
        more_layout.addLayout(form)
        hint = QLabel('可用变量：{nickname} 昵称 · {level} 等级\n{speed} 速度 · {accuracy} 正确率 · {streak} 连签\n事件缺少的数据会显示“暂无数据”。')
        hint.setWordWrap(True)
        hint.setProperty('companionHint', True)
        more_layout.addWidget(hint)
        layout.addWidget(self.more)
        self.more.hide()
        self.more_button.toggled.connect(self.more.setVisible)
        layout.addStretch()
        for signal in (self.lines.textChanged, self.duration.valueChanged, self.frame.valueChanged):
            signal.connect(self._edited)

    def load(self, draft, editable):
        self._loading = True
        self.draft = draft
        self.editable = editable
        idle = draft['states']['idle']
        for state in STATES:
            draft['states'].setdefault(state, copy.deepcopy(idle))
        self._key = ('state', 'idle')
        self._populate()
        self._show_entry()
        self.lines.setReadOnly(not editable)
        for widget in (self.replace, self.add, self.duration, self.frame):
            widget.setEnabled(editable)
        self.remove.setEnabled(editable and self._key[0] == 'meme')
        self._loading = False

    def _populate(self):
        self.selection.blockSignals(True)
        self.selection.clear()
        for key, name in STATES.items():
            self.selection.addItem(name, ('state', key))
        for index, _ in enumerate(self.draft['memes']):
            self.selection.addItem(f'表情包 {index + 1}', ('meme', index))
        index = next((i for i in range(self.selection.count())
                      if self.selection.itemData(i) == self._key), 0)
        self.selection.setCurrentIndex(index)
        self.selection.blockSignals(False)

    def current_entry(self):
        kind, key = self._key
        return self.draft['states'][key] if kind == 'state' else self.draft['memes'][key]

    def select_state(self, state):
        if state in STATES:
            self.selection.setCurrentIndex(list(STATES).index(state))

    def commit_current(self):
        if self.draft and self.editable and not self._loading:
            entry = self.current_entry()
            entry['lines'] = [line.strip() for line in self.lines.toPlainText().splitlines() if line.strip()]
            entry['duration_ms'] = self.duration.value() * 1000
            entry['frame'] = self.frame.value()

    def _selected(self):
        if self._loading or self.draft is None or self.selection.currentData() is None:
            return
        self.commit_current()
        self._key = self.selection.currentData()
        self._show_entry()
        self.selection_changed.emit()

    def _show_entry(self):
        previous = self._loading
        self._loading = True
        entry = self.current_entry()
        if self._key[0] == 'state':
            self.state_buttons[self._key[1]].setChecked(True)
        else:
            self.state_group.setExclusive(False)
            for button in self.state_buttons.values():
                button.setChecked(False)
            self.state_group.setExclusive(True)
        self.lines.setPlainText('\n'.join(entry.get('lines', [])))
        self.duration.setValue(entry.get('duration_ms', 6000) // 1000)
        self.frame.setValue(entry.get('frame', 0))
        self.remove.setEnabled(self.editable and self._key[0] == 'meme')
        self._loading = previous

    def _edited(self):
        if not self._loading and self.draft is not None:
            self.commit_current()
            self.changed.emit()

    def add_meme(self):
        if not self.editable:
            return
        if len(self.draft['memes']) >= 20:
            return
        self.commit_current()
        self.draft['memes'].append(copy.deepcopy(self.draft['states']['idle']))
        self._key = ('meme', len(self.draft['memes']) - 1)
        self._populate()
        self._show_entry()
        self.changed.emit()

    def remove_meme(self):
        if not self.editable or self._key[0] != 'meme':
            return
        self.draft['memes'].pop(self._key[1])
        self._key = ('state', 'idle')
        self._populate()
        self._show_entry()
        self.changed.emit()
