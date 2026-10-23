"""Build UI capabilities without letting pages instantiate repositories/services."""
from concurrent.futures import Future
from ..modules.english.api import EnglishService, EnglishSaveError
from ..modules.practice.api import KeyboardWarriorService
from ..modules.profile.api import SettingsService
from ..workflows.material import save_passage
import uuid

class DesktopQueries:
    """桌面 UI 的能力门面，读取脱离数据库的模型，少量写操作转发给异步应用入口。"""
    def __init__(self,application):
        """持有应用和只读模型，不持有 SQLite 会话。"""
        self.application=application
        self.models=application.models
    def __getattr__(self,name):
        """将配置/材料/导出写入转发应用，其余查询转发内存模型。"""
        if name in ('set_setting','set_settings','save_passage','export'):
            return getattr(self.application,name)
        return getattr(self.models,name)

class EnglishPresenter(EnglishService):
    """英语页面的异步提交适配器，保留待保存结果和会话，提交成功才确认当前题目。"""
    def __init__(self,queries,application,test_session=None):
        """装配英语只读能力、应用命令和临时资格，初始化待保存重试状态。"""
        super().__init__(queries,test_session=test_session)
        self.application=application
        self.pending_result=None
        self.pending_session=None

    def submit(self,answer):
        """先准备稳定作答结果，再异步保存；无会话或拒绝的输入不排写任务。"""
        if self.session is None:
            return dict(accepted=False)
        result=self.session.prepare(answer)
        if not result.get('accepted'):
            return result
        return self._persist(result)

    def reveal(self):
        """准备辅助作答事件并异步保存，再返回本题答案显示所需 Future。"""
        if self.session is None or self.session.finished:
            return ''
        result=self.session.prepare_reveal()
        if not result.get('accepted'):
            return self.session.current.word
        future=self._persist(result)
        return _map_future(future,lambda _:self.pending_session.current.word)

    def _persist(self,result):
        """保留原结果/会话供失败重试，用同一作答 ID 请求工作线程记录。"""
        if self.pending_result is not None and self.pending_result['id'] == result['id']:
            result = self.pending_result
        self.pending_result=result
        self.pending_session=self.session
        future=self.application.record_attempt(dict(result,deck=self.deck))
        return _map_future(future,lambda _:result)

    def confirm_saved(self):
        """数据库提交成功后确认原会话题目，并清除待保存结果。"""
        if self.pending_result is not None:
            self.pending_session.confirm(self.pending_result)
            self.pending_result=None
            self.pending_session=None

    def save_generated(self,*args,**kwargs):
        """将造句材料保存交给英语异步命令，UI 不消费券或写 SQL。"""
        return self.application.english_commands.save_generated(*args,**kwargs)
    def record_sentence(self,*args,**kwargs):
        """把句子训练结算交给工作线程，不在 UI 记录成绩。"""
        return self.application.english_commands.record_sentence(*args,**kwargs)


def _map_future(future,transform):
    """建立转换后的 Future，保留源请求失败语义，不在调用线程阻塞等待。"""
    mapped=Future()
    def done(source):
        """源 Future 完成后转换结果或转发异常。"""
        try:
            mapped.set_result(transform(source.result()))
        except Exception as error:
            mapped.set_exception(error)
    future.add_done_callback(done)
    return mapped


def english_presenter(queries,test_session=None):
    """生产查询装配异步 Presenter；同步服务只保留给隔离测试/兼容调用。"""
    if getattr(queries,'application',None) is not None:
        return EnglishPresenter(queries,getattr(queries,'application'),test_session)
    return EnglishService(queries,test_session=test_session)

def keyboard_presenter(queries):
    """生产页面取应用的键盘侠异步能力，隔离兼容夹具使用同步服务。"""
    if getattr(queries,'application',None) is not None:
        return getattr(queries,'application').keyboard
    return KeyboardWarriorService(queries)

def settings_presenter(queries,data_dir):
    """生产页面取应用设置命令，兼容夹具按其数据目录装配同步设置服务。"""
    if getattr(queries,'application',None) is not None:
        return getattr(queries,'application').settings
    return SettingsService(queries,data_dir)


def companion_agent_service():
    """Network-only capability; no database connection leaves the worker."""
    from ..integrations.companion_agent import CompanionAgentService
    return CompanionAgentService()


def companion_setup_service():
    """装配独立的桌宠连接检查能力，不传出数据库连接。"""
    from ..integrations.companion_agent.setup import AgentSetupService
    return AgentSetupService()


def companion_news_capabilities(queries):
    """只给生产桌面交付异步来信命令和可注入时钟，旧同步预览保持无调度器。"""
    application = getattr(queries, 'application', None)
    if application is None:
        return None
    return application.news_commands, application.news_local_now, application.news_utc_now


def development_index_service():
    """装配可选只读索引能力，固定入口选择留在集成层，不暴露任意文件读取。"""
    from ..integrations.development_index import DevelopmentIndexService, CODE_ENTRIES
    service = DevelopmentIndexService()
    class AllowedIndex:
        """只允许页面请求固定对象集合，不接受来自报告或索引的路径。"""
        def snapshot(self):
            """异步交付固定代码入口的安全展示快照。"""
            return service.snapshot(tuple(CODE_ENTRIES))
        def close(self):
            """关闭窗口时停止索引后台准入。"""
            service.close()
    return AllowedIndex()

def save_material(queries,balance,lang,topic,text,*,operation_id,test_mode=False):
    """根据装配方式选择生产异步或兼容同步材料保存，保持同一操作 ID 和资格边界。"""
    if getattr(queries,'application',None) is not None:
        return queries.save_passage(lang,topic,text,operation_id=operation_id,test_mode=test_mode)
    return save_passage(queries,balance,lang,topic,text,operation_id=operation_id,test_mode=test_mode)
