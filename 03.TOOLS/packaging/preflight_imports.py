"""Generate the installer's temporary Python package from its local import closure."""
import argparse
import ast
import re
from importlib.util import resolve_name
from pathlib import Path


ENTRIES = tuple('nodelang.' + name for name in (
    'assistant_registration', 'client_mcp_installation',
    'native_workshop_profile', 'workshop_config', 'runtime_credentials'))

RELEASE_ENTRIES = ENTRIES + tuple('nodelang.' + name for name in (
    '__init__', 'nograph_server', 'nograph_launcher', 'launcher', 'baboom_native_runtime',
    'native_agent_mcp', 'hook_decision', 'quiet_update', 'native_stop_hook',
    'host_addin_retarget')) + ('colleague_setup', 'app.secrets_store')


def import_closure(source, entries=ENTRIES):
    """Follow local imports, including imports nested in functions and guards.

    The installer uses a minimal package initializer for connector preflight.
    Release closure explicitly includes the real application initializer.
    """
    source = Path(source)
    pending = list(entries)
    found = {}
    seen = set()
    roots = [source / area for area in ('01.APP', '03.TOOLS', '06.CLOUD')] + [source]
    while pending:
        name = pending.pop()
        if name in seen or name == 'nodelang':
            continue
        seen.add(name)
        candidates = [root.joinpath(*name.split('.')).with_suffix('.py') for root in roots]
        candidates += [root.joinpath(*name.split('.'), '__init__.py') for root in roots]
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        if not path.is_file():
            continue  # Standard library, external dependency, or an imported attribute.
        found[name] = path.relative_to(source)
        package = name.removesuffix('.__init__') if path.name == '__init__.py' else name.rpartition('.')[0]
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
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                function = node.func
                if ((isinstance(function, ast.Name) and function.id == '__import__')
                        or (isinstance(function, ast.Attribute) and function.attr == 'import_module')):
                    target = node.args[0].value
                    if isinstance(target, str):
                        pending.append(resolve_name(target, package) if target.startswith('.') else target)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.py'):
                # Installer/source stamps and spec_from_file_location sibling helpers.
                relative = Path(node.value.replace('\\', '/'))
                if not relative.is_absolute() and '..' not in relative.parts:
                    sibling = path.parent / relative
                    if sibling.is_file():
                        pending.append(package + '.' + '.'.join(relative.with_suffix('').parts))
    missing = set(entries) - found.keys()
    if missing:
        raise ValueError('Missing preflight entry modules: ' + ', '.join(sorted(missing)))
    return sorted(set(found.values()))


def release_entries(repository):
    """All explicit Python inputs of the installer, in addition to app entry points."""
    repository = Path(repository)
    build = (repository / '03.TOOLS/installer/build_release.ps1').read_text(encoding='utf-8-sig')
    entries = set(RELEASE_ENTRIES)
    for value in re.findall(r"'([^'\r\n]+\.py)'", build):
        if value.startswith(('tools/', 'packaging/', 'app/', 'nodelang/')):
            entries.add(value[:-3].replace('/', '.'))
    return tuple(sorted(entries))


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
