"""Draft-only configuration in an open, responsive companion workspace."""
import uuid
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPalette, QPainter
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QCheckBox, QComboBox, QLineEdit, QPushButton, QScrollArea, QFrame, QStackedWidget,
    QGridLayout, QSizePolicy, QButtonGroup)
from ...modules.companion.api import AgentConfig, MODEL_PRESETS, NewsConfig, MemorySnapshot
from ...bootstrap.features import companion_setup_service, companion_news_capabilities, development_index_service
from ..tasks import TaskBridge
from ..assets.icons import icon
from .agent_visuals import settings_colors
from .agent_widgets import agent_style, label
from .agent_settings_art import SettingsSheet, SettingsSection, SettingsEmblem, paint_workspace
from .news_settings import NewsSettingsPanel
from .memory_presenter import MemoryPresenter
from .memory_page import MemoryPage


class AgentSettingsDialog(QDialog):
    """Qt 主线程的智能体配置草稿窗口，异步检查/保存，经任务 token 拒绝迟到结果。"""
    setup_progress = Signal(object)

    def __init__(self, presenter, parent=None, *, setup=None, portrait=None, news=None):
        """装配模型／搜索草稿和独立的来信、记忆组件，经异步命令保存后才关闭。"""
        super().__init__(parent)
        self.presenter = presenter
        self.news = news
        self._save_id = uuid.uuid4().hex
        self._save_values = None
        self.tasks = TaskBridge(self)
        self.saving = False
        self.setup = setup or companion_setup_service()
        self._own_setup = setup is None
        self._job = None
        self._job_token = None
        self._job_cancelled = False
        self._closed = False
        self._stage_layouts = []
        self._wide = None
        if self._own_setup:
            owned = self.setup
            self.destroyed.connect(lambda: owned.close())
        self.setup_progress.connect(self._progress, Qt.QueuedConnection)
        self.setWindowTitle('Sariana · 桌宠智能体')
        self.setObjectName('companionAgentSettings')
        self.setMinimumSize(560, 560)
        area = self.screen().availableGeometry()
        self.resize(min(820, area.width() - 40), min(660, area.height() - 40))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        intro = QVBoxLayout()
        intro.setSpacing(5)
        eyebrow = label('SARIANA / LITTLE SIGNAL ROOM')
        eyebrow.setProperty('agentEyebrow', True)
        intro.addWidget(eyebrow)
        title = label('她的小小指挥室', heading=True)
        title.setObjectName('settingsTitle')
        intro.addWidget(title)
        intro.addWidget(label('把好奇交给她，把新鲜事带给你。', muted=True))
        header.addLayout(intro, 1)
        header.addWidget(SettingsEmblem(portrait))
        stamp, stamp_body = self._panel('coral', 'settingsStamp')
        stamp_body.setContentsMargins(16, 12, 16, 12)
        stamp_body.setSpacing(3)
        stamp_body.addWidget(label('SEARCH / LETTER', muted=True))
        stamp_body.addWidget(label('搜索与来信'))
        header.addSpacing(8)
        header.addWidget(stamp, 0, Qt.AlignBottom)
        layout.addLayout(header)

        config = AgentConfig.from_settings(presenter)
        self.content = QWidget()
        self.content.setObjectName('agentSettingsContent')
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        channel = QHBoxLayout()
        self.enabled = QCheckBox('开启桌宠智能体')
        self.enabled.setChecked(config.enabled)
        channel.addWidget(self.enabled)
        channel.addSpacing(12)
        channel.addWidget(label('主动搜索，也可以按兴趣准备来信', muted=True), 1)
        content_layout.addLayout(channel)

        # Independent native buttons avoid the platform's document-tab backplate.
        navigation = QWidget()
        navigation.setObjectName('agentSectionNavigation')
        navigation.setAttribute(Qt.WA_StyledBackground, True)
        nav_layout = QHBoxLayout(navigation)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(12)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for index, (text, name, offset) in enumerate(
                [('模型搭档', 'zap', 0), ('搜索偏好', 'search', 10), ('定时来信', 'calendar', 3), ('记忆', 'copy', 8)]):
            holder = QWidget()
            stack = QVBoxLayout(holder)
            stack.setContentsMargins(0, offset, 0, 10 - offset)
            button = QPushButton(f'0{index + 1}  {text}')
            button.setProperty('agentNav', True)
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setIconSize(QSize(17, 17))
            button.setAccessibleName(text)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            stack.addWidget(button)
            nav_layout.addWidget(holder)
        nav_layout.addStretch()
        content_layout.addWidget(navigation)
        # Keep the existing page API used by previews and settings tests.
        self.tabs = QStackedWidget()
        self.tabs.setObjectName('agentSettingsTabs')
        self.tabs.setFrameShape(QFrame.NoFrame)
        self.tabs.setAccessibleName('桌宠智能体配置分区')
        self.model_scroll, model_body = self._page('modelSettingsPage')
        self.search_scroll, search_body = self._page('searchSettingsPage')
        future_scroll, future_body = self._page('futureSettingsPage')
        for page in (self.model_scroll, self.search_scroll, future_scroll):
            self.tabs.addWidget(page)
        content_layout.addWidget(self.tabs, 1)
        layout.addWidget(self.content, 1)

        model_body.addWidget(self._section_intro('01 / YOUR PARTNER',
            '先认识她的聪明搭档', '云端或本地都可以，选你喜欢的那一种。'))
        model_panel, model_panel_body = self._panel(name='settingsConnectionSheet')
        self.provider = QComboBox()
        for text, name in [('OpenAI', 'openai'), ('DeepSeek', 'deepseek'),
                           ('本地模型 · Ollama / LM Studio', 'local'), ('其他兼容接口', 'custom')]:
            self.provider.addItem(text, name)
        self.provider.setCurrentIndex(max(0, self.provider.findData(config.provider)))
        self.base_url = QLineEdit(config.base_url)
        self.model = QLineEdit(config.model)
        self.api_key = QLineEdit(config.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        fields = QGridLayout()
        fields.setHorizontalSpacing(14)
        fields.setVerticalSpacing(12)
        fields.setColumnStretch(0, 1)
        fields.setColumnStretch(1, 1)
        fields.addWidget(self._field('模型服务', self.provider), 0, 0, 1, 2)
        fields.addWidget(self._field('接口地址 · Base URL', self.base_url), 1, 0, 1, 2)
        fields.addWidget(self._field('模型名称', self.model), 2, 0)
        fields.addWidget(self._field('模型 API Key', self.api_key), 2, 1)
        model_panel_body.addLayout(fields)
        model_panel_body.addWidget(label('本地模型无需 Key · 搭档独立于英语和训练', muted=True))

        model_aside = QWidget()
        notes = QVBoxLayout(model_aside)
        notes.setContentsMargins(0, 30, 0, 0)
        notes.setSpacing(18)
        model_check, model_check_body = self._panel('lavender', 'settingsCheck')
        small = label('HELLO / 先打个招呼')
        small.setProperty('agentEyebrow', True)
        model_check_body.addWidget(small)
        self.model_status = label('还没和搭档打过招呼。', muted=True)
        model_check_body.addWidget(self.model_status)
        self.model_test = QPushButton('测试模型连接  ↗')
        self.model_test.setAutoDefault(False)
        self.model_test.setCursor(Qt.PointingHandCursor)
        self.model_test.clicked.connect(self.test_model)
        model_check_body.addWidget(self.model_test)
        model_check_body.addWidget(label('只发一条短消息，不保存草稿。云端测试可能产生少量费用。', muted=True))
        notes.addWidget(model_check)
        thought, thought_body = self._panel(name='settingsThoughtNote')
        self.thinking = QCheckBox('整理时开启思考')
        self.thinking.setChecked(config.thinking)
        self.thinking.toggled.connect(self._model_dirty)
        thought_body.addWidget(self.thinking)
        thought_body.addWidget(label('只显示正文，不保存思考内容。', muted=True))
        notes.addWidget(thought)
        notes.addStretch()
        model_body.addWidget(self._stage(model_panel, model_aside))
        model_body.addStretch()

        search_body.addWidget(self._section_intro('02 / CURIOSITY',
            '给好奇心选一条路线', '她先找公开线索，再把重点整理成一封手信。'))
        search_panel, search_panel_body = self._panel(name='settingsSearchSheet')
        self.search_form = search_form = QFormLayout()
        search_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        search_form.setVerticalSpacing(12)
        search_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.search_provider = QComboBox()
        for text, name in [('Edge 浏览器搜索 · 免 Key', 'web'), ('轻量网页搜索 · RSS', 'web-lite'),
                           ('Tavily · 搜索 API', 'tavily'), ('已有 SearXNG 服务', 'searxng')]:
            self.search_provider.addItem(text, name)
        self.search_provider.setCurrentIndex(max(0, self.search_provider.findData(config.search_provider)))
        self.search_key = QLineEdit(config.search_key)
        self.search_key.setEchoMode(QLineEdit.Password)
        self.search_url = QLineEdit(config.search_url)
        self.search_url.setPlaceholderText('例如 http://127.0.0.1:8080')
        self.default_topic = QLineEdit(config.default_topic)
        self.default_topic.setMaxLength(200)
        self.default_topic.setPlaceholderText('例如：人工智能、天文学')
        for text, widget in [('搜索服务', self.search_provider), ('搜索 API Key', self.search_key),
                             ('SearXNG 地址', self.search_url), ('默认话题', self.default_topic)]:
            widget.setAccessibleName(text)
            caption = label(text)
            caption.setBuddy(widget)
            search_form.addRow(caption, widget)
        search_panel_body.addLayout(search_form)
        self.search_note = label('', muted=True)
        search_panel_body.addWidget(self.search_note)

        search_aside = QWidget()
        notes = QVBoxLayout(search_aside)
        notes.setContentsMargins(0, 34, 0, 0)
        notes.setSpacing(18)
        search_check, search_check_body = self._panel('blue', 'settingsSearchCheck')
        small = label('ROUTE / 线索通不通')
        small.setProperty('agentEyebrow', True)
        search_check_body.addWidget(small)
        self.search_status = label('尚未检查搜索连接。', muted=True)
        search_check_body.addWidget(self.search_status)
        self.search_test = QPushButton('测试搜索  ↗')
        self.search_test.setAutoDefault(False)
        self.search_test.setCursor(Qt.PointingHandCursor)
        self.search_test.clicked.connect(self.test_search)
        search_check_body.addWidget(self.search_test)
        notes.addWidget(search_check)
        privacy, privacy_body = self._panel(name='settingsPrivacy')
        privacy_body.addWidget(label('留一点边界'))
        privacy_body.addWidget(label('只发送主动话题和搜索摘录。Key 保存在本机；云端请求可能产生费用。', muted=True))
        notes.addWidget(privacy)
        notes.addStretch()
        search_body.addWidget(self._stage(search_panel, search_aside))
        search_body.addStretch()

        capabilities = companion_news_capabilities(presenter)
        snapshot = presenter.news_snapshot() if capabilities is not None else MemorySnapshot()
        self.news_panel = NewsSettingsPanel(snapshot.config, snapshot, now_local=capabilities[1] if capabilities else None,
            agent_enabled=config.enabled, companion_enabled=presenter.get_setting('companion_enabled', '1') != '0')
        future_body.addWidget(self.news_panel)
        self.news_panel.run_requested.connect(self._run_news)
        self.news_panel.retry_requested.connect(self._retry_news)
        if news is not None:
            news.changed.connect(self._refresh_news)
        self.news_panel.memory_requested.connect(self._open_memory)
        if capabilities is not None:
            index_service = development_index_service()
            self.destroyed.connect(index_service.close)
            self.memory_page = MemoryPage(MemoryPresenter(presenter, capabilities[0], now_utc=capabilities[2]), index_service)
            self.memory_scroll, memory_body = self._page('memorySettingsPage')
            memory_body.addWidget(self.memory_page)
            self.tabs.addWidget(self.memory_scroll)
            self.memory_page.interests_saved.connect(self._interests_saved)
            if news is not None:
                news.changed.connect(self.memory_page.refresh)
                self.memory_page.report_requested.connect(news.agent.show_news_task)
        else:
            self.nav_buttons[-1].setEnabled(False)

        self.feedback = label('', muted=True)
        self.feedback.setAccessibleName('配置保存与连接测试状态')
        layout.addWidget(self.feedback)
        buttons = QHBoxLayout()
        self.cancel = QPushButton('取消')
        self.cancel.setProperty('agentQuiet', True)
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.reject)
        self.save = QPushButton('保存配置')
        self.save.setProperty('agentPrimary', True)
        self.save.setDefault(True)
        self.save.setCursor(Qt.PointingHandCursor)
        self.save.clicked.connect(self.save_config)
        buttons.addWidget(self.cancel)
        buttons.addStretch()
        buttons.addWidget(label('草稿只在保存后生效', muted=True))
        buttons.addSpacing(16)
        buttons.addWidget(self.save)
        layout.addLayout(buttons)
        self.provider.currentIndexChanged.connect(self._model_hint)
        self.search_provider.currentIndexChanged.connect(self._search_hint)
        self._model_hint()
        self._search_hint()
        for widget in (self.base_url, self.model, self.api_key):
            widget.textChanged.connect(self._model_dirty)
        self.provider.currentIndexChanged.connect(self._model_dirty)
        self.tabs.currentChanged.connect(self._tab_tone)
        self._tab_tone(0)
        self._reflow()

    @staticmethod
    def _settings_style(c):
        """生成配置页专用样式，显式统一导航/内容底色，覆盖原生平台深色底板。"""
        return f'''
        QDialog#companionAgentSettings {{background:{c.bg};}}
        QWidget#agentSettingsContent, QWidget#agentSectionNavigation,
        QStackedWidget#agentSettingsTabs, QScrollArea > QWidget {{
            background:transparent;border:0;}}
        QWidget#agentSectionNavigation, QStackedWidget#agentSettingsTabs {{background:{c.bg};border:0;}}
        QLabel#settingsTitle {{font-size:29px;font-weight:800;}}
        QFrame#settingsStamp {{border-top-left-radius:24px;border-top-right-radius:10px;
            border-bottom-left-radius:10px;border-bottom-right-radius:24px;}}
        QFrame#settingsThoughtNote, QFrame#settingsPrivacy {{
            background:transparent;border:0;border-left:2px solid {c.line};border-radius:0;}}
        QLabel[agentNumber="true"] {{font-size:34px;font-weight:700;color:{c.accent};}}
        QPushButton[agentNav="true"] {{background:{c.surface};border:1px solid {c.line};
            border-radius:18px;padding:8px 12px;min-height:24px;color:{c.muted};}}
        QPushButton[agentNav="true"]:checked {{background:{c.accent};color:{c.on_accent};border-color:{c.accent};}}
        QPushButton[agentNav="true"]:focus {{border:2px solid {c.ink};}}
        QPushButton[agentNav="true"]:hover {{border-color:{c.accent};}}
        QScrollArea, QWidget#qt_scrollarea_viewport,
        QWidget#modelSettingsPage, QWidget#searchSettingsPage, QWidget#futureSettingsPage
            {{background:transparent;border:0;}}
        QFrame[agentPanel="true"] {{background:{c.surface};border:1px solid {c.line};border-radius:18px;}}
        QFrame[agentTone="lavender"] {{background:{c.lavender};border:0;}}
        QFrame[agentTone="blue"] {{background:{c.blue};border:0;}}
        QFrame[agentTone="coral"] {{background:{c.coral};border:0;}}
        QFrame[agentIllustrated="true"] {{background:transparent;border:0;border-radius:0;}}
        '''

    @staticmethod
    def _panel(tone=None, name=None):
        """创建静态纸张面板及纵向布局，返回二者供表单与便签复用。"""
        panel = SettingsSheet(tone)
        panel.setFrameShape(QFrame.NoFrame)
        panel.setProperty('agentPanel', True)
        if tone:
            panel.setProperty('agentTone', tone)
        if name:
            panel.setObjectName(name)
        body = QVBoxLayout(panel)
        body.setContentsMargins(20, 20, 20, 22)
        body.setSpacing(12)
        return panel, body

    @staticmethod
    def _page(name):
        """创建无横向滚动的分区页面，返回滚动容器和内容布局。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName(name)
        body = QVBoxLayout(content)
        body.setContentsMargins(2, 2, 8, 8)
        body.setSpacing(20)
        scroll.setWidget(content)
        return scroll, body

    @staticmethod
    def _section_intro(eyebrow_text, title, detail):
        """创建章节说明区域，把标题/说明控件与静态大编号装饰组合。"""
        panel = SettingsSection('03' if eyebrow_text.startswith('COMING') else eyebrow_text[:2])
        body = QVBoxLayout(panel)
        body.setContentsMargins(4, 2, 0, 0)
        body.setSpacing(5)
        heading = label(title, heading=True)
        heading.setStyleSheet('font-size:21px;')
        body.addWidget(heading)
        body.addWidget(label(detail, muted=True))
        return panel

    def _stage(self, main, aside, *, future=False):
        """登记主表单和错位侧栏，交由窗口宽窄重排复用同一组控件。"""
        stage = QWidget()
        grid = QGridLayout(stage)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(12)
        main.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        aside.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._stage_layouts.append((grid, main, aside, future))
        return stage

    def _reflow(self):
        """以 700 逻辑像素为宽窄分界重排主表单/侧栏，保留草稿和任务状态。"""
        wide = self.width() >= 700
        if self._wide == wide:
            return
        self._wide = wide
        for grid, main, aside, future in self._stage_layouts:
            grid.removeWidget(main)
            grid.removeWidget(aside)
            if wide:
                main.setMaximumWidth(16777215)
                aside.setMaximumWidth(16777215 if future else 230)
                grid.setColumnStretch(0, 1 if future else 3)
                grid.setColumnStretch(1, 1)
                grid.addWidget(main, 0, 0, Qt.AlignTop)
                grid.addWidget(aside, 0, 1, Qt.AlignTop)
                grid.setRowMinimumHeight(0, 0)
            else:
                main.setMaximumWidth(410 if future else 16777215)
                aside.setMaximumWidth(370)
                grid.setColumnStretch(0, 1)
                grid.setColumnStretch(1, 0)
                grid.addWidget(main, 0, 0, 1, 2, Qt.AlignLeft if future else Qt.AlignmentFlag(0))
                grid.addWidget(aside, 1, 0, 1, 2, Qt.AlignRight)

    def resizeEvent(self, event):
        """窗口尺寸变化后触发分区重排，保留原生对话框尺寸处理。"""
        super().resizeEvent(event)
        self._reflow()

    def paintEvent(self, event):
        """在控件背后绘制章节几何装饰，不参与输入或网络请求。"""
        super().paintEvent(event)
        if hasattr(self, 'section_palette'):
            painter = QPainter(self)
            paint_workspace(self, painter)

    def _tab_tone(self, index):
        """切换章节时同步 Qt palette、样式及导航图标高亮，避免局部颜色不一致。"""
        c = settings_colors(max(0, index))
        self.section_palette = c
        palette = self.palette()
        for role, value in ((QPalette.Window, c.bg), (QPalette.Base, c.surface),
                            (QPalette.Button, c.surface), (QPalette.WindowText, c.ink),
                            (QPalette.Text, c.ink), (QPalette.ButtonText, c.ink),
                            (QPalette.PlaceholderText, c.muted), (QPalette.Highlight, c.accent),
                            (QPalette.HighlightedText, c.on_accent)):
            palette.setColor(role, QColor(value))
        self.setPalette(palette)
        self.setStyleSheet(agent_style(c) + self._settings_style(c))
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
            button.setIcon(icon(('zap', 'search', 'calendar', 'copy')[i], c.on_accent if i == index else c.muted, 17))
        self.update()

    @staticmethod
    def _field(title, widget):
        """组合字段标题与输入控件，并建立标签关联和无障碍名称。"""
        container = QWidget()
        body = QVBoxLayout(container)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(7)
        caption = label(title)
        caption.setBuddy(widget)
        widget.setAccessibleName(title)
        body.addWidget(caption)
        body.addWidget(widget)
        return container

    @classmethod
    def _planned_card(cls, tone, number, title, intro, detail, button_text):
        """构造后续迭代的错位说明卡片；操作保持禁用，不伪装已开放功能。"""
        outer = QWidget()
        body = QVBoxLayout(outer)
        body.setContentsMargins(0, 0 if number == '02' else 42, 0, 0)
        panel, content = cls._panel(tone)
        number_label = label(number)
        number_label.setProperty('agentNumber', True)
        content.addWidget(number_label)
        content.addWidget(label(title, heading=True))
        content.addWidget(label(intro))
        content.addWidget(label(detail, muted=True))
        planned = QPushButton(button_text)
        planned.setEnabled(False)
        planned.setAutoDefault(False)
        content.addWidget(planned, 0, Qt.AlignLeft)
        body.addWidget(panel)
        return outer

    def _model_hint(self):
        """按模型服务预设更新地址/模型占位提示，不覆盖用户填写的草稿。"""
        url, model = MODEL_PRESETS.get(self.provider.currentData(), ('', ''))
        self.base_url.setPlaceholderText(url or 'https://…/v1')
        self.model.setPlaceholderText(model or '填入模型名称')

    def _search_hint(self):
        """按搜索服务显示其必要字段和说明，模型密钥与搜索密钥分别填写。"""
        tavily = self.search_provider.currentData() == 'tavily'
        external = self.search_provider.currentData() == 'searxng'
        self.search_key.setEnabled(tavily)
        self.search_form.setRowVisible(self.search_key, tavily)
        self.search_form.setRowVisible(self.search_url, external)
        self.search_url.setEnabled(external)
        self.search_note.setText('在 tavily.com 获取搜索 Key，和模型 Key 分开填写。' if tavily else
            ('填写你已部署的 SearXNG 地址，需启用 JSON 格式。' if external else
             ('使用本机 Edge 读取真实搜索页面，并核对前两条公开来源的正文。无需搜索 Key 或 Docker；不使用个人浏览记录或登录状态。'
              if self.search_provider.currentData() == 'web' else
              '直接获取公开 RSS 搜索摘录，无需浏览器或 Key；结果较简略，可切换 Edge 搜索。')))

    def _model_dirty(self, *_):
        """无在途检查时提示模型草稿已变更，不自动发起网络。"""
        if self._job is None:
            self.model_status.setText('模型配置已修改，点击测试即可检查。')

    def draft_config(self):
        """将当前表单值包装为独立 AgentConfig 快照，用于草稿检查而不保存。"""
        class Draft:
            """只读草稿适配器，提供配置解析需要的 settings 接口。"""
            def __init__(self, values):
                """持有当前草稿值，替代数据库设置对象参与纯配置解析。"""
                self.values = values
            def settings(self):
                """返回草稿字典副本，防止配置解析修改表单状态。"""
                return dict(self.values)
        return AgentConfig.from_settings(Draft(self.values()))

    def _run_job(self, kind, factory, message):
        """捕获草稿和唯一 token 启动连接检查，锁定控件并经 TaskBridge 异步接收结果。"""
        if self.saving or self._job is not None or self._closed or self._memory_saving():
            return
        token = uuid.uuid4().hex
        config = self.draft_config()
        self._job_token = token
        self._job_cancelled = False
        self.content.setEnabled(False)
        self.save.setEnabled(False)
        self.cancel.setText('取消操作')
        self.feedback.setText(message)
        try:
            future = factory(config, lambda text:self.setup_progress.emit((token, text)))
        except Exception as error:
            self._complete_job(token, kind, config, error=error)
            return
        self._job = future
        self.tasks.resolve(future,
            lambda result:self._complete_job(token, kind, config, result=result),
            lambda error:self._complete_job(token, kind, config, error=error))

    def _progress(self, item):
        """仅展示当前、未取消检查 token 的排队进度。"""
        token, text = item
        if not self._closed and token == self._job_token and not self._job_cancelled:
            self.feedback.setText(text)

    def _complete_job(self, token, kind, config, *, result=None, error=None):
        """恢复检查控件；取消、关闭或草稿改变后的结果不应用到当前配置。"""
        if self._closed or token != self._job_token:
            return
        self._job = None
        self._job_token = None
        self.content.setEnabled(True)
        self.save.setEnabled(True)
        self.cancel.setText('取消')
        if self._job_cancelled:
            message = '操作已取消，草稿已保留。'
        elif config != self.draft_config():
            message = '配置已改变，本次结果不应用；请重新测试。'
        elif error is not None:
            message = str(error)
        else:
            message = result.message
        (self.model_status if kind == 'model' else self.search_status).setText(message)
        self.feedback.setText(message)

    def test_model(self):
        """用当前未保存草稿启动短模型连接检查，不执行搜索或保存。"""
        self._run_job('model', lambda config, progress:self.setup.test_model(config), '正在测试模型连接…')

    def test_search(self):
        """用当前未保存草稿启动只读搜索连接检查。"""
        self._run_job('search', lambda config, progress:self.setup.test_search(config, progress), '正在测试搜索连接…')

    def values(self):
        """合并模型搜索与来信草稿，返回 companion_agent／news 命名空间设置。"""
        values = {name: getattr(self, name).text().strip() for name in
                  ('base_url', 'model', 'api_key', 'search_key', 'search_url', 'default_topic')}
        values.update(enabled='1' if self.enabled.isChecked() else '0',
                      thinking='1' if self.thinking.isChecked() else '0',
                      provider=self.provider.currentData(),
                      search_provider=self.search_provider.currentData(),
                      managed_search='0')
        return dict({'companion_agent_' + name: value for name, value in values.items()}, **self.news_panel.values())

    def _refresh_news(self):
        """刷新只读排期与操作资格；区分正文／终态保存重试，不覆盖表单草稿。"""
        if not self._closed and self.news is not None:
            self.news_panel.set_snapshot(self.presenter.news_snapshot(), status=self.news.status, busy=self.news.busy,
                agent_enabled=AgentConfig.from_settings(self.presenter).enabled,
                companion_enabled=self.presenter.get_setting('companion_enabled', '1') != '0')
            if self.news.pending_report is not None or self.news._pending_failure is not None:
                self.news_panel.retry_button.setEnabled(not self.news.saving)
                self.news_panel.retry_button.setText('重试保存任务状态' if self.news._pending_failure is not None
                                                     else '重试保存已生成来信')
            else:
                self.news_panel.retry_button.setText('重试最近未完成来信')

    def _run_news(self):
        """显式联网动作只使用已保存配置，未保存草稿不会发送给模型。"""
        if self.news is None:
            self.feedback.setText('请在正式桌面应用中使用来信服务。')
        else:
            self.news.run_now()
            self._refresh_news()

    def _retry_news(self, task_id):
        """将明确重试交给拥有准入和待存报告的来信控制器。"""
        if self.news is not None:
            self.news.retry(task_id)

    def _open_memory(self):
        """由独立记忆页面模块提供入口，组件间不共享数据库对象。"""
        if hasattr(self, 'memory_page'):
            self.tabs.setCurrentWidget(self.memory_scroll)

    def _interests_saved(self, config):
        """记忆页显式提交兴趣后同步对应来信草稿，避免外层保存再覆盖刚提交的画像。"""
        self.news_panel.interests.setPlainText('\n'.join(config.interests))
        self.news_panel.enabled.setChecked(config.enabled)

    def _memory_saving(self):
        """共享外层／记忆页的保存门禁，禁止旧草稿排在兴趣提交后覆盖新值。"""
        return bool(getattr(getattr(self, 'memory_page', None), '_saving', False))

    def save_config(self):
        """禁用重复操作并请求 Presenter 异步保存；提交成功后才关闭配置窗口。"""
        if self.saving or self._job is not None:
            return
        if self._memory_saving():
            self.feedback.setText('记忆页正在保存，请完成后再保存配置。')
            return
        try:
            values = self.values()
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        if values != self._save_values:
            self._save_id = uuid.uuid4().hex
            self._save_values = values
        self.saving = True
        self.save.setEnabled(False)
        self.cancel.setEnabled(False)
        self.content.setEnabled(False)
        self.feedback.setText('正在保存配置…')
        try:
            capabilities = companion_news_capabilities(self.presenter)
            result = (capabilities[0].save_settings(values, operation_id=self._save_id,
                                                   now_utc=capabilities[2]()) if capabilities is not None
                      else self.presenter.set_settings(values))
        except Exception:
            self._failed(None)
            return
        self.tasks.resolve(result, self._saved, self._failed)

    def _saved(self, _):
        """接收成功保存结果，恢复保存状态并接受对话框。"""
        self.saving = False
        self.accept()

    def _failed(self, _):
        """保存失败后重新启用操作并保留全部草稿，允许用户重试。"""
        self.saving = False
        self.save.setEnabled(True)
        self.cancel.setEnabled(True)
        self.content.setEnabled(True)
        self.feedback.setText('配置保存失败，草稿还在，请重试。')

    def reject(self):
        """保存期间拒绝关闭；检查期间先请求取消，空闲时关闭且不提交草稿。"""
        if self.saving or self._memory_saving():
            return
        if self._job is not None and not self._job_cancelled:
            self._job_cancelled = True
            self.setup.cancel()
            self.feedback.setText('正在取消操作…')
            return
        self._closed = True
        if self._own_setup:
            self.setup.close()
        super().reject()

    def closeEvent(self, event):
        """窗口关闭时复用草稿取消规则；保存或检查仍在处理时按原状态决定是否接受关闭。"""
        if self.saving or self._memory_saving():
            event.ignore()
        else:
            self._closed = True
            if self._job is not None:
                self._job_cancelled = True
                self.setup.cancel()
            super().closeEvent(event)
