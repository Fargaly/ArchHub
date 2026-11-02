# Read-only: copy the Penpot file's token library (W3C DTCG, as Penpot holds it) into the ONE studio
# token file, keeping its $extensions (source + building-block map). Then: npm run build:studio.
# The designer owns Penpot; this never writes to it. Uses the PAT already stored as FTB/penpot.
param([string]$FileId = '751e8d0c-7080-8124-8008-d8e6f6eedbb6', [string]$Penpot = 'http://localhost:9001', [string]$SourceFile = '')
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class PenpotCredential {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  struct CRED { public int Flags; public int Type; public string TargetName; public string Comment; public long LastWritten;
    public int CredentialBlobSize; public IntPtr CredentialBlob; public int Persist; public int AttributeCount; public IntPtr Attributes;
    public string TargetAlias; public string UserName; }
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CredRead(string t, int type, int f, out IntPtr c);
  public static string Read(string t) { IntPtr p; if (!CredRead(t, 1, 0, out p)) return null;
    var c = (CRED)Marshal.PtrToStructure(p, typeof(CRED)); return Marshal.PtrToStringUni(c.CredentialBlob, c.CredentialBlobSize / 2); }
}
'@
$target = Join-Path $PSScriptRoot '..\..\01.APP\nodelang\studio\design-tokens.json'
if ($SourceFile) {
  if (-not (Test-Path -LiteralPath $SourceFile)) { throw "Design token source is missing: $SourceFile" }
  node -e @'
const fs = require("fs");
const [source, target] = process.argv.slice(1);
const lib = JSON.parse(fs.readFileSync(source, "utf8"));
const held = JSON.parse(fs.readFileSync(target, "utf8"));
const meta = (lib.$extensions && lib.$extensions["org.archhub.penpot"]) || {};
const order = meta.tokenSetOrder || [];
if (!order.length) throw new Error("DTCG handoff has no token set order");
const sets = Object.fromEntries(order.map(name => [name, {}]));
const place = (bucket, parts, token) => {
  let cursor = bucket;
  for (const part of parts.slice(0, -1)) cursor = cursor[part] || (cursor[part] = {});
  cursor[parts[parts.length - 1]] = token;
};
const walk = (node, parts) => {
  if (!node || typeof node !== "object" || Array.isArray(node)) return;
  if (Object.prototype.hasOwnProperty.call(node, "$value")) {
    const pen = node.$extensions && node.$extensions["org.archhub.penpot"];
    if (!pen || !sets[pen.set]) throw new Error("Token " + parts.join(".") + " has no known Penpot set");
    const value = Array.isArray(pen.value) ? pen.value.join(" ") : String(pen.value);
    place(sets[pen.set], parts, {$value: value, $type: pen.type || node.$type, $description: node.$description || ""});
    return;
  }
  for (const [key, value] of Object.entries(node)) {
    if (!key.startsWith("$")) walk(value, parts.concat(key));
  }
};
walk(lib, []);
const ext = {...held.$extensions, penpot: {...(held.$extensions && held.$extensions.penpot), fileId: meta.fileId, revn: meta.revision, file: held.$extensions && held.$extensions.penpot && held.$extensions.penpot.file, read: "DTCG handoff grouped into the Penpot token sets compile_studio already reads"}};
const next = {...sets, $metadata: {tokenSetOrder: order, activeThemes: [meta.theme || "ArchHub/Current"], activeSets: meta.activeSets || order}, $extensions: ext};
fs.writeFileSync(target, JSON.stringify(next, null, 1) + "\n");
console.log("design-tokens.json <- DTCG revision " + meta.revision + " (" + meta.tokenCount + " tokens)");
'@ $SourceFile $target
  return
}
$token = [PenpotCredential]::Read('FTB/penpot')
if (-not $token) { throw 'No Penpot credential FTB/penpot on this account.' }
$download = [IO.Path]::GetTempFileName()
try {
  Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 -OutFile $download -Uri "$Penpot/api/rpc/command/get-file?id=$FileId" `
    -Headers @{ Authorization = "Token $token"; Accept = 'application/json' }
  node -e @'
const fs = require('fs'), [file, target] = process.argv.slice(1);
const f = JSON.parse(fs.readFileSync(file, 'utf8')), held = JSON.parse(fs.readFileSync(target, 'utf8'));
const ext = {...held.$extensions, penpot: {...held.$extensions.penpot, fileId: f.id, revn: f.revn, file: f.name}};
const {$themes, ...lib} = f.data.tokensLib; // theme toggles are Penpot UI state; set order lives in $metadata
fs.writeFileSync(target, JSON.stringify({...lib, $extensions: ext}, null, 1) + '\n');
console.log('design-tokens.json <- Penpot revision ' + f.revn);
'@ $download $target
} finally { Remove-Item -LiteralPath $download -ErrorAction SilentlyContinue }
