# Read-only: copy the Penpot file's token library (W3C DTCG, as Penpot holds it) into the ONE studio
# token file, keeping its $extensions (source + building-block map). Then: npm run build:studio.
# The designer owns Penpot; this never writes to it. Uses the PAT already stored as FTB/penpot.
param([string]$FileId = '751e8d0c-7080-8124-8008-d8e6f6eedbb6', [string]$Penpot = 'http://localhost:9001')
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
$token = [PenpotCredential]::Read('FTB/penpot')
if (-not $token) { throw 'No Penpot credential FTB/penpot on this account.' }
$target = Join-Path $PSScriptRoot '..\..\01.APP\nodelang\studio\design-tokens.json'
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
