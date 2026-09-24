"""Passive setup evidence: fixtures never inspect or launch the user's hosts."""
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import colleague_setup as setup


class HostInstallationReadinessTests(unittest.TestCase):
    def rows(self, installations=None, files=(), compiler=False, dependency=True):
        expected = {str(Path(path)) for path in files}
        with patch.object(setup, "_setup_host_installations", return_value=installations or {}), \
             patch.object(setup, "_setup_compiler_candidates", return_value=compiler), \
             patch.object(setup, "_has", return_value=dependency), \
             patch.object(Path, "is_file", lambda path: str(path) in expected), \
             patch.object(setup.subprocess, "run", side_effect=AssertionError("no subprocess")), \
             patch.dict(setup.os.environ, {"APPDATA": "X:/roaming", "LOCALAPPDATA": "X:/local"}, clear=True):
            return setup.host_installation_readiness(Path("X:/archhub"))

    def test_declared_mcp_and_windows_com_dependencies_are_import_checked(self):
        probes = {probe for _, probe in setup.PACKAGES}
        self.assertIn("mcp", probes)
        if setup.sys.platform == "win32":
            self.assertTrue({"pythoncom", "win32com.client"} <= probes)

    def test_detected_host_does_not_imply_connector_packaged_or_ready(self):
        rows = self.rows({"revit": ["2026"], "autocad": ["2025"], "max": ["2026"]})
        for row in rows:
            self.assertNotIn("ready", row.values())
            if row["host"] in {"Revit", "AutoCAD", "3ds Max"}:
                self.assertEqual("executable-found", row["host_installation"])
                self.assertEqual("not-packaged", row["packaged"])
        self.assertEqual("compiler-not-found", next(row for row in rows if row["host"] == "Revit")["compiler"])

    def test_payload_files_and_compiler_candidate_do_not_prove_load_or_compatibility(self):
        rows = self.rows({"revit": ["2026"]}, files=(
            "X:/archhub/bridges/revit/2026/RevitMCP.dll",
            "X:/archhub/bridges/revit/2026/RevitMCPCore.dll"), compiler=True)
        revit = next(row for row in rows if row["host"] == "Revit")
        self.assertEqual("payload-files-present-unverified", revit["packaged"])
        self.assertEqual("candidate-unverified", revit["compiler"])
        self.assertEqual("unchecked", revit["deployment"])

    def test_existing_foreign_registration_is_not_adopted_or_reported_loaded(self):
        rows = self.rows({"revit": ["2025"]}, files=("X:/roaming/Autodesk/Revit/Addins/2025/RevitMCP.addin",))
        revit = next(row for row in rows if row["host"] == "Revit")
        self.assertEqual("registration-present-unverified", revit["deployment"])
        self.assertEqual("not-packaged", revit["packaged"])
        self.assertIn("ownership", revit["detail"])

    def test_script_packaging_and_unsupported_versions_are_separate(self):
        rows = self.rows({"rhino": ["7", "8"], "blender": ["3.5", "3.10"]}, files=(
            "X:/archhub/bridges/rhino/archhub_mcp.py",
            "X:/archhub/bridges/blender/archhub_mcp/__init__.py"))
        by_version = {(row["host"], row["version"]): row for row in rows}
        for host, version in (("Rhino", "7"), ("Blender", "3.5")):
            self.assertEqual("script-packaged", by_version[host, version]["packaged"])
            self.assertEqual("unsupported-version", by_version[host, version]["deployment"])
        for host, version in (("Rhino", "8"), ("Blender", "3.10")):
            self.assertEqual("activation-unchecked", by_version[host, version]["deployment"])

    def test_max_startup_file_is_not_proof_of_matching_source_or_loaded_host(self):
        rows = self.rows({"max": ["2026"]}, files=(
            "X:/local/Autodesk/3dsMax/2026 - 64bit/ENU/scripts/startup/max_mcp_startup.py",))
        row = next(row for row in rows if row["host"] == "3ds Max")
        self.assertEqual("startup-script-present-unverified", row["deployment"])
        self.assertIn("restart may be needed", row["detail"])

    def test_unshipped_max_source_is_never_reported_as_packaged(self):
        rows = self.rows({"max": ["2026"]}, files=(
            "X:/archhub/bridges/sources/max_mcp/max_mcp_startup.py",))
        row = next(row for row in rows if row["host"] == "3ds Max")
        self.assertEqual("not-packaged", row["packaged"])
        self.assertIn("does not package", row["detail"])

    def test_the_max_script_the_installer_ships_is_reported_as_packaged(self):
        # installer/ArchHub.iss places bridges/sources/max_mcp/max_mcp_startup.py at {app}/bridges/max.
        rows = self.rows({"max": ["2026"]}, files=("X:/archhub/bridges/max/max_mcp_startup.py",))
        row = next(row for row in rows if row["host"] == "3ds Max")
        self.assertEqual("script-packaged", row["packaged"])
        self.assertEqual("activation-unchecked", row["deployment"])
        self.assertNotIn("does not package", row["detail"])

    def test_every_packaged_script_probe_is_in_the_release_allowlist(self):
        import ast
        source = Path(setup.__file__).resolve()
        release = (source.parent / "installer" / "build_release.ps1").read_text(encoding="utf-8")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "host_installation_readiness")
        probes = {node.value for node in ast.walk(function)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and node.value.startswith("bridges/")}
        self.assertTrue(probes)
        # A probe names where the installer puts a script under {app}; the release
        # allowlist names the source file the installer copies there.
        installer = (source.parent / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
        placed = {}
        for match in re.finditer(r'^Source: "\.\.\\([^"]+)"; DestDir: "\{app\}\\([^"]+)"', installer, re.M):
            shipped = match.group(1).replace("\\", "/")
            placed[match.group(2).replace("\\", "/") + "/" + shipped.rsplit("/", 1)[-1]] = shipped
        for probe in sorted(probes):
            self.assertIn(probe, placed)
            self.assertIn("'%s'" % placed[probe], release)

    def test_missing_com_dependency_and_unchecked_assistant_registration_are_visible(self):
        rows = self.rows({"excel": ["version-unchecked"]}, dependency=False)
        excel = next(row for row in rows if row["host"] == "Excel")
        self.assertEqual("pywin32-missing", excel["packaged"])
        self.assertEqual("dependency-missing", rows[0]["packaged"])
        self.assertEqual("assistant-registration-unchecked", rows[0]["deployment"])

    def test_custom_registered_executable_evidence_is_passive_and_versioned(self):
        custom = Path("X:/custom/Revit 2027/Revit.exe")
        with patch.object(setup, "_setup_app_paths", side_effect=lambda exe: [custom] if exe == "Revit.exe" else []), \
             patch.object(Path, "is_file", lambda path: path == custom), \
             patch.object(setup.subprocess, "run", side_effect=AssertionError("no host process")), \
             patch.dict(setup.os.environ, {}, clear=True):
            self.assertEqual(["2027"], setup._setup_host_installations()["revit"])

    def test_host_evidence_runs_unguarded_before_the_ready_marker(self):
        import ast
        tree = ast.parse(Path(setup.__file__).read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

        def calls(node, name):
            return [call for call in ast.walk(node) if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name) and call.func.id == name]

        main = functions["main"]
        self.assertEqual(1, len(calls(main, "print_host_installation_readiness")))
        evidence = [index for index, statement in enumerate(main.body)
                    if isinstance(statement, ast.Expr) and calls(statement, "print_host_installation_readiness")]
        marker = [index for index, statement in enumerate(main.body)
                  if isinstance(statement, ast.Try) and calls(statement, "_write_ready")]
        self.assertEqual(1, len(evidence))
        self.assertEqual(1, len(marker))
        self.assertLess(evidence[0], marker[0])
        self.assertEqual(["root"], [ast.unparse(arg) for arg in main.body[evidence[0]].value.args])
        self.assertEqual(["root", "identity"],
                         [ast.unparse(arg) for arg in calls(main.body[marker[0]], "_write_ready")[0].args])
        guard = next(node for node in ast.walk(functions["print_host_installation_readiness"])
                     if isinstance(node, ast.Try) and calls(node, "host_installation_readiness"))
        self.assertEqual(["Exception"], [ast.unparse(handler.type) for handler in guard.handlers])
        self.assertFalse(any(isinstance(inner, (ast.Raise, ast.Return))
                             for handler in guard.handlers for inner in ast.walk(handler)))

    def test_host_evidence_defect_still_reaches_the_ready_marker(self):
        import io
        from contextlib import redirect_stdout
        events = []
        identity = "fixture-build:" + "0" * 64

        def defect(root):
            events.append("evidence")
            raise TypeError("fixture-private-detail")

        with patch.object(setup, "host_installation_readiness", side_effect=defect), \
             patch.object(setup, "readiness_identity", return_value=identity), \
             patch.object(setup, "prepare_environment", return_value=None), \
             patch.object(setup, "ready_for_build", return_value=True), \
             patch.object(setup, "_has", return_value=True), \
             patch.object(Path, "is_file", lambda path: path.name == "launch_archhub_test.py"), \
             patch.object(setup, "_write_ready", side_effect=lambda root, value: events.append(("ready", value))), \
             patch.object(setup, "_assistant_integration", side_effect=lambda root, value: events.append("assistant")), \
             patch.object(setup.subprocess, "run", side_effect=AssertionError("no subprocess")), \
             redirect_stdout(io.StringIO()) as output:
            status = setup.main()
        self.assertEqual(0, status)
        self.assertEqual(["evidence", ("ready", identity), "assistant"], events)
        self.assertIn("Host installation evidence is unavailable", output.getvalue())
        self.assertNotIn("fixture-private-detail", output.getvalue())
