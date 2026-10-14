"""只读检查自有 Python 源码的模块、类和函数说明覆盖，不导入应用或访问用户数据。"""
import argparse
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def definitions(node, parents=()):
    """递归枚举显式类、方法和嵌套函数的限定名称，包含条件分支中的定义。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = (*parents, child.name)
            yield '.'.join(qualified), child
            yield from definitions(child, qualified)
        else:
            yield from definitions(child, parents)


def audit_file(path):
    """解析一个 UTF-8 源文件，返回各类定义数量与缺失说明/语法错误，不执行源码。"""
    relative = path.relative_to(ROOT).as_posix()
    counts = dict(modules=0, classes=0, functions=0)
    missing = []
    try:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as error:
        return counts, [f'{relative}: 无法检查源码：{error}']
    counts['modules'] = 1
    if not ast.get_docstring(tree):
        missing.append(f'{relative}:1: 缺少模块说明')
    for name, node in definitions(tree):
        kind = 'classes' if isinstance(node, ast.ClassDef) else 'functions'
        counts[kind] += 1
        if not ast.get_docstring(node):
            missing.append(f'{relative}:{node.lineno}: {name} 缺少功能说明')
    return counts, missing


def main():
    """检查 app、scripts 与主入口，输出摘要或 JSON；缺说明/源码不可解析时返回非零。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='输出可供验工记录使用的 JSON')
    args = parser.parse_args()
    # 明确只扫描项目自有代码；不扫描 .local 中下载的 Pi、依赖、缓存或用户预览数据。
    paths = sorted({ROOT / 'main.py', *(ROOT / 'app').rglob('*.py'),
                    *(ROOT / 'scripts').rglob('*.py')})
    totals = dict(modules=0, classes=0, functions=0)
    missing = []
    for path in paths:
        counts, errors = audit_file(path)
        for kind, count in counts.items():
            totals[kind] += count
        missing.extend(errors)
    report = dict(files=len(paths), **totals, missing=missing)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for error in missing:
            print(error)
        print(f"注释覆盖：{len(paths)} 个文件，{totals['classes']} 个类，"
              f"{totals['functions']} 个函数/方法；缺失 {len(missing)} 项。")
    return int(bool(missing))


if __name__ == '__main__':
    raise SystemExit(main())
