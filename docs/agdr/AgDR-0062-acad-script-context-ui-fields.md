---
id: AgDR-0062
timestamp: 2026-09-01T18:55:00Z
agent: claude-code (Fable 5)
session: archhub-application-completion
trigger: /ship-discipline finish the application
status: proposed
category: connectors
projects: [archhub]
---

# AutoCAD script context gains the UIApp / UIDoc fields its wrapper binds

> In the context of making the CAD connector actually read the live
> drawing, facing every `/exec` against AutoCAD dying in the compiler,
> I decided to add two object fields (`UIApp`, `UIDoc`) to
> `AcadMCP.AcadScriptContext`, to match what the SHARED
> `ScriptCompiler.WrapSource` binds for every host, accepting that this
> edits a broker source file (hence this record), because without them
> no AutoCAD script can compile at all.

## The evidence

Every AutoCAD execution failed identically, before running a single
line of user code:

```
error CS1061: 'AcadScriptContext' does not contain a definition for 'UIApp'
error CS1061: 'AcadScriptContext' does not contain a definition for 'UIDoc'
```

`payload/sources/shared/ScriptCompiler.cs` emits this wrapper for every
host it serves:

```csharp
var UIApp = ctx.UIApp;
var UIDoc = ctx.UIDoc;
var Doc   = ctx.Doc;
```

Revit's context carries all three. AutoCAD's carried only `Doc`, so the
generated wrapper could never compile — the connector was structurally
incapable of running anything.

## The change

Five lines in `payload/sources/acad_mcp/AcadMCPApp.cs`: two fields and
the comment that says why they exist. AutoCAD has no application/document
split of Revit's kind, so both mirror the document.

## Consequence

`cad.host_lines` (read line work from the live drawing) becomes possible.
Nothing else changes: no route, no permission, no behaviour of an already
working path.

## Signature

Requires founder sign-off per the broker-source rule. Commit with
`ARCHHUB_ALLOW_CS_EDIT=1` once signed.
