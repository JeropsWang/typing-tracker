"""内置 Sariana 头像目录；仅保存稳定标识，不把素材路径写入用户设置。"""

DEFAULT_AVATAR = 'default'
AVATAR_PRESETS = (
    ('default', '默认'), ('chibi', 'Q 版'), ('front', '正脸'),
    ('side', '侧脸'), ('lino', '贝尔塔'),
)


def normalize_avatar(value):
    return value if value in dict(AVATAR_PRESETS) else DEFAULT_AVATAR
