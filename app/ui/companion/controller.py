"""Main-thread owner of one companion, one runtime, and the active creation."""
import json
import time
from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, QEvent
from PySide6.QtWidgets import QApplication, QMenu
from shiboken6 import isValid

from ...modules.companion.api import CompanionEvent, STATES, format_line
from ...modules.companion.api import DEFAULT_PACK, PackStore
from ...modules.companion.api import Runtime, REACTIONS
from ..presenters import QueryPresenter
from .desktop import available_screens, clamp_position
from .view import CompanionView


class CompanionController(QObject):
    """Qt 主线程的桌宠总控制器，连接只读活动、纯状态机、作品素材及窗口/桌面视图。"""
    def __init__(self,window,repo,data_dir,*,activity_provider=None):
        """装配活动与素材能力、桌宠视图和智能体浮层，初始化模式、计时器与屏幕监听。"""
        super().__init__(window)
        self.window, self.presenter = window, QueryPresenter(repo)
        self.activity_provider = activity_provider or window.activity_provider
        self.store = PackStore(data_dir)
        self.runtime = Runtime()
        self.view = CompanionView(window)
        from .agent_controller import CompanionAgentController
        self.agent = CompanionAgentController(self, data_dir=data_dir)
        self.mode = 'window'
        self._hidden = False
        self._stopped = False
        self._started = False
        self._workshop = None
        self._last_display = None
        self._agent_feedback = None
        self._last_line = {}
        self._last_meme = -1
        self._line = ''
        self._entry = None
        self._metric_at = -10
        self._values = {}
        self._last_level = None
        self._pet_times = []
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self.view.clicked.connect(self._pet)
        self.view.double_clicked.connect(lambda: self.handle_event(CompanionEvent('double_click')))
        self.view.dragged.connect(self._drag)
        self.view.drag_finished.connect(self._save_position)
        self.view.menu_requested.connect(self._menu)
        self.window.installEventFilter(self)
        self._screen_app = QApplication.instance()
        self._screens = []
        self._watch_screens()
        self._screen_app.screenRemoved.connect(self._screen_changed)
        self._screen_app.screenAdded.connect(self._screen_changed)
        self._screen_app.aboutToQuit.connect(self.shutdown)
        self.window.destroyed.connect(self.shutdown)
        try:
            self.pack = self.store.load(repo.get_setting('companion_pack', DEFAULT_PACK),
                                        repo.get_setting('companion_revision', '') or None)
        except (ValueError, OSError, KeyError, TypeError):
            self.pack = self.store.load(DEFAULT_PACK)
            self.warning = '当前角色作品无法加载，已回退星光陪伴；原文件保留。'
        else:
            self.warning = ''

    def start(self):
        """幂等启动桌宠并同步已提交设置，素材加载回退时提示用户。"""
        if self._started:
            return
        self._started = True
        self.sync_settings()
        if self.warning:
            self.window.show_toast('角色作品', self.warning)

    def sync_settings(self):
        """从 Presenter 同步开关、尺寸、话术、动效与显示模式，并刷新当前姿态。"""
        self.enabled = self.presenter.get_setting('companion_enabled', '1') != '0'
        self.bubbles = self.presenter.get_setting('companion_bubbles', '1') != '0'
        self.motion = self.presenter.get_setting('reduced_motion', '0') != '1'
        self.agent.sync_motion()
        if self.agent.news is not None:
            self.agent.news.sync_settings()
        self.runtime.set_frequency(self.presenter.get_setting('companion_frequency', 'normal'))
        try:
            size = int(self.presenter.get_setting('companion_size', '160'))
        except ValueError:
            size = 160
        self.view.set_character_size(size)
        self._values['nickname'] = self.presenter.get_setting('nickname', '打字新星') or '打字新星'
        mode = self.presenter.get_setting('companion_mode', 'window')
        self.switch_mode(mode if mode in ('window', 'desktop') else 'window', persist=False)
        self._last_display = None
        self._tick()

    def switch_mode(self, mode, *, persist=True, desktop_position=None, keep_drag=False):
        """在应用内与桌面间重设同一视图的父窗口；需要时保留正在进行的拖动手势。"""
        if mode not in ('window', 'desktop') or self._stopped:
            return
        drag = None
        if persist:
            self.presenter.set_setting('companion_mode', mode)
        if self.mode != mode:
            self._save_position()
            drag = self.view.drag_context() if keep_drag else None
            self.mode = mode
            self.view.hide()
            if mode == 'desktop':
                self.view.setParent(None, Qt.Tool | Qt.FramelessWindowHint |
                                    Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
                self.view.setAttribute(Qt.WA_ShowWithoutActivating)
                if desktop_position is None:
                    self._restore_position()
                else:
                    self.view.move(clamp_position(desktop_position, self.view.width(), self.view.height()))
            else:
                self.view.setParent(self.window, Qt.Widget)
        self.view.desktop = mode == 'desktop'
        self.sync_visibility()
        if keep_drag:
            self.view.resume_drag(drag)

    def _practicing(self):
        """从公共活动状态判断是否正在练习，供自动互动和动效让出优先级。"""
        return self.activity_provider.activity().practicing

    def sync_visibility(self):
        """依据模式和主窗口状态显示桌宠，更新纯 Runtime 可见性并启停视觉计时器。"""
        if not self._started or self._stopped:
            return
        visible = self.enabled and not self._hidden and (
            self.mode == 'desktop' or (self.window.isVisible() and not self.window.isMinimized()))
        self.runtime.set_visible(visible)
        activity = self.activity_provider.activity()
        self.runtime.update_activity(activity.day,activity.typed,activity.practicing)
        if self.mode == 'window':
            if self.view._dragging:
                self.view.move(self._clamp_window(self.view.pos()))
            else:
                self._restore_window_position()
        else:
            self.view.move(clamp_position(self.view.pos(), self.view.width(), self.view.height()))
        self.view.setVisible(visible)
        if visible:
            self.view.raise_()
            self._timer.start()
            self._render()
        else:
            self._timer.stop()
        self.view.set_motion_enabled(visible and self.motion and not self._practicing())

    def _tick(self):
        """刷新内存活动与低频成长展示数据，驱动纯姿态采样及视图呈现。"""
        if self._stopped:
            return
        activity = self.activity_provider.activity()
        self.runtime.update_activity(activity.day,activity.typed,activity.practicing)
        now = time.monotonic()
        if now - self._metric_at >= 1:
            summary=self.activity_provider.growth()
            self._values.update(level=summary.level,streak=summary.streak)
            self._metric_at = now
        self._render()

    def _choose_line(self, lines, key):
        """随机选择话术并尽量避开同状态上一句，避免连续重复回应。"""
        if not lines:
            return ''
        choices = [line for line in lines if line != self._last_line.get(key)] or lines
        line = self.runtime.rng.choice(choices)
        self._last_line[key] = line
        return line

    def _render(self):
        """把当前姿态、素材与安全话术送入视图；智能体反馈让位于练习、互动及奖励。"""
        pose = self.runtime.sample()
        feedback = self._agent_feedback
        if feedback and feedback[2] is not None and time.monotonic() >= feedback[2]:
            self._agent_feedback = feedback = None
        # Agent feedback is visual only; rewards, pats and training retain priority.
        if feedback and pose.kind in ('base', 'meme') and not self._practicing():
            state, line, _ = feedback
            entry = self.pack.entry_for(state)
            self.view.set_content(self.pack.sprite(entry), line if self.bubbles and not self.agent.actions.isVisible() else '',
                self.motion and self.runtime.visible, state=state, token=('agent', state))
            self._last_display = None
            return
        key = (pose.state, pose.kind, pose.token, self.pack.id)
        if key != self._last_display:
            if pose.kind == 'meme' and self.pack.manifest['memes']:
                indices = [i for i in range(len(self.pack.manifest['memes'])) if i != self._last_meme]
                self._last_meme = self.runtime.rng.choice(indices or [0])
                entry = self.pack.manifest['memes'][self._last_meme]
                self.runtime.set_reaction_duration(entry.get('duration_ms', 6000) / 1000)
                pose = self.runtime.sample()
            else:
                entry = self.pack.entry_for(pose.state)
            self._entry = entry
            self._line = format_line(self._choose_line(entry['lines'], pose.state),
                                     {**self._values, 'speed': None, 'accuracy': None, **pose.payload})
            self._last_display = key
            self.view.setToolTip(f"{self.pack.manifest['name']} · {STATES[pose.state]}\n拖出窗口到桌面 / 单击摸头 / 双击互动 / 右键菜单")
        text = self._line if pose.bubble and self.bubbles and not self.agent.actions.isVisible() else ''
        self.view.set_content(self.pack.sprite(self._entry), text,
                              self.motion and self.runtime.visible and not self._practicing(),
                              state=pose.state, token=(pose.kind, pose.token))

    def set_agent_feedback(self, state=None, line='', *, duration=None):
        """记录仅用于显示的智能体姿态/短句与秒级到期时间，不制造奖励业务事件。"""
        self._agent_feedback = ((state, line, time.monotonic() + duration if duration else None)
                                if state else None)
        if not self._stopped:
            self._render()

    def handle_event(self, event):
        """将提交后业务事件或用户互动交给 Runtime 去重/优先级判断，再刷新显示。"""
        state = REACTIONS.get(event.kind, ('idle', 0))[0]
        duration = self.pack.entry_for(state).get('duration_ms', 6000) / 1000
        if self.runtime.react(event, duration):
            self._render()

    def _pet(self):
        """按最近八秒的点击次数选择摸头或戳戳回应，不写入用户输入正文。"""
        now = time.monotonic()
        self._pet_times = [t for t in self._pet_times if now - t < 8] + [now]
        self.handle_event(CompanionEvent('poke' if len(self._pet_times) >= 3 else 'pet'))

    def apply_pack(self, pack_id):
        """载入指定已保存作品并请求保存应用版本，替换当前素材后刷新视图。"""
        pack = self.store.load(pack_id)
        self.presenter.set_settings({'companion_pack': pack_id, 'companion_revision': pack.revision})
        self.pack = pack
        self._last_display = None
        self._render()

    def hide_companion(self):
        """临时收起桌宠并同步可见状态，不更改作品或丢弃配置。"""
        self._hidden = True
        self.sync_visibility()

    def show_companion(self):
        """请求开启桌宠，清除临时隐藏标记并恢复显示。"""
        self.presenter.set_setting('companion_enabled', '1')
        self.enabled = True
        self._hidden = False
        self.sync_visibility()

    def _menu(self, point):
        """创建桌宠右键操作菜单，提供模式、作品、搜索、报告和显示入口。"""
        menu = QMenu(self.view)
        action = menu.addAction('切换到应用内' if self.mode == 'desktop' else '切换到桌面')
        action.triggered.connect(lambda: self.switch_mode('window' if self.mode == 'desktop' else 'desktop'))
        menu.addAction('本地二创工坊…', self.open_workshop)
        menu.addAction('联网搜索…', self.agent.open_search)
        menu.addAction('占卜…', self.agent.oracle.open)
        menu.addAction('来信与定时配置…', self.agent.open_news)
        last_report = menu.addAction('查看最近的搜索报告', self.agent.show_last_report)
        last_report.setEnabled(self.agent.report is not None and not self.agent._busy)
        menu.addAction('桌宠智能体设置…', lambda: self.agent.open_settings())
        menu.addAction('恢复主动互动' if self.runtime.frequency == 'off' else '暂停主动互动', self.toggle_random)
        menu.addSeparator()
        menu.addAction('收起角色', self.hide_companion)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(point)

    def toggle_random(self):
        """在暂停与正常主动互动间切换，保存频率并重排 Runtime 计时。"""
        value = 'normal' if self.runtime.frequency == 'off' else 'off'
        self.presenter.set_setting('companion_frequency', value)
        self.runtime.set_frequency(value)

    def _drag(self, point):
        """拖动在应用边界内时限制位置，移出后切换桌面并延续原手势。"""
        if self.mode == 'window':
            bounds = QRect(self.window.mapToGlobal(QPoint()), self.window.size())
            if bounds.contains(point + self.view._grab_local):
                self.view.move(self._clamp_window(self.window.mapFromGlobal(point)))
                return
            self.switch_mode('desktop', desktop_position=point, keep_drag=True)
        self.view.move(clamp_position(point, self.view.width(), self.view.height()))
        # Persist on release rather than every mouse movement.

    def _save_position(self):
        """分别保存桌面/应用内坐标，避免两种坐标系互相覆盖。"""
        if self.mode == 'desktop':
            self.presenter.set_setting('companion_position', json.dumps([self.view.x(), self.view.y()]))
        else:
            self.presenter.set_setting('companion_window_position', json.dumps([self.view.x(), self.view.y()]))

    def _clamp_window(self, point):
        """把应用内坐标限制在主窗口可容纳视图的范围。"""
        return QPoint(max(0, min(point.x(), self.window.width() - self.view.width())),
                      max(0, min(point.y(), self.window.height() - self.view.height())))

    def _restore_window_position(self):
        """读取应用内保存坐标，格式无效时使用默认位置并限制在窗口内。"""
        point = QPoint(max(0, self.window.width() - self.view.width() - 12),
                       max(50, self.window.height() - 145 - self.view.height()))
        try:
            raw = json.loads(self.presenter.get_setting('companion_window_position', 'null'))
            if isinstance(raw, list) and len(raw) == 2 and all(type(v) is int for v in raw):
                point = QPoint(*raw)
        except (ValueError, TypeError):
            pass
        self.view.move(self._clamp_window(point))

    def _restore_position(self):
        """读取桌面保存坐标，格式无效时使用默认位置并限制在可用屏幕内。"""
        area = available_screens()[0]
        point = QPoint(area.right() - self.view.width() - 30, area.bottom() - self.view.height() - 30)
        try:
            raw = json.loads(self.presenter.get_setting('companion_position', 'null'))
            if isinstance(raw, list) and len(raw) == 2 and all(type(v) is int for v in raw):
                point = QPoint(*raw)
        except (ValueError, TypeError):
            pass
        self.view.move(clamp_position(point, self.view.width(), self.view.height()))

    def _watch_screens(self):
        """重新绑定当前屏幕的可用区域、几何与 DPI 变化信号，解除旧连接。"""
        for screen in self._screens:
            if isValid(screen):
                for signal in (screen.availableGeometryChanged, screen.geometryChanged,
                               screen.logicalDotsPerInchChanged):
                    signal.disconnect(self._screen_changed)
        self._screens = self._screen_app.screens()
        for screen in self._screens:
            for signal in (screen.availableGeometryChanged, screen.geometryChanged,
                           screen.logicalDotsPerInchChanged):
                signal.connect(self._screen_changed)

    def _screen_changed(self, *_):
        """显示器/DPI 改变后刷新监听，并将桌宠恢复到仍可用的屏幕范围。"""
        if self._stopped:
            return
        self._watch_screens()
        if self.mode == 'desktop':
            self.view.move(clamp_position(self.view.pos(), self.view.width(), self.view.height()))

    def eventFilter(self, watched, event):
        """主窗口显示、隐藏、最小化或缩放后排队同步桌宠可见性。"""
        if watched is self.window and self._started and event.type() in (
                QEvent.Show, QEvent.Hide, QEvent.WindowStateChange, QEvent.Resize):
            QTimer.singleShot(0, self.sync_visibility)
        return False

    def open_workshop(self):
        """创建或复用本地作品工坊，保留其草稿并激活窗口。"""
        from .workshop import Workshop
        if self._workshop is None:
            self._workshop = Workshop(self.store, self, self.window)
        self._workshop.show()
        self._workshop.raise_()
        self._workshop.activateWindow()

    def shutdown(self):
        """保存位置并幂等停止智能体、动效、视图及屏幕监听，供退出流程调用。"""
        if self._stopped:
            return
        self._save_position()
        self._stopped = True
        self.agent.shutdown()
        self._timer.stop()
        self.runtime.set_visible(False)
        self.view.shutdown()
        self.view.deleteLater()
        if self._workshop is not None:
            self._workshop.hide()
        self._screen_app.screenRemoved.disconnect(self._screen_changed)
        self._screen_app.screenAdded.disconnect(self._screen_changed)
        self._screen_app.aboutToQuit.disconnect(self.shutdown)
        for screen in self._screens:
            if isValid(screen):
                for signal in (screen.availableGeometryChanged, screen.geometryChanged,
                               screen.logicalDotsPerInchChanged):
                    signal.disconnect(self._screen_changed)
        self._screens = []
