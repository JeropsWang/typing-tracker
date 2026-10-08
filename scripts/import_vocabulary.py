"""将锁定版本 ECDICT 整理成三套内置词库；原始 CSV 不随应用分发。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b'
SOURCE_HASH = '1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf'


def import_vocabulary(source, output, license_file):
    source, output = Path(source), Path(output)
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_HASH:
        raise ValueError('源文件与锁定 ECDICT 版本不一致，请使用 manifest 中的版本。')
    license_data = Path(license_file).read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    books = {'cet4': {}, 'cet6': {}, 'kaoyan': {}}
    counts = {'source_rows': 0, 'exam_tagged_rows': 0, 'excluded_rows': 0}
    tag_counts = {'cet4': 0, 'cet6': 0, 'ky': 0}
    with source.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            counts['source_rows'] += 1
            tags = set(row['tag'].split())
            for tag in tag_counts:
                tag_counts[tag] += tag in tags
            if not tags.intersection(tag_counts):
                continue
            counts['exam_tagged_rows'] += 1
            word = row['word'].strip()
            meaning = row['translation'].replace('\\n', '\n').strip()
            if not re.fullmatch(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", word) or not meaning or len(word) > 40:
                counts['excluded_rows'] += 1
                continue
            ranks = [int(row[k]) for k in ('frq', 'bnc') if row[k].isdigit() and int(row[k]) > 0]
            entry = dict(word=word, meaning=meaning, phonetic=row['phonetic'].strip(),
                         frequency_rank=min(ranks) if ranks else 0)
            for key, selected in (('cet4', 'cet4' in tags),
                                  ('cet6', bool(tags.intersection(('cet4', 'cet6')))),
                                  ('kaoyan', 'ky' in tags)):
                if selected:
                    books[key].setdefault(word.casefold(), entry)
    manifest = dict(source='https://github.com/skywind3000/ECDICT', revision=REVISION,
                    source_sha256=SOURCE_HASH, license='MIT', tag_counts=tag_counts,
                    validation=counts, books={})
    names = {'cet4': '四级', 'cet6': '六级（含四级基础词）', 'kaoyan': '考研'}
    for key, entries in books.items():
        words = sorted(entries.values(), key=lambda e: (e['frequency_rank'] or 10**9, e['word'].casefold()))
        path = output / f'{key}.json'
        path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest['books'][key] = dict(name=names[key], count=len(words),
                                      phonetic_count=sum(bool(e['phonetic']) for e in words),
                                      sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (output / 'LICENSE-ECDICT.txt').write_bytes(license_data)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'config/vocabulary')
    parser.add_argument('--license', type=Path, default=ROOT / 'config/vocabulary/LICENSE-ECDICT.txt')
    args = parser.parse_args()
    result = import_vocabulary(args.source, args.output, args.license)
    print(json.dumps({key: info['count'] for key, info in result['books'].items()}, ensure_ascii=False))
