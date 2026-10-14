"""An isolated studio preview; simulated events never reach business services."""
from pathlib import Path
from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QPushButton, QToolButton
from ...modules.companion.api import STATES, format_line
from ...modules.companion.api import Sprite
from ...modules.companion.api import REACTIONS
from .artwork import sprite_icon
from .view import CompanionView


class StudioCharacter(CompanionView):
    """工坊专用桌宠预览视图，禁用拖动，不触发真实桌宠状态或奖励。"""
    def __init__(self, parent=None):
        """建立复用桌宠绘制的预览角色并关闭拖动能力。"""
        super().__init__(parent)
        self.draggable = False

    def bubble_rect(self):
        """返回工坊预览话术区域，保持图片和文字有各自空间。"""
        return QRect(4, 4, min(190, self.width() - 8), 84)

    def image_rect(self):
        """按预览区域可用尺寸等比定位角色，不采用真实桌宠固定尺寸。"""
        if self._image.isNull():
            return QRect()
        size = self._image.size().scaled(max(1, self.width() - 48),
                                         max(1, self.height() - 70), Qt.KeepAspectRatio)
        return QRect(self.width() - size.width() - 24,
                     self.height() - size.height() - 16 + round(self._offset),
                     size.width(), size.height())

    def resizeEvent(self, event):
        """预览尺寸改变后同步透明命中区域。"""
        super().resizeEvent(event)
        self._update_mask()


class PreviewStage(QWidget):
    """包含静态背景和预览角色的工坊舞台，所有绘制在 Qt 主线程。"""
    def __init__(self, parent=None):
        """装载工坊背景并创建独立预览角色视图。"""
        super().__init__(parent)
        self.setMinimumHeight(330)
        self.background = QPixmap(str(Path(__file__).resolve().parents[1] / 'assets/companion/workshop-backdrop.png'))
        self.view = StudioCharacter(self)

    def resizeEvent(self, event):
        """根据舞台可用宽高重排角色视图，不改变草稿数据。"""
        super().resizeEvent(event)
        self.view.setFixedSize(max(200, self.width() - 16), max(260, self.height() - 16))
        self.view.move(max(0, self.width() - self.view.width() - 8),
                       max(0, self.height() - self.view.height() - 4))

    def paintEvent(self, event):
        """将背景等比铺满舞台并居中裁切，角色由子视图绘制。"""
        painter = QPainter(self)
        if not self.background.isNull():
            scaled = self.background.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2,
                               (self.height() - scaled.height()) // 2, scaled)


class CreationPreview(QWidget):
    """作品草稿的独立预览面板，使用示例指标替换话术，不改真实统计。"""
    state_selected = Signal(str)

    def __init__(self, parent=None):
        """创建状态缩略图、舞台和示例事件/动效控件。"""
        super().__init__(parent)
        self.draft = None
        self.assets = {}
        self._entry = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 0, 0)
        layout.setSpacing(10)
        self.stage = PreviewStage()
        self.view = self.stage.view
        layout.addWidget(self.stage, 1)
        title = QLabel('心情预览')
        title.setProperty('companionHeading', True)
        layout.addWidget(title)
        strip = QHBoxLayout()
        strip.setSpacing(8)
        self.state_buttons = {}
        for key in ('happy', 'shy', 'focused'):
            button = QToolButton()
            button.setText(STATES[key])
            button.setAccessibleName(f'预览并编辑{STATES[key]}状态')
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(92, 82))
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, state=key: self.state_selected.emit(state))
            self.state_buttons[key] = button
            strip.addWidget(button, 1)
        layout.addLayout(strip)
        controls = QHBoxLayout()
        self.controls = controls
        self.motion = QCheckBox('预览动效')
        self.motion.setChecked(True)
        self.motion.toggled.connect(self.refresh)
        controls.addWidget(self.motion)
        self.event = QComboBox()
        self.event.setAccessibleName('模拟互动类型')
        for key, title in [('pet', '摸摸头'), ('double_click', '突然互动'), ('finished', '完成练习'),
                           ('record', '刷新纪录'), ('encourage', '练习鼓励'), ('level', '升级庆祝')]:
            self.event.addItem(title, key)
        controls.addWidget(self.event, 1)
        button = QPushButton('模拟互动')
        self.simulate_button = button
        button.clicked.connect(lambda: self.simulate(self.event.currentData()))
        controls.addWidget(button)
        layout.addLayout(controls)
        self.note = QLabel('示例数据 · 预览不影响统计或奖励。')
        self.note.setWordWrap(True)
        self.note.setProperty('companionHint', True)
        layout.addWidget(self.note)

    def set_draft(self, draft, assets):
        """关联当前草稿和暂存素材，再刷新状态缩略图。"""
        self.draft, self.assets = draft, assets
        self.refresh_thumbnails()

    def refresh_thumbnails(self):
        """从当前条目素材重建缩略图，替换图片后不复用过期的状态图标。"""
        if not self.draft:
            return
        for key, button in self.state_buttons.items():
            entry = self.draft['states'].get(key, self.draft['states']['idle'])
            source = self.assets.get(entry['asset'])
            if source is not None:
                button.setIcon(sprite_icon(source, entry.get('rect')))
            button.setChecked(self._entry is entry)

    def show_entry(self, entry):
        """切换预览条目并同步缩略图选中态及角色内容。"""
        self._entry = entry
        self.refresh_thumbnails()
        self.refresh()

    def refresh(self, *_):
        """以固定示例值格式化草稿话术，素材缺失时使用待机条目并尊重预览动效开关。"""
        if not self._entry or not self.draft:
            return
        entry = self._entry
        source = self.assets.get(entry['asset'])
        if source is None:
            entry = self.draft['states']['idle']
            source = self.assets[entry['asset']]
        line = next(iter(entry.get('lines', [])), '这里会显示你写下的话术。')
        text = format_line(line, {'nickname': '打字新星', 'level': 12, 'speed': '68.5', 'accuracy': '96%', 'streak': 7})
        self.view.set_content(Sprite(source, entry.get('rect'), entry.get('frame', 0)), text,
                              self.motion.isChecked() and self.isVisible(),
                              state=next((key for key, value in self.draft['states'].items()
                                          if value is self._entry), 'surprised'))

    def simulate(self, kind):
        """把示例事件映射成对应草稿姿态，仅更新预览，不发布业务事件。"""
        if self.draft:
            state = REACTIONS.get(kind, ('idle', 0))[0]
            self.show_entry(self.draft['states'].get(state, self.draft['states']['idle']))

    def hideEvent(self, event):
        """预览隐藏时停止角色动效，避免后台持续重绘。"""
        self.view.set_motion_enabled(False)
        super().hideEvent(event)

    def showEvent(self, event):
        """预览显示后按当前草稿和开关恢复内容。"""
        super().showEvent(event)
        self.refresh()
