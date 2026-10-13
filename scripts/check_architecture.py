"""Enforce dependency direction without a third-party lint framework."""
import ast
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
PURE_FILES={'app/modules/tracking/domain.py','app/modules/tracking/clock.py',
            'app/modules/practice/domain.py','app/modules/practice/keyboard_session.py',
            'app/modules/english/session.py','app/modules/english/scoring.py','app/modules/english/review.py',
            'app/modules/companion/models.py','app/modules/companion/runtime.py'}


def dependencies(path,source):
    package=list(path.parent.relative_to(ROOT).parts)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Import):
            for name in node.names:
                yield node.lineno,name.name
        elif isinstance(node,ast.ImportFrom):
            base=package[:len(package)-node.level+1] if node.level else []
            target='.'.join(base+([node.module] if node.module else []))
            yield node.lineno,target
            if node.module is None:
                for name in node.names:
                    yield node.lineno,target+'.'+name.name


def check(path,source):
    relative=path.relative_to(ROOT).as_posix()
    errors=[]
    for line,target in dependencies(path,source):
        if relative.startswith('app/ui/') and target.startswith(('app.storage','sqlite3','psycopg','redis')):
            errors.append(f'{relative}:{line}: UI must use presenter/query interfaces: {target}')
        if relative in PURE_FILES and target.startswith(('PySide6','sqlite3','urllib','http','socket','app.storage','app.integrations')):
            errors.append(f'{relative}:{line}: domain cannot depend on infrastructure: {target}')
        own=relative.split('/')[2] if relative.startswith('app/modules/') else None
        if own and target.startswith('app.modules.'):
            parts=target.split('.')
            if len(parts)>=3 and parts[2]!=own and (len(parts)<4 or parts[3]!='api'):
                errors.append(f'{relative}:{line}: cross-module imports must use api.py: {target}')
    if relative.startswith('app/ui/'):
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Attribute) and node.attr=='_conn':
                errors.append(f'{relative}:{node.lineno}: UI cannot reach a SQL connection')
    return errors


def main():
    errors=[]
    for path in (ROOT/'app').rglob('*.py'):
        errors.extend(check(path,path.read_text(encoding='utf-8-sig')))
    for error in errors:
        print(error)
    if not errors:
        print('Architecture import boundaries passed.')
    return int(bool(errors))

if __name__=='__main__':sys.exit(main())
