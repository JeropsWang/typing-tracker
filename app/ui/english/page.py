"""独立英语入口：组件装配、可失效请求与服务调用。"""
import time
import uuid
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QBoxLayout, QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget
from ...modules.english.api import EnglishSaveError, sentence_alignment
from ...bootstrap.features import english_presenter
from ..tasks import TaskBridge, finish_network_result
from ..palette import P
from ..widgets.design import PaperPage, PageHeading
from .library import LibraryPanel
from .spelling import SpellingPanel
from .sentences import SentencePanel
from .requests import SentenceRequest
from .typography import english_type


class EnglishPage(PaperPage):
    """Qt 主线程英语学习页面，组合只读模型和异步提交，保存成功才推进/庆祝。"""
    result_saved = Signal(dict)
    running_changed = Signal(bool)
    settings_requested = Signal()

    def __init__(self, repo, balance, ai_service, parent=None, *, test_session=None):
        """装配英语 Presenter、拼写/造句面板、异步桥及各类待保存状态。"""
        super().__init__(parent)
        self.service = english_presenter(repo,test_session)
        self._tasks = TaskBridge(self)
        self._spelling_saving = False
        self._reveal_pending = False
        self._sentence_saving = False
        self._sentence_pending = None
        self._font_saving = False
        self._font_key = self.service.get_setting('english_font_size', 'large')
        if self._font_key not in ('standard', 'large', 'extra'):
            self._font_key = 'large'
        self._pending_material = None
        self._material_saving = False
        self._balance, self._ai_service = balance, ai_service
        self._mode = 'spelling'
        self._running = False
        self._request = None
        self._targets = ()
        self._sentence_run = None
        heading = PageHeading('把新词，\n敲成小星星', 'WORD / PLAY   ·   中文释义 → 英文拼写 · AI 语句 · 待复习')
        heading.title.setStyleSheet('font:36px "KaiTi"; color:#EEE5D6; background:transparent;')
        self.set_header(heading)
        self.body.setContentsMargins(30, 25, 30, 30)
        self.body.setSpacing(15)
        modes = QHBoxLayout()
        self.mode_buttons = {}
        self._mode_group = QButtonGroup(self)
        for mode, title in [('spelling', '单词拼写'), ('sentence', 'AI 语句'), ('review', '错词复习'), ('due', '今日到期')]:
            button = QPushButton(title)
            button.setCheckable(True)
            button.setProperty('growthTab', True)
            self._mode_group.addButton(button)
            button.clicked.connect(lambda checked=False, key=mode: self._set_mode(key))
            self.mode_buttons[mode] = button
            modes.addWidget(button)
        self.mode_buttons['spelling'].setChecked(True)
        modes.addStretch()
        self.body.addLayout(modes)
        type_row = QHBoxLayout()
        self.type_note = QLabel('一点一点，把陌生敲熟。')
        self.type_note.setProperty('textRole', 'paperMuted')
        type_row.addWidget(self.type_note, 1)
        type_row.addWidget(QLabel('字号'))
        self.font_combo = QComboBox()
        self.font_combo.setAccessibleName('英语字号')
        for key, label in [('standard', '标准'), ('large', '大'), ('extra', '特大')]:
            self.font_combo.addItem(label, key)
        self.font_combo.setCurrentIndex(self.font_combo.findData(self._font_key))
        self.font_combo.currentIndexChanged.connect(self._font_changed)
        type_row.addWidget(self.font_combo)
        self.body.addLayout(type_row)
        row = QBoxLayout(QBoxLayout.LeftToRight)
        self._study_row = row
        row.setSpacing(23)
        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(505)
        self.spelling = SpellingPanel()
        self.sentences = SentencePanel()
        self.stack.addWidget(self.spelling)
        self.stack.addWidget(self.sentences)
        row.addWidget(self.stack, 1)
        self.library = LibraryPanel()
        sidebar = QWidget()
        self._sidebar = sidebar
        offset = QVBoxLayout(sidebar)
        offset.setContentsMargins(0, 24, 0, 0)
        offset.addWidget(self.library, 0, Qt.AlignTop)
        offset.addStretch()
        row.addWidget(sidebar, 0)
        self.body.addLayout(row)
        self.library.deck_changed.connect(self._deck_changed)
        self.spelling.start_requested.connect(self._start_spelling)
        self.spelling.submit_requested.connect(self._submit_spelling)
        self.spelling.hint_requested.connect(self._hint)
        self.spelling.reveal_requested.connect(self._reveal)
        self.spelling.correction_skipped.connect(lambda: self._correct(skip=True))
        self.sentences.generate_requested.connect(self._generate)
        self.sentences.targets_requested.connect(self._choose_targets)
        self.sentences.settings_requested.connect(self.settings_requested.emit)
        self.sentences.start_requested.connect(self._start_sentence)
        self.sentences.finish_requested.connect(self._finish_sentence)
        self.sentences.retry_requested.connect(self._start_sentence)
        self.sentences.material_changed.connect(self._reset_sentence)
        self.sentences.input.textChanged.connect(self._sentence_progress)
        self._deck_changed()
        self._apply_type()

    def _font_changed(self):
        """异步提交新字号，期间防重复操作；成功应用，失败恢复原档位。"""
        if self._font_saving:
            return
        old, key = self._font_key, self.font_combo.currentData()
        self._font_saving = True
        self.font_combo.setEnabled(False)
        def saved(_):
            """确认字号提交成功后更新页面排版并恢复选择控件。"""
            self._font_saving = False
            self.font_combo.setEnabled(True)
            self._font_key = key
            self.type_note.setText('一点一点，把陌生敲熟。')
            self._apply_type()
        def failed(_):
            """字号保存失败时恢复旧选项和可见提示，不假装配置生效。"""
            self._font_saving = False
            self.font_combo.setEnabled(True)
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentIndex(self.font_combo.findData(old))
            self.font_combo.blockSignals(False)
            self.type_note.setText('字号未保存，请重试。')
        try:
            self._tasks.resolve(self.service.set_font_size(key), saved, failed)
        except Exception as error:
            failed(error)

    def _apply_type(self):
        """将已生效字号同步到词库、拼写与句子面板并重排学习区域。"""
        t = english_type(self._font_key)
        self.paper.setObjectName('englishPaper')
        self.paper.setStyleSheet(f'''QWidget#englishPaper QLabel {{font-size:{t.body}px;}}
            QWidget#englishPaper QLabel[textRole="paperMuted"] {{font-size:{t.helper}px;}}
            QWidget#englishPaper QPushButton, QWidget#englishPaper QComboBox {{font-size:{t.body}px;min-height:40px;}}''')
        self.spelling.set_type(self._font_key)
        self.sentences.set_type(self._font_key)
        self.library.set_type(self._font_key)
        self._arrange_study()

    def _arrange_study(self):
        """依据纸张宽度和特大字号切换并列/上下学习布局，复用原控件。"""
        if not hasattr(self, '_study_row'):
            return
        stacked = self.paper.width() < 820 or (self._font_key == 'extra' and self.paper.width() < 980)
        self._study_row.setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.library.setFixedWidth(max(254, self.paper.width() - 60) if stacked else 280)

    def resizeEvent(self, event):
        """页面宽度变化时更新学习面板排布。"""
        super().resizeEvent(event)
        self._arrange_study()

    def _set_saving_controls(self, saving):
        """保存期间锁定模式、词库和辅助操作，避免待保存结果输入资格被改变。"""
        for button in self.mode_buttons.values():
            button.setEnabled(not saving)
        self.library.deck_combo.setEnabled(not saving)
        self.library.round_combo.setEnabled(not saving)
        self.spelling.start_button.setEnabled(not saving)
        if saving:
            for button in (self.spelling.submit_button, self.spelling.hint_button,
                           self.spelling.reveal_button, self.spelling.skip_button):
                button.setEnabled(False)
            self.spelling.answer.setReadOnly(True)

    def _set_running(self, running):
        """聚合练习运行状态变化并发布信号，供桌宠/全局动效让出优先级。"""
        if self._running != running:
            self._running = running
            self.running_changed.emit(running)

    def _set_mode(self, mode):
        """仅非保存期间切换学习模式，取消失效生成并重置旧练习会话。"""
        if self._spelling_saving or self._sentence_saving or self._material_saving:
            return
        self._cancel_request()
        self._reset_sentence()
        self.service.session = None
        self.spelling.set_active(False)
        self.spelling.skip_button.hide()
        self._set_running(False)
        self._mode = mode
        self.stack.setCurrentWidget(self.sentences if mode == 'sentence' else self.spelling)
        if mode == 'sentence':
            self.sentences.status.setText(self.service.ai_access(self._ai_service, self._balance)[1])
        self.spelling.progress.setText('只练还没记牢的词。' if mode == 'review' else '看中文，敲出英文。')

    def _deck_changed(self):
        """词库切换时取消旧请求并清理会话，刷新目标词、复习概览和材料历史。"""
        self._cancel_request()
        self._reset_sentence()
        self.service.session = None
        self.spelling.set_active(False)
        self.spelling.skip_button.hide()
        self.spelling.meaning.setPlainText('词库已选好，开始新的一轮吧。')
        self._set_running(False)
        self._choose_targets()
        self.refresh()
        self.sentences.set_history(self.service.sentence_history(self.library.deck))

    def refresh(self):
        """从只读服务刷新当前词库概览、到期词数和已提交头像。"""
        plan = self.service.review_plan(self.library.deck)
        self.library.set_summary(self.service.summary(self.library.deck), plan)
        self.mode_buttons['due'].setText(f"今日到期 {plan['due_count']}")
        self.library.avatar.set_preset(self.service.get_setting('avatar_preset', 'default'))

    def _start_spelling(self):
        """按当前模式创建新会话，失败展示原因，成功进入题目与练习状态。"""
        if self._spelling_saving or self._sentence_saving or self._material_saving:
            return
        self._reveal_pending = False
        try:
            session = self.service.start(self.library.deck, self.library.count,
                                         review=self._mode == 'review', due=self._mode == 'due')
        except ValueError as exc:
            self.spelling.feedback.setText(str(exc))
            return
        self._set_running(True)
        self._show_word(session)
        self.spelling.start_button.setText('重新开始这一轮')

    def _submit_spelling(self):
        """根据纠正/已判定/新答案阶段推进或异步保存，保存时冻结当前输入。"""
        if self._spelling_saving:
            return
        session = self.service.session
        if session is None or session.finished:
            return
        if session.correcting:
            self._correct()
            return
        if session.result is not None:
            if self.service.advance():
                self._set_running(True)
                self._show_word(session)
            else:
                view = self.service.spelling_view()
                self.spelling.set_active(False)
                self.spelling.feedback.setText(f'这一轮完成！首次独立答对 {view.first_correct} / {view.first_total}。\n'
                    f'纠正 {view.corrected} 次 · 跳过 {view.correction_skipped} 次\n'
                    f'复测独立答对 {view.retest_correct} / {view.retest_total}，复习安排已保存。')
                self._set_running(False)
                self.result_saved.emit({'id': f"spelling:{session.results[-1]['id']}",
                                        'accuracy': view.first_correct / max(1, view.first_total)})
            return
        try:
            result = self.service.submit(self.spelling.answer.text())
        except EnglishSaveError as exc:
            self.spelling.feedback.setText(str(exc))
            return
        if isinstance(result, dict) and not result.get('accepted'):
            if result.get('error'):
                self.spelling.feedback.setText(result['error'])
            return
        self._spelling_saving=True
        self._set_saving_controls(True)
        self._tasks.resolve(result,lambda result:self._spelling_saved(session,result),self._spelling_failed)

    def _spelling_saved(self,session,result):
        """确认提交后的原会话结果，仅有效会话展示反馈/纠正并刷新概览。"""
        self._spelling_saving=False
        self._reveal_pending=False
        self._set_saving_controls(False)
        confirm=getattr(self.service,'confirm_saved',None)
        if confirm:
            confirm()
        if session is not self.service.session:
            return
        if result.get('accepted'):
            self._set_running(session.correcting)
            self.spelling.show_result(session.current,result)
            if session.correcting:
                self.spelling.show_correction(session.current)
            self.refresh()
        elif result.get('error'):
            self.spelling.set_active(True)
            self.spelling.feedback.setText(result['error'])

    def _spelling_failed(self,error):
        """保留被冻结答案及原结果，恢复为重试保存操作，不提前跳题。"""
        self._spelling_saving=False
        self._set_saving_controls(False)
        self.spelling.set_active(True)
        self.spelling.answer.setReadOnly(True)
        self.spelling.hint_button.setEnabled(False)
        self.spelling.reveal_button.setEnabled(self._reveal_pending)
        self.spelling.submit_button.setText('重试保存 →')
        self.spelling.feedback.setText('本次成绩未保存，输入已保留，请重试。')

    def _hint(self):
        """标记辅助资格后展示首字母，保存期间不允许变更资格。"""
        if self._spelling_saving:
            return
        first = self.service.hint()
        if first:
            self.spelling.feedback.setText(f'首字母是 {first}。这一题会记为辅助完成。')

    def _reveal(self):
        """异步保存查看答案事件，完成前不把未提交事件当成已判定题目。"""
        if self._spelling_saving:
            return
        self._reveal_pending = True
        try:
            answer=self.service.reveal()
        except EnglishSaveError as error:
            self._spelling_failed(error)
            return
        session=self.service.session
        self._spelling_saving=True
        self._set_saving_controls(True)
        self._tasks.resolve(answer,lambda answer:self._revealed(session,answer),self._spelling_failed)

    def _revealed(self,session,answer):
        """查看答案事件提交后确认原会话，展示结果并进入必要纠正。"""
        self._spelling_saving=False
        self._reveal_pending=False
        self._set_saving_controls(False)
        confirm=getattr(self.service,'confirm_saved',None)
        if confirm:
            confirm()
        if answer and session is self.service.session:
            self._set_running(session.correcting)
            self.spelling.show_result(session.current,session.result)
            if session.correcting:
                self.spelling.show_correction(session.current)
            self.refresh()

    def _show_word(self, session):
        """展示当前词及首测/轮末复测进度。"""
        self.spelling.show_word(session.current, session.index, len(session.words))
        if session.phase == 'retest':
            self.spelling.progress.setText(f'轮末复测 {session.index - session.first_total + 1} / {len(session.words) - session.first_total}')

    def _correct(self, *, skip=False):
        """正确纠正或显式跳过后回到题目推进，纠正不重新算一次独立成绩。"""
        if self._spelling_saving:
            return
        session = self.service.session
        if session and self.service.correct(self.spelling.answer.text(), skip=skip):
            self.spelling.skip_button.hide()
            self._submit_spelling()
        elif session and session.correcting:
            self.spelling.feedback.setText(f'再核对一次：{session.current.word}。也可以跳过纠正。')

    def _choose_targets(self):
        """从当前词库挑选本轮造句目标词并更新展示，不请求模型。"""
        self._targets = tuple(w.word for w in self.service.catalog.sample(self.library.deck, 3))
        self.sentences.targets.setText('本轮目标词  /  ' + '  ·  '.join(self._targets))

    def _generate(self):
        """检查模型/资格/当前状态后捕获输入发起造句异步请求。"""
        if self._sentence_saving or self._spelling_saving:
            return
        if self._sentence_pending is not None:
            self.sentences.status.setText('上次成绩尚未保存，请先重试记录。')
            return
        if self._pending_material is not None:
            if not self._material_saving:
                self._save_generated()
            return
        if self._request is not None:
            return
        allowed, reason = self.service.ai_access(self._ai_service, self._balance)
        if not allowed:
            self.sentences.status.setText(reason)
            return
        self._reset_sentence()
        request = SentenceRequest(self._ai_service, self.library.deck, self._targets,
                                  self.sentences.topic.text().strip(), self,
                                  test_mode=self.service.test_session.enabled)
        request.done.connect(self._generated, Qt.QueuedConnection)
        self._request = request
        self.sentences.set_busy(True)
        self.sentences.usage_label.begin_request()
        self.sentences.status.setText('正在生成；只有有效材料保存成功才会使用训练券。')
        try:
            request.start()
        except Exception as error:
            self._request=None
            self.sentences.set_busy(False)
            self.sentences.status.setText(str(error))
            request.deleteLater()

    @Slot(str, bool, object)
    def _generated(self,request_id,ok,result):
        """按请求 ID 拒绝迟到生成，成功内容保留供单独保存，用量只属于本次请求。"""
        request=self._request
        if request is None or request_id!=request.id or request.deck!=self.library.deck:
            return
        self._request=None
        self.sentences.usage_label.set_usage(request.usage)
        if not ok:
            finish_network_result(request)
            request.deleteLater()
            self.sentences.set_busy(False)
            self.sentences.status.setText(str(result))
            return
        self._pending_material=(request,result)
        self._save_generated()

    def _save_generated(self):
        """用原请求操作 ID 异步保存材料及消费资格，失败重试不再次调用模型。"""
        request,result=self._pending_material
        self._material_saving=True
        self._set_saving_controls(True)
        self.sentences.set_busy(True)
        try:
            saved=self.service.save_generated(request.deck,request.topic,list(request.words),result,
                self._balance,test_mode=request.test_mode,operation_id=request.id)
        except Exception as error:
            self._material_failed(error)
            return
        self._tasks.resolve(saved,self._material_saved,self._material_failed)

    def _material_failed(self,error):
        """保留生成内容和请求 ID，开放保存重试，不重复消耗 API token。"""
        self._material_saving=False
        self._set_saving_controls(False)
        self.sentences.set_busy(False)
        self.sentences.status.setText(f'材料未保存，训练券未使用：{error}。点击生成按钮重试保存。')

    def _material_saved(self,_):
        """材料提交成功后刷新本机历史并结束结果处理租约。"""
        if self._pending_material is None:
            return
        request,result=self._pending_material
        self._pending_material=None
        self._material_saving=False
        self._set_saving_controls(False)
        finish_network_result(request)
        deck=request.deck
        request.deleteLater()
        self.sentences.set_busy(False)
        if deck==self.library.deck:
            self.sentences.set_history(self.service.sentence_history(deck))
            self.sentences.status.setText('语句已经收好。选一句，开始跟打吧。')

    def _cancel_request(self):
        """取消结果接收并清除无效生成状态，传输结束由共享准入独立管理。"""
        if self._pending_material is not None and not self._material_saving:
            request=self._pending_material[0]
            request.cancel()
            request.deleteLater()
            self._pending_material=None
        if self._request is not None:
            self.sentences.usage_label.set_usage(self._request.usage)
            self._request.cancel()
            self._request.deleteLater()
            self._request = None
            self.sentences.set_busy(False)
            self.sentences.status.setText('本次生成已取消，训练券未使用。')

    def _reset_sentence(self):
        """重置句子练习临时输入/时间状态，不删除已保存材料。"""
        self._sentence_run = None
        self._sentence_pending = None
        self.sentences.input.setReadOnly(False)
        self.sentences.set_running(False)
        self.sentences.generate_button.setEnabled(True)
        self.sentences.shuffle_button.setEnabled(True)
        self._set_running(False)

    def _start_sentence(self):
        """捕获选中参考句及新作答 ID 开始训练，重练不重新生成材料。"""
        reference = self.sentences.reference_text
        if (not reference or self._sentence_run is not None or self._request is not None
                or self._sentence_saving or self._material_saving or self._pending_material is not None):
            return
        self._sentence_run = (uuid.uuid4().hex, self.library.deck, reference, time.monotonic())
        self.sentences.set_running(True)
        self.scroll.ensureWidgetVisible(self.sentences.input)
        self.sentences.status.setText('照着英文手动输入，完成后记录这一次。')
        self._set_running(True)

    def _finish_sentence(self):
        """冻结本次句子答案数值与用时，异步提交评分结果，保存中禁止重复结算。"""
        if self._sentence_run is None or self._sentence_saving:
            return
        answer = self.sentences.input.toPlainText()
        if not answer.strip():
            self.sentences.status.setText('先输入句子，再记录这一次。')
            return
        event_id, deck, reference, started = self._sentence_run
        if self._sentence_pending is None:
            self._sentence_pending = (event_id, deck, reference, answer, time.monotonic() - started,
                                      sentence_alignment(answer, reference))
        event_id, deck, reference, answer, elapsed, _ = self._sentence_pending
        self._sentence_saving = True
        self._set_saving_controls(True)
        self.sentences.input.setReadOnly(True)
        self.sentences.finish_button.setEnabled(False)
        self.sentences.generate_button.setEnabled(False)
        self.sentences.shuffle_button.setEnabled(False)
        try:
            result = self.service.record_sentence(deck, reference, answer, elapsed, event_id)
        except Exception as exc:
            self._sentence_failed(exc)
            return
        self._tasks.resolve(result,lambda result:self._sentence_saved(event_id,result),
                            self._sentence_failed)

    def _sentence_failed(self, error):
        """保留原句子结算事件与输入，允许用原 ID 重试保存。"""
        self._sentence_saving = False
        self._set_saving_controls(False)
        self.sentences.finish_button.setEnabled(True)
        self.sentences.status.setText('本次成绩未保存，输入已保留，请重试。')

    def _sentence_saved(self,event_id,result):
        """提交成功后展示数值与瞬时单词对齐并恢复控件，不持久化答案原文。"""
        self._sentence_saving = False
        self._set_saving_controls(False)
        if self._sentence_run is None or self._sentence_run[0] != event_id:
            return
        tokens = self._sentence_pending[-1]
        self._reset_sentence()
        self.sentences.generate_button.setEnabled(True)
        self.sentences.shuffle_button.setEnabled(True)
        self.sentences.show_alignment(tokens)
        self.sentences.status.setText(f"这一句完成 · 单词正确率 {result['accuracy']:.1%} · 错误词数 {result['errors']} · 用时 {result['elapsed']:.1f} 秒")
        if result['saved']:
            self.result_saved.emit({'id': f'sentence:{event_id}', 'accuracy': result['accuracy']})

    def _sentence_progress(self):
        """根据当前主动输入更新句子训练的临时进度提示。"""
        if self._sentence_run is not None:
            _, _, reference, _ = self._sentence_run
            count = len(self.sentences.input.toPlainText())
            self.sentences.status.setText(f'已输入 {count} / {len(reference)} 字符 · 完成后记录这一次')

    def set_motion_enabled(self, enabled):
        """把全局动效资格同步给拼写反馈装饰。"""
        self.spelling.set_motion_enabled(enabled)

    def apply_theme(self):
        """同步三个学习面板和页面布局的颜色/字号。"""
        self.library.apply_theme()
        self.spelling.apply_theme()
        self.sentences.apply_theme()
        self._apply_type()
        self.paper.update()

    def hideEvent(self, event):
        """页面隐藏时取消未接收生成并暂停视觉反馈，已受理保存按提交结果完成。"""
        self._cancel_request()
        # 最小化、托盘与切页都保留题目/草稿；只有显式换模式或词库重置练习。
        self._set_running(False)
        self.set_motion_enabled(False)
        super().hideEvent(event)

    def showEvent(self, event):
        """页面显示后恢复允许的动效并刷新展示状态。"""
        super().showEvent(event)
        self.refresh()
        session = self.service.session
        spelling_active = session is not None and not session.finished and (session.result is None or session.correcting)
        self._set_running(self._sentence_run is not None or spelling_active)

    def update_exit_status(self):
        """返回是否正在保存及是否有未完成学习，供更新退出检查。"""
        saving = self._spelling_saving or self._sentence_saving or self._material_saving or self._font_saving
        session = self.service.session
        unfinished = bool((session and not session.finished) or self._sentence_run or self._request
                          or self._pending_material or self._sentence_pending)
        return saving, unfinished

    def discard_for_update(self):
        """仅非保存期间显式丢弃未完成学习和生成结果，保留已提交材料/成绩。"""
        if self.update_exit_status()[0]:
            raise RuntimeError('学习结果正在保存，请稍候。')
        self._cancel_request()
        self.service.session = None
        if hasattr(self.service, 'pending_result'):
            self.service.pending_result = None
            self.service.pending_session = None
        self._reset_sentence()
        self.spelling.set_active(False)
        self.spelling.skip_button.hide()
        self._set_running(False)
