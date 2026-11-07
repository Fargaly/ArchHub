"""Generate the installer's temporary Python package from its local import closure."""
import argparse
import ast
from importlib.util import resolve_name
from pathlib import Path


ENTRIES = tuple('nodelang.' + name for name in (
    'assistant_registration', 'client_mcp_installation',
    'native_workshop_profile', 'workshop_config', 'cell_secret_keys'))


def import_closure(source, entries=ENTRIES):
    """Follow local imports, including imports nested in functions and guards.

    The installer deliberately creates an empty nodelang __init__: importing
    the application initializer would enter the retired graph runtime.
    """
    source = Path(source)
    pending = list(entries)
    found = {}
    while pending:
        name = pending.pop()
        if name in found or name == 'nodelang':
            continue
        path = source.joinpath(*name.split('.')).with_suffix('.py')
        if not path.is_file():
            path = source.joinpath(*name.split('.'), '__init__.py')
        if not path.is_file():
            continue  # Standard library, external dependency, or an imported attribute.
        found[name] = path.relative_to(source)
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        # Package initializers are dependencies too (except the intentional stub).
        parts = name.split('.')
        pending.extend('.'.join(parts[:i]) for i in range(1, len(parts)))
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))):
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = resolve_name('.' * node.level + (node.module or ''), package) if node.level else (node.module or '')
                pending.append(base)
                pending.extend(base + '.' + alias.name for alias in node.names if alias.name != '*')
    missing = set(entries) - found.keys()
    if missing:
        raise ValueError('Missing preflight entry modules: ' + ', '.join(sorted(missing)))
    return sorted(found.values())


def generate(source, output):
    source, output = Path(source).resolve(), Path(output)
    files = import_closure(source)
    file_lines, code_lines = [], []
    for index, relative in enumerate(files):
        target = str(relative).replace('/', '\\')
        archived = f'preflight-{index}.py'
        file_lines.append(f'Source: "{source / relative}"; DestName: "{archived}"; Flags: dontcopy')
        code_lines.extend((
            f"    ForceDirectories(ExtractFileDir(ConnectorTemp + '\\{target}'));",
            f"    ExtractTemporaryFile('{archived}');",
            f"    if not FileCopy(ExpandConstant('{{tmp}}\\{archived}'), ConnectorTemp + '\\{target}', False) then",
            f"      RaiseException('Could not stage preflight module: {target}');"))
    output.mkdir(parents=True, exist_ok=True)
    for name, lines in (('preflight-files.iss', file_lines), ('preflight-code.iss', code_lines)):
        (output / name).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return files


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    arguments = parser.parse_args()
    print(f'Preflight import closure: {len(generate(arguments.source, arguments.output))} files')
