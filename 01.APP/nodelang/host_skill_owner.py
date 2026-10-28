"""Inert host packages in one plain owner file, activated by one sealed review (no graph)."""
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import tempfile
import threading
import zipfile

from .universal_cell import InvalidCell

PREFIX = "app:host-package-review:"
SCRIPT_SUFFIXES = {".py", ".js", ".ps1", ".sh", ".exe", ".dll"}
NETWORK = re.compile(r"https?://|\b(?:fetch|requests|urllib|socket|network)\b", re.I)


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _path(value):
    if (type(value) is not str or not value or "\\" in value or ":" in value or "\0" in value
            or PurePosixPath(value).is_absolute() or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise InvalidCell("Package paths must stay inside their bundle")
    if PurePosixPath(value).name.lower() in {".env", "cloud.json"} or value.lower().endswith((".key", ".pem")):
        raise InvalidCell("Credentials belong in the account vault, never a package")
    return value


def _files(values, *, byte_budget: int = 262144):
    if type(values) is not dict or len(values) > 64:
        raise InvalidCell("A package holds at most 64 contained files")
    total = 0
    result = {}
    for name, data in values.items():
        name = _path(name)
        if type(data) is not str:
            raise InvalidCell("Uploaded package files must be UTF-8 text")
        total += len(data.encode())
        if total > byte_budget:
            raise InvalidCell("Package content exceeds 256 KiB")
        result[name] = data
    if len({name.casefold() for name in result}) != len(result):
        raise InvalidCell("Package paths must be unique on every host")
    return result


def _setting(schema, value):
    if schema.get("sensitive") or schema.get("secret"):
        raise InvalidCell("Sensitive settings use the account vault, never this package")
    kind = schema.get("type", "string")
    valid = ((kind == "boolean" and type(value) is bool)
        or (kind == "number" and type(value) in (int, float) and math.isfinite(value))
        or (kind in {"string", "text"} and type(value) is str and len(value) <= 2000))
    if not valid or ("enum" in schema and value not in schema["enum"]):
        raise InvalidCell("Configuration must match the declared type and options")
    if kind == "number":
        limits = [schema.get("min", -math.inf), schema.get("max", math.inf)]
        if any(type(v) not in (int, float) or math.isnan(v) for v in limits) or not limits[0] <= value <= limits[1]:
            raise InvalidCell("Configuration is outside the declared numeric range")
    return value


def _bundle(upload, *, byte_budget: int = 262144, record_budget: int = 524288):
    if type(upload) is not dict or set(upload) != {"name", "base64"}:
        raise InvalidCell("Choose a local MCPB or JSON package")
    if type(upload["name"]) is not str or type(upload["base64"]) is not str or len(upload["base64"]) > record_budget:
        raise InvalidCell("Package upload exceeds its bounded content budget")
    try:
        raw = base64.b64decode(upload["base64"], validate=True)
        if len(raw) > byte_budget:
            raise InvalidCell("Package upload exceeds 256 KiB")
        if upload["name"].lower().endswith(".json"):
            value = json.loads(raw)
            if type(value) is not dict:
                raise InvalidCell("Manifest must be a JSON object")
            manifest, files = value.get("manifest", value), _files(value.get("files", {}))
            files["manifest.json"] = raw.decode("utf-8")
        elif upload["name"].lower().endswith(".mcpb"):
            files = {}
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > 64 or sum(e.file_size for e in entries) > byte_budget:
                    raise InvalidCell("Expanded package exceeds its file or byte budget")
                for entry in entries:
                    if entry.is_dir():
                        _path(entry.filename.rstrip("/"))
                        continue
                    name = _path(entry.filename)
                    if stat.S_ISLNK(entry.external_attr >> 16) or name in files or entry.flag_bits & 1:
                        raise InvalidCell("Linked, encrypted and duplicate package files are refused")
                    files[name] = archive.read(entry).decode("utf-8")
            files = _files(files)
            manifest = json.loads(files["manifest.json"])
        else:
            raise InvalidCell("Choose a local .mcpb or .json package")
    except (ValueError, KeyError, UnicodeError, zipfile.BadZipFile, RuntimeError) as error:
        raise InvalidCell("Package cannot be read as a bounded UTF-8 manifest and files") from error
    if (type(manifest) is not dict or manifest.get("manifest_version") not in {"0.1", "0.2", "0.3"}
            or any(type(manifest.get(k)) is not str or not manifest[k].strip() for k in ("name", "version", "description"))):
        raise InvalidCell("MCPB manifest needs its version, name, package version and description")
    server = manifest.get("server")
    if (type(server) is not dict or server.get("type") not in {"python", "node"}
            or server.get("entry_point") not in files or type(server.get("mcp_config")) is not dict):
        raise InvalidCell("Bundle must contain its declared Python or Node entry point and MCP configuration")
    config = server["mcp_config"]
    if (type(config.get("command")) is not str or not config["command"].strip()
            or type(config.get("args", [])) is not list or any(type(a) is not str for a in config.get("args", []))
            or type(config.get("env", {})) is not dict):
        raise InvalidCell("MCP command, arguments and environment must be declared values")
    if config.get("env"):
        raise InvalidCell("Environment settings require a supported account-vault binding; no literal secrets are stored")
    if re.search(r"omniroute|lov0u", manifest["name"], re.I):
        raise InvalidCell("This connector is unavailable under the existing tool policy")
    tools = manifest.get("tools", [])
    schemas = manifest.get("user_config", {})
    if (type(tools) is not list or len(tools) > 64 or any(
            not (type(t) is str and t.strip() or type(t) is dict and type(t.get("name")) is str and t["name"].strip()) for t in tools)
            or type(schemas) is not dict or len(schemas) > 64):
        raise InvalidCell("Bundle tools and typed settings must be declared")
    values = {}
    for key, schema in schemas.items():
        if type(schema) is not dict or type(key) is not str or not key:
            raise InvalidCell("Configuration entries must be named typed declarations")
        if schema.get("sensitive") or re.search(r"key|token|secret|password", key, re.I):
            raise InvalidCell("Bundle secret settings require a supported account-vault binding")
        kind = schema.get("type", "string")
        values[key] = _setting(schema, schema.get("default", False if kind == "boolean" else 0 if kind == "number" else ""))
    return {"kind":"connector", "manifest":manifest, "files":files}, values


_LOCK = threading.Lock()


class HostSkillOwner:
    """Host packages in one plain owner file, settings/host-packages.json (no graph)."""

    def __init__(self, state_dir, request_id=""):
        self.path = Path(state_dir) / "settings" / "host-packages.json"
        self.request_id = str(request_id or secrets.token_hex(16))
        self.owner = "app:host-packages"

    def _file(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"revision":0, "packages":{}}

    @staticmethod
    def package_files(record):
        return record["package"]["files"]

    def _records(self):
        return list(self._file()["packages"].items())

    def _record(self, root):
        value = self._file()["packages"].get(root)
        if value is None:
            raise InvalidCell("Package is not in this ArchHub")
        return value

    def _save(self, root, value, *, record_budget: int = 524288):
        if len(_encoded(value)) > record_budget:
            raise InvalidCell("Package record exceeds 512 KiB; existing state is unchanged")
        with _LOCK:
            data = self._file()
            data["packages"][root] = value
            data["revision"] += 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=1)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def _import(self, package, settings, *, record_budget: int = 524288):
        digest = _digest(package)
        prior = next((root for root, row in self._records() if row["digest"] == digest), None)
        if prior:
            return self._row(prior, self._record(prior))
        record = {"owner":self.owner, "package":package, "digest":digest, "settings":settings,
            "enabled":False, "installed":False, "audit":None, "proposals":[], "activeDigest":None, "descriptor":None}
        if len(_encoded(record)) > record_budget:
            raise InvalidCell("Package record exceeds 512 KiB")
        root = "app:host-package:" + digest[:24]
        self._save(root, record)
        return self._row(root, record)

    def import_skill(self, value, *, byte_budget: int = 262144):
        import yaml
        if (type(value) is not dict or set(value) - {"host", "name", "text", "files"}
                or type(value.get("host")) is not str or not value["host"].strip() or len(value["host"]) > 128
                or type(value.get("text")) is not str or len(value["text"].encode()) > byte_budget):
            raise InvalidCell("Choose a host and bounded SKILL.md instructions")
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)\Z", value["text"], re.S)
        if not match:
            raise InvalidCell("SKILL.md needs YAML name and description frontmatter")
        try:
            if any(isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(match[1])):
                raise InvalidCell("Skill manifests cannot expand YAML anchors or aliases")
            manifest = yaml.safe_load(match[1])
            _encoded(manifest)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError) as error:
            raise InvalidCell("Skill manifest is invalid YAML") from error
        if (type(manifest) is not dict or any(type(manifest.get(k)) is not str or not manifest[k].strip()
                for k in ("name", "description")) or not match[2].strip()):
            raise InvalidCell("Skill manifest needs name, description and instructions")
        files = _files(value.get("files", {}))
        if "SKILL.md" in files:
            raise InvalidCell("SKILL.md must be supplied exactly once")
        files["SKILL.md"] = value["text"]
        files = _files(files)
        return self._import({"kind":"skill", "manifest":manifest, "host":value["host"], "files":files}, {})

    def inspect(self, upload):
        package, settings = _bundle(upload)
        return self._import(package, settings)

    def _row(self, root, record):
        package, manifest = record["package"], record["package"]["manifest"]
        files = package["files"]
        text = "\n".join(files.values())
        findings = record["audit"]
        return {"id":root, "name":manifest.get("display_name", manifest["name"]), "host":package.get("host", ""),
            "description":re.sub(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", "", files["SKILL.md"], count=1, flags=re.S).strip()
                if package["kind"] == "skill" else manifest["description"],
            "format":"SKILL.md" if package["kind"] == "skill" else "MCPB",
            "digest":record["digest"], "enabled":record["enabled"], "installed":record["installed"],
            "activeDigest":record["activeDigest"], "connected":False,
            "scripts":sorted(name for name in files if PurePosixPath(name).suffix.lower() in SCRIPT_SUFFIXES), "network":bool(NETWORK.search(text)),
            "audit":"Access findings recorded; code not executed" if findings else "Needs access review", "findings":findings,
            "tools":manifest.get("tools", []), "config":[{"key":k, "label":s.get("title", k),
                "type":s.get("type", "string"), "sensitive":False, "value":record["settings"][k]}
                for k, s in manifest.get("user_config", {}).items()],
            "status":"Installed" if record["installed"] else "Ready for review"}

    def read(self):
        records = self._records()
        skills = [self._row(root, row) for root, row in records if row["package"]["kind"] == "skill"]
        bundles = [self._row(root, row) for root, row in records if row["package"]["kind"] == "connector"]
        return {"owner":self.owner, "hostSkills":skills, "connectorBundles":bundles,
            "connectorBundle":bundles[-1] if bundles else None}

    def configure(self, root, key, value):
        record = self._record(root)
        schema = record["package"]["manifest"].get("user_config", {}).get(key)
        if record["package"]["kind"] != "connector" or schema is None:
            raise InvalidCell("Choose a declared bundle setting")
        value = _setting(schema, value)
        if record["settings"][key] != value:
            record["settings"][key] = value
            record.update(installed=False, activeDigest=None)
            self._save(root, record)
        return self._row(root, record)

    def audit(self, root, *, limitations: str = "Static declarations and text findings only; no safety certification or code execution"):
        record = self._record(root)
        row = self._row(root, record)
        record["audit"] = {"digest":_digest(record["package"]), "scripts":row["scripts"],
            "network":row["network"], "license":record["package"]["manifest"].get("license", "Unspecified"),
            "limitations":limitations}
        self._save(root, record)
        return self._row(root, record)

    def _material(self, record):
        return {"package":_digest(record["package"]), "settings":record["settings"]}

    def request(self, root, action):
        record = self._record(root)
        if action not in {"enable", "install"} or (action == "enable") != (record["package"]["kind"] == "skill"):
            raise InvalidCell("Choose the matching package activation")
        if record["digest"] != _digest(record["package"]):
            raise InvalidCell("Package digest changed; import and review the new content")
        if not record["audit"] or record["audit"]["digest"] != record["digest"]:
            self.audit(root)
            record = self._record(root)
        material = self._material(record)
        for proposal in record["proposals"]:
            active = record["enabled" if action == "enable" else "installed"]
            if (proposal["action"] == action and proposal["material"] == material
                    and (proposal["status"] == "pending" or proposal["status"] == "approved" and active)):
                return self.card(proposal["id"])
        identity = PREFIX+_digest([self.owner, root, self.request_id])
        if any(p["id"] == identity for p in record["proposals"]):
            raise InvalidCell("This request identity names a closed approval; use a fresh request")
        record["proposals"].append({"id":identity, "action":action,
            "material":material, "input_digest":_digest(material), "status":"pending"})
        self._save(root, record)
        return self.card(record["proposals"][-1]["id"])

    def set_enabled(self, root, enabled):
        if type(enabled) is not bool:
            raise InvalidCell("Skill enabled must be a boolean")
        if enabled:
            return self.request(root, "enable")
        record = self._record(root)
        if record["package"]["kind"] != "skill":
            raise InvalidCell("Choose a host skill")
        record.update(enabled=False, activeDigest=None)
        for proposal in record["proposals"]:
            if proposal["status"] == "pending":
                proposal["status"] = "declined"
        record["descriptor"] = None
        self._save(root, record)
        return self._row(root, record)

    def _proposal(self, identity):
        for root, record in self._records():
            for proposal in record["proposals"]:
                if proposal["id"] == identity:
                    return root, record, proposal
        raise InvalidCell("Approval is not in this ArchHub")

    def card(self, identity):
        root, record, proposal = self._proposal(identity)
        review = {"status":"pending", "rows":[], "rubric":{}, "events":[]}
        stale = proposal["material"] != self._material(record) or record["digest"] != _digest(record["package"])
        return {**review, "id":identity, "delegation":identity, "work":root, "input_digest":proposal["input_digest"],
            "approvalKind":"hostskills", "kind":"qc", "title":proposal["action"].title()+" "+record["package"]["manifest"]["name"],
            "status":"stale" if stale else review["status"] if proposal["status"] == "pending" else proposal["status"],
            "rows":review["rows"] or [{"element":root, "before":"Disabled; no imported code executed",
                "after":json.dumps({"action":proposal["action"], "digest":record["digest"], "settings":record["settings"],
                    "tools":record["package"]["manifest"].get("tools", []), "server":record["package"]["manifest"].get("server"),
                    "audit":record["audit"]}, ensure_ascii=False)}], "revision":self._file()["revision"]}

    def reviews(self):
        return [self.card(proposal["id"]) for _, record in self._records() for proposal in record["proposals"]]

    def decide(self, identity, digest, decision):
        # The founder decides in his own app; the server admits only his bootstrapped Studio session.
        root, record, proposal = self._proposal(identity)
        if (decision not in {"approve", "deny"} or digest != proposal["input_digest"]
                or digest != _digest(self._material(record)) or record["digest"] != _digest(record["package"])):
            raise InvalidCell("Package or configuration digest changed; review a fresh approval")
        if proposal["status"] == "approved" and decision == "approve":
            return self.card(identity)
        if proposal["status"] != "pending":
            raise InvalidCell("This package approval is closed")
        if decision == "approve":
            descriptor = record["package"]["files"].get("SKILL.md") if proposal["action"] == "enable" else json.dumps(
                {"server":record["package"]["manifest"]["server"], "tools":record["package"]["manifest"].get("tools", []),
                 "settings":record["settings"], "digest":record["digest"]}, ensure_ascii=False)
            # The installed descriptor is runnable data; imported processes remain inert.
            record["enabled" if proposal["action"] == "enable" else "installed"] = True
            record.update(activeDigest=record["digest"], descriptor=descriptor)
        proposal["status"] = "approved" if decision == "approve" else "declined"
        self._save(root, record)
        return self.card(identity)
