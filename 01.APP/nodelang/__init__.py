"""File-based ArchHub runtime; importing the package executes no graph."""

def _use_packed_runtime():
    """An agent connector reads its runtime from two zips (03.TOOLS/packaging/pack_runtime.py):
    one file read instead of hundreds, so it answers initialize fast. Only connector processes
    (ARCHHUB_COORDINATION_VENDOR is set by their MCP entry), only for the interpreter they were built for."""
    import json
    import os
    import sys
    from pathlib import Path
    folder = Path(__file__).resolve().parents[1] / "packed"
    # The connector runs from its `-c` loader (client_mcp_installation.LOADER); a governance gate
    # child (a script, same vendor variable) keeps the plain interpreter.
    if (not os.environ.get("ARCHHUB_COORDINATION_VENDOR") or sys.argv[:1] != ["-c"]
            or not (folder / "stamp.json").is_file()):
        return
    try:
        stamp = json.loads((folder / "stamp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        sys.stderr.write("packed runtime ignored: %s\n" % unreadable)
        return
    if stamp.get("hexversion") != sys.hexversion:
        return
    # site.zip must hold exactly what the environment holds (one version of each packed distribution),
    # or the connector would run other code than the app, or mix zip pydantic with venv pydantic_core.
    import site
    installed = {}
    for path in site.getsitepackages():
        try:
            entries = os.listdir(path)
        except OSError:
            continue
        for entry in entries:
            if entry.endswith(".dist-info") and "-" in entry:
                name, version = entry[:-len(".dist-info")].lower().split("-", 1)
                installed.setdefault(name, set()).add(version)
    packed = stamp.get("versions") or {}
    differ = sorted(name for name, version in packed.items() if installed.get(name) != {version})
    if not packed or differ:
        sys.stderr.write("packed runtime ignored: differs from the environment in %s\n" % (differ or "versions"))
        return
    sys.path[0:0] = [str(folder / "site.zip"), str(folder / "stdlib.zip")]


_use_packed_runtime()
