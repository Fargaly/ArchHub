# Code Signing — ArchHub Windows Installer

This doc covers how the ArchHub `ArchHub-Setup-X.Y.Z.exe` is signed, and how to
wire up signing once a certificate is available. The build pipeline is already
set up to sign — it just needs the right secrets configured in GitHub Actions.
Until then, the installer ships unsigned and SmartScreen will warn the user.

## Why we sign

A signed installer changes three things that materially affect installs:

- **SmartScreen.** Unsigned executables get the red "Windows protected your PC"
  dialog where the only path forward is the "More info" link. Signed installers
  start with a yellow warning that fades to no warning as the cert builds
  reputation (EV certs start green, OV/Trusted Signing build reputation over
  the first ~3000 installs).
- **Windows Defender / antivirus.** Unsigned binaries that match generic
  heuristics get flagged or quarantined silently. A signed binary with a valid
  Authenticode chain skips most heuristic checks.
- **Enterprise installs.** Group Policy in most large orgs blocks unsigned
  installers entirely. Without a signature, ArchHub cannot be deployed via
  Intune, SCCM, or any standard managed-device flow.

## The two supported paths

The build script `scripts/sign_installer.ps1` auto-detects which signing path
is configured via environment variables. The selection rule is:

1. If `AZURE_TENANT_ID` is set → **Path A — Azure Trusted Signing**.
2. Else if `ARCHHUB_SIGN_CERT_PATH` is set → **Path B — Classic .pfx**.
3. Else → no signing; build still succeeds (unsigned installer).

If `AZURE_TENANT_ID` is set but any of the other five Azure env vars are
missing, the script aborts with a clear error rather than falling through to
.pfx. Don't half-configure.

---

## Path A — Azure Trusted Signing (recommended)

Microsoft's hosted code-signing service. **$9.99/month**, no hardware token,
no .pfx file to babysit, no annual cert-rotation drill. The cert is short-lived
(72 hours) and Azure rotates it for you; what GitHub Actions hits is a stable
endpoint that proxies the request to the current cert.

This is the right answer for almost everybody now that Microsoft is the one
running it.

