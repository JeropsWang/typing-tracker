"""内置考试参考词库；只读取资源，不访问用户数据库或网络。"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import re

VOCABULARY_PATH = Path(__file__).resolve().parents[2] / 'config/vocabulary'
DECKS = {'cet4': '四级', 'cet6': '六级 · 含基础词', 'kaoyan': '考研'}
WORD_PATTERN = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


@dataclass(frozen=True)
class Word:
    word: str
    meaning: str
    phonetic: str = ''
    frequency_rank: int = 0

    @property
    def key(self):
        return self.word.casefold()


class VocabularyCatalog:
    def __init__(self, directory=VOCABULARY_PATH):
        self.directory = Path(directory)
        self._cache = {}

    def load(self, deck):
        if deck not in DECKS:
            raise ValueError('请选择四级、六级或考研词库。')
        if deck not in self._cache:
            try:
                data = (self.directory / f'{deck}.json').read_bytes()
                manifest = json.loads((self.directory / 'manifest.json').read_text(encoding='utf-8'))
                info = manifest['books'][deck]
                if hashlib.sha256(data).hexdigest() != info['sha256']:
                    raise ValueError('词库文件校验失败，请重新安装应用。')
                words = tuple(Word(**row) for row in json.loads(data))
                if len(words) != info['count'] or len({w.key for w in words}) != len(words):
                    raise ValueError('词库数量或词条重复，请重新导入。')
                if any(not WORD_PATTERN.fullmatch(w.word) or not w.meaning.strip() for w in words):
                    raise ValueError('词库包含无效单词或空释义。')
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError('词库资源不可用，请检查安装目录。') from error
            self._cache[deck] = words
        return self._cache[deck]

    def sample(self, deck, count, keys=None):
        if count < 1:
            raise ValueError('每轮至少练习一个单词。')
        words = self.load(deck)
        if keys is not None:
            words = tuple(w for w in words if w.key in keys)
        return random.SystemRandom().sample(words, min(count, len(words)))
