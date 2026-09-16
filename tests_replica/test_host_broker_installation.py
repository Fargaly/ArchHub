"""Fixture-only deployment courts. No real host or user profile is touched.

Contract courted here (claude717 review 2026-09-16, majors B1-B7 + minors):

* B1  A foreign vendor registration in either root coexists; the install
      registers, touches nothing else, and refuse courts prove nothing was
      created.
* B2  user_profile_root is a required keyword; the user root must lie
      inside it and the machine root outside it. Nothing is ever published
      outside the caller-supplied profile.
* B3  Same-length tampering reaches the digest compare; size mismatch is a
      separate reason.
* B4  Every traversal form is refused by the manifest path check itself,
      with the leaf file present so nothing else can refuse first.
* B5  ADDIN_ID is pinned to bridges/sources/revit_mcp/RevitMCP.addin
      (ClientId), and the generated XML has Type/Name/VendorId and no
      ClientId.
* B6  Every refusal carries an exact reason; programming errors propagate.
* B7  Unreadable foreign registrations refuse naming the path.

Reason format: pure argument validation (year, digest hex) is the bare
reason; every refusal about a file, directory or manifest entry is
"<reason>: <path>" where <path> is the absolute path inspected, or the
raw manifest string for entries that must never be resolved. Root checks
run in the order: leaf must be Addins, user != machine, user inside
profile, machine outside profile.
"""
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nodelang import host_broker_installation as deployment

SOURCE_ADDIN = Path(__file__).resolve().parents[1] / "bridges" / "sources" / "revit_mcp" / "RevitMCP.addin"
FOREIGN_GUID = "b39107c3-a1d7-47f4-a5a1-532ddf6edb5d"
XML_DECLARATION = b'<?xml version="1.0" encoding="utf-8"?>\n'


def pin(path):
    return {"size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def body(name="pyRevit", guid=FOREIGN_GUID, class_name="PyRevitLoader.PyRevitLoaderApplication",
         tag="AddInId", assembly=r"C:\Vendor\vendor.dll"):
    return (f'<RevitAddIns>\n  <AddIn Type="Application">\n    <Name>{name}</Name>\n'
            f'    <Assembly>{assembly}</Assembly>\n    <{tag}>{guid}</{tag}>\n'
            f'    <FullClassName>{class_name}</FullClassName>\n    <VendorId>VNDR</VendorId>\n'
            f'  </AddIn>\n</RevitAddIns>\n')


def foreign(**fields):
    return XML_DECLARATION + body(**fields).encode()


def install(args):
    return deployment.install_revit_broker(**args)


def year(args, which):
    return args[which] / "2026"


def seed(directory, name, data):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def listing(directory):
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else None


def snapshot(args):
    seen = {}
    for which in ("user_addins_root", "machine_addins_root"):
        root = args[which]
        if root.exists():
            for path in sorted(root.rglob("*")):
                seen[str(path)] = path.read_bytes() if path.is_file() else None
    return seen


def refused(result, reason):
    assert result["status"] == "refused", result
    assert result["reason"] == reason, result
    assert result["registered"] is False
    assert not result["host_loaded"] and not result["execution_authority"]


@pytest.fixture
def rig(tmp_path):
    root = tmp_path / "ArchHub"
    host = tmp_path / "Revit 2026" / "Revit.exe"
    host.parent.mkdir()
    host.write_bytes(b"fixture host")
    api = {}
    for name in ("RevitAPI.dll", "RevitAPIUI.dll"):
        path = host.parent / name
        path.write_bytes(name.encode())
        api[name] = pin(path)
    rows = []
    for name in ("RevitMCP.dll", "RevitMCPCore.dll", "System.Text.Json.dll"):
        relative = "bridges/revit/2026/" + name
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        rows.append({"path": relative, **pin(path)})
    manifest = {"schema": "archhub-host-artifacts/v1", "source_revision": "a" * 40,
                "host": "revit", "host_version": "2026",
                "assembly": "bridges/revit/2026/RevitMCP.dll", "files": rows,
                "runtime_closure_reviewed": True, "host_api": api,
                "activation": {"eligibility": "reviewed-authenticated-broker", "review_sha256": "b" * 64}}
    manifest_path = root / "host-artifacts.json"
    profile = tmp_path / "user"
    profile.mkdir()
    args = dict(package_root=root, manifest_path=manifest_path, host_version="2026",
                host_executable=host, user_profile_root=profile,
                user_addins_root=profile / "Addins",
                machine_addins_root=tmp_path / "machine" / "Addins")

    def seal():
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        args["expected_manifest_sha256"] = pin(manifest_path)["sha256"]
    seal()
    return args, manifest, seal


