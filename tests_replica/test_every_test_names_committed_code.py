"""Court: every test names code that is committed (founder, 2026-09-29).

"Not committed = does not exist." On a clean archive of HEAD, router and chat
tests called code no commit holds -- removed by a later commit, or living only
in someone's worktree -- and each agent's own run passed because its worktree
held the missing pieces.

Every test module (tests_replica, cloud_backend/tests, tests, tests_domains) is
read as source, never run, and checked against the code in THIS tree:
  * every module it imports from nodelang / tests_replica / the cloud backend
    exists as a file;
  * every name it takes from such a module (``from m import n``, ``m.n``,
    ``Class.n``, ``monkeypatch.setattr(m, "n", ...)``) is defined there.
Names are found in the module's own source first (top-level definitions,
assignments, imports, ``__all__``, class bodies). Only a name the source does
not show is looked up by importing, and a module that cannot be read or
imported is itself a finding -- never a pass. Names a test guards with
hasattr/getattr, and names rebound in the enclosing function, are not required.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SUITE_DIRS = ("tests_replica", "cloud_backend/tests", "tests", "tests_domains")
_ROOTS = ("nodelang", "tests_replica")


class _Tree:
    """One source tree: where modules live and what they define."""

    def __init__(self, root):
        self.root = Path(root)
        self.cloud = self.root / "cloud_backend"
        self._defined = {}

    def is_cloud_module(self, name):
        head = name.split(".")[0]
        return (self.cloud / (head + ".py")).is_file() or (self.cloud / head).is_dir()

    def module_path(self, name):
        for base in (self.root.joinpath(*name.split(".")), self.cloud.joinpath(*name.split("."))):
            if base.with_suffix(".py").is_file():
                return base.with_suffix(".py")
            if (base / "__init__.py").is_file():
                return base / "__init__.py"
            if base.is_dir() and any(base.glob("*.py")):
                return base          # a namespace package
        return None

    def defined(self, name):
        """Names the module's source binds at top level, or None when it cannot say."""
        if name not in self._defined:
            path = self.module_path(name)
            self._defined[name] = _bound_names(path) if path and path.is_file() else None
        return self._defined[name]

    def class_defined(self, module, cls):
        path = self.module_path(module)
        if not path or not path.is_file():
            return None
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError):
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                if node.bases and not all(isinstance(b, ast.Name) and b.id == "object" for b in node.bases):
                    return None      # inherited names: ask the class itself
                return _bound_names_in(node.body)
        return None

    def imported(self, module):
        """The module as imported from this tree, or None; sys.path is restored."""
        saved = list(sys.path)
        try:
            sys.path[:0] = [str(self.root), str(self.cloud)]
            return importlib.import_module(module)
        except Exception:  # noqa: BLE001 -- an unimportable module is reported, not trusted
            return None
        finally:
            sys.path[:] = saved


def _bound_names_in(body):
    names, star = set(), False
    stack = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    star = True
                else:
                    names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                names |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for field in ("body", "orelse", "finalbody", "handlers"):
                for child in getattr(node, field, ()) or ():
                    stack.extend(child.body if isinstance(child, ast.ExceptHandler) else [child])
    if star or "__getattr__" in names:
        return None                  # the source cannot say what it exports
    return names


def _bound_names(path):
    try:
        return _bound_names_in(ast.parse(path.read_text(encoding="utf-8-sig")).body)
    except (OSError, SyntaxError):
        return None


