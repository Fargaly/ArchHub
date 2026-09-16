"""Per-user registration of release-reviewed Revit broker artifacts.

The release caller supplies a previously authenticated manifest digest. This
module neither approves a release nor grants graph execution authority. No
current legacy broker is eligible: activation requires a pinned custody review.
Registration only schedules a future host load; it never proves a live broker.

Integration contract
--------------------
Call install_revit_broker with absolute package_root, manifest_path,
host_executable, user_profile_root, user_addins_root and machine_addins_root.
user_profile_root is the selected Windows user's profile directory (the
caller's USERPROFILE); user_addins_root and machine_addins_root are that
user's and the machine's Autodesk/Revit/Addins roots (the caller builds them
from APPDATA and ProgramData, see colleague_setup). Both roots must end in
"Addins", the user root must lie inside the profile and the machine root
outside it: nothing is ever published outside the caller-supplied profile,
whatever a swapped or mistaken argument says. host_version is one explicitly
selected four-digit year. No discovery, environment reading, elevation,
consent handling or all-version install happens here. The release caller
authenticates expected_manifest_sha256 against its release evidence before
calling, and owns user selection and filesystem custody.

Broker identity: ADDIN_ID is the ClientId and CLASS_NAME the FullClassName of
bridges/sources/revit_mcp/RevitMCP.addin, pinned by court against that file.
Changing either breaks continuity with every registration Revit already
loaded. The generated registration carries the identity as AddInId.

Manifest JSON, schema archhub-host-artifacts/v1:
* source_revision: reviewed 40-64 lowercase hexadecimal revision;
* host: revit; host_version: selected year;
* assembly: bridges/revit/<year>/RevitMCP.dll;
* files: complete reviewed runtime closure, each {path, size, sha256}; only
  bridges/revit/<year>/ and bin/csc/ relative paths, no traversal/duplicates;
* runtime_closure_reviewed: true, established during release review;
* host_api: RevitAPI.dll and RevitAPIUI.dll, each {size, sha256}, matched against
  the selected host installation, never redistributed;
* activation: {eligibility: reviewed-authenticated-broker, review_sha256: ...},
  referring to the release's actual custody review. Current unauthenticated
  legacy brokers are ineligible. Setup must never invent these review fields
  or calculate acceptance pins from whatever happens to exist on disk.

The release pipeline remains responsible for verifying the closure is complete,
has no unreviewed loadable extras, and for immutable package custody. File checks
here are bounded mismatch checks, not an OS isolation boundary against another
process changing the installation after verification.

Existing registrations: both selected-year directories are inventoried before
anything is written. Foreign vendor registrations (another AddInId/ClientId and
another FullClassName) coexist untouched; files without the .addin suffix are
ignored. A RevitMCP.addin that is not byte-identical to ours, and any other file
carrying our AddInId or FullClassName, refuses. A .addin that cannot be read as
plain well-formed XML within budget (empty, malformed, oversized, a directory,
a redirect) refuses naming its path: Revit's reaction to it is unknown and
publishing beside it would hide the fault. DOCTYPE and ENTITY declarations
refuse, checked on text decoded through any UTF-16 BOM first, because entity
expansion is unbounded and no Revit registration needs them. Bundle add-ins
under ProgramData/Autodesk/ApplicationPlugins are outside both roots and are
not inventoried.

Every refusal carries an exact reason. Pure argument validation reasons are
bare; every reason about a file, directory or manifest entry is
"<reason>: <path>", where <path> is the absolute path inspected, or the raw
manifest string for entries that must never be resolved. Programming errors
(wrong argument types) propagate. Only RegistrationRefused becomes status
refused; only OSError becomes failed or partial_failure, with the exception
class and message (path and errno) in reason.

States: registered_pending_host_restart or unchanged_pending_host_restart means
the exact registration exists, not that a host loaded it. refused means pins,
eligibility, paths, or existing registrations prevent publication. failed means
an I/O attempt did not publish our registration. partial_failure reports a
remaining temporary file or a post-publication failure, with registered and
cleanup_pending describing the observed result. Empty created directories may
remain after a failed attempt. Differing registrations require a separate
reviewed migration; this function never overwrites or removes them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

from .client_mcp_installation import RegistrationRefused, _require_plain

# Pinned to bridges/sources/revit_mcp/RevitMCP.addin: ClientId, FullClassName, VendorId.
ADDIN_ID = "9f5c3b6f-2a1c-4e1f-bd0a-7a31c0e22c1d"
CLASS_NAME = "RevitMCP.RevitMCPApp"
VENDOR_ID = "FRGL"
MAX_MANIFEST = 1024 * 1024
MAX_REGISTRATION = 256 * 1024
MAX_INVENTORY = 256
MAX_ARTIFACT = 256 * 1024 * 1024
MAX_CLOSURE = 512 * 1024 * 1024
# Windows scanners hold fresh files briefly; bounded retries before reporting residue.
_CLEANUP_BACKOFF = (0.0, 0.05, 0.15)


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _refuse(reason, path):
    return RegistrationRefused(f"{reason}: {path}")


def _read(path, limit):
    _require_plain(path, "file")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise _refuse("file exceeds inspection budget", path)
    return data


def _verify_file(path, row):
    if not _digest(row.get("sha256")) or type(row.get("size")) is not int or not 0 < row["size"] <= MAX_ARTIFACT:
        raise _refuse("artifact pin is missing or outside budget", path)
    before = _require_plain(path, "file")
    if before[2] != row["size"]:
        raise _refuse("artifact size mismatch", path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = row["size"]
        while remaining:
            block = stream.read(min(remaining, 1024 * 1024))
            if not block:
                raise _refuse("artifact truncated during verification", path)
            digest.update(block)
            remaining -= len(block)
        if stream.read(1):
            raise _refuse("artifact grew during verification", path)
    if digest.hexdigest() != row["sha256"] or before != _require_plain(path, "file"):
        raise _refuse("artifact digest or identity mismatch", path)


def _manifest(root, path, expected, year, host):
    raw = _read(path, MAX_MANIFEST)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise _refuse("release manifest digest mismatch", path)
    try:
        value = json.loads(raw)
    except ValueError:
        raise _refuse("release manifest is not valid JSON", path) from None
    if not isinstance(value, dict) or value.get("schema") != "archhub-host-artifacts/v1" or value.get("host") != "revit" or value.get("host_version") != year:
        raise _refuse("manifest does not select this Revit version", path)
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("source_revision", ""))):
        raise _refuse("source revision is missing", path)
    activation = value.get("activation", {})
    if not isinstance(activation, dict) or activation.get("eligibility") != "reviewed-authenticated-broker" or not _digest(activation.get("review_sha256")):
        raise _refuse("broker custody is not reviewed for activation", path)
    if value.get("runtime_closure_reviewed") is not True:
        raise _refuse("runtime closure has not been reviewed", path)
    prefix = f"bridges/revit/{year}/"
    if value.get("assembly") != prefix + "RevitMCP.dll":
        raise _refuse("unexpected broker entry assembly", path)
    rows = value.get("files")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 256:
        raise _refuse("artifact closure is missing or outside budget", path)
    seen = set()
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise _refuse("invalid artifact entry", path)
        relative = row.get("path")
        # Judged on the raw manifest string; an escaping entry is never resolved.
        if not isinstance(relative, str) or "\\" in relative or ":" in relative or any(p in ("", ".", "..") for p in relative.split("/")) or not (relative.startswith(prefix) or relative.startswith("bin/csc/")):
            raise _refuse("artifact path escapes selected payload", relative)
        if relative.casefold() in seen:
            raise _refuse("duplicate artifact path", relative)
        seen.add(relative.casefold())
        _verify_file(root / PurePosixPath(relative), row)
        total += row["size"]
        if total > MAX_CLOSURE:
            raise _refuse("artifact closure exceeds budget", path)
    if not {prefix.lower() + "revitmcp.dll", prefix.lower() + "revitmcpcore.dll"} <= seen:
        raise _refuse("broker shim or core is absent from closure", path)
    api = value.get("host_api")
    if not isinstance(api, dict) or set(api) != {"RevitAPI.dll", "RevitAPIUI.dll"}:
        raise _refuse("exact selected host API pins are required", path)
    _require_plain(host, "file")
    if host.name.casefold() != "revit.exe":
        raise _refuse("selected host executable is not Revit", host)
    for name, row in api.items():
        if not isinstance(row, dict):
            raise _refuse("invalid host API pin", path)
        library = host.parent / name
        try:
            _verify_file(library, row)
        except RegistrationRefused as error:
            raise _refuse("selected host API differs from reviewed target; "
                          "host update requires compatibility review", library) from error
    return root / PurePosixPath(value["assembly"])


def _registration(assembly):
    tree = ET.Element("RevitAddIns")
    entry = ET.SubElement(tree, "AddIn", Type="Application")
    for tag, value in (("Name", "RevitMCP"), ("Assembly", str(assembly)), ("FullClassName", CLASS_NAME),
                       ("AddInId", ADDIN_ID), ("VendorId", VENDOR_ID), ("VendorDescription", "ArchHub Revit broker")):
        ET.SubElement(entry, tag).text = value
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def _same_id(text):
    try:
        return uuid.UUID(text.strip()) == uuid.UUID(ADDIN_ID)
    except (ValueError, AttributeError):
        return False


def _decode_registration(raw):
    """The text handed to the parser. UTF-16 is decoded first so a BOM cannot hide a declaration."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:2] == b"<\x00":
        return raw.decode("utf-16-le")
    if raw[:2] == b"\x00<":
        return raw.decode("utf-16-be")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Single-byte declared encodings stay readable; the compared fields are ASCII.
        return raw.decode("latin-1")


