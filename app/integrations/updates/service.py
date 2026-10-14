"""Updater transport and process integration. No Qt or database access."""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = 'JeropsWang/typing-tracker'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases/latest'
APP_ID = '{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}'
_HASH = re.compile(r'[0-9a-fA-F]{64}')


class UpdateCancelled(Exception):
    """更新下载被明确取消的异常，界面应与网络/校验失败区分。"""
    pass


class UpdateRateLimited(RuntimeError):
    """GitHub 已明确限流的可重试错误，携带服务器允许再次检查的本机时间戳。"""
    def __init__(self, retry_at):
        """生成脱敏提示及恢复时间，不展示上游正文中的出口 IP 或认证信息。"""
        self.retry_at = retry_at
        resume = datetime.fromtimestamp(retry_at).strftime('%m-%d %H:%M:%S')
        super().__init__(f'GitHub 请求额度暂时用完，预计 {resume} 后可再检查（本机时间）。\n'
                         '可打开版本页手动下载。')


def _rate_limit_error(error, now):
    """根据响应头和有界错误正文识别限流，区分普通 403；返回限流凭据或 None。"""
    headers = {key.lower(): str(value) for key, value in (error.headers or {}).items()}
    try:
        body = error.read(8192).decode('utf-8', errors='replace').lower()
    except OSError:
        body = ''
    if not (error.code == 429 or headers.get('x-ratelimit-remaining') == '0' or
            'retry-after' in headers or 'rate limit' in body):
        return None
    # 默认至少等待一分钟；遵守服务器的 Retry-After 和额度恢复时刻，不自动反复重试。
    delays = [60]
    try:
        delays.append(int(headers.get('retry-after', '0')))
    except ValueError:
        pass
    if headers.get('x-ratelimit-remaining') == '0':
        try:
            delays.append(int(headers.get('x-ratelimit-reset', '0')) - now)
        except ValueError:
            pass
    # 恶意/异常头部不能生成不可表示的日期或永久封锁本次应用会话。
    return UpdateRateLimited(now + min(max(delays), 24 * 60 * 60))


def background(action):
    """用独立更新线程执行 action，立即返回 Future，不阻塞 Qt 或数据库线程。"""
    future = Future()
    def run():
        """仅未取消的 Future 执行后台操作，将结果或异常回传给调用方。"""
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(action())
            except BaseException as error:
                future.set_exception(error)
    threading.Thread(target=run, name='sariana-updates', daemon=True).start()
    return future


def stable_version(value):
    """解析正式三段版本为可比较整数元组，预发布/无效版本抛 ValueError。"""
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:\+[\w.]+)?', str(value))
    if not match:
        raise ValueError('版本号不是正式版本。')
    return tuple(int(part) for part in match.groups())


