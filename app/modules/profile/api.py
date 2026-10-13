from .service import SettingsService, validate_ai

from typing import Protocol

class ProfileQueries(Protocol):
    def get_setting(self,key: str,default=None): ...

class ProfileCommands(Protocol):
    def save(self,values: dict,avatar_action=None): ...