# --- happy path and identity pins (B5, Type/VendorId/Name minor) -----------

def test_install_exact_path_and_repeat_without_rewrite(rig):
    args, _, _ = rig
    result = install(args)
    assert result["status"] == "registered_pending_host_restart", result
    assert result["registered"] and not result["host_loaded"] and not result["execution_authority"]
    target = Path(result["registration_path"])
    assert target == year(args, "user_addins_root") / "RevitMCP.addin"
    first = target.stat().st_mtime_ns
    xml = ET.fromstring(target.read_bytes())
    assert xml.findtext("AddIn/Assembly") == str(args["package_root"] / "bridges/revit/2026/RevitMCP.dll")
    assert xml.findtext("AddIn/AddInId") == deployment.ADDIN_ID
    assert xml.findtext("AddIn/FullClassName") == deployment.CLASS_NAME
    assert install(args)["status"] == "unchanged_pending_host_restart"
    assert target.stat().st_mtime_ns == first
    assert listing(target.parent) == ["RevitMCP.addin"]
    assert not args["machine_addins_root"].exists()


def test_source_addin_pins_broker_identity():
    source = ET.fromstring(SOURCE_ADDIN.read_bytes())
    entries = source.findall("AddIn")
    assert len(entries) == 1
    assert entries[0].findtext("ClientId") == deployment.ADDIN_ID
    assert entries[0].findtext("FullClassName") == deployment.CLASS_NAME


def test_generated_registration_shape_matches_source_addin(rig):
    args, _, _ = rig
    raw = Path(install(args)["registration_path"]).read_bytes()
    assert raw.startswith(b"<?xml")
    generated = ET.fromstring(raw)
    reference = ET.fromstring(SOURCE_ADDIN.read_bytes()).find("AddIn")
    assert generated.tag == "RevitAddIns"
    entries = generated.findall("AddIn")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.get("Type") == "Application" == reference.get("Type")
    assert entry.findtext("Name") == reference.findtext("Name") == "RevitMCP"
    assert entry.findtext("VendorId") == reference.findtext("VendorId")
    assert entry.findtext("VendorDescription")
    assert entry.find("ClientId") is None
    assert entry.findtext("AddInId") == reference.findtext("ClientId") == deployment.ADDIN_ID
    assert Path(entry.findtext("Assembly")).is_absolute()


# --- B1 coexistence -----------------------------------------------------------

def test_coexists_with_foreign_registrations_in_both_roots(rig):
    args, _, _ = rig
    user, machine = year(args, "user_addins_root"), year(args, "machine_addins_root")
    vendor_user = foreign()
    vendor_machine = foreign(name="Enscape", guid="0a2b4c6d-8e0f-4a1b-9c2d-3e4f5a6b7c8d",
                             class_name="Enscape.Revit.App", tag="ClientId")
    user_path = seed(user, "vendor.addin", vendor_user)
    machine_path = seed(machine, "enscape.addin", vendor_machine)
    result = install(args)
    assert result["status"] == "registered_pending_host_restart", result
    assert user_path.read_bytes() == vendor_user
    assert machine_path.read_bytes() == vendor_machine
    assert listing(user) == ["RevitMCP.addin", "vendor.addin"]
    assert listing(machine) == ["enscape.addin"]


