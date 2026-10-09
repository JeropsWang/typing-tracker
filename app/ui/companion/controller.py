"""Main-thread owner of one companion, one runtime, and the active creation."""
import json
import time
from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, QEvent
from PySide6.QtWidgets import QApplication, QMenu
from shiboken6 import isValid

from ...companion.models import CompanionEvent, STATES, format_line
from ...companion.packs import DEFAULT_PACK, PackStore
from ...companion.runtime import Runtime, REACTIONS
from ...services.exp_service import level_and_progress
from .desktop import available_screens, clamp_position
from .view import CompanionView


class CompanionController(QObject):
    def __init__(self, window, repo, data_dir):
        super().__init__(window)
        self.window, self.repo = window, repo
        self.store = PackStore(data_dir)
        self.runtime = Runtime()
        self.view = CompanionView(window)
        self.mode = 'window'
        self._hidden = False
        self._stopped = False
        self._started = False
        self._workshop = None
        self._last_display = None
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
        if self._started:
            return
        self._started = True
        self.sync_settings()
        if self.warning:
            self.window.show_toast('角色作品', self.warning)

    def sync_settings(self):
        self.enabled = self.repo.get_setting('companion_enabled', '1') != '0'
        self.bubbles = self.repo.get_setting('companion_bubbles', '1') != '0'
        self.motion = self.repo.get_setting('reduced_motion', '0') != '1'
        self.runtime.set_frequency(self.repo.get_setting('companion_frequency', 'normal'))
        try:
            size = int(self.repo.get_setting('companion_size', '160'))
        except ValueError:
            size = 160
        self.view.set_character_size(size)
        self._values['nickname'] = self.repo.get_setting('nickname', '打字新星') or '打字新星'
        mode = self.repo.get_setting('companion_mode', 'window')
        self.switch_mode(mode if mode in ('window', 'desktop') else 'window', persist=False)
        self._last_display = None
        self._tick()

    def switch_mode(self, mode, *, persist=True, desktop_position=None, keep_drag=False):
        if mode not in ('window', 'desktop') or self._stopped:
            return
        drag = None
        if persist:
            self.repo.set_setting('companion_mode', mode)
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
        return any(bool(getattr(getattr(self.window, name, None), '_running', False))
                   for name in ('_challenge_page', '_english_page'))

    def sync_visibility(self):
        if not self._started or self._stopped:
            return
        visible = self.enabled and not self._hidden and (
            self.mode == 'desktop' or (self.window.isVisible() and not self.window.isMinimized()))
        self.runtime.set_visible(visible)
        snap = self.window._engine.snapshot()
        self.runtime.update_activity(snap['day'], snap['typed'], self._practicing())
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
        if self._stopped:
            return
        snap = self.window._engine.snapshot()
        self.runtime.update_activity(snap['day'], snap['typed'], self._practicing())
        now = time.monotonic()
        if now - self._metric_at >= 1:
            level, _, _ = level_and_progress(self.repo.get_exp(), self.window._balance)
            if self._last_level is not None and level > self._last_level:
                self.handle_event(CompanionEvent('level', {'level': level}, f'level:{level}'))
            self._last_level = level
            self._values.update(level=level, streak=self.repo.get_streak(snap['day']))
            self._metric_at = now
        self._render()

    def _choose_line(self, lines, key):
        if not lines:
            return ''
        choices = [line for line in lines if line != self._last_line.get(key)] or lines
        line = self.runtime.rng.choice(choices)
        self._last_line[key] = line
        return line

    def _render(self):
        pose = self.runtime.sample()
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
        text = self._line if pose.bubble and self.bubbles else ''
        self.view.set_content(self.pack.sprite(self._entry), text,
                              self.motion and self.runtime.visible and not self._practicing(),
                              state=pose.state, token=(pose.kind, pose.token))

    def handle_event(self, event):
        state = REACTIONS.get(event.kind, ('idle', 0))[0]
        duration = self.pack.entry_for(state).get('duration_ms', 6000) / 1000
        if self.runtime.react(event, duration):
            self._render()

    def _pet(self):
        now = time.monotonic()
        self._pet_times = [t for t in self._pet_times if now - t < 8] + [now]
        self.handle_event(CompanionEvent('poke' if len(self._pet_times) >= 3 else 'pet'))

    def apply_pack(self, pack_id):
        pack = self.store.load(pack_id)
        self.repo.set_settings({'companion_pack': pack_id, 'companion_revision': pack.revision})
        self.pack = pack
        self._last_display = None
        self._render()

    def hide_companion(self):
        self._hidden = True
        self.sync_visibility()

    def show_companion(self):
        self.repo.set_setting('companion_enabled', '1')
        self.enabled = True
        self._hidden = False
        self.sync_visibility()

    def _menu(self, point):
        menu = QMenu(self.view)
        action = menu.addAction('切换到应用内' if self.mode == 'desktop' else '切换到桌面')
        action.triggered.connect(lambda: self.switch_mode('window' if self.mode == 'desktop' else 'desktop'))
        menu.addAction('本地二创工坊…', self.open_workshop)
        menu.addAction('恢复主动互动' if self.runtime.frequency == 'off' else '暂停主动互动', self.toggle_random)
        menu.addSeparator()
        menu.addAction('收起角色', self.hide_companion)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(point)

    def toggle_random(self):
        value = 'normal' if self.runtime.frequency == 'off' else 'off'
        self.repo.set_setting('companion_frequency', value)
        self.runtime.set_frequency(value)

    def _drag(self, point):
        if self.mode == 'window':
            bounds = QRect(self.window.mapToGlobal(QPoint()), self.window.size())
            if bounds.contains(point + self.view._grab_local):
                self.view.move(self._clamp_window(self.window.mapFromGlobal(point)))
                return
            self.switch_mode('desktop', desktop_position=point, keep_drag=True)
        self.view.move(clamp_position(point, self.view.width(), self.view.height()))
        # Persist on release rather than every mouse movement.

    def _save_position(self):
        if self.mode == 'desktop':
            self.repo.set_setting('companion_position', json.dumps([self.view.x(), self.view.y()]))
        else:
            self.repo.set_setting('companion_window_position', json.dumps([self.view.x(), self.view.y()]))

    def _clamp_window(self, point):
        return QPoint(max(0, min(point.x(), self.window.width() - self.view.width())),
                      max(0, min(point.y(), self.window.height() - self.view.height())))

    def _restore_window_position(self):
        point = QPoint(max(0, self.window.width() - self.view.width() - 12),
                       max(50, self.window.height() - 145 - self.view.height()))
        try:
            raw = json.loads(self.repo.get_setting('companion_window_position', 'null'))
            if isinstance(raw, list) and len(raw) == 2 and all(type(v) is int for v in raw):
                point = QPoint(*raw)
        except (ValueError, TypeError):
            pass
        self.view.move(self._clamp_window(point))

    def _restore_position(self):
        area = available_screens()[0]
        point = QPoint(area.right() - self.view.width() - 30, area.bottom() - self.view.height() - 30)
        try:
            raw = json.loads(self.repo.get_setting('companion_position', 'null'))
            if isinstance(raw, list) and len(raw) == 2 and all(type(v) is int for v in raw):
                point = QPoint(*raw)
        except (ValueError, TypeError):
            pass
        self.view.move(clamp_position(point, self.view.width(), self.view.height()))

    def _watch_screens(self):
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
        if self._stopped:
            return
        self._watch_screens()
        if self.mode == 'desktop':
            self.view.move(clamp_position(self.view.pos(), self.view.width(), self.view.height()))

    def eventFilter(self, watched, event):
        if watched is self.window and self._started and event.type() in (
                QEvent.Show, QEvent.Hide, QEvent.WindowStateChange, QEvent.Resize):
            QTimer.singleShot(0, self.sync_visibility)
        return False

    def open_workshop(self):
        from .workshop import Workshop
        if self._workshop is None:
            self._workshop = Workshop(self.store, self, self.window)
        self._workshop.show()
        self._workshop.raise_()
        self._workshop.activateWindow()

    def shutdown(self):
        if self._stopped:
            return
        self._save_position()
        self._stopped = True
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
