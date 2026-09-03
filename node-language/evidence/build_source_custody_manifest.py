"""Build the deterministic public-source custody manifest.

This is a packaging evidence generator, not semantic authority. It admits only
portable T0 product source and rejects common secret, private-custody, nested
repository, generated-output, and machine-bound path defects before Git
ingestion.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence" / "source-custody-manifest.json"

EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "test-results",
}
EXCLUDED_RELATIVE_PATHS = {
    "evidence/build_current_evidence.py",
    "evidence/current-evidence.json",
    "grand_sweep_ledger.json",
    "grandmap.session.json",
    "self-hosting-map.html",
    "tests_replica/test_authority_coherence.py",
}
EXCLUDED_PREFIXES = {
    "domain_sessions/",
}
DENIED_SUFFIXES = {
    ".db",
    ".dwg",
    ".env",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".rvt",
    ".sqlite",
    ".sqlite3",
}
DENIED_NAMES = {
    "cloud.json",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
}
CLIENT_PROJECT_MARKERS = (
    "BBC" + "4",
    "JPD" + "17",
    "Miss" + "oni",
)
MACHINE_PATH_PATTERN = re.compile(
    r"(?i)(?:[A-Z]:\\"
    + "Users"
    + r"\\[^\\\s]+|/"
    + "Users"
    + r"/[^/\s]+|/"
    + "home"
    + r"/[^/\s]+)"
)
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-" + r"[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"postgres" + r"(?:ql)?://[^\s\"']+"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*"
        r"[\"'][^\"']{8,}[\"']"
    ),
)
TEXT_SUFFIXES = {
    "",
    ".cjs",
    ".css",
    ".html",
    ".iss",
    ".js",
    ".json",
    ".jsonc",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sample",
    ".spec",
    ".txt",
    ".vbs",
}


class CustodyViolation(RuntimeError):
    """The candidate public source contains a denied custody condition."""


def _is_admitted_file(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if path == OUTPUT:
        return False
    relative_text = relative.as_posix()
    if relative_text in EXCLUDED_RELATIVE_PATHS:
        return False
    if any(relative_text.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    return path.is_file()


def _scan_text(relative: str, text: str) -> None:
    is_test_fixture = relative.startswith(
        ("tests/", "tests_domains/", "tests_js/", "tests_replica/")
    )
    if not is_test_fixture and MACHINE_PATH_PATTERN.search(text):
        raise CustodyViolation(f"{relative}: machine-bound user path")
    for marker in CLIENT_PROJECT_MARKERS:
        if marker.lower() in text.lower():
            raise CustodyViolation(f"{relative}: client project marker")
    secret_scan_text = re.sub(
        r"postgres(?:ql)?://fixture\.invalid/[^\s\"']+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    for pattern in SECRET_PATTERNS:
        if pattern.search(secret_scan_text):
            raise CustodyViolation(f"{relative}: secret-like material")


def build_manifest() -> dict:
    entries = []
    for path in sorted(ROOT.rglob("*"), key=lambda item: item.as_posix()):
        if not _is_admitted_file(path):
            continue
        relative = path.relative_to(ROOT).as_posix()
        suffix = path.suffix.lower()
        if suffix in DENIED_SUFFIXES or path.name.lower() in DENIED_NAMES:
            raise CustodyViolation(f"{relative}: denied public-source file")
        content = path.read_bytes()
        if suffix in TEXT_SUFFIXES:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CustodyViolation(f"{relative}: text is not UTF-8") from exc
            _scan_text(relative, text)
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )

    chain = hashlib.sha256()
    for entry in entries:
        chain.update(entry["path"].encode("utf-8"))
        chain.update(b"\0")
        chain.update(entry["sha256"].encode("ascii"))
        chain.update(b"\0")
        chain.update(str(entry["size"]).encode("ascii"))
        chain.update(b"\n")

    return {
        "schema": "archhub.source-custody-manifest.v1",
        "authority": "evidence-only",
        "custody": "T0_PUBLIC",
        "file_count": len(entries),
        "byte_count": sum(entry["size"] for entry in entries),
        "tree_sha256": chain.hexdigest(),
        "files": entries,
    }


def main() -> None:
    manifest = build_manifest()
    OUTPUT.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"{manifest['file_count']} files, {manifest['byte_count']} bytes, "
        f"{manifest['tree_sha256']}"
    )


if __name__ == "__main__":
    main()
