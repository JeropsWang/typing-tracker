"""Updater transport and process integration. No Qt or database access."""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = 'JeropsWang/typing-tracker'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
APP_ID = '{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}'
_HASH = re.compile(r'[0-9a-fA-F]{64}')


class UpdateCancelled(Exception):
    pass


def background(action):
    future = Future()
    def run():
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(action())
            except BaseException as error:
                future.set_exception(error)
    threading.Thread(target=run, name='sariana-updates', daemon=True).start()
    return future


def stable_version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:\+[\w.]+)?', str(value))
    if not match:
        raise ValueError('版本号不是正式版本。')
    return tuple(int(part) for part in match.groups())


def _trusted_url(url, *, redirect=False):
    parsed = urlsplit(url)
    hosts = {'api.github.com', 'github.com'}
    if redirect:
        hosts.update({'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('更新地址不属于受信任的 GitHub HTTPS 地址。')
    return url


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _trusted_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    digest: str = ''


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    notes: str
    installer: Asset | None = None
    portable: Asset | None = None
    checksums: Asset | None = None


@dataclass(frozen=True)
class VerifiedInstaller:
    path: Path
    size: int
    digest: str

    def verify(self):
        if not self.path.is_file() or self.path.stat().st_size != self.size:
            raise ValueError('安装包大小校验失败，请重新下载。')
        with self.path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _stream_hash(stream)
        if digest != self.digest:
            raise ValueError('安装包 SHA-256 校验失败，请重新下载。')
        return self


def _stream_hash(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def parse_release(payload, current_version):
    if not isinstance(payload, dict):
        raise ValueError('GitHub 返回了无效版本信息。')
    if payload.get('draft') or payload.get('prerelease'):
        return None
    tag = payload.get('tag_name', '')
    try:
        newer = stable_version(tag) > stable_version(current_version)
    except ValueError:
        return None
    if not newer:
        return None
    base = f'https://github.com/{REPOSITORY}/releases'
    url = payload.get('html_url', '')
    if url != f'{base}/tag/{quote(tag, safe="")}':
        raise ValueError('版本页不属于指定仓库。')
    version = tag.removeprefix('v').split('+')[0]
    assets = {}
    for raw in payload.get('assets', []):
        name = raw.get('name', '')
        expected = f'{base}/download/{quote(tag, safe="")}/{quote(name, safe="")}'
        if raw.get('browser_download_url') != expected:
            continue
        if not isinstance(raw.get('size'), int) or raw['size'] <= 0 or raw.get('state', 'uploaded') != 'uploaded':
            continue
        digest = raw.get('digest') or ''
        digest = digest[7:].lower() if digest.startswith('sha256:') and _HASH.fullmatch(digest[7:]) else ''
        assets[name] = Asset(name, expected, raw['size'], digest)
    # Both supported release brands share the stable installer AppId.
    def find(suffix):
        return next((assets[name] for brand in ('Sariana', 'TypingTracker')
                     if (name := f'{brand}-{version}-{suffix}') in assets), None)
    return Release(version, url, str(payload.get('body') or ''),
                   find('windows-x64-setup.exe'), find('windows-x64-portable.zip'), find('SHA256SUMS.txt'))


class UpdateService:
    def __init__(self, cache_dir, current_version, *, opener=None):
        self.cache_dir = Path(cache_dir)
        self.current_version = current_version
        self._opener = opener or build_opener(_Redirects())

    def _open(self, url):
        _trusted_url(url)
        request = Request(url, headers={'User-Agent': f'Sariana/{self.current_version}',
                                       'Accept': 'application/vnd.github+json' if url == API_URL else 'application/octet-stream',
                                       'X-GitHub-Api-Version': '2026-03-10'})
        try:
            return self._opener.open(request, timeout=20)
        except HTTPError as error:
            if error.code in (403, 429):
                raise RuntimeError('GitHub 请求受限，请稍后再检查。') from error
            if error.code == 404:
                raise RuntimeError('暂无可用的正式版本或下载文件。') from error
            raise RuntimeError(f'GitHub 请求失败（HTTP {error.code}）。') from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError('无法连接 GitHub，请检查网络后重试。') from error

    def check(self):
        with self._open(API_URL) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('版本信息超过大小限制。')
        return parse_release(json.loads(data), self.current_version)

    def download(self, release, cancel, progress=lambda *_: None):
        asset = release.installer
        if asset is None:
            raise ValueError('此版本没有 Windows x64 安装包。')
        digest = asset.digest
        if not digest:
            checksums = release.checksums
            if checksums is None or checksums.size > 1024 * 1024:
                raise ValueError('此版本缺少 SHA-256 校验信息，不能安装。')
            with self._open(checksums.url) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) != checksums.size:
                raise ValueError('校验文件大小不一致。')
            matches = []
            for line in data.decode('utf-8').splitlines():
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and _HASH.fullmatch(parts[0]) and parts[1].lstrip('*') == asset.name:
                    matches.append(parts[0].lower())
            if len(matches) != 1:
                raise ValueError('校验文件缺少安装包的唯一 SHA-256。')
            digest = matches[0]
        if cancel.is_set():
            raise UpdateCancelled('下载已取消。')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Versioned names come exclusively from validated release asset names.
        destination = self.cache_dir / asset.name
        partial = destination.with_suffix(destination.suffix + '.partial')
        partial.unlink(missing_ok=True)
        try:
            received = 0
            hasher = hashlib.sha256()
            with self._open(asset.url) as response, partial.open('wb') as output:
                while True:
                    if cancel.is_set():
                        raise UpdateCancelled('下载已取消。')
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    received += len(block)
                    if received > asset.size:
                        raise ValueError('安装包超过公布大小。')
                    output.write(block)
                    hasher.update(block)
                    progress(received, asset.size)
            if cancel.is_set():
                raise UpdateCancelled('下载已取消。')
            if received != asset.size or hasher.hexdigest() != digest:
                raise ValueError('安装包大小或 SHA-256 校验失败，请重新下载。')
            partial.replace(destination)
            return VerifiedInstaller(destination, asset.size, digest)
        finally:
            partial.unlink(missing_ok=True)


def installation_kind(*, frozen=None, executable=None, registry_locations=None):
    if frozen is None:
        frozen = getattr(sys, 'frozen', False)
    if not frozen:
        return 'source'
    executable = Path(executable or sys.executable).resolve()
    if registry_locations is None:
        registry_locations = []
        if sys.platform == 'win32':
            import winreg
            key_name = f'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_ID}_is1'
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view) as key:
                            registry_locations.append(winreg.QueryValueEx(key, 'InstallLocation')[0])
                    except OSError:
                        pass
    for location in registry_locations:
        if location and executable.parent == Path(location).resolve() and executable.name.lower() in ('sariana.exe', 'typingtracker.exe'):
            return 'installed'
    return 'portable'


@dataclass
class InstallerHandoff:
    process: object
    ready_file: Path
    token: str

    def authorize(self):
        # Only written after database close; helper also requires parent termination.
        self.ready_file.write_text(self.token, encoding='ascii')

    def cancel(self):
        self.ready_file.unlink(missing_ok=True)
        if self.process.poll() is None:
            self.process.terminate()


def launch_installer_helper(installer, data_dir):
    """Start a hidden helper; it waits for this process to exit before opening Inno Setup."""
    installer.verify()
    if not getattr(sys, 'frozen', False) or sys.platform != 'win32':
        raise RuntimeError('只有 Windows 安装版可以启动安装向导。')
    token=uuid.uuid4().hex
    ready_file=Path(data_dir)/'update-cache'/f'authorization-{token}.ready'
    process=subprocess.Popen([sys.executable, '--run-update-installer', str(installer.path),
                             '--update-parent-pid', str(os.getpid()), '--update-sha256', installer.digest,
                             '--update-size', str(installer.size), '--data-dir', str(data_dir),
                             '--update-authorization',token],
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return InstallerHandoff(process,ready_file,token)


def run_installer_helper(args):
    import ctypes
    from ctypes import wintypes
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        raise RuntimeError('安装辅助程序仅用于 Windows 发布版本。')
    cache = (Path(args.data_dir) / 'update-cache').resolve()
    path = Path(args.run_update_installer).resolve()
    if path.parent != cache or not re.fullmatch(r'(Sariana|TypingTracker)-\d+\.\d+\.\d+-windows-x64-setup\.exe', path.name):
        raise ValueError('安装包不在更新缓存中。')
    if not _HASH.fullmatch(args.update_sha256 or '') or args.update_parent_pid <= 0:
        raise ValueError('无效安装辅助参数。')
    if not re.fullmatch(r'[0-9a-f]{32}',args.update_authorization or ''):
        raise ValueError('无效更新授权参数。')
    ready_file=cache/f'authorization-{args.update_authorization}.ready'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.OpenProcess(0x00100000, False, args.update_parent_pid)
    if process:
        try:
            if kernel.WaitForSingleObject(process, 120_000) != 0:
                raise RuntimeError('应用未完成退出，已取消安装。')
        finally:
            kernel.CloseHandle(process)
    elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: parent already exited
        raise RuntimeError('无法确认应用已经退出，已取消安装。')
    try:
        if not ready_file.is_file() or ready_file.read_text(encoding='ascii')!=args.update_authorization:
            raise RuntimeError('应用没有完成更新退出，已取消安装。')
        VerifiedInstaller(path, args.update_size, args.update_sha256.lower()).verify()
        subprocess.Popen([str(path)])
    finally:
        ready_file.unlink(missing_ok=True)
    return 0