def test_non_registration_files_and_foreign_client_ids_are_not_conflicts(rig):
    args, _, _ = rig
    user, machine = year(args, "user_addins_root"), year(args, "machine_addins_root")
    seed(user, "notes.txt", b"<!DOCTYPE anything>")
    seed(user, "old.addin.bak", b"")
    braced = foreign(guid="{" + FOREIGN_GUID.upper() + "}", tag="ClientId")
    seed(machine, "vendor.addin", braced)
    result = install(args)
    assert result["status"] == "registered_pending_host_restart", result
    assert listing(user) == ["RevitMCP.addin", "notes.txt", "old.addin.bak"]
    assert listing(machine) == ["vendor.addin"]


# --- B2 profile binding, root minors -----------------------------------------

def test_swapped_roots_refuse_publication_outside_profile(rig):
    args, _, _ = rig
    swapped = dict(args, user_addins_root=args["machine_addins_root"],
                   machine_addins_root=args["user_addins_root"])
    refused(install(swapped), f"user registration root is outside the selected profile: {args['machine_addins_root']}")
    assert not args["machine_addins_root"].exists()
    assert not args["user_addins_root"].exists()


def test_machine_root_inside_profile_refuses(rig):
    args, _, _ = rig
    machine = args["user_profile_root"] / "Roaming" / "Addins"
    refused(install(dict(args, machine_addins_root=machine)),
            f"machine registration root is inside the selected profile: {machine}")
    assert not machine.exists() and not args["user_addins_root"].exists()


def test_missing_profile_refuses(rig):
    args, _, _ = rig
    profile = args["user_profile_root"].with_name("nobody")
    result = install(dict(args, user_profile_root=profile, user_addins_root=profile / "Addins"))
    refused(result, f"path is missing: {profile}")
    assert not profile.exists()


def test_user_and_machine_roots_must_differ(rig):
    args, _, _ = rig
    same = args["user_addins_root"]
    refused(install(dict(args, machine_addins_root=same)),
            f"user and machine registration roots must differ: {same}")
    assert not same.exists()


@pytest.mark.parametrize("which", ["user_addins_root", "machine_addins_root"])
def test_registration_root_leaf_must_be_addins(rig, which):
    args, _, _ = rig
    bad = args[which].with_name("Plugins")
    refused(install(dict(args, **{which: bad})), f"registration root leaf must be Addins: {bad}")
    assert not bad.exists() and not args["user_addins_root"].exists()


@pytest.mark.parametrize("value", ["26", 2026, "2026 ", "20266", None, "2o26"])
def test_bad_host_version_refuses(rig, value):
    args, _, _ = rig
    refused(install(dict(args, host_version=value)), "an exact selected Revit year is required")
    assert not args["user_addins_root"].exists()


# --- B3 tampering -------------------------------------------------------------

def test_same_length_artifact_tamper_reaches_digest_compare(rig):
    args, _, _ = rig
    path = args["package_root"] / "bridges/revit/2026/RevitMCPCore.dll"
    original = path.read_bytes()
    path.write_bytes(original.swapcase())
    assert path.stat().st_size == len(original) and path.read_bytes() != original
    refused(install(args), f"artifact digest or identity mismatch: {path}")
    assert not args["user_addins_root"].exists()


def test_size_mismatch_artifact_tamper_refuses(rig):
    args, _, _ = rig
    path = args["package_root"] / "bridges/revit/2026/RevitMCPCore.dll"
    path.write_bytes(b"tampered")
    refused(install(args), f"artifact size mismatch: {path}")
    assert not args["user_addins_root"].exists()


@pytest.mark.parametrize("mutate", [bytes.swapcase, lambda data: data + b"!"], ids=["same-length", "size"])
def test_host_api_tamper_refuses_with_compatibility_reason(rig, mutate):
    args, _, _ = rig
    path = args["host_executable"].parent / "RevitAPI.dll"
    path.write_bytes(mutate(path.read_bytes()))
    refused(install(args), "selected host API differs from reviewed target; "
                           f"host update requires compatibility review: {path}")
    assert not args["user_addins_root"].exists()


