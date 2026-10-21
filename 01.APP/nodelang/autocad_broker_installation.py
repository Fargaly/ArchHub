"""Per-user AutoCAD registration of the release-reviewed AcadMCP add-in.

AutoCAD loads .NET add-ins it is told about through an ApplicationPlugins
bundle: <plugins>/<name>.bundle/PackageContents.xml, one ComponentEntry per
release series, each loading a module relative to the bundle. This owner
writes exactly one bundle, %APPDATA%/Autodesk/ApplicationPlugins/
ArchHub.AcadMCP.bundle, for the selected user; it never needs elevation,
never starts AutoCAD, and AutoCAD reads it at its next start.

Integration contract (colleague_setup.register_autocad_add_ins): rows are the
HOST_ARTIFACTS.json "autocad" entries of the detected years, written by
installer/build_host_bridges.ps1 ({assembly, files, host_api, activation}).
Each year is registered only when:
* its activation is {eligibility: reviewed-authenticated-broker,
  review_sha256: <64 hex>}, the release's custody review (never invented here);
* every file of its closure matches its size and SHA-256 pin, and the closure
  holds only bridges/autocad/<year>/ paths including AcadMCP.dll;
* the installed AutoCAD <year> acmgd/acdbmgd/accoremgd match the reviewed pins;
* its release series is known (SERIES); an unknown year is refused, not guessed.
The verified closure is copied into Contents/<year>/, so AutoCAD loads the
reviewed bytes, and archhub-bundle.sha256 lists every file placed ("sha256
relative/path" lines). An existing bundle is ours only when its files are
exactly that list with those digests: then it is left alone when identical, or
replaced whole by a newly verified bundle; otherwise it is foreign or edited
and refused, untouched; ours also requires the install record ArchHub wrote in
its own state (state_root/autocad-bundle.json: bundle path, ProductCode and the
receipt digest), so a receipt that only matches its own files, or an empty
one, never makes a bundle ours. Another bundle in either ApplicationPlugins root
carrying our ProductCode refuses (it would load the broker twice). Uninstall
(installer/host_registrations.iss) deletes only listed files whose digest
still matches.

States per year: registered_pending_host_restart / unchanged_pending_host_restart
mean the bundle is written, not that AutoCAD loaded it; refused carries the
exact reason; failed / partial_failure carry the OSError.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from .client_mcp_installation import RegistrationRefused, _require_plain
from .host_broker_installation import _describe, _digest, _refuse, _verify_file

BUNDLE = "ArchHub.AcadMCP.bundle"
RECEIPT = "archhub-bundle.sha256"
RECORD_NAME = "autocad-bundle.json"
RECORD_SCHEMA = "archhub-autocad-bundle/v1"
PRODUCT_CODE = "{4E7C1A52-9B3D-4F68-A0E1-2C5D8B7F3A19}"
UPGRADE_CODE = "{8B2F6D40-3C71-4E95-B6A8-1D9E0F5C7A24}"
HOST_API = ("acmgd.dll", "acdbmgd.dll", "accoremgd.dll")
# AutoCAD release series per year (R25.0 = 2025, R25.1 = 2026, R26.0 = 2027 per
# Autodesk's developer blog). A year not listed is refused until reviewed here.
SERIES = {"2020": "R23.1", "2021": "R24.0", "2022": "R24.1", "2023": "R24.2", "2024": "R24.3",
          "2025": "R25.0", "2026": "R25.1", "2027": "R26.0"}
MAX_FILES = 256
MAX_INVENTORY = 1024


def _verify_year(root, year, row, program_files):
    """[(bundle relative path, pinned bytes)] of one reviewed year, else RegistrationRefused."""
    if not re.fullmatch(r"20[0-9]{2}", year):
        raise RegistrationRefused("an exact AutoCAD year is required")
    if year not in SERIES:
        raise RegistrationRefused("no known AutoCAD release series for %s; not guessed" % year)
    if not isinstance(row, dict):
        raise RegistrationRefused("AutoCAD artifact entry is invalid")
    activation = row.get("activation")
    if (not isinstance(activation, dict) or activation.get("eligibility") != "reviewed-authenticated-broker"
            or not _digest(activation.get("review_sha256"))):
        raise RegistrationRefused("AutoCAD add-in custody is not reviewed for activation")
    prefix = "bridges/autocad/%s/" % year
    if row.get("assembly") != prefix + "AcadMCP.dll":
        raise RegistrationRefused("unexpected AutoCAD add-in entry assembly")
    files = row.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise RegistrationRefused("AutoCAD artifact closure is missing or outside budget")
    placed, seen = [], set()
    for entry in files:
        relative = entry.get("path") if isinstance(entry, dict) else None
        if (not isinstance(relative, str) or "\\" in relative or ":" in relative
                or any(part in ("", ".", "..") for part in relative.split("/"))
                or not relative.startswith(prefix) or relative.count("/") != 3):
            raise _refuse("artifact path escapes selected payload", relative)
        if relative.casefold() in seen:
            raise _refuse("duplicate artifact path", relative)
        seen.add(relative.casefold())
        source = root / PurePosixPath(relative)
        _verify_file(source, entry)
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise _refuse("artifact changed during verification", source)
        placed.append(("Contents/%s/%s" % (year, relative.rsplit("/", 1)[1]), data))
    if (prefix + "acadmcp.dll").casefold() not in seen:
        raise RegistrationRefused("AcadMCP.dll is absent from the AutoCAD closure")
    api = row.get("host_api")
    if not isinstance(api, dict) or set(api) != set(HOST_API):
        raise RegistrationRefused("exact AutoCAD host API pins are required")
    host = Path(program_files) / "Autodesk" / ("AutoCAD %s" % year)
    for name in HOST_API:
        library = host / name
        try:
            _verify_file(library, api[name] if isinstance(api[name], dict) else {})
        except RegistrationRefused as error:
            raise _refuse("selected host API differs from reviewed target; "
                          "host update requires compatibility review", library) from error
    return placed


def _package_contents(years):
    package = ET.Element("ApplicationPackage", SchemaVersion="1.0", AutodeskProduct="AutoCAD",
                         ProductType="Application", Name="ArchHub AcadMCP", AppVersion="1.0.0",
                         Description="ArchHub AutoCAD broker", Author="Fargaly",
                         ProductCode=PRODUCT_CODE, UpgradeCode=UPGRADE_CODE)
    ET.SubElement(package, "CompanyDetails", Name="Fargaly")
    components = ET.SubElement(package, "Components")
    for year in years:
        entry = ET.SubElement(components, "ComponentEntry", AppName="ArchHubAcadMCP",
                              ModuleName="./Contents/%s/AcadMCP.dll" % year,
                              AppDescription="ArchHub AutoCAD broker", AppType=".Net",
                              LoadOnAutoCADStartup="True")
        ET.SubElement(entry, "RuntimeRequirements", OS="Win64", SeriesMin=SERIES[year], SeriesMax=SERIES[year])
    return ET.tostring(package, encoding="utf-8", xml_declaration=True)


def _receipt(files):
    return "".join("%s  %s\n" % (hashlib.sha256(data).hexdigest(), path)
                   for path, data in sorted(files.items())).encode("utf-8")


def _inventory(bundle):
    """{relative path: sha256} of every file in an existing bundle; refuses redirects."""
    found = {}
    for current, directories, names in os.walk(bundle):
        for name in directories + names:
            _require_plain(Path(current) / name, "directory" if name in directories else "file")
        for name in names:
            path = Path(current) / name
            found[path.relative_to(bundle).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            if len(found) > MAX_INVENTORY:
                raise _refuse("bundle inventory exceeds budget", bundle)
    return found



def _check_other_bundles(roots, bundle):
    for plugins in roots:
        if _require_plain(plugins, "directory", may_be_absent=True) is None:
            continue
        for other in sorted(plugins.iterdir()):
            if other == bundle or not other.name.casefold().endswith(".bundle"):
                continue
            contents = other / "PackageContents.xml"
            try:
                text = contents.read_bytes()[:256 * 1024].decode("utf-8", "replace")
            except OSError:
                continue
            if PRODUCT_CODE.casefold() in text.casefold():
                raise _refuse("AcadMCP already registered by another bundle", other)


def _write_tree(directory, files):
    for relative, data in files.items():
        target = directory / PurePosixPath(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def _owned_listing(bundle, record_path):
    """The receipt of a bundle THIS install placed, else RegistrationRefused.

    Ours means: our install record (in ArchHub's own state, written only after
    we published) names this bundle, our ProductCode and the receipt's exact
    digest; the receipt is non-empty, lists PackageContents.xml carrying our
    ProductCode, and lists exactly the files present with their digests. A
    same-named bundle whose receipt merely matches its own files is not ours.
    """
    foreign = _refuse("existing bundle was not placed by ArchHub or was changed; left unchanged", bundle)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise foreign from None
    inventory = _inventory(bundle)
    if RECEIPT not in inventory:
        raise foreign
    receipt_digest = inventory.pop(RECEIPT)
    if (not isinstance(record, dict) or record.get("schema") != RECORD_SCHEMA
            or record.get("bundle") != str(bundle) or record.get("product_code") != PRODUCT_CODE
            or record.get("receipt_sha256") != receipt_digest):
        raise foreign
    listed = {}
    for line in (bundle / RECEIPT).read_bytes().decode("utf-8", "replace").splitlines():
        digest, separator, path = line.partition("  ")
        if not separator or not _digest(digest) or not path:
            raise foreign
        listed[path] = digest
    if not listed or "PackageContents.xml" not in listed or listed != inventory:
        raise foreign
    contents = (bundle / "PackageContents.xml").read_bytes()[:256 * 1024].decode("utf-8", "replace")
    if PRODUCT_CODE not in contents:
        raise foreign
    return listed


def _write_record(record_path, bundle, receipt):
    record_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"schema": RECORD_SCHEMA, "bundle": str(bundle), "product_code": PRODUCT_CODE,
                       "receipt_sha256": hashlib.sha256(receipt).hexdigest()}, indent=2) + "\n"
    descriptor, name = tempfile.mkstemp(prefix=".autocad-bundle-", dir=record_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
        os.replace(name, record_path)
    finally:
        Path(name).unlink(missing_ok=True)


def install_autocad_broker(*, package_root, rows, program_files, user_profile_root,
                           user_plugins_root, machine_plugins_root, state_root):
    """Register every reviewed detected year in one per-user bundle; a result row per year.

    state_root is ArchHub's own per-user state folder; the install record there
    (autocad-bundle.json) is what lets a later run recognise the bundle as ours.
    """
    root, profile = Path(package_root), Path(user_profile_root)
    record_path = Path(state_root) / RECORD_NAME
    plugins, machine = Path(user_plugins_root), Path(machine_plugins_root)
    results, placed = {}, {}
    for year in sorted(rows):
        try:
            placed[year] = _verify_year(root, year, rows[year], program_files)
        except RegistrationRefused as error:
            results[year] = {"host_version": year, "status": "refused", "reason": str(error)}
        except OSError as error:
            results[year] = {"host_version": year, "status": "failed", "reason": _describe(error, None)}
    if not placed:
        return [results[year] for year in sorted(results)]
    bundle = plugins / BUNDLE
    outcome = {"status": "refused", "bundle_path": str(bundle)}
    temporary = retired = None
    try:
        _require_plain(profile, "directory")
        if plugins.name != "ApplicationPlugins" or machine.name != "ApplicationPlugins":
            raise _refuse("registration root leaf must be ApplicationPlugins", plugins)
        if not plugins.is_relative_to(profile) or machine.is_relative_to(profile):
            raise _refuse("user plug-in root must be inside, machine root outside, the profile", plugins)
        years = sorted(placed)
        files = {path: data for year in years for path, data in placed[year]}
        files["PackageContents.xml"] = _package_contents(years)
        wanted = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
        files[RECEIPT] = _receipt(files)
        _check_other_bundles((plugins, machine), bundle)
        if _require_plain(bundle, "directory", may_be_absent=True) is not None:
            if _owned_listing(bundle, record_path) == wanted:
                outcome["status"] = "unchanged_pending_host_restart"
                return _finish(results, placed, outcome)
        plugins.mkdir(parents=True, exist_ok=True)
        _require_plain(plugins, "directory")
        temporary = Path(tempfile.mkdtemp(prefix=".archhub-bundle-", dir=plugins))
        _write_tree(temporary, files)
        if bundle.exists():
            retired = Path(tempfile.mkdtemp(prefix=".archhub-bundle-old-", dir=plugins))
            os.rmdir(retired)
            os.rename(bundle, retired)
        os.rename(temporary, bundle)  # never replaces: fails if another writer placed a bundle
        temporary = None
        outcome["status"] = "registered_pending_host_restart"
        try:
            _write_record(record_path, bundle, files[RECEIPT])
        except OSError as error:
            # Published but unrecorded: a later run will refuse it as not ours.
            outcome.update(status="partial_failure", record_pending=True, reason=_describe(error, record_path))
    except RegistrationRefused as error:
        outcome["reason"] = str(error)
    except OSError as error:
        outcome.update(status="failed", reason=_describe(error, bundle))
        if retired is not None and not bundle.exists():
            try:
                os.rename(retired, bundle)  # the previous verified bundle stays in effect
                retired = None
            except OSError:
                pass
    finally:
        for leftover in (temporary, retired):
            if leftover is not None:
                shutil.rmtree(leftover, ignore_errors=True)
                if leftover.exists():
                    outcome.update(status="partial_failure", cleanup_pending=True)
    return _finish(results, placed, outcome)


def _finish(results, placed, outcome):
    for year in placed:
        results[year] = {"host_version": year, **outcome,
                         "registered": outcome["status"].endswith("_pending_host_restart")}
    return [results[year] for year in sorted(results)]


__all__ = ["BUNDLE", "PRODUCT_CODE", "RECEIPT", "SERIES", "install_autocad_broker"]