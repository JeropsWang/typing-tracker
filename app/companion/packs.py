"""Local immutable pack revisions, with atomic activation pointers."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid
import zipfile

from .validation import ID_RE, MAX_FILE, MAX_FILES, MAX_TOTAL, safe_path, validate_manifest

BUILTIN_DIR = Path(__file__).resolve().parents[1] / 'ui/assets/companion'
DEFAULT_PACK = 'starlight'


@dataclass(frozen=True)
class Sprite:
    path: Path
    rect: list | None = None
    frame: int = 0


@dataclass(frozen=True)
class LoadedPack:
    manifest: dict
    root: Path
    builtin: bool = False

    @property
    def id(self):
        return self.manifest['id']

    @property
    def revision(self):
        return '' if self.builtin else self.root.name

    def entry_for(self, state):
        return self.manifest['states'].get(state, self.manifest['states']['idle'])

    def sprite(self, entry):
        return Sprite(self.root / entry['asset'], entry.get('rect'), entry.get('frame', 0))

    def asset_for(self, state):
        return self.sprite(self.entry_for(state))


class PackStore:
    def __init__(self, data_dir, builtin_dir=BUILTIN_DIR):
        self.user_dir = Path(data_dir) / 'companion/packs'
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.builtin_dir = Path(builtin_dir)
        self.errors = []

    def load(self, pack_id, revision=None):
        if not isinstance(pack_id, str) or not ID_RE.fullmatch(pack_id):
            raise ValueError('作品标识无效。')
        builtin = (self.builtin_dir / pack_id / 'manifest.json').is_file()
        if builtin:
            root = self.builtin_dir / pack_id
        else:
            folder = self.user_dir / pack_id
            if revision is None:
                pointer = json.loads((folder / 'current.json').read_text(encoding='utf-8'))
                revision = pointer['revision']
            if not isinstance(revision, str) or not re_revision(revision):
                raise ValueError('作品保存记录损坏。')
            root = folder / 'revisions' / revision
        if root.is_symlink():
            raise ValueError('作品目录不能是符号链接。')
        path = root / 'manifest.json'
        if path.stat().st_size > MAX_FILE:
            raise ValueError('作品说明文件过大。')
        manifest = validate_manifest(json.loads(path.read_text(encoding='utf-8')), root)
        if manifest['id'] != pack_id:
            raise ValueError('作品标识和保存目录不一致。')
        return LoadedPack(manifest, root, builtin)

    def list_packs(self):
        self.errors = []
        ids = {p.name for base in (self.builtin_dir, self.user_dir) if base.is_dir()
               for p in base.iterdir() if p.is_dir() and ID_RE.fullmatch(p.name)}
        result = []
        for key in sorted(ids):
            try:
                result.append(self.load(key))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.errors.append(f'{key}：{exc}')
        return sorted(result, key=lambda p: (not p.builtin, p.manifest['name']))

    def save(self, manifest, assets, *, new=False):
        data = json.loads(json.dumps(manifest, ensure_ascii=False))
        key = data.get('id', '')
        if new or not key.startswith('user_') or not (self.user_dir / key / 'current.json').is_file():
            key = 'user_' + uuid.uuid4().hex
        if not ID_RE.fullmatch(key):
            raise ValueError('作品标识无效。')
        data['id'] = key
        if len(assets) + 1 > MAX_FILES:
            raise ValueError('作品最多包含 100 个文件。')
        with tempfile.TemporaryDirectory(prefix='.stage-', dir=self.user_dir) as stage:
            root = Path(stage)
            total = 0
            folded = set()
            for name, source in assets.items():
                safe_path(name)
                if name.casefold() in folded:
                    raise ValueError('素材路径存在大小写冲突。')
                folded.add(name.casefold())
                source = Path(source)
                if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_FILE:
                    raise ValueError('素材不存在或超过 10 MiB。')
                total += source.stat().st_size
                if total > MAX_TOTAL:
                    raise ValueError('作品资源超过 50 MiB。')
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            data = validate_manifest(data, root)
            encoded = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
            if len(encoded) > MAX_FILE or total + len(encoded) > MAX_TOTAL:
                raise ValueError('作品数据过大。')
            (root / 'manifest.json').write_bytes(encoded)
            revision = uuid.uuid4().hex
            folder = self.user_dir / key
            revisions = folder / 'revisions'
            revisions.mkdir(parents=True, exist_ok=True)
            target = revisions / revision
            # Move the complete revision; old revisions remain valid for active views.
            os.replace(root, target)
            # Final paths can fail even when staging succeeded (e.g. Windows path limits).
            # Verify the actual revision before publishing the latest-version pointer.
            pack = self.load(key, revision)
            pointer = folder / ('pending-' + revision + '.json')
            pointer.write_text(json.dumps({'revision': revision}), encoding='utf-8')
            os.replace(pointer, folder / 'current.json')
        return pack

    def import_zip(self, path):
        with tempfile.TemporaryDirectory(prefix='.import-', dir=self.user_dir) as temp:
            root = Path(temp)
            with zipfile.ZipFile(path) as archive:
                files = archive.infolist()
                if len(files) > MAX_FILES or sum(f.file_size for f in files) > MAX_TOTAL:
                    raise ValueError('作品包超过文件数量或 50 MiB 限制。')
                seen = set()
                for item in files:
                    if item.is_dir():
                        # Directory entries are unnecessary; require a harmless relative assets path.
                        directory = item.filename.rstrip('/')
                        safe_path(directory + '/check.png')
                        continue
                    name = safe_path(item.filename, manifest=True)
                    if name.casefold() in seen or item.file_size > MAX_FILE:
                        raise ValueError('作品包存在大小写冲突或超大文件。')
                    seen.add(name.casefold())
                    if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                        raise ValueError('不支持链接文件或加密作品包。')
                    content = archive.read(item)
                    if len(content) != item.file_size:
                        raise ValueError('作品包文件大小不一致。')
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            try:
                manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError('作品包缺少有效的 manifest.json。') from exc
            assets = {p.relative_to(root).as_posix(): p for p in (root / 'assets').rglob('*') if p.is_file()}
            return self.save(manifest, assets, new=True)

    def export_zip(self, pack_id, path):
        pack = self.load(pack_id)
        target = Path(path)
        pending = target.with_name(target.name + '.' + uuid.uuid4().hex + '.pending')
        try:
            with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(pack.manifest, ensure_ascii=False, indent=2))
                entries = list(pack.manifest['states'].values()) + pack.manifest['memes']
                for name in sorted({entry['asset'] for entry in entries}):
                    archive.write(pack.root / name, name)
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)

    def delete(self, pack_id):
        pack = self.load(pack_id)
        if pack.builtin:
            raise ValueError('内置作品不可删除，请复制后编辑。')
        # Remove the activation pointer, preserving immutable data for any active reader.
        (self.user_dir / pack_id / 'current.json').unlink()


def re_revision(value):
    return len(value) == 32 and all(c in '0123456789abcdef' for c in value)