# --- B4 traversal -------------------------------------------------------------

TRAVERSAL = [
    ("bridges/revit/2026/../../escape.dll", "bridges/escape.dll"),
    ("bin/csc/../../escape.dll", "escape.dll"),
    ("bridges\\revit\\2026\\System.Text.Json.dll", None),
    ("/bridges/revit/2026/System.Text.Json.dll", None),
    ("ABSOLUTE", None),
    ("other/System.Text.Json.dll", "other/System.Text.Json.dll"),
    ("bridges/revit/2026//System.Text.Json.dll", None),
    ("bridges/revit/2026/./System.Text.Json.dll", None),
    ("bridges/revit/2025/System.Text.Json.dll", "bridges/revit/2025/System.Text.Json.dll"),
]


@pytest.mark.parametrize("form,leaf", TRAVERSAL, ids=[
    "dotdot", "bin-dotdot", "backslash", "leading-slash", "absolute",
    "outside-prefix", "double-slash", "dot-segment", "other-year"])
def test_manifest_path_forms_refuse_with_exact_reason(rig, form, leaf):
    args, manifest, seal = rig
    root = args["package_root"]
    payload = root / "bridges/revit/2026/System.Text.Json.dll"
    if form == "ABSOLUTE":
        form = str(payload)
    if leaf:
        target = root / leaf
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload.read_bytes())
    manifest["files"][2] = {"path": form, **pin(payload)}
    seal()
    refused(install(args), f"artifact path escapes selected payload: {form}")
    assert not args["user_addins_root"].exists()


# --- manifest eligibility (B6 exact reasons, digest minor) ------------------

@pytest.mark.parametrize("field,value,reason", [
    ("host_version", "2025", "manifest does not select this Revit version"),
    ("schema", "archhub-host-artifacts/v0", "manifest does not select this Revit version"),
    ("runtime_closure_reviewed", False, "runtime closure has not been reviewed"),
    ("activation", {}, "broker custody is not reviewed for activation"),
    ("source_revision", "", "source revision is missing"),
    ("assembly", "bridges/revit/2026/Other.dll", "unexpected broker entry assembly"),
    ("files", [], "artifact closure is missing or outside budget"),
    ("host_api", {}, "exact selected host API pins are required"),
])
def test_ineligible_manifest_never_creates_registration(rig, field, value, reason):
    args, manifest, seal = rig
    manifest[field] = value
    seal()
    refused(install(args), f"{reason}: {args['manifest_path']}")
    assert not args["user_addins_root"].exists()
    assert not args["machine_addins_root"].exists()


def test_external_manifest_pin_is_required(rig):
    args, manifest, _ = rig
    manifest["activation"]["eligibility"] = "unreviewed"
    args["manifest_path"].write_text(json.dumps(manifest), encoding="utf-8")
    refused(install(args), f"release manifest digest mismatch: {args['manifest_path']}")
    assert not args["user_addins_root"].exists()


@pytest.mark.parametrize("value", [None, "", "A" * 64, "a" * 63, "a" * 65])
def test_manifest_digest_must_be_lowercase_hex(rig, value):
    args, _, _ = rig
    refused(install(dict(args, expected_manifest_sha256=value)),
            "verified release manifest digest must be 64 lowercase hex")
    assert not args["user_addins_root"].exists()


def test_manifest_that_is_not_json_refuses(rig):
    args, _, _ = rig
    args["manifest_path"].write_bytes(b"{not json")
    args["expected_manifest_sha256"] = pin(args["manifest_path"])["sha256"]
    refused(install(args), f"release manifest is not valid JSON: {args['manifest_path']}")
    assert not args["user_addins_root"].exists()


def test_programming_errors_propagate_instead_of_refusing(rig):
    args, _, _ = rig
    with pytest.raises(TypeError):
        install(dict(args, package_root=None))
    assert not args["user_addins_root"].exists()


# --- existing registrations (B1 refuse side, FullClassName/DOCTYPE/UTF-16 minors)

