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
    if stamp.get("hexversion") == sys.hexversion:
        sys.path[0:0] = [str(folder / "site.zip"), str(folder / "stdlib.zip")]


_use_packed_runtime()
