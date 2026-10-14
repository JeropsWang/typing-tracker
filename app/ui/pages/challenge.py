"""打字竞速挑战页：范文对照输入 → 逐字高亮 → 实时指标 → 成绩与历史最佳。

- 正确率 = 与原文逐字对比（精确口径，区别于全局按键近似）
- 文本来源：内置范文 + AI 生成（OpenAI 兼容 / Ollama 本地，可持久化）
- 挑战中的输入会计入今日全局统计（说明见页面提示）
- 纸张与输入由独立组件呈现；窗口尺寸由共享布局策略计算
"""
from __future__ import annotations
from ..presenters import QueryPresenter, PracticePresenter, PracticeState
from ...bootstrap.features import save_material
from ..tasks import TaskBridge, begin_network, cancel_network, finish_network_result
import uuid

import html
import time
import threading

from PySide6.QtCore import Qt, QEvent, QObject, QTimer, Signal
from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ...modules.practice.api import TEXTS
from ...modules.growth.api import level_and_progress
from ...modules.growth.api import AITestSession
from ..palette import P
from ..widgets.ai_passage_composer import AIPassageComposer
from ..widgets.training_workspace import TrainingWorkspace
from ..widgets.practice_leaderboard import PracticeLeaderboard
from ..widgets.keyboard_warrior import KeyboardWarriorPanel
from ..widgets.chaos import ChaosPanel
from ..widgets.responsive import stage_layout_for
from ..widgets.design import (
    ArtTitle, Disclosure, Panel, is_compact, paper_padding,
)


# 构造期占位；实际尺寸统一由 responsive.StageLayout 覆盖。
ART_HEIGHT = 220
MARGIN_X, MARGIN_TOP = 48, 44
SECONDARY_MIN, SECONDARY_MAX = 54, 62
BEFORE_PAPER, AFTER_PAPER = 50, 16
DEFAULT_SIZE = (900, 640)


def _fixed_gap(layout, height: int) -> QSpacerItem:
    """固定高度间隙；紧凑窗口按 frames 改高度（QVBoxLayout.addSpacing 不返回对象）。"""
    spacer = QSpacerItem(0, height, QSizePolicy.Minimum, QSizePolicy.Fixed)
    layout.addSpacerItem(spacer)
    return spacer


class _GenThread(QObject):
    """AI 范文生成线程：done(ok, text, err)"""

    done = Signal(bool, str, str)
    finished = Signal()

    def __init__(self, ai_svc, topic, lang, length, parent=None, *, test_mode=False):
        """建立普通训练与生成材料组件的依赖与初始状态。"""
        super().__init__(parent)
        # 构造发生在主线程：先读配置，run() 中的网络调用不再访问 SQLite。
        self.id = uuid.uuid4().hex
        self._valid = True
        self._svc = ai_svc.snapshot()
        self._topic = topic
        self._lang = lang
        self._length = length
        self.test_mode = test_mode
        self.usage = None
        self._thread = None

    def start(self):
        """通过共享准入启动配置快照的材料生成，结果只经 Qt 信号回传。"""
        def deliver(result):
            """将完整 AIResult 转为生成完成信号，不在网络线程操作控件。"""
            self.done.emit(result.ok,result.body if result.ok else '',result.error)
        begin_network(self,self._svc,
                      lambda:self._svc.generate(self._topic,self._lang,self._length),deliver)

    def cancel(self):
        """使本次结果无效，网络真正结束前仍持有共享准入。"""
        cancel_network(self)

    def isRunning(self):
        """判断所属后台传输线程是否仍活跃，供按钮忙碌资格使用。"""
        return self._thread is not None and self._thread.is_alive()


