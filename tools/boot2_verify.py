"""Sequential targeted BOOT2 courts, invoked only through run-heavy."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
OWNED = ["nodelang/application_server.py", "nodelang/clean_coordination_host.py",
         "nodelang/unified_authority.py", "nodelang/unified_authority_runtime.py",
         "nodelang/studio/studio.html", "nodelang/studio/studio-authority.js",
         "nodelang/studio/studio-lm.jsx"]


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in OWNED}


def run(label, arguments, environment):
    output = EVIDENCE / ("BOOT2-" + label + ".txt")
    print("RUN " + label, flush=True)
    with output.open("w", encoding="utf-8") as stream:
        result = subprocess.run(arguments, cwd=ROOT, env=environment, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    print("EXIT %s %d" % (label, result.returncode), flush=True)
    print("\n".join(output.read_text(encoding="utf-8", errors="replace").splitlines()[-4:]), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-workspace", action="store_true",
                        help="reuse recorded unchanged-source Home/catalogue courts; rerun workspace file, then remaining courts")
    parser.add_argument("--resume-studio", action="store_true",
                        help="rerun full cold-view file, or current-main lazy-boot file, against existing build; then timings/ratchet")
    parser.add_argument("--resume-results", action="store_true",
                        help="reuse unchanged-source courts; run only paired timing/ratchet and bind hashes")
    parser.add_argument("--current-main", action="store_true",
                        help="verify Home/assets/idle/Studio composition after a source rebase; unchanged core courts remain recorded")
    parser.add_argument("--resume-ui", action="store_true",
                        help="rebuild and verify Studio after a UI-only correction; reuse unchanged backend courts")
    args = parser.parse_args()
    frozen = hashes()
    assert sum((args.resume_workspace, args.resume_studio, args.resume_results, args.resume_ui)) <= 1, "select one resume point"
    assert not args.resume_ui or args.current_main, "UI-only resume requires current-main source binding"
    assert not (args.current_main and args.resume_workspace), "current-main reuses unchanged core courts"
    if args.resume_workspace or args.resume_studio or args.resume_results or args.current_main:
        record = "BOOT2-current-source-start.json" if args.current_main else "BOOT2-frozen-source-start.json"
        recorded = json.loads((EVIDENCE / record).read_text(encoding="utf-8"))
        assert recorded["hashes"] == frozen, "recorded courts cannot be reused after product changes"
    parent = ROOT / ".pytest_cache" / "BOOT2"
    parent.mkdir(parents=True, exist_ok=True)
    assert parent.resolve().is_relative_to(ROOT.resolve())
    with tempfile.TemporaryDirectory(prefix="verify-", dir=parent) as directory:
        temporary = Path(directory).resolve()
        assert temporary.is_relative_to(parent.resolve())
        environment = dict(os.environ, LOCALAPPDATA=str(temporary / "local"),
                           PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
                           ARCHHUB_GRAND_MAP_PATH=str(ROOT / "nodelang/data/public_runtime_map.json"))
        base = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "--tb=short"]
        if args.resume_studio:
            label = "studio-lazy-current" if args.current_main else "studio-cold-GREEN"
            source = "studio_lazyboot_home.test.cjs" if args.current_main else "studio_lazy_cold_views.test.cjs"
            run(label, ["node", "--test", "--test-concurrency=1", "--test-force-exit",
                "tests_js/" + source], environment)
        elif args.resume_results:
            pass
        elif args.current_main:
            run("studio-build-current", ["node", "--max-old-space-size=512", "packaging/compile_studio.cjs"], environment)
            if not args.resume_ui:
                run("home-current", base + ["tests/test_boot2.py", "tests/test_ds_port_assets.py",
                "tests_replica/test_first_click_after_boot_pays_no_cold_catalogue.py",
                "tests_replica/test_derived_interactions_equivalence.py", "--basetemp", str(temporary / "home")], environment)
                run("zero-idle-current", base + ["-s", "tests/test_zero_idle_growth.py",
                "--basetemp", str(temporary / "idle")], environment)
            run("studio-current", ["node", "--test", "--test-concurrency=1", "--test-force-exit",
                "tests_js/studio_boot2_home.test.cjs", "tests_js/studio_first_run_no_model.test.cjs",
                "tests_js/studio_authority_clean_canvas.test.cjs", "tests_js/studio_lazyboot_home.test.cjs",
                "tests_js/studio_home_design.test.cjs", "tests_js/studio_lazy_cold_views.test.cjs",
                "tests_js/studio_session_renew_write.test.cjs", "tests_js/studio_ds_port.test.cjs"], environment)
        else:
            if args.resume_workspace:
                run("workspace-GREEN", base + ["tests_replica/test_workspace_roots_graph_current.py",
                    "--basetemp", str(temporary / "workspace")], environment)
            else:
                run("home-final", base + ["tests/test_boot2.py",
                "tests_replica/test_first_click_after_boot_pays_no_cold_catalogue.py",
                "tests_replica/test_derived_interactions_equivalence.py",
                    "--basetemp", str(temporary / "home")], environment)
                run("catalogue-GREEN", base + ["tests/test_boot2_catalogues.py",
                "tests_replica/test_base_catalogue_stability.py", "tests_replica/test_agent_session_catalogue.py",
                "tests_replica/test_coordination_workshop.py", "tests_replica/test_clean_coordination_host.py",
                "tests_replica/test_unified_authority.py", "tests_replica/test_workspace_root_machine_permit.py",
                "tests_replica/test_workspace_roots_graph_current.py", "--basetemp", str(temporary / "catalogue")], environment)
            run("generation-final", base + ["-s", "tests/test_boot2_generations.py",
                "tests_replica/test_unified_authority_runtime.py", "--basetemp", str(temporary / "generation")], environment)
            run("zero-idle", base + ["-s", "tests/test_zero_idle_growth.py",
                "--basetemp", str(temporary / "idle")], environment)
            run("studio-build", ["node", "--max-old-space-size=512", "packaging/compile_studio.cjs"], environment)
            run("studio-GREEN", ["node", "--test", "--test-concurrency=1", "--test-force-exit",
                "tests_js/studio_boot2_home.test.cjs", "tests_js/studio_first_run_no_model.test.cjs",
                "tests_js/studio_authority_clean_canvas.test.cjs", "tests_js/studio_lazyboot_home.test.cjs",
                "tests_js/studio_home_design.test.cjs", "tests_js/studio_lazy_cold_views.test.cjs",
                "tests_js/studio_session_renew_write.test.cjs"], environment)
        suffix = "-current" if args.current_main else ""
        run("after" + suffix, [sys.executable, "-m", "tools.boot2_timing", "--out", "evidence/BOOT2-after" + suffix + ".json"], environment)
        run("ratchet" + suffix, [sys.executable, "tools/ratchet.py", "compare", ".", "evidence/ratchet.json"], environment)
        assert hashes() == frozen, "product source changed during verification"
        (EVIDENCE / "BOOT2-frozen-source.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
        print("BOOT2 FROZEN SOURCE MATCH", flush=True)


if __name__ == "__main__":
    main()
