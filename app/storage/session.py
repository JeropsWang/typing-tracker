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
    def __init__(self, conn, events=None):
        self._conn = conn
        self.uow = UnitOfWork(conn, events)
        self.profile = ProfileRepository(conn)
        self.tracking = TrackingRepository(conn)
        self.growth = GrowthRepository(conn)
        self.practice = PracticeRepository(conn)
        self.reporting = ReportingRepository(conn)
        self.english = EnglishRepository(conn, self.uow)

    def transaction(self):
        return self.uow.transaction()

    def operation(self, kind, operation_id, action):
        return self.uow.operation(kind, operation_id, action)

    def set_setting(self,key,value):
        return self.set_settings({key:value})

    def set_settings(self,values):
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
        for topic in ('profile', 'tracking', 'growth', 'practice', 'reporting'):
            store = getattr(self, topic)
            if hasattr(store, name):
                method = getattr(store, name)
                if name.startswith(('set_', 'add_', 'upsert_', 'clean_', 'use_', 'unlock_', 'delete_')):
                    @wraps(method)
                    def write(*args, **kwargs):
                        with self.transaction():
                            result = method(*args, **kwargs)
                            self.uow.changed(topic)
                            return result
                    return write
                return method
        raise AttributeError(name)

    def close(self):
        self._conn.close()
