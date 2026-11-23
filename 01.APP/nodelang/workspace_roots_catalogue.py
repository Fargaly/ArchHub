"""Registered workspace folders from the NOGRAPH Settings owner."""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath
from .user_paths import state_directory

class WorkspaceRootRefused(ValueError):
    pass

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROOT_PATH_PREFIX = 'workspace-roots/'
def project_folder_layout(parent, governed_root=''):
    base = Path(parent).resolve()
    root = Path(governed_root).resolve() if governed_root else None
    return 'Governed work folder' if root and (root / '00.GOVERNANCE').is_dir() and (root / '10.PRODUCT').is_dir() and base.is_relative_to(root) else 'Empty folder'


def read_project_template(template_source, parent, name, governed_root=''):
    directories = []
    source = Path(template_source)
    base = Path(parent)
    target = base / str(name or '')
    template = project_folder_layout(base, governed_root)
    if template != 'Empty folder':
        raise ValueError('Local templates apply outside the governed ArchHub workspace.')
    if not source.is_absolute() or not source.is_dir():
        raise ValueError('Choose an available local template folder.')
    if any(part.is_symlink() or part.is_junction() for part in (source, *source.parents)):
        raise ValueError('Choose the template at its real location without redirected folders.')
    if target.resolve().is_relative_to(source.resolve()):
        raise ValueError('The new project cannot be inside its template.')
    pending, entries = [source], 0
    try:
        while pending:
            with os.scandir(pending.pop()) as children:
                for entry in children:
                    entries += 1
                    if entries > 4096:
                        raise ValueError('Choose a template with at most 4096 entries.')
                    item = Path(entry.path)
                    if item.is_symlink() or item.is_junction():
                        raise ValueError('Templates cannot contain redirected folders.')
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    relative = item.relative_to(source)
                    if len(directories) >= 1024 or len(relative.parts) > 12:
                        raise ValueError('Choose a template with at most 1024 folders and 12 levels.')
                    directories.append(relative)
                    pending.append(item)
    except OSError as error:
        raise ValueError('The template could not be read. No project was created.') from error
    return directories


def create_project_folder(parent, name, governed_root='', template_directories=None):
    """Create one new work folder; registration stays with the workspace owner."""
    if (type(name) is not str or not name or len(name) > 100 or name != name.strip()
            or name.endswith('.') or name in ('.', '..')
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)
            or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
        raise ValueError('Use one ordinary project folder name without reserved characters.')
    base = Path(parent)
    if not base.is_absolute() or not base.is_dir():
        raise ValueError('Choose an available registered parent folder.')
    if any(part.is_symlink() or part.is_junction() for part in (base, *base.parents)):
        raise ValueError('The parent folder is redirected. Choose its real registered location.')
    template = project_folder_layout(base, governed_root)
    if template == 'Governed work folder' and base.resolve() == Path(governed_root).resolve():
        raise ValueError('Choose a work parent inside a numbered workspace area.')
    if template_directories is not None and template != 'Empty folder':
        raise ValueError('Local templates apply outside the governed ArchHub workspace.')
    target = base / name
    try:
        target.mkdir()  # Never merge with, truncate or replace an existing project.
    except FileExistsError:
        raise ValueError('That folder already exists. Add it as a workspace instead.') from None
    if template_directories is not None:
        try:
            for relative in template_directories:
                (target / relative).mkdir()
        except OSError as error:
            raise ValueError('Project creation was incomplete at %s. Existing files were preserved: %s' % (target, error)) from error
        return target
    if template == 'Empty folder':
        return target
    try:
        (target / '_WIP').mkdir()
        with (target / 'README.md').open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('# ' + name + '\n\nResults belong beside this README and REGISTER.md.\n'
                         'Keep received sources, drafts, scripts and superseded revisions in _WIP.\n')
        rows = ['# REGISTER: ' + name, '', 'Generated from the files on disk when this project was created.', '',
                '| File | SHA-256 |', '|---|---|']
        for item in sorted(target.rglob('*')):
            relative = item.relative_to(target).as_posix()
            rows.append('| `' + relative + ('/` | |' if item.is_dir() else
                '` | ' + hashlib.sha256(item.read_bytes()).hexdigest() + ' |'))
        with (target / 'REGISTER.md').open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(rows) + '\n')
    except OSError as error:
        raise ValueError('Project creation was incomplete at %s. Existing files were preserved: %s' % (target, error)) from error
    return target

