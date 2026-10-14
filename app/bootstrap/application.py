"""Desktop composition root and asynchronous application commands."""
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from ..storage.db import connect_db, init_schema
from ..storage.session import DataSession
from ..modules.tracking.api import TrackingService
from ..modules.growth.api import CheckinService, RewardService, AchievementService, EncourageService, level_and_progress
from ..modules.practice.api import ChallengeService, KeyboardWarriorService
from ..modules.profile.api import SettingsService
from .read_models import ReadModels, TABLES
from ..modules.english.api import EnglishService
from ..workflows.events import Change, EventBus
from ..workflows.material import save_passage
from .worker import ApplicationWorker

class RemoteService:
    """供 UI 使用的命令/查询代理：写命令发往 ApplicationWorker，查询读取脱离连接的模型。"""
    def __init__(self,application,name,queries,commands):
        """登记业务服务名、只读能力和允许异步执行的命令集合。"""
        self._application,self._name,self._queries,self._commands=application,name,queries,set(commands)
    def __getattr__(self,name):
        """命令转为工作线程调用，其余属性从只读能力取得，不暴露数据库连接。"""
        if name in self._commands:
            return lambda *args,**kwargs:self._application.command(self._name,name,*args,**kwargs)
        return getattr(self._queries,name)

class DesktopApplication:
    """桌面应用装配根，协调唯一数据库线程、展示模型、异步命令及最终统计提交。"""
    def __init__(self,data_dir,balance,definitions,defaults=None):
        """创建事件/展示模型和工作线程，启动恢复后装配各模块对外命令代理。"""
        self.events=EventBus()
        self.models=ReadModels()
        self.balance=balance
        self.definitions=definitions
        self.data_dir=Path(data_dir)
        from .. import __version__
        from ..integrations.updates import UpdateService
        self.update_service=UpdateService(self.data_dir/'update-cache',__version__)
        self._defaults=defaults or {}
        self._checkpoint_pending=None
        self._closing=False
        self._closed=False
        self._checkpoint_lock=__import__('threading').Lock()
        self._command_lock=__import__('threading').Lock()
        self._pending_commands=set()
        self._update_preparing=False
        self._update_ready=False
        self.last_saved_at=None
        self.save_error=None
        self.worker=ApplicationWorker(self._initialize,lambda context:context['repo'].close())
        # Startup must finish migrations/recovery before input hooks and windows exist.
        context=self.worker.ready.result()
        self.counter=context['counter']
        self.startup_checkin=context['startup_checkin']
        self.startup_unlocks=context['startup_unlocks']
        self.checkin=RemoteService(self,'checkin',CheckinService(self.models,balance),('checkin_if_needed','apply_makeup_card'))
        self.rewards=RemoteService(self,'rewards',RewardService(self.models,balance),('activate_exp_boost','use_exp_boost'))
        self.achievements=RemoteService(self,'achievements',AchievementService(self.models,balance,definitions),('check_all','claim'))
        self.encourage=RemoteService(self,'encourage',None,('check',))
        self.practice=RemoteService(self,'practice',ChallengeService(self.models),('record',))
        self.keyboard=RemoteService(self,'keyboard',KeyboardWarriorService(self.models),('record',))
        self.settings=RemoteService(self,'settings',None,('save',))
        self.english_commands=RemoteService(self,'english',None,('save_generated','record_sentence'))

    def _initialize(self):
        """在应用线程打开/迁移数据库并装配业务，发布初始模型后切断计数器的直接 SQL 保存入口。"""
        conn=connect_db(self.data_dir/'app.db')
        try:
            init_schema(conn)
            repo=DataSession(conn)
            with repo.transaction():
                repo.set_settings({k:v for k,v in self._defaults.items() if repo.get_setting(k) is None})
            counter=TrackingService(repo,repo.get_setting,self.balance)
            context=dict(repo=repo,counter=counter,
                checkin=CheckinService(repo,self.balance),rewards=RewardService(repo,self.balance),
                achievements=AchievementService(repo,self.balance,self.definitions),encourage=EncourageService(repo,self.balance),
                practice=ChallengeService(repo),keyboard=KeyboardWarriorService(repo),
                settings=SettingsService(repo,self.data_dir),english=EnglishService(repo))
            context['startup_checkin']=context['checkin'].checkin_if_needed(counter.current_day())
            context['startup_unlocks']=context['achievements'].check_all(counter)
            self._refresh(repo,set(TABLES))
            previous=conn.execute('SELECT saved_at FROM tracking_checkpoint WHERE id=1').fetchone()
            self.last_saved_at=previous['saved_at'] if previous else None
            repo.uow.events.subscribe(lambda event:self._changed(context,event))
            # Counter never reaches SQL from a UI or input thread in the desktop path.
            counter._save=None
            counter._get_setting=self.models.get_setting
            return context
        except BaseException:
            conn.close()
            raise

    def _refresh(self,repo,topics):
        """在数据库线程读取变化主题所属表，转换为独立行后替换展示模型。"""
        names={name for topic in topics for name in TABLES.get(topic,())}
        self.models.replace({name:[dict(r) for r in repo._conn.execute(f'SELECT * FROM {name}')] for name in names})

    def _changed(self,context,event):
        """提交通知后先刷新只读模型再发布业务事件，升级反馈以已提交经验为依据。"""
        changes=event.payload if event.topic=='commit' else (event,)
        before=level_and_progress(self.models.get_exp(),self.balance)[0]
        self._refresh(context['repo'],{change.topic for change in changes})
        for change in changes:
            self.events.publish(change)
        after=level_and_progress(self.models.get_exp(),self.balance)[0]
        if after>before:
            self.events.publish(Change('level',dict(previous=before,level=after)))

    def stop_accepting(self):
        """标记退出准入关闭，不再接收新的应用命令。"""
        self._closing=True

    def _submit(self,action):
        """持锁登记异步命令 Future，拒绝退出后的新请求，并在完成回调中移除在途记录。"""
        with self._command_lock:
            if self._closing:
                future=Future()
                future.set_exception(RuntimeError('应用正在退出，不再接受新任务。'))
                return future
            future=self.worker.submit(action)
            self._pending_commands.add(future)
        def completed(value):
            """从在途命令集合移除已完成 Future，不在回调中等待其他任务。"""
            with self._command_lock:
                self._pending_commands.discard(value)
        future.add_done_callback(completed)
        return future

    def has_pending_commands(self):
        """检查是否仍有未完成写命令，供退出/更新流程决定是否可继续。"""
        with self._command_lock:
            return any(not future.done() for future in self._pending_commands)

    def prepare_update_exit(self):
        """Drain accepted commands and commit final statistics without closing the worker.

        The shell must stop input hooks and timers before calling this. Failure leaves
        dirty counter state and the database worker intact, ready for a retry.
        """
        with self._command_lock:
            if self._closed or self._update_preparing:
                future=Future()
                future.set_exception(RuntimeError('应用已关闭或正在准备更新。'))
                return future
            self._closing=True
            self._update_preparing=True
            self._update_ready=False
        def prepare(context):
            """排空后提交最终检查点并确认版本；失败保留工作线程/脏计数并恢复可重试准入。"""
            from ..workflows.checkpoint import CheckpointWriter
            try:
                checkpoint=self.counter.prepare_checkpoint()
                if checkpoint is not None:
                    saved=CheckpointWriter(context['repo'],self.balance).save(checkpoint)
                    self.counter.acknowledge(checkpoint)
                    self.last_saved_at=saved
                    self.save_error=None
                    self.events.publish(Change('saved',saved))
                unlocks=context['achievements'].check_all(self.counter)
                for item in unlocks:
                    self.events.publish(Change('achievement',item))
                self._update_ready=True
                return self.last_saved_at
            except Exception as error:
                self.save_error=str(error)
                self.events.publish(Change('save_failed',dict(error=str(error),last_saved_at=self.last_saved_at)))
                self.cancel_update_exit()
                raise
        return self.worker.submit(prepare)

    def cancel_update_exit(self):
        """更新准备失败时恢复命令准入和准备标记，前提是应用尚未最终关闭。"""
        if not self._closed:
            with self._command_lock:
                self._closing=False
                self._update_preparing=False
                self._update_ready=False

    def finish_update_exit(self):
        """Close asynchronously only after prepare_update_exit succeeded."""
        from ..integrations.updates.service import background
        if not self._update_preparing or not self._update_ready:
            future=Future()
            future.set_exception(RuntimeError('尚未完成更新前的保存。'))
            return future
        def finish():
            """在独立清理任务中等待应用线程关闭，再标记更新退出完成。"""
            self.worker.close()
            self._closed=True
        return background(finish)

    def command(self,service,method,*args,**kwargs):
        """把指定业务服务/方法封装为工作线程命令，返回 Future。"""
        return self._submit(lambda context:getattr(context[service],method)(*args,**kwargs))

    def set_settings(self,values):
        """异步提交一批个人设置，界面草稿不直接修改数据库。"""
        return self.command('settings','save',values)
    def set_setting(self,key,value):
        """将单键设置写入转为统一异步批量提交。"""
        return self.set_settings({key:value})
    def save_passage(self,lang,topic,text,*,operation_id,test_mode=False):
        """异步执行材料保存/资格消费的跨模块事务，沿用请求的稳定操作 ID。"""
        return self._submit(lambda context:save_passage(context['repo'],self.balance,lang,topic,text,
                                  operation_id=operation_id,test_mode=test_mode))
    def record_attempt(self,event):
        """异步保存英语作答，UI 在 Future 成功后确认会话状态。"""
        def action(context):
            """在数据库所属线程调用英语记录服务。"""
            return context['english'].record_attempt(event)
        return self._submit(action)
    def export(self,out_dir):
        """将数据导出工作排到应用线程，避免 UI 同步访问数据库。"""
        from ..workflows.export import export_all
        return self._submit(lambda context:export_all(context['repo'],out_dir))

    def flush(self):
        """捕获不可变统计检查点并合并重复保存请求，已有在途检查点不再排一份。"""
        if self._update_preparing:
            return None
        with self._checkpoint_lock:
            if self._checkpoint_pending is not None and not self._checkpoint_pending.done():
                return self._checkpoint_pending
            checkpoint=self.counter.prepare_checkpoint()
            if checkpoint is None:
                return None
            def write(context):
                """在工作线程提交检查点；成功后确认版本/发布成就和保存状态，失败保留脏计数。"""
                from ..workflows.checkpoint import CheckpointWriter
                try:
                    saved=CheckpointWriter(context['repo'],self.balance).save(checkpoint)
                    self.counter.acknowledge(checkpoint)
                    self.last_saved_at=saved
                    self.save_error=None
                    unlocks=context['achievements'].check_all(self.counter)
                    for item in unlocks:
                        self.events.publish(Change('achievement',item))
                    self.events.publish(Change('saved',saved))
                    return saved
                except Exception as error:
                    self.save_error=str(error)
                    self.events.publish(Change('save_failed',dict(error=str(error),last_saved_at=self.last_saved_at)))
                    raise
            self._checkpoint_pending=self.worker.submit(write)
            return self._checkpoint_pending

    def close(self):
        """停止准入并等待最后统计保存，随后关闭工作线程及其数据库连接。"""
        if self._closed:
            return
        self.stop_accepting()
        # Hooks are already stopped by the shell before calling this.
        pending=self._checkpoint_pending
        if pending:
            try:
                pending.result()
            except Exception:
                pass
        final=self.flush()
        try:
            if final:
                final.result()
        finally:
            self.worker.close()
            self._closed=True