class _Refs(ast.NodeVisitor):
    def __init__(self, tree, test_is_cloud):
        self.tree = tree
        self.cloud = test_is_cloud
        self.aliases = {}
        self.classes = {}
        self.needs = []
        self.rebound = [set()]
        self.guarded = set()

    def _tracked(self, module):
        return module.split(".")[0] in _ROOTS or (self.cloud and self.tree.is_cloud_module(module))

    def visit_FunctionDef(self, node):
        names = {a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg)}
        names |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                  and isinstance(n.ctx, (ast.Store, ast.Del))}
        self.rebound.append(names)
        self.generic_visit(node)
        self.rebound.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node):
        for alias in node.names:
            if self._tracked(alias.name):
                self.needs.append((node.lineno, alias.name, None, None))
                self.aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0])

    def visit_ImportFrom(self, node):
        module = node.module or ""
        if node.level or not self._tracked(module):
            return
        self.needs.append((node.lineno, module, None, None))
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            if self.tree.module_path(module + "." + alias.name):
                self.needs.append((node.lineno, module + "." + alias.name, None, None))
                self.aliases[local] = module + "." + alias.name
            else:
                self.needs.append((node.lineno, module, alias.name, None))
                if alias.name[:1].isupper():
                    self.classes[local] = (module, alias.name)

    def visit_Attribute(self, node):
        if (isinstance(node.value, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.value.id not in self.rebound[-1]):
            base = node.value.id
            if base in self.aliases:
                self.needs.append((node.lineno, self.aliases[base], node.attr, None))
            elif base in self.classes:
                module, cls = self.classes[base]
                self.needs.append((node.lineno, module, node.attr, cls))
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if (isinstance(func, ast.Name) and func.id in ("hasattr", "getattr") and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name) and node.args[0].id in self.aliases
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            self.guarded.add((self.aliases[node.args[0].id], node.args[1].value))
        if (isinstance(func, ast.Attribute) and func.attr == "setattr"
                and isinstance(func.value, ast.Name) and func.value.id == "monkeypatch"
                and len(node.args) == 3 and not node.keywords and isinstance(node.args[0], ast.Name)
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            target = node.args[0].id
            if target in self.aliases:
                self.needs.append((node.lineno, self.aliases[target], node.args[1].value, None))
            elif target in self.classes:
                module, cls = self.classes[target]
                self.needs.append((node.lineno, module, node.args[1].value, cls))
        self.generic_visit(node)


def _has(tree, module, name, cls):
    """True / False, or None when neither the source nor an import can tell."""
    names = tree.class_defined(module, cls) if cls else tree.defined(module)
    if names is not None and name in names:
        return True
    loaded = tree.imported(module)
    if loaded is None:
        return None if names is None else False
    holder = getattr(loaded, cls, None) if cls else loaded
    if holder is None:
        return None
    return hasattr(holder, name)


def missing_references(root=ROOT, suites=None):
    """(test file, line, what is missing) for every reference to absent code."""
    tree = _Tree(root)
    suite_dirs = [tree.root / s for s in _SUITE_DIRS] if suites is None else [Path(s) for s in suites]
    found = []
    for suite in suite_dirs:
        for test in sorted(suite.glob("*.py")) if suite.is_dir() else ():
            rel = test.relative_to(tree.root).as_posix()
            try:
                source = ast.parse(test.read_text(encoding="utf-8-sig"))
            except SyntaxError as broken:
                found.append((rel, broken.lineno or 0, "does not parse"))
                continue
            refs = _Refs(tree, test_is_cloud=suite == tree.cloud / "tests")
            refs.visit(source)
            for lineno, module, name, cls in refs.needs:
                if not tree.module_path(module):
                    found.append((rel, lineno, "module %s is not in this tree" % module))
                    continue
                if name is None or (cls is None and (module, name) in refs.guarded):
                    continue
                present = _has(tree, module, name, cls)
                label = "%s%s.%s" % (module, ("." + cls) if cls else "", name)
                if present is None:
                    found.append((rel, lineno, "cannot verify %s: its module neither shows nor imports it" % label))
                elif not present:
                    found.append((rel, lineno, "%s does not exist" % label))
    return sorted(set(found))

# Found on a clean archive of HEAD (2026-09-29), each waiting on its owner:
# commit 326b6579 removed these names and this module but left the tests that
# call them; test_workshop_project_revision.py exists only untracked in one
# worktree. A fixed entry must be deleted here; nothing may be added.
KNOWN = frozenset({
    ("tests_replica/test_legacy_core_node_bridge.py",
     "module nodelang.cell_baboom_connector_execution is not in this tree"),
    ("tests_replica/test_legacy_self_extension_bridge.py",
     "module nodelang.cell_baboom_connector_execution is not in this tree"),
    ("tests_replica/test_native_contact.py",
     "module tests_replica.test_workshop_project_revision is not in this tree"),
    ("tests_replica/test_the_chat_answers_after_a_restart.py",
     "nodelang.model_router.first_reachable_route does not exist"),
    ("tests_replica/test_the_chat_answers_after_a_restart.py",
     "nodelang.agent_composer.first_reachable_route does not exist"),
    ("tests_replica/test_the_workshop_is_where_the_agents_meet.py",
     "nodelang.universal_application._agent_session_runtime_label does not exist"),
    ("tests_replica/test_the_workshop_is_where_the_agents_meet.py",
     "nodelang.universal_application._work_title_for_workshop does not exist"),
    ("tests_replica/test_the_workshop_is_where_the_agents_meet.py",
     "nodelang.cell_deliberation._IDEMPOTENCY_TAIL_ENTRIES does not exist"),
})


def test_no_test_names_code_that_is_not_committed():
    missing = missing_references()
    new = [row for row in missing if (row[0], row[2]) not in KNOWN]
    assert new == [], "a test names code no commit holds:\n" + "\n".join(
        "%s:%d: %s" % row for row in new)


def test_the_known_list_only_shrinks():
    still = {(row[0], row[2]) for row in missing_references()}
    fixed = sorted(KNOWN - still)
    assert fixed == [], "fixed -- delete from KNOWN: %s" % fixed


def test_the_court_sees_a_test_that_names_missing_code(tmp_path):
    """A tree of its own: a module that raises on import is still read from its
    source, so an absent name in it is reported, not skipped; a module whose
    source cannot say (star import) and does not import is reported too."""
    pkg = tmp_path / "nodelang"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "raises.py").write_text(
        "raise RuntimeError('needs a service')\ndef present():\n    return 1\n", encoding="utf-8")
    (pkg / "opaque.py").write_text("from somewhere_missing import *\n", encoding="utf-8")
    suite = tmp_path / "tests_replica"
    suite.mkdir()
    (suite / "test_ghost.py").write_text(
        "from nodelang import raises, opaque\n"
        "import tests_replica.helper_nobody_committed\n"
        "def test_x():\n"
        "    raises.a_function_nobody_committed()\n"
        "    raises.present()\n"
        "    opaque.anything()\n", encoding="utf-8")
    rows = [(line, what) for _f, line, what in missing_references(root=tmp_path, suites=(suite,))]
    assert (2, "module tests_replica.helper_nobody_committed is not in this tree") in rows
    assert (4, "nodelang.raises.a_function_nobody_committed does not exist") in rows
    assert not any(line == 5 for line, _w in rows), "a defined name was reported"
    assert (6, "cannot verify nodelang.opaque.anything: its module neither shows nor imports it") in rows


def test_the_scan_leaves_the_import_path_as_it_found_it():
    before = list(sys.path)
    missing_references()
    assert sys.path == before