def _trusted_url(url, *, redirect=False):
    """限制更新请求为白名单 GitHub HTTPS 地址，资产重定向仅开放指定下载域名。"""
    parsed = urlsplit(url)
    hosts = {'api.github.com', 'github.com'}
    if redirect:
        hosts.update({'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('更新地址不属于受信任的 GitHub HTTPS 地址。')
    return url


class _Redirects(HTTPRedirectHandler):
    """更新请求的受限重定向处理器，重定向仍需通过 HTTPS/域名白名单。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """验证目标下载域名后才允许跟随重定向，拒绝越出更新信任边界。"""
        _trusted_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Asset:
    """正式发布附件的不可变名称、下载 URL、大小与可选 SHA-256 描述。"""
    name: str
    url: str
    size: int
    digest: str = ''


@dataclass(frozen=True)
class Release:
    """已解析的较新正式版本及安装/便携/校验附件，不含草稿或预发布。"""
    version: str
    url: str
    notes: str
    installer: Asset | None = None
    portable: Asset | None = None
    checksums: Asset | None = None


@dataclass(frozen=True)
class VerifiedInstaller:
    """缓存安装文件与期望大小/摘要的校验凭据，启动前须再次验证。"""
    path: Path
    size: int
    digest: str

    def verify(self):
        """核对文件存在、大小和 SHA-256，任一不一致拒绝安装，成功返回自身。"""
        if not self.path.is_file() or self.path.stat().st_size != self.size:
            raise ValueError('安装包大小校验失败，请重新下载。')
        with self.path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _stream_hash(stream)
        if digest != self.digest:
            raise ValueError('安装包 SHA-256 校验失败，请重新下载。')
        return self


def _stream_hash(stream):
    """分块计算文件 SHA-256，供缺少 hashlib.file_digest 的 Python 版本兼容。"""
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def parse_release(payload, current_version):
    """拒绝草稿/预发布，比较版本并仅接受命名/URL/大小合规的正式附件。"""
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
        """按新旧品牌名查找当前正式版本指定后缀附件。"""
        return next((assets[name] for brand in ('Sariana', 'TypingTracker')
                     if (name := f'{brand}-{version}-{suffix}') in assets), None)
    return Release(version, url, str(payload.get('body') or ''),
                   find('windows-x64-setup.exe'), find('windows-x64-portable.zip'), find('SHA256SUMS.txt'))


class UpdateService:
    """隔离网络线程使用的正式版本查询与有界下载服务，不执行安装或读写用户数据库。"""
    def __init__(self, cache_dir, current_version, *, opener=None):
        """绑定专用更新缓存目录、当前版本和受限/可注入传输。"""
        self.cache_dir = Path(cache_dir)
        self.current_version = current_version
        self._opener = opener or build_opener(_Redirects())
        self._check_retry_at = 0.0

    def _open(self, url):
        """打开受信任更新 URL，设置请求标识和超时，将上游错误转为可读提示。"""
        _trusted_url(url)
        if url == API_URL and time.time() < self._check_retry_at:
            raise UpdateRateLimited(self._check_retry_at)
        request = Request(url, headers={'User-Agent': f'Sariana/{self.current_version}',
                                       'Accept': 'application/vnd.github+json' if url == API_URL else 'application/octet-stream',
                                       'X-GitHub-Api-Version': '2026-03-10'})
        try:
            return self._opener.open(request, timeout=20)
        except HTTPError as error:
            try:
                if error.code in (403, 429):
                    limited = _rate_limit_error(error, time.time())
                    if limited:
                        # API 额度不影响已知附件的独立下载入口，冷却只阻止再次检查版本。
                        if url == API_URL:
                            self._check_retry_at = limited.retry_at
                        raise limited from error
                    raise RuntimeError('GitHub 拒绝了更新请求（HTTP 403），可打开版本页手动下载。') from error
                if error.code == 404:
                    raise RuntimeError('暂无可用的正式版本或下载文件。') from error
                raise RuntimeError(f'GitHub 请求失败（HTTP {error.code}）。') from error
            finally:
                error.close()
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError('无法连接 GitHub，请检查网络后重试。') from error

    def check(self):
        """有界读取正式版本信息并解析是否有更新，不下载或启动安装器。"""
        with self._open(API_URL) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('版本信息超过大小限制。')
        return parse_release(json.loads(data), self.current_version)

    def download(self, release, cancel, progress=lambda *_: None):
        """下载指定安装附件到临时缓存并核对大小/摘要，取消或失败清理本次临时文件。"""
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
    """根据冻结状态、运行路径及安装注册表区分源码、安装版和便携版。"""
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
    """主程序与隐藏安装辅助进程的交接凭据，仅完成保存/关闭后允许授权。"""
    process: object
    ready_file: Path
    token: str

    def authorize(self):
        # Only written after database close; helper also requires parent termination.
        """数据库已关闭后写出本次授权 token；辅助程序还需等待主进程实际退出。"""
        self.ready_file.write_text(self.token, encoding='ascii')

    def cancel(self):
        """移除本次授权文件并终止自己启动的辅助进程，不碰其他安装进程。"""
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
    """在主进程退出且授权/缓存路径/摘要均合格后启动安装器，最后清理一次性授权。"""
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