def _read_registration(candidate):
    try:
        raw = _read(candidate, MAX_REGISTRATION)
        return raw, _decode_registration(raw)
    except (RegistrationRefused, UnicodeDecodeError):
        raise _refuse("unreadable foreign registration", candidate) from None


def _parse_registration(candidate, text):
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise _refuse("registration XML contains unsupported declarations", candidate)
    try:
        # A str input makes expat parse exactly the text inspected above.
        return ET.fromstring(text)
    except ET.ParseError:
        raise _refuse("unreadable foreign registration", candidate) from None


def _check_registrations(directory, destination, expected):
    if _require_plain(directory, "directory", may_be_absent=True) is None:
        return
    candidates = [c for c in sorted(directory.iterdir()) if c.suffix.casefold() == ".addin"]
    if len(candidates) > MAX_INVENTORY:
        raise _refuse("registration inventory exceeds budget", directory)
    for candidate in candidates:
        ours = candidate.name.casefold() == "revitmcp.addin"
        try:
            raw, text = _read_registration(candidate)
        except RegistrationRefused:
            if ours:
                raise _refuse("conflicting existing RevitMCP registration", candidate) from None
            raise
        if candidate == destination and raw == expected:
            continue
        if ours:
            raise _refuse("conflicting existing RevitMCP registration", candidate)
        for entry in _parse_registration(candidate, text).iter("AddIn"):
            if (_same_id(entry.findtext("ClientId", "")) or _same_id(entry.findtext("AddInId", ""))
                    or entry.findtext("FullClassName", "").strip() == CLASS_NAME):
                raise _refuse("broker already registered in another file", candidate)


