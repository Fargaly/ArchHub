"""Regenerate agent skill copies from one plugin source; never patch its cache."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pipeline.strict_check import node_timeout

OWNERSHIP_MARKER = '.archhub-skill-owner'


class SkillSyncRefused(ValueError):
    """A skill source or derived installation cannot be verified."""


def _plain(path, *, stop=None):
    for part in (path, *path.parents):
        if part == stop:
            break
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise SkillSyncRefused('redirected skill path: ' + str(part))


def _tree(root, *, boundary=None):
    _plain(root, stop=boundary)
    if not root.exists():
        return {}
    result = {}
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise SkillSyncRefused('redirected skill path: ' + str(path))
                if stat.S_ISREG(info.st_mode):
                    result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
                elif stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                else:
                    raise SkillSyncRefused('nonregular skill path: ' + str(path))
    return result


def _json(path, *, boundary=None):
    _plain(path, stop=boundary)
    return json.loads(path.read_bytes())


def _owned(target, owner):
    marker = target / OWNERSHIP_MARKER
    _plain(marker, stop=target.parent)
    try:
        return marker.read_text(encoding='utf-8') == owner
    except FileNotFoundError:
        return False


def _contents(target):
    tree = _tree(target, boundary=target.parent)
    tree.pop(OWNERSHIP_MARKER, None)
    return tree


def _skill_name(path):
    _plain(path, stop=path.parent.parent)
    if not path.is_file():
        return None
    text = path.read_text(encoding='utf-8-sig')
    front = re.match(r'\A---\s*\n(.*?)\n---(?:\s|$)', text, re.S)
    match = re.search(r'^name:\s*([a-z0-9-]+|"[a-z0-9-]+"|\'[a-z0-9-]+\')\s*$',
                      front[1], re.M) if front else None
    return match[1].strip('\'"') if match else None


def _adoptable(source, skill, target):
    if (target / OWNERSHIP_MARKER).exists() or not (source / 'skills' / skill).is_dir():
        return False
    expected = _skill_name(source / 'skills' / skill / 'SKILL.md')
    if expected is not None and _skill_name(target / 'SKILL.md') == expected:
        return True
    path = target / 'SKILL.md'
    _plain(path, stop=target.parent)
    if not path.is_file():
        return False
    # Legacy copies can predate the current frontmatter identity.
    history = subprocess.run(['git', '-C', str(source), 'log', '--all', '--format=', '--raw',
                              '--no-abbrev', '--', 'skills/' + skill + '/SKILL.md'],
                             capture_output=True, text=True, timeout=node_timeout())
    if history.returncode:
        return False
    content = path.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    return any(blob in line.split()[2:4] for line in history.stdout.splitlines() if line.startswith(':'))


def _inputs(source, home):
    source, home = Path(source).absolute(), Path(home).absolute()
    if '..' in source.parts or '..' in home.parts:
        raise SkillSyncRefused('skill source and home require normalized paths')
    _plain(source)
    _plain(home)
    manifest = _json(source / '.claude-plugin/plugin.json', boundary=source)
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-skills\.[0-9a-f]{64})?', manifest['version']):
        raise SkillSyncRefused('source plugin requires a numeric semantic version')
    market = _json(source.parent / '.claude-plugin/marketplace.json', boundary=source.parent)
    name, marketplace = manifest['name'], market['name']
    if not all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value) for value in (name, marketplace)):
        raise SkillSyncRefused('invalid plugin or marketplace name')
    entries = [entry for entry in market['plugins'] if entry.get('name') == name]
    if len(entries) != 1 or entries[0].get('source') != './' + source.name:
        raise SkillSyncRefused('skill source must be the named local marketplace plugin')
    tree = _tree(source / 'skills', boundary=source)
    names = {key.split('/')[0] for key in tree}
    if not names or any(name + '/SKILL.md' not in tree for name in names):
        raise SkillSyncRefused('source requires nonempty complete skill directories')
    if any(name + '/' + OWNERSHIP_MARKER in tree for name in names):
        raise SkillSyncRefused('source contains reserved installer ownership marker')
    digest = hashlib.sha256(json.dumps(tree, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    registry = home / '.claude/plugins/installed_plugins.json'
    records = _json(registry, boundary=home)['plugins'].get(name + '@' + marketplace, []) if registry.exists() else []
    known = home / '.claude/plugins/known_marketplaces.json'
    registration = _json(known, boundary=home).get(marketplace) if known.exists() else None
    if records and registration is None:
        raise SkillSyncRefused('registered marketplace is missing')
    if registration is not None:
        if (registration.get('source', {}).get('source') != 'directory'
                or Path(registration['source']['path']).resolve() != source.parent.resolve()
                or Path(registration['installLocation']).resolve() != source.parent.resolve()):
            raise SkillSyncRefused('registered marketplace differs from the local skill source')
    cache = home / '.claude/plugins/cache' / marketplace / name
    for record in records:
        path = Path(record['installPath']).absolute()
        _plain(path, stop=home)
        if '..' in path.parts or not path.is_relative_to(cache) or path == cache:
            raise SkillSyncRefused('plugin installation is outside its native cache')
    owned = set(names)
    # Removed skills are found by their markers, never by inactive native caches.
    targets = []
    for relative in ('.agents/skills', '.codex/skills', '.config/opencode/skills',
                     '.claude/skills', '.opencode/skills'):
        root = home / relative
        _plain(root, stop=home)
        if root.exists():
            owned.update(path.name for path in root.iterdir()
                         if path.name not in names and path.is_dir() and _owned(path, name + '@' + marketplace))
        for skill in sorted(owned):
            target = root / skill
            _plain(target, stop=root)
            if target.is_relative_to(source) or source.is_relative_to(target):
                raise SkillSyncRefused('skill source and output overlap: ' + str(target))
            if relative in ('.agents/skills', '.codex/skills', '.config/opencode/skills') or target.exists():
                targets.append((skill, target))
    return source, home, manifest, marketplace, tree, digest, names, records, targets


def _differences(expected, actual, path):
    return [str(path / name) for name in sorted(set(expected) | set(actual))
            if expected.get(name) != actual.get(name)]


def check(source, home, *, claude_executable=None, _deferred=()):
    source, home, manifest, market, tree, digest, names, records, targets = _inputs(source, home)
    problems = []
    skipped = []
    native_skipped = not (claude_executable or shutil.which('claude.exe' if os.name == 'nt' else 'claude'))
    if native_skipped:
        print('SKILLSYNC WARNING: Claude CLI missing; plugin-cache refresh skipped')
    if not native_skipped and not manifest['version'].endswith('-skills.' + digest):
        problems.append('source plugin version is not bound to current skill hashes')
    if not native_skipped and (not records or not any(record['scope'] == 'user' for record in records)):
        problems.append('native user plugin installation is missing')
    for record in records:
        if native_skipped:
            continue
        path = Path(record['installPath'])
        if record['version'] != manifest['version']:
            problems.append('native plugin version differs: ' + str(path))
        problems.extend(_differences(tree, _tree(path / 'skills', boundary=path), path / 'skills'))
    for skill, target in targets:
        if str(target) in _deferred:
            continue
        if target.exists() and not _owned(target, manifest['name'] + '@' + market):
            if _adoptable(source, skill, target):
                problems.append('legacy skill requires adoption: ' + str(target))
                continue
            skipped.append(str(target))
            print('SKILLSYNC WARNING: foreign folder left untouched: ' + str(target))
            continue
        expected = {key[len(skill) + 1:]: value for key, value in tree.items() if key.startswith(skill + '/')}
        problems.extend(_differences(expected, _contents(target), target))
    if problems:
        raise SkillSyncRefused('stale agent skills; run governance regeneration:\n' + '\n'.join(problems))
    return {'sha256': digest, 'skills': len(names), 'targets': len(targets) - len(skipped) - len(_deferred),
            'version': manifest['version'], 'skipped': skipped, 'native_skipped': native_skipped,
            'deferred': list(_deferred)}


def _in_use(error):
    return os.name == 'nt' and (isinstance(error, PermissionError)
                              or getattr(error, 'winerror', None) in (5, 32, 33))


def _replace_skill(source, target, archive, expected, owner):
    """Archive before replacement; Windows watchers may forbid directory rename."""
    in_place = False
    if target.exists():
        try:
            target.rename(archive)
        except OSError as error:
            if not _in_use(error):
                raise
            before = _tree(target)
            archive.mkdir()
            for name in before:
                output = archive / name
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target / name, output)
            if _tree(archive) != before:
                raise SkillSyncRefused('skill archive differs: ' + str(archive))
            # Probe without truncating anything before the first in-place write.
            for name in before:
                with (target / name).open('r+b'):
                    pass
            if not expected:
                raise error
            for name in before.keys() - expected.keys() - {OWNERSHIP_MARKER}:
                (target / name).unlink()
            in_place = True
    if expected:
        if in_place:
            for name in expected:
                output = target / name
                if output.is_dir():
                    for directory in sorted(output.rglob('*'), reverse=True):
                        directory.rmdir()
                    output.rmdir()
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, output)
        else:
            shutil.copytree(source, target)
        (target / OWNERSHIP_MARKER).write_text(owner, encoding='utf-8')


def synchronize(source, home, *, claude_executable=None, runner=subprocess.run):
    source, home, manifest, market, tree, digest, _names, records, targets = _inputs(source, home)
    plugin_stale = (not records or not manifest['version'].endswith('-skills.' + digest)
                    or any(record['version'] != manifest['version']
                           or _tree(Path(record['installPath']) / 'skills', boundary=Path(record['installPath'])) != tree
                           for record in records))
    executable = claude_executable or shutil.which('claude.exe' if os.name == 'nt' else 'claude')
    if plugin_stale and executable:
        scopes = {record['scope'] for record in records} or {'user'}
        if scopes != {'user'}:
            raise SkillSyncRefused('non-user plugin scopes require their native project update')
        version = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-skills\.[0-9a-f]{64})?', manifest['version'])
        if not version:
            raise SkillSyncRefused('source plugin requires a numeric semantic version')
        manifest['version'] = '%s.%s.%d-skills.%s' % (*version.group(1, 2), int(version[3]) + 1, digest)
        metadata = source / '.claude-plugin/plugin.json'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=metadata.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, metadata)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        environment = dict(os.environ, USERPROFILE=str(home), HOME=str(home),
                           CLAUDE_CONFIG_DIR=str(home / '.claude'), DISABLE_AUTOUPDATER='1',
                           CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
        if not records:
            runner([str(executable), 'plugin', 'marketplace', 'add', str(source.parent)],
                   env=environment, cwd=source.parent, check=True, capture_output=True, text=True, timeout=node_timeout())
        runner([str(executable), 'plugin', 'update' if records else 'install',
                manifest['name'] + '@' + market, '--scope', 'user'],
               env=environment, cwd=source.parent, check=True, capture_output=True, text=True, timeout=node_timeout())
        # Native success is not proof. Refuse before touching other runtimes if
        # its selected bytes or source changed during the CLI operation.
        after = _inputs(source, home)
        if after[4] != tree or not after[7] or any(
                record['version'] != manifest['version']
                or _tree(Path(record['installPath']) / 'skills', boundary=Path(record['installPath'])) != tree
                for record in after[7]):
            raise SkillSyncRefused('native plugin update did not publish the current skill bytes')
    deferred = []
    for skill, target in targets:
        try:
            adopt = False
            if target.exists() and not _owned(target, manifest['name'] + '@' + market):
                adopt = _adoptable(source, skill, target)
                if not adopt:
                    continue
            expected = {key[len(skill) + 1:]: value for key, value in tree.items() if key.startswith(skill + '/')}
            if not adopt and _contents(target) == expected:
                continue
            _plain(target)
            archive = home / '.archhub/skill-archive' / target.parent.parent.name.lstrip('.')
            _plain(archive)
            archive.mkdir(parents=True, exist_ok=True)
            archive /= skill + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            _replace_skill(source / 'skills' / skill, target, archive, expected, manifest['name'] + '@' + market)
        except OSError as error:
            if not _in_use(error):
                raise
            deferred.append(str(target))
            print('SKILLSYNC WARNING: skill in use; retry next commit: ' + str(target) + ': ' + str(error))
    return check(source, home, claude_executable=executable, _deferred=deferred)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--home', default=str(Path.home()))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = check(args.source, args.home) if args.check else synchronize(args.source, args.home)
        print(('SKILLSYNC DEFERRED ' if result['deferred'] else 'SKILLSYNC PASS ') + json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('SKILLSYNC REFUSED: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
