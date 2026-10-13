"""Build UI capabilities without letting pages instantiate repositories/services."""
from concurrent.futures import Future
from ..modules.english.api import EnglishService, EnglishSaveError
from ..modules.practice.api import KeyboardWarriorService
from ..modules.profile.api import SettingsService
from ..workflows.material import save_passage
import uuid

class DesktopQueries:
    def __init__(self,application):
        self.application=application
        self.models=application.models
    def __getattr__(self,name):
        if name in ('set_setting','set_settings','save_passage','export'):
            return getattr(self.application,name)
        return getattr(self.models,name)

class EnglishPresenter(EnglishService):
    def __init__(self,queries,application,test_session=None):
        super().__init__(queries,test_session=test_session)
        self.application=application
        self.pending_result=None
        self.pending_session=None

    def submit(self,answer):
        if self.session is None:
            return dict(accepted=False)
        result=self.session.prepare(answer)
        if not result.get('accepted'):
            return result
        return self._persist(result)

    def reveal(self):
        if self.session is None or self.session.finished:
            return ''
        result=self.session.prepare_reveal()
        if not result.get('accepted'):
            return self.session.current.word
        future=self._persist(result)
        return _map_future(future,lambda _:self.pending_session.current.word)

    def _persist(self,result):
        if self.pending_result is not None and self.pending_result['id'] == result['id']:
            result = self.pending_result
        self.pending_result=result
        self.pending_session=self.session
        future=self.application.record_attempt(dict(result,deck=self.deck))
        return _map_future(future,lambda _:result)

    def confirm_saved(self):
        if self.pending_result is not None:
            self.pending_session.confirm(self.pending_result)
            self.pending_result=None
            self.pending_session=None

    def save_generated(self,*args,**kwargs):
        return self.application.english_commands.save_generated(*args,**kwargs)
    def record_sentence(self,*args,**kwargs):
        return self.application.english_commands.record_sentence(*args,**kwargs)


def _map_future(future,transform):
    mapped=Future()
    def done(source):
        try:
            mapped.set_result(transform(source.result()))
        except Exception as error:
            mapped.set_exception(error)
    future.add_done_callback(done)
    return mapped


def english_presenter(queries,test_session=None):
    if getattr(queries,'application',None) is not None:
        return EnglishPresenter(queries,getattr(queries,'application'),test_session)
    return EnglishService(queries,test_session=test_session)

def keyboard_presenter(queries):
    if getattr(queries,'application',None) is not None:
        return getattr(queries,'application').keyboard
    return KeyboardWarriorService(queries)

def settings_presenter(queries,data_dir):
    if getattr(queries,'application',None) is not None:
        return getattr(queries,'application').settings
    return SettingsService(queries,data_dir)

def save_material(queries,balance,lang,topic,text,*,operation_id,test_mode=False):
    if getattr(queries,'application',None) is not None:
        return queries.save_passage(lang,topic,text,operation_id=operation_id,test_mode=test_mode)
    return save_passage(queries,balance,lang,topic,text,operation_id=operation_id,test_mode=test_mode)
