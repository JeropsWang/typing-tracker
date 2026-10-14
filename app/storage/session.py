"""Internal workflow session. UI receives presenters, never this SQL object."""
from functools import wraps
from .unit_of_work import UnitOfWork
from ..modules.profile.repository import ProfileRepository
from ..modules.tracking.repository import TrackingRepository
from ..modules.growth.repository import GrowthRepository
from ..modules.practice.repository import PracticeRepository
from ..modules.reporting.repository import ReportingRepository
from ..modules.english.repository import EnglishRepository


class DataSession:
    """工作线程内部的模块仓储与 UnitOfWork 适配器；生产 UI 不持有它或 SQLite 连接。"""
    def __init__(self, conn, events=None):
        """为同一连接装配各业务仓储与统一提交协调者。"""
        self._conn = conn
        self.uow = UnitOfWork(conn, events)
        self.profile = ProfileRepository(conn)
        self.tracking = TrackingRepository(conn)
        self.growth = GrowthRepository(conn)
        self.practice = PracticeRepository(conn)
        self.reporting = ReportingRepository(conn)
        self.english = EnglishRepository(conn, self.uow)

    def transaction(self):
        """提供统一事务上下文，不允许仓储自行提交。"""
        return self.uow.transaction()

    def operation(self, kind, operation_id, action):
        """以业务类型和稳定操作 ID 执行幂等写入，重试返回原已提交结果。"""
        return self.uow.operation(kind, operation_id, action)

    def set_setting(self,key,value):
        """把单个配置写入转成统一批量设置事务。"""
        return self.set_settings({key:value})

    def set_settings(self,values):
        """按键归属把成长状态和资料配置分给各自仓储，在同一事务登记变更。"""
        growth_keys={'milestone_granted','exp_boost_until','last_encourage_at','typing_exp_date',
                     'typing_exp_today','typing_exp_blocks','challenge_exp_date','challenge_exp_today'}
        growth={key:value for key,value in values.items() if key in growth_keys}
        profile={key:value for key,value in values.items() if key not in growth_keys}
        with self.transaction():
            if growth:
                self.growth.set_state_settings(growth)
                self.uow.changed('growth')
            if profile:
                self.profile.set_settings(profile)
                self.uow.changed('profile')

    def __getattr__(self, name):
        """为旧接口查找归属仓储；写方法加事务和变更通知，读方法直接转发。"""
        for topic in ('profile', 'tracking', 'growth', 'practice', 'reporting'):
            store = getattr(self, topic)
            if hasattr(store, name):
                method = getattr(store, name)
                if name.startswith(('set_', 'add_', 'upsert_', 'clean_', 'use_', 'unlock_', 'delete_')):
                    @wraps(method)
                    def write(*args, **kwargs):
                        """在统一事务中执行选定仓储写入并登记所属主题，提交成功才会通知。"""
                        with self.transaction():
                            result = method(*args, **kwargs)
                            self.uow.changed(topic)
                            return result
                    return write
                return method
        raise AttributeError(name)

    def close(self):
        """关闭所属工作线程的 SQLite 连接，后续不再使用该会话。"""
        self._conn.close()
