"""开发者可选的只读本地索引适配；固定源码入口，不执行索引给出的命令或链接。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import sys

CODE_ENTRIES = {
    'app/modules/companion/api.py': '桌宠公共契约',
    'app/modules/companion/news_service.py': '任务事务与保存',
    'app/modules/companion/repository.py': '来信持久化',
    'app/ui/companion/news_controller.py': '排期与通知协调',
    'app/ui/companion/memory_presenter.py': '记忆展示能力',
}
LIMIT = 2 * 1024 * 1024


@dataclass(frozen=True)
class CodeEntry:
    """脱离文件的安全展示条目；路径只可能来自应用固定白名单。"""
    path: str
    title: str
    module: str
    local_path: str = ''
    semantics: str = ''
    state: str = '索引不可用'


@dataclass(frozen=True)
class CodeIndexSnapshot:
    """开发者只读结果，不含其他对象、本机配置、鉴权 URL 或用户数据。"""
    status: str
    entries: tuple[CodeEntry, ...]


class DevelopmentIndexService:
    """在独立后台线程有界读取源码索引，产品不依赖 AOCI 服务在线。"""
    def __init__(self, root=None, *, frozen=None):
        """源码根默认取安装模块位置；冻结模式只显示模块定位而不猜测源码提交。"""
        self.root = Path(root or Path(__file__).resolve().parents[2]).resolve()
        self.frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else frozen
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='memory-index')

    def snapshot(self, object_refs):
        """捕获对象集合后异步读取；非白名单入口失败，不把索引内容当作路径授权。"""
        return self._executor.submit(self._read, tuple(object_refs))

    def _bounded(self, relative):
        """拒绝符号链接越界和超限文件，读取最多 2MiB 加一字节以防大小竞争。"""
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path.stat().st_size > LIMIT:
            raise ValueError('本地索引文件不可用。')
        with path.open('rb') as source:
            data = source.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('本地索引文件过大。')
        return data

    def _read(self, refs):
        """只解析允许对象的 FRAS 原文和基线摘要，不推导认知或声称治理已对齐。"""
        if any(ref not in CODE_ENTRIES for ref in refs):
            raise ValueError('代码入口不在允许列表中。')
        index, hashes = {}, {}
        status = '本地索引快照，治理状态未核验'
        if self.frozen:
            status = '此版本未附源码；可按下方模块名定位，源码提交入口不可用。'
        else:
            try:
                baseline = json.loads(self._bounded('.aoci/baseline.json'))
                if baseline.get('version') != 1 or not isinstance(baseline.get('files'), dict):
                    raise ValueError('不支持的基线格式')
                hashes = {path: baseline['files'].get(path, {}).get('sha256') for path in refs}
                current = ''
                for line in self._bounded('aoci.code.txt').decode('utf-8-sig').splitlines():
                    if line.startswith('===') and line.endswith('==='):
                        current = line[3:-3].replace('\\', '/').rstrip('/')
                        continue
                    match = re.fullmatch(r'([^\[\r\n]+)\[([A-Z0-9.]+)\]: (.+)', line)
                    if match:
                        full = current + '/' + match[1]
                        for ref in refs:
                            if full == self.root.as_posix() + '/' + ref:
                                index[ref] = match[2] + ' · ' + match[3]
            except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
                status = '本地索引不可用；产品记忆与代码模块定位仍可查看。'
        entries = []
        for ref in refs:
            local, state = '', '源码未附带' if self.frozen else '索引未收录'
            if not self.frozen:
                try:
                    digest = hashlib.sha256(self._bounded(ref)).hexdigest()
                    local = str((self.root / ref).resolve())
                    state = ('源码摘要匹配，治理未核验' if digest == hashes.get(ref) else '源码已变化，索引过期或未核验')
                except (OSError, ValueError):
                    state = '源码入口不可用'
            entries.append(CodeEntry(ref, CODE_ENTRIES[ref], ref[:-3].replace('/', '.'), local,
                                     index.get(ref, ''), state))
        return CodeIndexSnapshot(status, tuple(entries))

    def close(self):
        """停止接收新读取，取消尚未开始任务，不阻塞 Qt 等待后台文件读取。"""
        self._executor.shutdown(wait=False, cancel_futures=True)
