"""Provision the run's own unified authority with the product's own provisioning.

Runs in a child process whose environment is the run's (LOCALAPPDATA in the run folder), so the
runtime root, the authority DPAPI provider and the caller key store all land inside the run.
argv: <code root> <specification path> <sha256> <grand map path> <sha256>
"""
import json
import sys
from pathlib import Path

code_root, spec_path, spec_sha, map_path, map_sha = sys.argv[1:6]
sys.path.insert(0, code_root)
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider  # noqa: E402
from nodelang.clean_runtime_bootstrap import provision_clean_runtime  # noqa: E402
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore  # noqa: E402
from nodelang.unified_authority_runtime import default_runtime_root  # noqa: E402

built = provision_clean_runtime(
    default_runtime_root(),
    WindowsDpapiSigningKeyProvider(WindowsDpapiSigningKeyProvider.default_path()),
    WindowsDpapiCallerKeyStore(WindowsDpapiCallerKeyStore.default_path()),
    caller_key_id="founder.bootstrap",
    specification_source=Path(spec_path).read_bytes(), specification_sha256=spec_sha,
    grand_map_source=Path(map_path).read_bytes(), grand_map_sha256=map_sha,
)
try:
    print(json.dumps({"ok": True, "graph_id": built.location.authority.manifest.graph_id,
                      "database": str(built.location.database_path)}))
finally:
    built.location.authority.store.close()
