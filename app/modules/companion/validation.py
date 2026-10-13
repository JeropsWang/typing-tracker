"""Bounded, portable JSON and Windows-safe resource paths."""
import copy
import re
from pathlib import PurePosixPath
from string import Formatter

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImageReader
from .models import PLACEHOLDERS, STATES

MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
MAX_FILES = 100
FORMATS = {'.png', '.webp', '.gif'}
ID_RE = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')


def safe_path(name, *, manifest=False):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('素材路径必须是包内的相对路径。')
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('作品包含不安全的路径。')
    for part in path.parts:
        if part[-1:] in (' ', '.') or any(ord(c) < 32 for c in part):
            raise ValueError('作品包含无效的 Windows 文件名。')
        stem = part.split('.')[0].upper()
        if stem in ('CON', 'PRN', 'AUX', 'NUL') or re.fullmatch(r'(COM|LPT)[1-9]', stem):
            raise ValueError('作品包含保留的 Windows 文件名。')
    if name == 'manifest.json' and manifest:
        return name
    if len(path.parts) < 2 or path.parts[0] != 'assets' or path.suffix.lower() not in FORMATS:
        raise ValueError('仅支持 assets/ 内的 PNG、静态 WebP 和 GIF。')
    return name


def image_size(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError('素材不存在、为链接或超过 10 MiB。')
    # Decode bounded bytes so an exception traceback cannot retain a Windows file handle.
    buffer = QBuffer()
    buffer.setData(path.read_bytes())
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if (not reader.canRead() or not size.isValid() or max(size.width(), size.height()) > 2048):
        raise ValueError('素材无法解码，或图片边长超过 2048 像素。')
    fmt = bytes(reader.format()).decode('ascii', 'replace').lower()
    if fmt not in ('png', 'webp', 'gif') or (fmt == 'webp' and reader.supportsAnimation()):
        raise ValueError('动画素材请使用 GIF，静态素材请使用 PNG 或 WebP。')
    if reader.read().isNull():
        raise ValueError('素材内容损坏。')
    return size.width(), size.height()


def validate_lines(lines):
    if not isinstance(lines, list) or len(lines) > 50:
        raise ValueError('每个状态最多支持 50 条话术。')
    for line in lines:
        if not isinstance(line, str) or not line.strip() or len(line) > 160:
            raise ValueError('话术需要 1–160 个字符。')
        try:
            fields = list(Formatter().parse(line))
        except ValueError as exc:
            raise ValueError('话术中的花括号不完整。') from exc
        for _, field, spec, conversion in fields:
            if field is not None and (field not in PLACEHOLDERS or spec or conversion):
                raise ValueError('话术仅支持 {nickname}、{level}、{speed}、{accuracy}、{streak}。')
        # Literal doubled braces are intentionally not a separate template syntax.
        if '{{' in line or '}}' in line:
            raise ValueError('请使用单层花括号填写话术变量。')


def validate_manifest(manifest, root):
    if not isinstance(manifest, dict) or set(manifest) - {
            'schema_version', 'id', 'name', 'author', 'description', 'version', 'states', 'memes'}:
        raise ValueError('作品格式含未知字段。')
    data = copy.deepcopy(manifest)
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('不支持此作品格式版本。')
    if not ID_RE.fullmatch(str(data.get('id', ''))):
        raise ValueError('作品标识无效。')
    for key, limit in (('name', 60), ('author', 60), ('description', 500), ('version', 30)):
        value = data.setdefault(key, '' if key != 'version' else '1.0')
        if not isinstance(value, str) or len(value) > limit or (key == 'name' and not value.strip()):
            raise ValueError(f'作品 {key} 字段无效。')
    states = data.get('states')
    if not isinstance(states, dict) or 'idle' not in states or set(states) - set(STATES):
        raise ValueError('作品必须包含待机状态，且只能使用已支持的状态。')
    memes = data.setdefault('memes', [])
    if not isinstance(memes, list) or len(memes) > 20:
        raise ValueError('每个作品最多支持 20 张表情包。')
    sizes = {}
    entries = [('idle', states['idle'])] + [(k, v) for k, v in states.items() if k != 'idle']
    entries += [('meme', entry) for entry in memes]
    for key, entry in entries:
        if not isinstance(entry, dict) or set(entry) - {'asset', 'rect', 'frame', 'duration_ms', 'lines'}:
            raise ValueError('状态格式含未知字段。')
        name = safe_path(entry.get('asset'))
        validate_lines(entry.setdefault('lines', []))
        duration = entry.setdefault('duration_ms', 6000)
        frame = entry.setdefault('frame', 0)
        if type(duration) is not int or not 1000 <= duration <= 30000:
            raise ValueError('状态持续时间需要在 1–30 秒之间。')
        if type(frame) is not int or not 0 <= frame <= 100:
            raise ValueError('静态预览帧需要在 0–100 之间。')
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('素材路径越过作品目录。')
        try:
            if name not in sizes:
                sizes[name] = image_size(path)
            w, h = sizes[name]
            rect = entry.get('rect')
            if rect is not None and (not isinstance(rect, list) or len(rect) != 4
                    or any(type(v) is not int for v in rect) or min(rect[:2]) < 0
                    or min(rect[2:]) < 1 or rect[0] + rect[2] > w or rect[1] + rect[3] > h):
                raise ValueError('素材图集选区越界。')
        except ValueError:
            if key == 'idle':
                raise
            entry['asset'] = states['idle']['asset']
            entry['rect'] = states['idle'].get('rect')
            entry['frame'] = states['idle']['frame']
    return data