def built_in_path() -> str:
    """The built-in governed tree: the same folder the application resolves as
    its workspace root (workspace_root.workspace_root_for_map over the selected
    map). A running application passes its own resolved root as built_in, so
    admission and the view always use that instance's tree; this is only the
    fallback for callers without one. Never a hardcoded machine path."""
    from .map_import import resolve_map_path
    from .workspace_root import workspace_root_for_map
    return str(PureWindowsPath(workspace_root_for_map(resolve_map_path())))

def folder_identity(path):
    """(volume serial, file index) exactly as the hooks read it."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume_serial", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.POINTER(Info))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(path), 0x80, 0x7, None, 3, 0x02000000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        return None
    try:
        info = Info()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            return None
        return (info.volume_serial, (info.index_high << 32) | info.index_low)
    finally:
        kernel.CloseHandle(handle)

def _local_folder_path(text) -> bool:
    if type(text) is not str or not text or len(text) > 1024 or "\x00" in text:
        return False
    path = PureWindowsPath(text)
    drive = path.drive
    return (len(drive) == 2 and drive[1] == ":" and path.is_absolute()
            and len(path.parts) > 1 and ":" not in path.name
            and not text.startswith(chr(92) * 2)
            and not any(part != part.rstrip(" .") for part in path.parts[1:]))

def root_id_from_name(name, path, roots):
    """A valid, unused root id derived from what the user typed (or the folder name).

    Founder 2026-10-12: typing "BBC4" for E:\\01.PERSONAL\\BBC4 must register, not refuse.
    """
    raw = name if type(name) is str and name.strip() else PureWindowsPath(str(path or "")).name
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower()).strip("-")[:63].strip("-")
    if not slug:
        slug = "workspace"
    if slug == "archhub":
        slug = "archhub-workspace"
    used = {root.get("root_id") for root in roots or []}
    candidate, n = slug, 2
    while candidate in used:
        suffix = "-%d" % n
        candidate = slug[:63 - len(suffix)].strip("-") + suffix
        n += 1
    return candidate

def canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")

def registry_dir():
    home = os.environ.get('USERPROFILE') or str(Path.home())
    return state_directory() / 'workspace-registry' if 'ARCHHUB_TEST_STATE_DIR' in os.environ else Path(home) / '.archhub'


def default_snapshot_path():
    return registry_dir() / 'workspace-roots.json'


def project_register(row):
    settings = row.get('settings', {})
    legacy_override = any(key.startswith('Projects.') for key in settings) if isinstance(settings, dict) else False
    register = {'number': row.get('project_number', ''), 'override': row.get('project_override', legacy_override)}
    for key, field in REGISTER_REFERENCES.items():
        if row.get(field):
            register[key] = row[field]
    if row.get('issued_destination'):
        register['issuedDestination'] = row['issued_destination']
    return register


# The project's own adopted registers: its naming register (grammar and code lists, e.g. a register workbook;
# never a folder inventory) and its issued-containers register. The row keeps only a relative reference, never
# contents; which standard a register follows is the project's, not ArchHub's.
REGISTER_REFERENCES = {'namingRegister': 'naming_register', 'issuedRegister': 'issued_register'}
REGISTER_FORMS = {'namingRegister': ('.xlsx', '.xlsm', '.csv'), 'issuedRegister': ('.md', '.xlsx', '.xlsm', '.csv')}


def issued_destination(root, value):
    if not isinstance(value, str) or len(value) > 240 or not value.strip() or not value.isprintable():
        raise ValueError('Choose an issued folder inside this project.')
    base = Path(root).resolve()
    folder = base / value.strip()
    if not folder.is_relative_to(base) or folder == base or '..' in folder.parts:
        raise ValueError('Choose an issued subfolder inside this project.')
    for part in (folder, *folder.parents):
        if part == base:
            break
        if part.is_symlink() or part.is_junction():
            raise ValueError('Choose an issued folder without links or junctions.')
    if not folder.is_dir() or not folder.resolve().is_relative_to(base):
        raise ValueError('Choose an existing issued folder inside this project.')
    return str(folder.relative_to(base))


def register_reference(root, value, key='issuedRegister'):
    """A project-relative path (a picked absolute path inside the folder becomes relative) in a register form
    that stays inside the folder, or ValueError."""
    if not isinstance(value, str) or len(value) > 240 or any(not c.isprintable() for c in value):
        raise ValueError('Use a register path of up to 240 printable characters.')
    relative = PureWindowsPath(value.strip().replace('/', '\\'))
    if relative.drive or relative.root:  # a file picker answers with an absolute path
        try:
            relative = PureWindowsPath(Path(str(relative)).resolve().relative_to(Path(root).resolve()))
        except (OSError, ValueError):
            raise ValueError('Choose a register file inside this project folder.') from None
    forms = REGISTER_FORMS[key]
    if (relative.drive or relative.root or not relative.parts or any(part in ('.', '..') for part in relative.parts)
            or relative.suffix.lower() not in forms):
        raise ValueError('Choose the register file inside this project folder (%s).' % ' or '.join(forms))
    base = Path(root).resolve()
    target = base / Path(*relative.parts)
    probe = target
    while probe != base:  # no link or junction anywhere between the project folder and the register
        if probe.is_symlink() or probe.is_junction():
            raise ValueError('The register path passes through a link; choose a file inside this project folder.')
        probe = probe.parent
    if not target.resolve().is_relative_to(base):
        raise ValueError('The register path leaves this project folder.')
    return str(relative)


def register_paths(row):
    """Owner read contract: each set register as an absolute path inside the row's folder, re-checked now.

    Pass the row of the document's own registered project (its properties.project), not the active one.
    """
    return {key: Path(row['path']) / register_reference(row['path'], row[field], key)
            for key, field in REGISTER_REFERENCES.items() if row.get(field)}


def register_files(row):
    """For Settings: each set register 'usable' (a file there now), 'missing' or 'refused' (no longer valid)."""
    states = {}
    for key, field in REGISTER_REFERENCES.items():
        if row.get(field):
            try:
                path = Path(row['path']) / register_reference(row['path'], row[field], key)
            except ValueError:
                states[key] = 'refused'
            else:
                states[key] = 'usable' if path.is_file() else 'missing'
    return states


def applied_workspace_settings(row):
    settings = row.get('settings', {})
    if row.get('project_override') is False:
        return {key: value for key, value in settings.items() if not key.startswith('Projects.')}
    return settings


def read_registered_roots(verifier=None, *, snapshot_path=None, pin_path=None,
                          last_good_path=None, registry_state=None):
    from .nograph_server import JsonFile
    rows = JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []}).read()['roots']
    return {row['root_id']: {'privacy': 'private', **row} for row in rows}, None


def root_bound_registration(path, *, runtime=None, **kwargs):
    parts = str(path).split('/')
    if (len(parts) < 3 or parts[0] != 'workspace-roots' or not _ID.fullmatch(parts[1])
            or any(part in ('', '.', '..') for part in parts[2:])):
        raise ValueError('workspace-root write path is invalid')
    roots, _pin = read_registered_roots()
    entry = roots.get(parts[1])
    if entry is None:
        raise ValueError('This workspace is not registered in Settings.')
    base = Path(entry['path'])
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        raise ValueError('Registered workspace is unavailable or redirected.')
    if entry.get('identity') and list(folder_identity(base) or ()) != entry['identity']:
        raise ValueError('Registered workspace folder identity changed.')
    if runtime and 'writers' in entry and runtime not in entry['writers']:
        raise ValueError('This agent is not enabled for the registered workspace.')
    return 'workspace-root:' + parts[1], hashlib.sha256(canonical(entry)).hexdigest(), entry


def root_bound_admission(path, **kwargs):
    container, digest, _entry = root_bound_registration(path, **kwargs)
    return container, digest