**Prerequisites:** an Azure subscription and an Entra ID tenant. If you have a
Microsoft 365 account, you already have Entra. You also need to pass
[Microsoft's identity verification](https://learn.microsoft.com/en-us/azure/trusted-signing/concept-trusted-signing-resources-roles)
— a one-time $40 background check (individual) or $359 (organization).

### Setup walkthrough

1. **Sign in to the Azure portal** at <https://portal.azure.com>.
2. **Create a Trusted Signing account.** Search the top bar for
   *"Trusted Signing Accounts"* → **Create**. Pick a region close to your
   build runner (East US, West Europe, etc. — this is the region that ends
   up in `AZURE_TRUSTED_SIGNING_ENDPOINT`). Set SKU to **Basic**.
3. **Complete identity verification.** Inside the new account, go to
   *Verifications* → **+ New identity verification**. Pick *Individual* or
   *Organization*. Pay the fee. Approval typically takes 1–7 business days.
4. **Create a certificate profile.** Once verification is approved: account →
   *Certificate profiles* → **+ Create**. Profile type is *Public Trust*.
   Subject name auto-populates from the verified identity. Name it something
   memorable (e.g. `archhub-prod`) — this becomes
   `AZURE_TRUSTED_SIGNING_CERT_PROFILE`.
5. **Register an Entra application (service principal).** Top-bar search →
   *App registrations* → **+ New registration**. Name it
   `archhub-codesigning-ci`. Single tenant. No redirect URI. After creation,
   copy the **Application (client) ID** → that's `AZURE_CLIENT_ID`. The
   **Directory (tenant) ID** is `AZURE_TENANT_ID`.
6. **Create a client secret.** Inside the app registration → *Certificates &
   secrets* → **+ New client secret**. 24-month lifetime. Copy the *Value*
   (not the *Secret ID*) **immediately** — Azure shows it once. This is
   `AZURE_CLIENT_SECRET`.
7. **Grant the service principal access to the signing account.** Trusted
   Signing account → *Access control (IAM)* → **+ Add role assignment**.
   Role: **Trusted Signing Certificate Profile Signer**. Assign access to:
   *User, group, or service principal*. Pick the app you just registered.
   **Review + assign.**
8. **Note the endpoint URL.** Trusted Signing account → *Overview* → the
   URI under *Account URI* is `AZURE_TRUSTED_SIGNING_ENDPOINT`. It will look
   like `https://eus.codesigning.azure.net` (the region prefix matches step 2).
9. **Note the account name.** Same Overview blade, the resource name itself
   is `AZURE_TRUSTED_SIGNING_ACCOUNT_NAME`.
10. **Add the six secrets to GitHub Actions.** Repo → *Settings* → *Secrets and
    variables* → *Actions* → **New repository secret**. Paste each of:
    `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
    `AZURE_TRUSTED_SIGNING_ENDPOINT`, `AZURE_TRUSTED_SIGNING_ACCOUNT_NAME`,
    `AZURE_TRUSTED_SIGNING_CERT_PROFILE`. Push a tag and the next release will
    be signed.

### How it works under the hood

`signtool.exe` is invoked with `/dlib Azure.CodeSigning.Dlib.dll /dmdf metadata.json`.
The dlib is a signtool plug-in distributed via NuGet as
`Microsoft.Trusted.Signing.Client`; `sign_installer.ps1` downloads and caches it
on first run. The metadata JSON tells the dlib which endpoint, account, and
cert profile to hit. The dlib authenticates to Azure using the
`AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` env vars (the
`DefaultAzureCredential` chain → `EnvironmentCredential` → client-secret flow).

---

## Path B — Classic EV/OV cert in a .pfx file

If you bought a code-signing certificate from a traditional CA, you'll end up
with a `.pfx` (or `.p12`) file. This is the legacy path; the only reason to
prefer it over Path A is if your org already owns an EV cert and the
hardware-token / cloud-HSM flow is in place.

### Vendor pricing (approximate, late 2025)

| Vendor    | OV (1yr)  | EV (1yr)  | EV (3yr) | Notes                                |
|-----------|-----------|-----------|----------|--------------------------------------|
| SSL.com   | ~$129     | ~$249     | ~$599    | Cloud-HSM option for EV.             |
| Sectigo   | ~$215     | ~$330     | ~$799    | Hardware token by default.           |
| DigiCert  | ~$474     | ~$600     | ~$1500   | Hardware token; cloud option extra.  |
| Certum    | ~$59      | ~$179     | n/a      | Cheapest entry, smaller CA.          |

**EV vs OV:** EV is the only option that triggers instant SmartScreen
reputation (no warning from install #1). OV builds reputation over the first
~3000 installs.

**Hardware token vs cloud HSM:** As of mid-2023 the CA/Browser Forum requires
EV private keys to live in a FIPS 140-2 Level 2 device. That used to mean a
USB token shipped to your house (terrible for CI). Most CAs now offer a cloud
HSM option (SSL.com eSigner, DigiCert KeyLocker, Sectigo Cloud Signing) that
you can call over an API — much better, slightly pricier.

### Setup

1. Buy the cert. Complete validation (OV: phone + DUNS; EV: notarized docs +
   in-person verification).
2. Export the cert as `.pfx` with a strong password. If you got a hardware
   token, you'll instead export the credentials/API key for the cloud-HSM
   bridge — adapt accordingly.
3. Base64-encode the .pfx so it can travel through GitHub Secrets:
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("archhub.pfx")) | Set-Clipboard
   ```
4. Add two GitHub Actions secrets:
   - `ARCHHUB_SIGN_CERT_BASE64` — the base64 string from step 3.
   - `ARCHHUB_SIGN_CERT_PASSWORD` — the .pfx password (omit the secret entirely
     if the .pfx isn't password-protected).
5. Push a tag. The workflow's *Sign installer* step decodes the base64 back to
   a temp file on the runner, sets `ARCHHUB_SIGN_CERT_PATH` to point at it,
   then invokes `sign_installer.ps1` which auto-selects Path B.

For local-dev signing on a workstation with the .pfx sitting on disk, just
set the env vars directly:

```powershell
$env:ARCHHUB_SIGN_CERT_PATH     = "C:\secrets\archhub.pfx"
$env:ARCHHUB_SIGN_CERT_PASSWORD = "..."
.\scripts\build_installer.ps1 -Sign
```

---

## Testing signing locally before pushing a tag

You can dry-run the sign step against an already-built installer without
touching GitHub:

```powershell
# Build first
.\scripts\build_installer.ps1

# Then sign (Path A)
$env:AZURE_TENANT_ID                    = "..."
$env:AZURE_CLIENT_ID                    = "..."
$env:AZURE_CLIENT_SECRET                = "..."
$env:AZURE_TRUSTED_SIGNING_ENDPOINT     = "https://eus.codesigning.azure.net"
$env:AZURE_TRUSTED_SIGNING_ACCOUNT_NAME = "archhub"
$env:AZURE_TRUSTED_SIGNING_CERT_PROFILE = "archhub-prod"
.\scripts\sign_installer.ps1 -InstallerPath ".\dist\ArchHub-Setup-0.16.0.exe"

# Or Path B
$env:ARCHHUB_SIGN_CERT_PATH     = "C:\secrets\archhub.pfx"
$env:ARCHHUB_SIGN_CERT_PASSWORD = "..."
.\scripts\sign_installer.ps1 -InstallerPath ".\dist\ArchHub-Setup-0.16.0.exe"
```

With nothing set, the script logs `unsigned - no signing config` and exits 0,
which is the same behavior CI gets when no secrets are configured.

---

## Verifying a signed installer

```powershell
signtool verify /pa /v .\dist\ArchHub-Setup-0.16.0.exe
```

You should see:

```
SignTool Output: File is signed and trusted.

Successfully verified: .\dist\ArchHub-Setup-0.16.0.exe
```

`/pa` uses the default "Authenticode" policy (required for installers).
`/v` is verbose — prints the cert chain, timestamp, and digest algorithm.

For the timestamp specifically:

```powershell
signtool verify /pa /v /tw .\dist\ArchHub-Setup-0.16.0.exe
```

`/tw` warns (instead of failing) if there's no countersignature. The build
pipeline always timestamps, so any failure here is a real bug.

---

## Timestamp servers

A countersignature (RFC 3161 timestamp) is what lets the binary keep being
trusted after your code-signing cert expires. **Always timestamp.** Pick one
of the following — all are free and public.

| Provider  | URL                                          | Notes                          |
|-----------|----------------------------------------------|--------------------------------|
| DigiCert  | `http://timestamp.digicert.com`              | Default in our scripts.        |
| Sectigo   | `http://timestamp.sectigo.com`               | Reliable fallback.             |
| GlobalSign| `http://timestamp.globalsign.com/tsa/r6advanced1` | Slower but very stable.   |
| Apple     | `http://timestamp.apple.com/ts01`            | Works on Windows too.          |
| Certum    | `http://time.certum.pl`                      | Free, lower reliability.       |

If `timestamp.digicert.com` is down (it does happen), override at call time:

```powershell
.\scripts\sign_installer.ps1 -InstallerPath ... -TimestampUrl "http://timestamp.sectigo.com"
```

---

## Troubleshooting

### `signtool : error : SignerSign() failed.` `(-2147024809 / 0x80070057)`

`E_INVALIDARG`. Most common causes:

- The cert profile name in `AZURE_TRUSTED_SIGNING_CERT_PROFILE` doesn't match
  what's configured in the Azure portal. Names are case-sensitive.
- For Path B: the .pfx password is wrong, or the .pfx contains multiple
  certs and signtool picked the wrong one. Add `/n "Subject Name"` to disambiguate.
- The endpoint URL has a trailing slash or wrong region prefix. Should be
  `https://eus.codesigning.azure.net` exactly — no trailing slash.

### `SignTool Error: No certificates were found that met all the given criteria.`

For Path B: the `/f` path is wrong, the password is wrong, or the .pfx is
corrupt. Re-export from the source store; verify by running
`certutil -dump archhub.pfx` (it'll prompt for the password).

For Path A: this error usually means the dlib couldn't authenticate to Azure.
Check that `AZURE_CLIENT_SECRET` hasn't expired (they default to 24mo) and
that the service principal has the **Trusted Signing Certificate Profile
Signer** role on the account.

### `error: 0x800B010A — A certificate chain processed, but terminated in a root certificate which is not trusted by the trust provider.`

Happens when the cross-cert / intermediate isn't installed on the verifying
machine. Path A handles this automatically (Microsoft's roots are in every
Windows install). For Path B, make sure the .pfx was exported **with the full
chain** — re-export with *"Include all certificates in the certification path"*
checked.

### `error MSB3325: Cannot import the following key file: archhub.pfx`

Not a signtool error — that's MSBuild trying to use the .pfx as a strong-name
key. Ignore; ArchHub doesn't strong-name. If you see this in the sign script
itself, you've set `ARCHHUB_SIGN_CERT_PATH` to a key file that isn't a .pfx.

### `Azure.CodeSigning.Dlib.dll not found after install`

The NuGet download for `Microsoft.Trusted.Signing.Client` failed silently (the
GitHub runner sometimes flakes on the NuGet API). Bump the package version
in `sign_installer.ps1` or rerun the job — usually clears on retry.

### `The specified timestamp server either could not be reached or returned an invalid response.`

The timestamp server is down. Switch to one of the fallbacks listed in the
*Timestamp servers* table above by passing `-TimestampUrl` at invocation
(or set it as a default in `sign_installer.ps1` if the failure is sustained).

### Signature works locally but SmartScreen still warns

Reputation is per-cert, not per-binary. A fresh OV cert needs ~3000 successful
installs before SmartScreen stops warning. EV certs start with reputation from
day one. There's no way to fast-track this; you'll see the warning fade as
download numbers climb.

### Signed binary fails Windows Defender scan

Most likely cause: the installer was compiled with debug symbols that include
strings flagging heuristic scanners. Either strip symbols at compile time (Inno
Setup already does this by default for installer payloads) or submit a
false-positive ticket to Microsoft at <https://www.microsoft.com/wdsi/filesubmission>.
