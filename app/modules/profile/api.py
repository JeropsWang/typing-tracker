"""个人设置的公开查询/提交接口，不向生产 UI 暴露数据库连接。"""
from .service import SettingsService, validate_ai

from typing import Protocol

class ProfileQueries(Protocol):
    """个人配置的只读查询契约，缺失值支持默认回退。"""
    def get_setting(self,key: str,default=None):
        """读取指定设置值，键不存在时返回传入默认值。"""
        ...

class ProfileCommands(Protocol):
    """设置与头像的统一提交契约，界面应通过异步能力调用。"""
    def save(self,values: dict,avatar_action=None):
        """原子保存配置及头像操作；失败保留旧配置并补偿头像文件。"""
        ...
