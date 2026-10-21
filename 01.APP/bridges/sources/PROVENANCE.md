# Host connector source provenance

These existing host connector sources were promoted from the public
[ArchHub repository](https://github.com/Fargaly/ArchHub), revision
`28feccfb2e8dded98fe4bfc7b6903fdff8cb63b0`. Their original paths were under
`payload/sources/`. The source and project bytes are preserved; relative project
references resolve within this directory.

| Original subdirectory | Canonical subdirectory | Contents |
|---|---|---|
| `revit_mcp` | `revit_mcp` | Revit shim, event handler, project and add-in template |
| `revit_mcp_core` | `revit_mcp_core` | Revit core and project |
| `acad_mcp` | `acad_mcp` | AutoCAD connector and project |
| `max_mcp` | `max_mcp` | 3ds Max startup script |
| `shared` | `shared` | Core loader, interface and script compiler |

The three original `build-manifest.json` files are preserved separately as
`legacy-build-evidence/<original-subdirectory>-build-manifest.json`. Their pins
are historical evidence only. They must not participate in current artifact
selection, release approval, deployment verification or readiness decisions.

This promotion includes source only. It does not include a legacy application
manager, MCP server, activation state, installer, compiled host binary or
runtime import from another checkout. Host deployment and runtime access remain
subject to the canonical application's existing owners and admission rules.
The raw legacy execution listeners are not approved for activation by this
source promotion.

See `NOTICE.txt` for the original project license and `BUILD-PROPOSAL.md` for
the unresolved build and deployment prerequisites. Source availability is not
evidence of a supported host version or a loaded connector.

## Committed import (2026-09-24)

The promotion above was written on 2026-09-15 but never committed. The
committed import took the same files from `10.PRODUCT/12.PRODUCTION` at commit
`2ecb61d` (`payload/sources/`, last changed there in `7b81185`); every source
and project file is byte-identical to the promoted copy (line endings aside),
and the three build manifests were then moved to `legacy-build-evidence/` as
described above. Changes after the import are in this repository's history:
the caller check (`shared/BridgeAuth.cs`) and its use in the Revit Core and
AutoCAD listeners, and `/ping` no longer reporting the compiler path.