class ChallengePage(QWidget):
    """Qt 主线程普通训练/键盘侠/混乱模式协调页，生成与成绩写入异步，保存失败原结果重试。"""
    result_saved = Signal(dict)
    running_changed = Signal(bool)
    confetti_requested = Signal(int)    # 彩带庆祝（1=金色 2=多彩）
    settings_requested = Signal()

    def __init__(self, repo, balance, challenge_svc, ai_service=None, parent=None, *, test_session=None):
        """建立普通训练与生成材料组件的依赖与初始状态。"""
        super().__init__(parent)
        self._presenter = PracticePresenter(repo,challenge_svc)
        self._tasks = TaskBridge(self)
        self._balance = balance
        self._svc = challenge_svc
        self._ai = ai_service
        self._ai_session = test_session or AITestSession()
        self._running = False
        self._practice_running = False
        self._keyboard_active = False
        self._start_ts = 0.0
        self._elapsed = 0.0
        self._gen_thread = None
        self._pending_material = None
        self._material_saving = False
        self._compact = None
        self._paper_w = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        modes = QHBoxLayout()
        self._mode_row = modes
        modes.setContentsMargins(48, 8, 48, 0)
        self.mode_buttons = {}
        self._mode_group = QButtonGroup(self)
        for key, title in [('practice', '范文练习'), ('keyboard', '键盘侠 · 15 秒'), ('chaos', '混乱 · 60 字')]:
            button = QPushButton(title)
            button.setCheckable(True)
            button.setProperty('growthTab', True)
            button.setMinimumHeight(36)
            button.clicked.connect(lambda checked=False, mode=key: self._select_mode(mode))
            self._mode_group.addButton(button)
            self.mode_buttons[key] = button
            modes.addWidget(button)
        modes.addStretch()
        self.mode_buttons['practice'].setChecked(True)
        outer.addLayout(modes)
        self._module_stack = QStackedWidget()
        outer.addWidget(self._module_stack)
        self._page_scroll = QScrollArea(self)
        self._page_scroll.setFrameShape(QFrame.NoFrame)
        self._page_scroll.setWidgetResizable(True)
        self._page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName('challengeCanvas')
        self._page_scroll.setStyleSheet(
            'QScrollArea { background: transparent; border: none; }'
            'QWidget#challengeCanvas { background: transparent; }')
        self._page_scroll.viewport().setAutoFillBackground(False)
        self._page_scroll.setWidget(canvas)
        self._module_stack.addWidget(self._page_scroll)
        self.keyboard_panel = KeyboardWarriorPanel(repo, balance)
        self.chaos_panel = ChaosPanel(ai_service)
        self.keyboard_panel.running_changed.connect(self._keyboard_running)
        self.chaos_panel.settings_requested.connect(self.settings_requested.emit)
        self._module_stack.addWidget(self.keyboard_panel)
        self._module_stack.addWidget(self.chaos_panel)
        root = QVBoxLayout(canvas)
        self._root = root
        root.setContentsMargins(MARGIN_X, MARGIN_TOP, MARGIN_X, 0)
        root.setSpacing(0)

        # 艺术标题（交付 SVG，已转曲）+ 装饰短句（紧凑窗口按规范省去）
        self._art = ArtTitle()
        self._art.setFixedHeight(ART_HEIGHT)
        art_row = QHBoxLayout()
        art_row.setContentsMargins(0, 0, 0, 0)
        art_row.addWidget(self._art, 0, Qt.AlignLeft | Qt.AlignTop)
        art_row.addStretch(1)
        root.addLayout(art_row)
        self._decoration = QLabel('一点点练习，也会成为很亮的光。')
        self._decoration.setProperty('textRole', 'muted')
        root.addWidget(self._decoration)
        self._before_paper = _fixed_gap(root, BEFORE_PAPER)

        # ---- 纸张：范文选择 / 范文 / 输入 / 实时指标 + 主动作 ----
        paper_row = QHBoxLayout()
        paper_row.setContentsMargins(0, 0, 0, 0)
        self._paper = TrainingWorkspace()
        self._paper_layout = self._paper.content
        paper_row.addWidget(self._paper, 0, Qt.AlignTop)
        paper_row.addStretch(1)
        root.addLayout(paper_row)
        # 页面保留服务编排和兼容访问点，控件构造与几何归 TrainingWorkspace。
        self._text_combo = self._paper.source_combo
        self._combo_box = self._combo_field = self._paper.source_field
        self._reset_btn = self._paper.restart_button
        self._ref_hint = self._paper.reference_hint
        self._next_btn = self._paper.next_button
        self._ref_label = self._paper.reference
        self._input = self._paper.input
        self._metrics_box = self._paper.metrics
        self._metrics_row = self._paper.actions
        self._metric_labels = self._paper.metric_labels
        self._time_label, self._speed_label, self._acc_label, self._prog_label = self._metric_labels
        self._start_btn = self._paper.start_button
        self._paper.source_changed.connect(self._reset)
        self._paper.restart_requested.connect(self._reset)
        self._paper.next_requested.connect(self._next_text)
        self._paper.start_requested.connect(self._start)
        self._paper.input_changed.connect(self._on_text_changed)
        self._paper.paste_blocked.connect(self._on_paste_blocked)

        # ---- 次级区（状态 / 结果 / AI / 历史）：页内滚动，紧凑尺寸不消失 ----
        self._secondary_gap = _fixed_gap(root, AFTER_PAPER)
        strip = QHBoxLayout()
        strip.setContentsMargins(paper_padding(), 0, 0, 0)
        self._strip = strip
        self._secondary = QScrollArea()
        self._secondary.setFrameShape(QFrame.NoFrame)
        self._secondary.setWidgetResizable(True)
        self._secondary.setMinimumHeight(SECONDARY_MIN)
        self._secondary.setMaximumHeight(SECONDARY_MAX)
        sec_body = QWidget()
        self._secondary_content = QVBoxLayout(sec_body)
        self._secondary_content.setContentsMargins(32, 0, 32, 0)
        self._secondary_content.setSpacing(10)
        self._secondary.setWidget(sec_body)
        sec_body.installEventFilter(self)
        strip.addWidget(self._secondary)
        strip.addStretch(1)
        root.addLayout(strip)

        # 状态条 = 设计稿的次级单行条：状态文本 + AI/历史折叠入口（紧凑也不被裁掉）
        self._status_strip = Panel()
        self._entry_row = QHBoxLayout(self._status_strip)
        self._entry_row.setContentsMargins(16, 8, 16, 8)
        self._entry_row.setSpacing(16)
        self._hint_label = QLabel('练习输入会计入今日统计；与范文不同的字符会加下划线。')
        self._hint_label.setWordWrap(True)
        self._hint_label.setProperty('textRole', 'muted')
        self._status_text = (self._hint_label.text(), '')
        self._entry_row.addWidget(self._hint_label, 1)
        self._secondary_content.addWidget(self._status_strip)

        # 结果（完成状态；与 AI / 历史共用同一可滚动底部区域）
        self._result = Panel()
        rv = QVBoxLayout(self._result)
        rv.setContentsMargins(16, 12, 16, 12)
        rv.setSpacing(4)
        result_head = QHBoxLayout()
        result_head.setContentsMargins(0, 0, 0, 0)
        result_head.setSpacing(14)
        self._result_title = QLabel('')
        self._result_title.setProperty('textRole', 'heading')
        self._score_label = QLabel('0')
        self._score_label.setProperty('textRole', 'metric')
        self._score_unit = QLabel('练习得分 · 按速度、有效字数与正确率计算')
        self._score_unit.setProperty('textRole', 'muted')
        self._score_unit.setWordWrap(True)
        result_head.addWidget(self._result_title)
        result_head.addWidget(self._score_label)
        result_head.addWidget(self._score_unit, 1)
        rv.addLayout(result_head)
        self._result_detail = QLabel('')
        self._result_detail.setWordWrap(True)
        self._result_detail.setProperty('textRole', 'muted')
        rv.addWidget(self._result_detail)
        self._result.hide()
        self._secondary_content.addWidget(self._result)
        self._score_anim = QTimer(self)
        self._score_anim.timeout.connect(self._tick_score)
        self._score_now = self._score_target = 0

        if self._ai is not None:
            self._ai_section = Disclosure('AI 定制范文', self)
            self._ai_section.hide()
            self._ai_composer = AIPassageComposer()
            self._topic_edit = self._ai_composer.topic_edit
            self._lang_combo = self._ai_composer.language_combo
            self._ai_btn = self._ai_composer.generate_button
            self._ai_status = self._ai_composer.status_label
            self._ai_access_label = self._ai_composer.access_label
            self._ai_composer.generate_requested.connect(self._ai_generate)
            self._ai_composer.settings_requested.connect(self.settings_requested.emit)
            self._ai_composer.back_requested.connect(lambda: self._ai_section.toggle.setChecked(False))
            self._ai_section.toggle.toggled.connect(self._show_ai_workspace)
            root.insertWidget(4, self._ai_composer, 0, Qt.AlignLeft)
            self._ai_composer.hide()
            self._entry_row.insertWidget(0, self._entry_style(self._ai_section.detach_toggle()))

        recent = Disclosure('记录 / 个人榜')
        self._recent_disclosure = recent
        self._recent_label = QLabel('')
        self._recent_label.setWordWrap(True)
        self._recent_label.setTextFormat(Qt.PlainText)
        self._recent_label.setProperty('textRole', 'muted')
        recent.content.addWidget(self._recent_label)
        self._leaderboard = PracticeLeaderboard()
        recent.content.addWidget(self._leaderboard)
        self._entry_row.insertWidget(1, self._entry_style(recent.detach_toggle()))
        self._secondary_content.addWidget(recent)
        recent.hide()
        recent.toggle.toggled.connect(recent.setVisible)
        self._secondary_content.addStretch(1)
        root.addStretch(1)      # 余量留在导航上方，次级区保持设计高度

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # 纸张宽度变化后文档要重新折行，行数会变；等宽度真正落到控件上再重算
        # 范文区高度（否则 set 宽度的那一次调用里读到的还是旧折行结果）。
        self._ref_label.installEventFilter(self)
        self.set_compact(is_compact(*DEFAULT_SIZE))
        self._reload_texts()
        self._refresh_recent()
        self.apply_theme()

    # ---------- 版式 ----------
    def _select_mode(self, mode):
        """非保存/待重试期间切换训练模块，取消离开的生成任务并恢复相应只读展示。"""
        if self._presenter.state in (PracticeState.SAVING,PracticeState.SAVE_FAILED):
            return
        target = {'practice': self._page_scroll, 'keyboard': self.keyboard_panel,
                  'chaos': self.chaos_panel}[mode]
        if target is self._module_stack.currentWidget():
            return
        if self._module_stack.currentWidget() is self._page_scroll and self._running:
            self._reset()
        if target is not self._page_scroll:
            self._cancel_generation()
        self._module_stack.setCurrentWidget(target)
        if mode == 'keyboard':
            self.keyboard_panel.refresh()
        elif mode == 'practice':
            self.update_ai_access()
            self._sync_controls()

    def _keyboard_running(self, running):
        """聚合键盘侠和普通练习状态，通知全局/桌宠暂停装饰动效。"""
        self._keyboard_active = running
        self._running = self._practice_running or self._keyboard_active
        self.running_changed.emit(self._running)

    def _stage_layout(self):
        """取得当前页面尺寸的统一响应式布局模型。"""
        return stage_layout_for(self)

    def _paper_width(self):
        """从统一布局模型取得正文纸张目标宽度。"""
        return self._stage_layout().content_width

    def set_compact(self, compact):
        """更新普通训练与生成材料的紧凑布局、间距和尺寸约束。"""
        self._compact = self._stage_layout().compact
        stage = self._stage_layout()
        self._root.setContentsMargins(stage.margin_x, stage.margin_top, stage.margin_x, 0)
        self._art.set_compact(self._compact)
        self._decoration.setFixedHeight(16)
        self._decoration.setVisible(True)
        self._secondary_gap.changeSize(0, stage.blend(4, 16))
        self._strip.setContentsMargins(stage.paper_padding, 0, 0, 0)
        self._secondary_content.setContentsMargins(0, 0, 0, 0)
        self._entry_row.setContentsMargins(12, 4, 12, 4)
        self._entry_row.setSpacing(stage.blend(10, 16))
        if self._ai is not None:
            self._ai_section.set_toggle_label('AI 范文' if self._compact else 'AI 定制范文')
            self._ai_composer.set_stage_layout(stage)
        self._recent_disclosure.set_toggle_label('个人榜' if self._compact else '记录 / 个人榜')
        text, short = getattr(self, '_status_text', ('', ''))
        self._hint_label.setText(short if (self._compact and short) else text)
        self._sync_workspace_header()
        self._apply_widths()
        self._sync_secondary_height()
        self._schedule_widths()

    def _sync_primary_size(self):
        """强制同步训练工作区的尺寸和间距。"""
        self._paper.apply_layout(self._stage_layout(), force=True)

    def _apply_paper_height(self):
        # 纸张随可用高度增长，长范文保持内部滚动，避免整页被撑成巨长表单。
        """按实际内容最小高度与响应式目标设置纸张，长正文留内部滚动。"""
        height = max(self._stage_layout().training_height, self._paper_layout.minimumSize().height())
        self._paper.setFixedHeight(height)

    def _apply_widths(self):
        """同步训练纸张、结果/排行榜区域与 AI 话题纸张宽度。"""
        stage = self._stage_layout()
        self._paper.apply_layout(stage, force=True)
        self._paper_w = stage.content_width
        strip_width = stage.content_width - 2 * stage.paper_padding
        self._secondary.setFixedWidth(max(240, strip_width))
        composer = getattr(self, '_ai_composer', None)
        if composer is not None:
            composer.setFixedWidth(stage.composer_width)
            composer.set_stage_layout(stage)

    def _schedule_widths(self) -> None:
        """主题 QSS 重新 polish 会把下拉框的宽度约束复位（实测切主题后 combo 被拉回
        容器宽度并被顶出纸张），所以在本轮事件循环结束后再按当前纸张宽度重算一次；
        重算后立刻激活布局，避免只跑一轮事件时几何停在旧值上。"""
        if getattr(self, '_widths_pending', False):
            return
        self._widths_pending = True

        def run():
            """在 Qt 布局下一拍统一重算宽度和选择器几何，合并重复排版请求。"""
            self._widths_pending = False
            if getattr(self, '_paper', None) is None:
                return
            self._apply_widths()
            layout = self._combo_box.layout()
            if layout is not None:
                layout.activate()
            self._combo_box.updateGeometry()

        QTimer.singleShot(0, run)

    def resizeEvent(self, event):
        """更新紧凑布局并排队在折行完成后测量正文/纸张高度。"""
        if getattr(self, '_paper', None) is not None:
            self.set_compact(is_compact(self.width(), self.height()))
            # 宽度落到控件上之后文档才重新折行，纸张高度要等这一拍再量
            QTimer.singleShot(0, self._sync_reference_height)
            QTimer.singleShot(0, self._apply_paper_height)
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        """范文控件宽度变了 → 折行结果会变，等 Qt 本轮布局走完再重算高度。

        resize 事件里立刻量到的还是**旧宽度**下的折行结果（实测：setFixedWidth
        之后马上读 document().size() 仍是一行 44px，把范文区压回 57），所以延到
        事件循环的下一拍；_sync_reference_height 自身有幂等判断，不会来回抖。
        """
        if obj is getattr(self, '_ref_label', None) and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._sync_reference_height)
            QTimer.singleShot(0, self._apply_paper_height)
        secondary = getattr(self, '_secondary', None)
        if secondary is not None and obj is secondary.widget() and event.type() == QEvent.LayoutRequest:
            self._sync_secondary_height()
        return super().eventFilter(obj, event)

    def _sync_secondary_height(self):
        """按结果/历史是否展开计算副区高度，避免旧固定高度裁切内容。"""
        secondary = getattr(self, '_secondary', None)
        if secondary is None:
            return
        expanded = (getattr(self, '_recent_disclosure', None) is not None
                    and self._recent_disclosure.toggle.isChecked())
        expanded = expanded or (getattr(self, '_result', None) is not None
                                and not self._result.isHidden())
        if expanded:
            layout = secondary.widget().layout()
            width = max(1, secondary.width())
            height = max(180, layout.minimumSize().height(), layout.sizeHint().height(),
                         layout.heightForWidth(width)) + 8
        else:
            height = self._stage_layout().blend(60, 62)
        if secondary.minimumHeight() != height or secondary.maximumHeight() != height:
            secondary.setFixedHeight(height)
            secondary.updateGeometry()

    def _show_ai_workspace(self, visible):
        """切换书写工作区，不重置训练或 AI 草稿。"""
        self._paper.setVisible(not visible)
        self._ai_composer.setVisible(visible)
        self._secondary.setVisible(not visible)
        self._art.set_role('ai' if visible else 'training')
        self._art.setAccessibleName('把灵感 敲成星光' if visible else '今天也要 闪闪发光')
        self._decoration.setText('给下一段练习，写一点喜欢的故事。' if visible
                                 else '一点点练习，也会成为很亮的光。')
        self._sync_workspace_header()
        self._apply_widths()
        self._root.activate()
        self._page_scroll.verticalScrollBar().setValue(0)

    def _sync_workspace_header(self):
        """按话题区展开状态调整艺术字和留白，为真实模式选择控件预留空间。"""
        stage = self._stage_layout()
        expanded = (getattr(self, '_ai_section', None) is not None
                    and self._ai_section.toggle.isChecked())
        height = stage.blend(98, 220) if expanded else stage.hero_height
        # Reserve the selector from decorative header space, preserving paper tokens.
        height = max(44, height - self._mode_row.sizeHint().height())
        self._art.setFixedSize(round(height * 650 / 220), height)
        self._before_paper.changeSize(0, stage.blend(6, 24) if expanded else stage.paper_gap)
        self._root.invalidate()

    # ---------- 文本库 ----------
    def _reload_texts(self):
        """合并内置与已保存 AI 材料，更新选择器后重置临时练习状态。"""
        self._texts = list(TEXTS)
        for row in self._presenter.list_ai_texts():
            self._texts.append({
                'id': f'ai:{row["id"]}',
                'name': f'AI · {row["topic"]}',
                'lang': row['lang'],
                'text': row['text'],
            })
        self._text_combo.blockSignals(True)
        self._text_combo.clear()
        for t in self._texts:
            self._text_combo.addItem(t['name'], t['id'])
        self._text_combo.blockSignals(False)
        self._reset()

    def _current_text(self) -> str:
        """取得当前材料纯文本，找不到选择时回退首条有效材料。"""
        tid = self._text_combo.currentData()
        for t in self._texts:
            if t['id'] == tid:
                return t['text']
        return self._texts[0]['text']

    def _text_name(self, tid: str) -> str:
        """把材料 ID 转为显示名称，未知 ID 保留其标识。"""
        for t in self._texts:
            if t['id'] == tid:
                return t['name']
        return tid

    def _next_text(self):
        """换一篇：仅在待开始状态可用（练习中不能换范文）。"""
        if self._running or self._busy() or self._text_combo.count() < 2:
            return
        index = (self._text_combo.currentIndex() + 1) % self._text_combo.count()
        self._text_combo.setCurrentIndex(index)

    # ---------- AI 定制训练 ----------
    def update_ai_access(self):
        """等级/训练券访问控制（升级后由主窗口调用刷新）。"""
        if self._ai is None:
            self._sync_controls()
            return
        if self._running or self._busy():
            self._ai_btn.setEnabled(False)
            self._topic_edit.setEnabled(False)
            self._lang_combo.setEnabled(False)
            self._sync_controls()
            return
        self._lang_combo.setEnabled(True)
        if not self._ai.enabled():
            self._ai_btn.setEnabled(False)
            self._topic_edit.setEnabled(False)
            self._ai_access_label.setText('AI 未启用：设置 → AI 配置（支持 OpenAI 兼容 / Ollama）')
            self._sync_controls()
            return
        level, _, _ = level_and_progress(self._presenter.get_exp(), self._balance)
        passes = self._presenter.count_ai_passes()
        unlock = self._balance.get('ai', {}).get('unlock_level', 45)
        allowed, hint = self._ai_session.access(level, passes, unlock)
        self._ai_btn.setEnabled(allowed)
        self._topic_edit.setEnabled(allowed)
        self._ai_access_label.setText(hint)
        self._sync_controls()

    def _ai_generate(self):
        """资格允许时冻结话题/语言启动生成；已有待保存材料则只重试保存。"""
        if self._pending_material is not None:
            if not self._material_saving:
                self._save_material()
            return
        if self._ai is None or self._running or self._busy() or not self._ai_btn.isEnabled():
            return
        topic = self._topic_edit.text().strip()
        if not topic:
            self._ai_composer.set_status('请先输入练习主题。')
            return
        # 生成前预检库存：曾等生成成功后才扣券，券不足时 API 已计费而文本
        # 被丢弃（v0.8.9 修复）
        level, _, _ = level_and_progress(self._presenter.get_exp(), self._balance)
        unlock = self._balance.get('ai', {}).get('unlock_level', 45)
        if level < unlock and not self._ai_session.enabled and self._presenter.count_ai_passes() <= 0:
            self._ai_composer.set_status('AI 训练券不足（速度跃升可获得训练券）', 'error')
            return
        self._generation = (topic, self._lang_combo.currentData())
        self._ai_btn.setEnabled(False)
        self._topic_edit.setEnabled(False)
        self._lang_combo.setEnabled(False)
        self._ai_composer.set_status('生成中…（本地模型可能较慢）')
        self._ai_composer.usage_label.begin_request()
        self._gen_thread = _GenThread(self._ai, topic,
                                      self._lang_combo.currentData(), 260, self,
                                      test_mode=self._ai_session.enabled)
        self._gen_thread.done.connect(self._ai_done)
        self._gen_thread.finished.connect(self._generation_finished)
        try:
            self._gen_thread.start()
        except Exception as error:
            self._ai_composer.set_status(str(error),'error')
            self._gen_thread.deleteLater()
            self._gen_thread=None
            self.update_ai_access()
        self._sync_controls()

    def _generation_finished(self):
        """传输结束后释放请求对象展示引用，待保存材料仍单独保留。"""
        thread = self._gen_thread
        self._gen_thread = None
        if thread is not None and self._pending_material is None:
            thread.deleteLater()
        self._sync_controls()
        self.update_ai_access()

    def _ai_done(self,ok,text,err):
        """接收有效生成结果与用量，成功正文留给独立事务保存，不直接扣券。"""
        request=self._gen_thread
        if request is not None and not getattr(request,'_valid',True):
            finish_network_result(request)
            return
        self._ai_composer.usage_label.set_usage(request.usage if request is not None else None)
        if not ok:
            self._ai_composer.set_status(f'生成失败：{err}','error')
            if request is not None:
                finish_network_result(request)
            return
        topic,lang=self._generation
        self._pending_material=(request,getattr(request,'id',uuid.uuid4().hex),lang,topic,text,
                                bool(request and request.test_mode))
        self._save_material()

    def _save_material(self):
        """用原请求操作 ID 保存材料及资格消费，失败重试不再次生成。"""
        request,operation_id,lang,topic,text,test_mode=self._pending_material
        self._material_saving=True
        self._ai_btn.setEnabled(False)
        try:
            saved=save_material(self._presenter,self._balance,lang,topic,text,
                                operation_id=operation_id,test_mode=test_mode)
        except Exception as error:
            self._material_failed(error)
            return
        self._tasks.resolve(saved,self._material_saved,self._material_failed)

    def _material_failed(self,error):
        """保留正文和请求身份，开放保存重试并显示错误。"""
        self._material_saving=False
        self._ai_composer.set_status(f'材料未保存，训练券未使用：{error}。点击生成按钮重试保存。','error')
        self._ai_btn.setEnabled(True)

    def _material_saved(self,_):
        """材料已提交后更新范文库并结束结果租约，不再重复消费训练券。"""
        if self._pending_material is None:
            return
        request,operation_id,lang,topic,text,test_mode=self._pending_material
        self._pending_material=None
        self._material_saving=False
        if request is not None:
            finish_network_result(request)
            request.deleteLater()
        self._ai_composer.set_status(f'已生成并加入范文库：{topic}。返回训练即可练习。','success')
        self._reload_texts()
        self.update_ai_access()
        for i,item in enumerate(self._texts):
            if item['id'].startswith('ai:') and item['name'].endswith(topic):
                self._text_combo.setCurrentIndex(i)
                break

    def _cancel_generation(self):
        """取消未接收生成或未受理材料结果，已在保存的事务按提交结果完成。"""
        request=self._gen_thread
        if request is not None:
            request.cancel()
        if self._pending_material is not None and not self._material_saving:
            pending=self._pending_material[0]
            if pending is not None:
                pending.cancel()
                pending.deleteLater()
            self._pending_material=None

    def hideEvent(self,event):
        """离开页面时作废生成结果接收，保留原业务保存边界。"""
        self._cancel_generation()
        super().hideEvent(event)

    # ---------- 主题 ----------
    def apply_theme(self):
        """将当前主题颜色、字号和图标同步到普通训练与生成材料，保持现有业务状态。"""
        self.keyboard_panel.apply_theme()
        self.chaos_panel.apply_theme()
        # 设计稿里范文是纸面上的散文本行（无输入框描边/底色），不是控件方框：
        # 内联样式覆盖主题 QSS 给 QTextBrowser 的 padding:12px + 白底 + 1px 边框。
        # padding 会同时吃掉「视口高度」和「可用行宽」，是叠行的帮凶之一。
        self._ref_label.setStyleSheet(
            f'QTextBrowser {{ font-size:20px; color:{P.paper_text}; '
            f'background:transparent; border:none; padding:0px; }}')
        self._ref_label.document().setDocumentMargin(2)
        self._result_detail.setStyleSheet(
            f'color:{P.surface_muted}; font-size:13px;')   # 深色面板上需 ≥4.5:1
        self._score_label.setStyleSheet(
            f'font-size:32px; font-weight:700; color:{P.accent_ochre};')
        self._result_title.setStyleSheet(f'font-size:16px; font-weight:600; color:{P.text};')
        self._style_input()
        self._sync_primary_size()
        self._render_reference(self._input.toPlainText())
        self.update_ai_access()
        if self._ai is not None:
            self._ai_composer.apply_theme()
        # 主题 QSS 重新 polish 会复位下拉框的宽度约束，等本轮事件结束再按纸张宽度重算
        self._schedule_widths()

    def _style_input(self):
        """输入区为深色书写面（设计稿待开始/运行/完成三态一致），纸面正文与输入对比度达标。"""
        self._input.setStyleSheet(
            f'QPlainTextEdit {{ font-size:20px; padding:12px; background:{P.surface}; '
            f'color:{P.surface_text}; border-radius:12px; border:1px solid {P.border}; }}'
            f'QPlainTextEdit:focus {{ border:2px solid {P.focus}; }}')

    @staticmethod
    def _entry_style(button):
        """次级单行条里的折叠入口：低矮文字按钮，紧凑窗口也能整行落在视口内。"""
        button.setProperty('buttonRole', 'entry')
        style = button.style()
        if style is not None:
            style.unpolish(button)
            style.polish(button)
        return button

    def _set_status(self, text: str, short: str = '') -> None:
        """状态信息就近显示；紧凑窗口用短文案，保证单行条不被撑高。"""
        self._status_text = (text, short)
        self._hint_label.setText(short if (self._compact and short) else text)

    def _busy(self):
        """判断成绩写入或模型传输仍在途，限制互相冲突的操作。"""
        return self._presenter.state == PracticeState.SAVING or (self._gen_thread is not None and self._gen_thread.isRunning())

    def _sync_controls(self):
        """按状态同步主动作、重来与换一篇（状态矩阵：待开始 / 训练中 / 完成）。"""
        busy = self._busy()
        if self._presenter.state == PracticeState.SAVE_FAILED:
            text, enabled = '重试保存', True
        elif self._presenter.state == PracticeState.SAVING:
            text, enabled = '正在保存…', False
        elif self._result.isVisible():
            text, enabled = '练习已完成', False
        elif self._running:
            text, enabled = '练习中…', False
        else:
            text, enabled = '开始练习 →', not busy
        self._start_btn.setText(text)
        self._start_btn.setEnabled(enabled)
        self._text_combo.setEnabled(not self._running and not busy and self._presenter.state != PracticeState.SAVE_FAILED)
        self._next_btn.setEnabled(not self._running and not busy and self._presenter.state != PracticeState.SAVE_FAILED)
        self._reset_btn.setEnabled(self._running or self._result.isVisible())
        section = getattr(self, '_ai_section', None)
        if section is not None:
            section.toggle.setEnabled(not self._running)

    def _set_running(self, running):
        """同步普通/键盘侠聚合练习状态、输入样式和按钮资格。"""
        self._practice_running = running
        self._running = self._practice_running or self._keyboard_active
        self._style_input()
        self._sync_controls()
        self.update_ai_access()
        self.running_changed.emit(self._running)

    # ---------- 流程 ----------
    def _start(self):
        """失败状态复用原成绩保存，其余情况下创建新操作 ID 并开始单调计时。"""
        if self._presenter.state == PracticeState.SAVE_FAILED:
            self._store_result(*self._presenter.pending)
            return
        if self._busy():
            return
        self._reset()
        self._presenter.start()
        self._set_running(True)
        self._start_ts = time.monotonic()
        self._input.setEnabled(True)
        self._input.setFocus()
        self._timer.start(100)
        self._set_status('正在练习 · 输入达到范文长度后自动结算；逐字正确率包含尚未输入的位置。',
                         '正在练习 · 打满自动结算。')

    def _reset(self, *_):
        """非保存期间清理临时练习与反馈，保留已提交材料和历史记录。"""
        if self._presenter.state == PracticeState.SAVING:
            return
        self._presenter.state = PracticeState.IDLE
        self._set_running(False)
        self._timer.stop()
        self._input.setEnabled(False)
        self._input.clear()
        self._time_label.setText('用时 —')
        self._speed_label.setText('速度 — tw/分')
        self._acc_label.setText('正确率 —')
        self._prog_label.setText('进度 0%')
        self._set_status('练习输入会计入今日统计；与范文不同的字符会加下划线。',
                         '输入会计入今日统计；错字加下划线。')
        self._result.setVisible(False)
        self._score_anim.stop()
        self._score_now = 0
        self._score_target = 0
        self._style_input()
        self._sync_controls()
        self._render_reference('')
        self._refresh_recent()

    def _on_paste_blocked(self):
        """训练进行时提示粘贴被拒绝，不能把粘贴文本计为有效挑战输入。"""
        if self._running:
            self._set_status('❌ 挑战中禁止粘贴——请手动输入！', '❌ 挑战中禁止粘贴')

    def _tick(self):
        """按单调时钟更新本轮秒级用时，墙上时间变化不影响成绩。"""
        if self._running:
            self._elapsed = time.monotonic() - self._start_ts
            self._time_label.setText(f'用时 {self._elapsed:.1f}s')

    def _on_text_changed(self):
        """更新逐字对齐和真实进度，达到参考长度时冻结并结算。"""
        inp = self._input.toPlainText()
        ref = self._current_text()
        self._render_reference(inp)

        if not self._running:
            return
        total = len(ref) or 1
        self._prog_label.setText(f'进度 {min(100, int(len(inp) / total * 100))}%')
        if inp:
            s = self._presenter.evaluate(inp,ref,time.monotonic()-self._start_ts,self._balance)
            self._speed_label.setText(f'速度 {s["speed"]:.1f} tw/分')
            self._acc_label.setText(f'正确率 {s["accuracy"] * 100:.1f}%')
        # 完成检测
        if inp and len(inp) >= len(ref):
            self._finish(inp, ref)

    def _finish(self, inp, ref):
        """停止计时/输入状态，计算纯评分并请求异步提交本轮结果。"""
        self._set_running(False)
        self._timer.stop()
        self._elapsed = time.monotonic() - self._start_ts
        self._time_label.setText(f'用时 {self._elapsed:.1f}s')
        s = self._presenter.evaluate(inp,ref,self._elapsed,self._balance)
        s['elapsed_seconds'] = self._elapsed
        self._store_result(self._text_combo.currentData(),s,self._balance)

    def _store_result(self,text_id,s,balance):
        """冻结输入并交 Presenter 保存，成功/失败由 TaskBridge 回 Qt 线程。"""
        self._input.setEnabled(False)
        try:
            result=self._presenter.complete(text_id,s,balance)
        except Exception as error:
            self._save_failed(error)
            return
        self._sync_controls()
        self._tasks.resolve(result,lambda r:self._result_saved(r,s),self._save_failed)

    def _save_failed(self,error):
        """保留原成绩与操作 ID，显示重试保存而不庆祝或重新评分。"""
        self._presenter.failed()
        self._set_status('成绩未保存，本轮结果已保留，请点击重试保存。')
        self._sync_controls()

    def _result_saved(self,r,s):
        """提交成功后确认完成、发布桌宠反馈并展示纪录/评分动画。"""
        self._presenter.saved()
        self.result_saved.emit({'id': f'challenge:{self._start_ts}', 'is_best': r['is_best'],
                                'accuracy': s['accuracy'], 'speed': s['speed']})

        if r['is_best']:
            self._result_title.setText('🎉 新纪录！')
            self._result_title.setStyleSheet(
                f'font-size:16px; font-weight:900; color:{P.accent_ochre};')
        else:
            self._result_title.setText('挑战完成！')
            self._result_title.setStyleSheet(f'font-size:16px; font-weight:700; color:{P.text};')
        self._result_detail.setText(
            f'速度 {s["speed"]:.1f} tw/分　·　正确率 {s["accuracy"] * 100:.1f}%　·　'
            f'用时 {self._elapsed:.1f}s　·　有效 {s["typed_chars"] - s["errors"]} 字\n'
            f'公式：速度×0.6 + 字数×0.1 + 正确率%×0.5，×10000 × 完成系数\n'
            f'历史最佳 {r["prev_best"]:,} 分'
            + ('　← 你刚刷新了纪录！' if r['is_best'] else '')
            + (f'　·　+{r["exp_gained"]} 经验' if r.get('exp_gained') else ''))
        self._result.setVisible(True)
        self._input.setEnabled(False)
        # 设计稿完成态：底部状态条一行给出分数与下一步（明细仍在可滚动次级区）
        self._set_status(
            f'挑战完成 · {s["score_points"]:,} 分 · 本次经验由服务结算 · 点「重新开始」再练一次',
            f'挑战完成 · {s["score_points"]:,} 分')
        self._style_input()
        self._sync_controls()
        # 分数档位彩带：≥100万金色，≥200万多彩
        if s['score_points'] >= 1_000_000:
            self.confetti_requested.emit(2 if s['score_points'] >= 2_000_000 else 1)
        self._refresh_recent()
        # 分数滚动动画（百万级大数字）
        self._score_now = 0
        self._score_target = s['score_points']
        self._score_label.setText(f'{self._score_now:,}')
        if self._presenter.get_setting('reduced_motion', '0') == '1':
            self._score_now = self._score_target
            self._score_label.setText(f'{self._score_target:,}')
        else:
            self._score_anim.start(24)

    def _tick_score(self):
        """分数从 0 滚动到目标（约 0.6s 完成）。"""
        step = max(1, self._score_target // 24)
        self._score_now = min(self._score_target, self._score_now + step)
        self._score_label.setText(f'{self._score_now:,}')
        if self._score_now >= self._score_target:
            self._score_anim.stop()
            self._score_label.setText(f'{self._score_target:,}')   # 动画中断时也有最终值

    # ---------- 渲染 ----------
    def _render_reference(self, inp: str):
        """按主动输入逐字标色并转义正文，处理 UTF-16 光标位置，不保存用户输入原文。"""
        if not hasattr(self, '_texts'):
            return                          # 构造期文本库未载入，_reload_texts 会重渲染
        ref = self._current_text()
        parts = []
        for i, ch in enumerate(ref):
            if i < len(inp):
                if inp[i] == ch:
                    style = f'color:{P.success_on_paper};'
                else:
                    style = f'color:{P.danger_on_paper}; text-decoration:underline;'
            elif i == len(inp):
                style = f'background-color:{P.primary}; color:{P.primary_text};'
            else:
                style = f'color:{P.paper_text};'
            parts.append(f'<span style="{style}">{html.escape(ch)}</span>')
        self._ref_label.setHtml(''.join(parts))
        # 规范要求范文行距约 1.6；Qt 的 QSS 不支持 line-height，用块格式设置。
        # 口径乙下范文视口固定 57px、文字仍 20px。实机排版是**三行**（范文内宽要扣掉
        # 内部滚动条，45 字 × 20px 放不下两行），所以行距按「3 行装进 57px」倒推：
        # 3×20×(比例/100)+4 ≤ 57 → 比例约 88，取 90 留余量。整篇范文因此完整可读，
        # 既不被硬裁也不叠行；更长范文仍由内部滚动条接管（光标随输入 ensureCursorVisible）。
        # 常规档沿用 1.6 倍。
        cursor = self._ref_label.textCursor()
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        height_type = getattr(QTextBlockFormat, 'ProportionalHeight', 1)
        block.setLineHeight(90.0 if self._compact else 160.0,
                            int(getattr(height_type, 'value', height_type)))
        cursor.mergeBlockFormat(block)
        cursor.clearSelection()
        position = len(ref[:min(len(inp), len(ref))].encode('utf-16-le')) // 2
        cursor.setPosition(position)
        self._ref_label.setTextCursor(cursor)
        self._ref_label.ensureCursorVisible()
        self._sync_reference_height()

    def _sync_reference_height(self) -> None:
        """根据实际折行分配高度；长范文内部滚动，保留输入区与操作入口。"""
        if not hasattr(self, '_texts'):
            return                          # 构造期还未载入文本库
        stage = self._stage_layout()
        document = self._ref_label.document()
        layout = document.documentLayout()
        if layout is not None:
            layout.documentSize()
        needed = int(document.size().height() + 2 * document.documentMargin()) + 2
        target = max(stage.reference_height, min(stage.blend(57, 220), needed))
        if (self._ref_label.minimumHeight() != target
                or self._ref_label.maximumHeight() != target):
            self._ref_label.setFixedHeight(target)
            self._apply_paper_height()

    def _refresh_recent(self):
        """从只读服务刷新同范文单次排行榜及有界近期训练摘要。"""
        tid = self._text_combo.currentData()
        self._leaderboard.set_records(self._text_name(tid), self._svc.leaderboard(tid))
        rows = self._svc.recent(6)
        if not rows:
            self._recent_label.setText('近期挑战：暂无记录，来一次吧 ⚡')
            return
        lines = []
        for r in rows:
            lines.append(
                f'{self._text_name(r["text_id"])} · {r["score"]:.0f}分 · '
                f'{r["elapsed_seconds"]:.1f}s · {r["accuracy"] * 100:.0f}%')
        self._recent_label.setText('🕘 近期挑战：' + '　|　'.join(lines))