def _describe(error, path):
    """Exception class, code, message and plain paths, so a failure names what failed."""
    winerror = getattr(error, "winerror", None)
    code = (f"[WinError {winerror}] " if winerror is not None
            else f"[Errno {error.errno}] " if error.errno is not None else "")
    named = [os.fsdecode(p) for p in (error.filename, error.filename2) if p is not None]
    if not named and path is not None:
        named = [os.fsdecode(path)]
    text = f"{type(error).__name__}: {code}{error.strerror or str(error) or 'no detail'}"
    return text + (": " + " -> ".join(named) if named else "")


def _remove(path):
    """Unlink our temporary with bounded retries; True once it is gone."""
    for delay in _CLEANUP_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            continue
    return False


def install_revit_broker(*, package_root, manifest_path, expected_manifest_sha256,
                         host_version, host_executable, user_profile_root,
                         user_addins_root, machine_addins_root):
    """Register one selected year; all paths explicit, no discovery or processes.

    Roots are Autodesk/Revit/Addins for the selected user and machine; the user
    root must be inside user_profile_root and the machine root outside it.
    Inspect both, write only the user's selected year. Differing prior
    registrations need an explicit migration; this function never overwrites them.
    """
    result = {"status": "refused", "registered": False,
              "host_loaded": False, "execution_authority": False,
              "host_version": host_version}
    temporary = None
    target = None
    linked = False
    try:
        if not isinstance(host_version, str) or not re.fullmatch(r"20[0-9]{2}", host_version):
            raise RegistrationRefused("an exact selected Revit year is required")
        if not _digest(expected_manifest_sha256):
            raise RegistrationRefused("verified release manifest digest must be 64 lowercase hex")
        root, host = Path(package_root), Path(host_executable)
        profile = Path(user_profile_root)
        user_root, machine_root = Path(user_addins_root), Path(machine_addins_root)
        _require_plain(profile, "directory")
        for candidate in (user_root, machine_root):
            if candidate.name != "Addins":
                raise _refuse("registration root leaf must be Addins", candidate)
        if user_root == machine_root:
            raise _refuse("user and machine registration roots must differ", user_root)
        if not user_root.is_relative_to(profile):
            raise _refuse("user registration root is outside the selected profile", user_root)
        if machine_root.is_relative_to(profile):
            raise _refuse("machine registration root is inside the selected profile", machine_root)
        _require_plain(root, "directory")
        assembly = _manifest(root, Path(manifest_path), expected_manifest_sha256, host_version, host)
        user = user_root / host_version
        machine = machine_root / host_version
        destination = target = user / "RevitMCP.addin"
        expected = _registration(assembly)
        _check_registrations(machine, destination, expected)
        _check_registrations(user, destination, expected)
        result["registration_path"] = str(destination)
        if destination.exists():
            if _read(destination, MAX_REGISTRATION) != expected:
                raise _refuse("registration changed during verification", destination)
            result.update(status="unchanged_pending_host_restart", registered=True)
            return result
        user.mkdir(parents=True, exist_ok=True)
        _require_plain(user, "directory")
        descriptor, temporary = tempfile.mkstemp(prefix=".archhub-addin-", suffix=".tmp", dir=user)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and fails if another writer won.
        # Never replace an existing registration, including during a race.
        _check_registrations(machine, destination, expected)
        _check_registrations(user, destination, expected)
        os.link(temporary, destination)
        linked = True
        result.update(status="registered_pending_host_restart", registered=True)
    except RegistrationRefused as error:
        result["reason"] = str(error)
    except OSError as error:
        result.update(status="partial_failure" if linked else "failed",
                      registered=linked, reason=_describe(error, target))
    finally:
        if temporary is not None and not _remove(Path(temporary)):
            result.update(status="partial_failure", cleanup_pending=True)
    return result


__all__ = [
    "ADDIN_ID",
    "CLASS_NAME",
    "MAX_REGISTRATION",
    "RegistrationRefused",
    "install_revit_broker",
]
