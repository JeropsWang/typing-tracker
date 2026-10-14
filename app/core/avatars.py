"""内置 Sariana 头像目录；仅保存稳定标识，不把素材路径写入用户设置。"""

DEFAULT_AVATAR = 'default'
AVATAR_PRESETS = (
    ('default', '默认'), ('chibi', 'Q 版'), ('front', '正脸'),
    ('side', '侧脸'), ('lino', '贝尔塔'),
)


def normalize_avatar(value):
    """将未知头像标识回退默认预设，用户设置仅保存稳定标识。"""
    return value if value in dict(AVATAR_PRESETS) else DEFAULT_AVATAR
