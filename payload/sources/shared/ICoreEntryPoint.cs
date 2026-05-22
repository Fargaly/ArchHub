// AgDR-0027 — historical placeholder.
//
// The first draft put ICoreEntryPoint + IWorkQueue here so shim and
// Core could share an interface.  That broke type identity (each
// assembly compiled its OWN copy of the interface via <Link>), so
// IsAssignableFrom returned false at runtime and Core was never
// discovered → shim crashed silently → listener never bound.
//
// The fix lives in CoreLoader.cs: bind by NAME ("CoreEntry") and
// invoke via reflection using only BCL types (Func, Action,
// IDictionary).  No shared user-defined types cross the assembly
// boundary, so type identity is irrelevant.
//
// This file is intentionally empty (sans this comment) so existing
// csproj <Link> entries keep working without dragging in stale
// interface types.

namespace ArchHub.Shared
{
    // (no public surface — see header)
}
