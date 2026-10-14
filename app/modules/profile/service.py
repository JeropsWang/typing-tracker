"""设置草稿的校验与提交，UI 不直接协调数据库和头像文件。"""
from __future__ import annotations
from ...storage.unit_of_work import transactional

from pathlib import Path
from urllib.parse import urlsplit
from ...core.avatars import normalize_avatar


def validate_ai(config: dict) -> str:
    """检查启用 AI 的接口地址，合法/未启用返回空串，否则返回可见校验提示。"""
    if config.get('backend') == 'off' or not config.get('base_url'):
        return ''
    try:
        url = urlsplit(config['base_url'])
        if url.scheme in ('http', 'https') and url.hostname and url.port != 0:
            return ''
    except ValueError:
        pass
    return '请输入有效的 http:// 或 https:// 服务地址；留空使用默认地址。'


class SettingsService:
    """工作线程中的设置/头像提交服务，文件写入失败或数据库失败都保留原有状态。"""
    def __init__(self, repo, data_dir=None):
        """装配配置仓储和可选数据目录，头像写入只发生在指定目录。"""
        self._repo = repo
        self._data_dir = Path(data_dir) if data_dir else None

    def save(self, values: dict, avatar_action=None):
        """None 保持上传头像、False 切回内置 Sariana、bytes 保存 PNG。"""
        values = dict(values)
        if 'avatar_preset' in values:
            values['avatar_preset'] = normalize_avatar(values['avatar_preset'])
        target = None
        original = None
        if isinstance(avatar_action, bytes):
            if self._data_dir is None:
                raise ValueError('数据目录不可用，无法保存头像。')
            folder = self._data_dir / 'avatars'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / 'avatar.png'
            original = target.read_bytes() if target.exists() else None
            staged = folder / 'avatar.pending.png'
            staged.write_bytes(avatar_action)
            staged.replace(target)
            values['avatar_image'] = '1'
        elif avatar_action is False:
            # 保留原文件，方便以后恢复；展示切回所选 Sariana。
            values['avatar_image'] = ''
        try:
            with self._repo.transaction():
                self._repo.set_settings(values)
        except Exception:
            if target is not None:
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(original)
            raise