@pytest.mark.parametrize("location,filename,reason", [
    ("user_addins_root", "RevitMCP.addin", "conflicting existing RevitMCP registration"),
    ("machine_addins_root", "RevitMCP.addin", "conflicting existing RevitMCP registration"),
    ("user_addins_root", "custom.addin", "broker already registered in another file"),
    ("machine_addins_root", "custom.addin", "broker already registered in another file"),
])
def test_existing_conflict_preserved(rig, location, filename, reason):
    args, _, _ = rig
    path = seed(year(args, location), filename,
                foreign(name="RevitMCP", guid=deployment.ADDIN_ID, class_name="Legacy.App",
                        assembly=r"C:\legacy\RevitMCP.dll"))
    before = snapshot(args)
    refused(install(args), f"{reason}: {path}")
    assert snapshot(args) == before


@pytest.mark.parametrize("tag", ["ClientId", "AddInId"])
def test_equivalent_braced_guid_is_duplicate(rig, tag):
    args, _, _ = rig
    path = seed(year(args, "user_addins_root"), "renamed.addin",
                f'<RevitAddIns><AddIn><{tag}> {{{deployment.ADDIN_ID.upper()}}} </{tag}></AddIn></RevitAddIns>'.encode())
    before = snapshot(args)
    refused(install(args), f"broker already registered in another file: {path}")
    assert snapshot(args) == before


@pytest.mark.parametrize("class_name", [deployment.CLASS_NAME, f" {deployment.CLASS_NAME}\n"], ids=["exact", "padded"])
def test_fullclassname_only_conflict_refuses(rig, class_name):
    args, _, _ = rig
    path = seed(year(args, "machine_addins_root"), "fork.addin",
                foreign(name="Fork", guid="7c1e0d2a-5b4f-4c3e-9a8b-1d2e3f4a5b6c", class_name=class_name))
    before = snapshot(args)
    refused(install(args), f"broker already registered in another file: {path}")
    assert snapshot(args) == before
    assert not args["user_addins_root"].exists()


@pytest.mark.parametrize("declaration", [
    b'<!DOCTYPE RevitAddIns [<!ENTITY e "x">]>',
    b'<!doctype RevitAddIns>',
    b'<!DOCTYPE RevitAddIns SYSTEM "never.dtd">',
], ids=["internal-entity", "lowercase", "system"])
def test_doctype_declarations_refuse_naming_path(rig, declaration):
    args, _, _ = rig
    path = seed(year(args, "machine_addins_root"), "vendor.addin",
                XML_DECLARATION + declaration + b"\n" + body().encode())
    before = snapshot(args)
    refused(install(args), f"registration XML contains unsupported declarations: {path}")
    assert snapshot(args) == before
    assert not args["user_addins_root"].exists()


def test_utf16_bom_foreign_file_cannot_hide_a_doctype(rig):
    args, _, _ = rig
    text = ('<?xml version="1.0" encoding="utf-16"?>\n<!DOCTYPE RevitAddIns [<!ENTITY e "x">]>\n'
            + body(name="&e;"))
    path = seed(year(args, "machine_addins_root"), "vendor.addin", text.encode("utf-16"))
    assert path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff")
    before = snapshot(args)
    refused(install(args), f"registration XML contains unsupported declarations: {path}")
    assert snapshot(args) == before
    assert not args["user_addins_root"].exists()


def test_utf16_bom_wellformed_foreign_file_coexists(rig):
    args, _, _ = rig
    data = ('<?xml version="1.0" encoding="utf-16"?>\n' + body()).encode("utf-16")
    user = year(args, "user_addins_root")
    path = seed(user, "vendor.addin", data)
    result = install(args)
    assert result["status"] == "registered_pending_host_restart", result
    assert path.read_bytes() == data
    assert listing(user) == ["RevitMCP.addin", "vendor.addin"]


# --- B7 unreadable foreign registrations, inventory minor --------------------

@pytest.mark.parametrize("location", ["user_addins_root", "machine_addins_root"])
@pytest.mark.parametrize("shape", ["empty", "garbage", "oversized", "directory", "symlink"])
def test_malformed_foreign_registration_refuses_naming_path(rig, tmp_path, location, shape):
    args, _, _ = rig
    directory = year(args, location)
    directory.mkdir(parents=True)
    path = directory / f"{shape}.addin"
    if shape == "empty":
        path.write_bytes(b"")
    elif shape == "garbage":
        path.write_bytes(b"<RevitAddIns><AddIn>")
    elif shape == "oversized":
        path.write_bytes(b"<RevitAddIns>" + b" " * deployment.MAX_REGISTRATION + b"</RevitAddIns>")
    elif shape == "directory":
        path.mkdir()
    else:
        target = tmp_path / "elsewhere.addin"
        target.write_bytes(foreign())
        try:
            os.symlink(target, path)
        except OSError as error:
            pytest.skip(f"symlink creation not permitted here: {error}")
    seed(directory, "vendor.addin", foreign())
    before = snapshot(args)
    refused(install(args), f"unreadable foreign registration: {path}")
    assert snapshot(args) == before
    other = "machine_addins_root" if location == "user_addins_root" else "user_addins_root"
    assert not args[other].exists()


def test_registration_inventory_over_256_refuses_naming_directory(rig):
    args, _, _ = rig
    directory = year(args, "machine_addins_root")
    for index in range(257):
        seed(directory, f"vendor-{index:03d}.addin",
             foreign(name=f"Vendor{index}", guid=str(uuid.uuid5(uuid.NAMESPACE_URL, f"vendor-{index}")),
                     class_name=f"Vendor{index}.App"))
    refused(install(args), f"registration inventory exceeds budget: {directory}")
    assert len(listing(directory)) == 257
    assert not args["user_addins_root"].exists()


# --- publication failures (B6 honest status, path/errno minor) --------------

def test_racing_destination_never_overwritten(rig, monkeypatch):
    args, _, _ = rig
    actual_link = deployment.os.link

    def competing_link(source, target):
        Path(target).write_bytes(b"other installer")
        return actual_link(source, target)
    monkeypatch.setattr(deployment.os, "link", competing_link)
    result = install(args)
    target = year(args, "user_addins_root") / "RevitMCP.addin"
    assert result["status"] == "failed" and not result["registered"], result
    assert result["reason"].startswith("FileExistsError") and str(target) in result["reason"], result
    assert target.read_bytes() == b"other installer"
    assert listing(target.parent) == ["RevitMCP.addin"]


def test_write_failure_is_honest_and_cleans_temporary(rig, monkeypatch):
    args, _, _ = rig

    def fail(*_):
        raise PermissionError(13, "fixture denial")
    monkeypatch.setattr(deployment.os, "link", fail)
    result = install(args)
    assert result["status"] == "failed" and not result["registered"], result
    assert result["reason"].startswith("PermissionError") and "fixture denial" in result["reason"], result
    assert listing(year(args, "user_addins_root")) == []


def test_cleanup_failure_reports_published_registration_and_residue(rig, monkeypatch):
    args, _, _ = rig
    original = Path.unlink

    def failed_cleanup(path, *a, **kw):
        if path.name.startswith(".archhub-addin-"):
            raise PermissionError("fixture cleanup denial")
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, "unlink", failed_cleanup)
    result = install(args)
    assert result["status"] == "partial_failure", result
    assert result["registered"] and result["cleanup_pending"]
    assert Path(result["registration_path"]).is_file()


def test_redirected_registration_root_refuses(rig, monkeypatch):
    args, _, _ = rig
    original = deployment._require_plain
    redirected = year(args, "user_addins_root")

    def checked(path, kind, **kwargs):
        if path == redirected:
            raise deployment.RegistrationRefused(f"path is redirected: {path}")
        return original(path, kind, **kwargs)
    monkeypatch.setattr(deployment, "_require_plain", checked)
    refused(install(args), f"path is redirected: {redirected}")
    assert not args["user_addins_root"].exists()
