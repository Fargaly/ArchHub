# Azure Trusted Signing — quickstart for ArchHub

**Goal:** every `git tag vX.Y.Z` push produces a SIGNED installer with no manual work.

**Cost:** $9.99/mo subscription + $40 one-time identity verification.
**Time:** 30-60 min today, ~3-5 business days for identity verification.

## The four steps

### Step 1 — Sign up + identity verification (manual, can't automate)

1. Sign in to <https://portal.azure.com> (any Microsoft account — gmail/outlook works).
2. If you don't have an active subscription, click **Subscriptions → + Add** → "Pay-As-You-Go" (no charges until something is actually used).
3. In the top search bar, type **"Trusted Signing Accounts"** → open the service page → click **Create**.
4. Fill in:
   - **Subscription:** the one from step 2
   - **Resource group:** click "Create new" → `archhub-signing-rg`
   - **Account name:** `archhub-trusted-signing`
   - **Region:** `East US` (cheapest + fastest from most CI runners)
   - **Pricing tier:** **Basic** (`$9.99/mo`, 5,000 signings/month)
5. After creation (~30 s), open the account → **Identity Validations** → **+ Add**.
6. Pick **Individual** (you, solo founder). Fill in legal name + address. Pay $40 with a card.
7. Microsoft emails a verification link within minutes. Click it → upload a photo of your passport/driver's licence → submit.
8. Wait. Most validations clear in **2-5 business days**. You'll get an email titled "Trusted Signing — identity validation complete."

### Step 2 — Install Azure CLI locally (one-time)

```powershell
winget install -e --id Microsoft.AzureCLI
az login
```

Sign in with the same Microsoft account you used in step 1.

### Step 3 — Run the setup helper (this repo)

```powershell
.\scripts\setup_azure_trusted_signing.ps1
```

This is idempotent. Safe to re-run if anything errors mid-way. It:
- Registers the `Microsoft.CodeSigning` resource provider
- Verifies the resource group + Trusted Signing account exist
- Creates a `Certificate Profile` (fails gracefully if step 1 verification isn't complete yet — re-run after it clears)
- Creates an Entra service principal scoped to the account with role **Trusted Signing Certificate Profile Signer**
- Prints the 6 GitHub Actions secret values you need to paste

### Step 4 — Add the 6 secrets to GitHub

The script will print exact values for these. Paste each one at:
<https://github.com/Fargaly/ArchHub/settings/secrets/actions>

| Secret | Source |
|---|---|
| `AZURE_TENANT_ID` | Azure tenant (same for everyone in your org) |
| `AZURE_CLIENT_ID` | Service principal app id |
| `AZURE_CLIENT_SECRET` | Service principal password (only shown ONCE — save it) |
| `AZURE_TRUSTED_SIGNING_ENDPOINT` | `https://eus.codesigning.azure.net` (East US) |
| `AZURE_TRUSTED_SIGNING_ACCOUNT_NAME` | `archhub-trusted-signing` |
| `AZURE_TRUSTED_SIGNING_CERT_PROFILE` | `archhub-default-profile` |

If you lose `AZURE_CLIENT_SECRET`, delete the service principal in the Azure portal (Entra ID → App registrations) and re-run the script — it creates a new one.

## Verify it worked

After all 6 secrets are saved, push a real tag:

```bash
git tag v1.1.1 -m "First signed release"
git push origin v1.1.1
```

The GitHub Action build job logs should show:
```
=== Sign installer ===
Path A: Azure Trusted Signing
signtool sign /dlib ... /v ArchHub-Setup-1.1.1.exe
Successfully signed: ArchHub-Setup-1.1.1.exe
=== Verify signature ===
Successfully verified: ArchHub-Setup-1.1.1.exe
```

Download the asset from the release, right-click → **Properties → Digital Signatures** in Explorer. You'll see:
- **Name of signer:** Ahmed Yasser Fargaly (or whatever name passed identity validation)
- **Algorithm:** sha256RSA
- **Timestamp:** signed time stamp from `http://timestamp.acs.microsoft.com`

## Common pitfalls

- **"Identity not validated"** when running the script → step 1 verification not done yet. Wait + re-run.
- **`signtool` not found in CI** → Windows Image already has it; if you self-host a runner, install the Windows SDK.
- **First few installs still show SmartScreen warning** → Trusted Signing certs **build reputation over the first ~3000 installs**. Yellow warning fades to no warning after that. Cannot be skipped.
- **Setup helper hangs on `az login`** → run `az login --use-device-code` from a separate terminal, then re-run the script.

## What this unlocks

- No more SmartScreen "Windows protected your PC" red panel
- Enterprise IT can deploy ArchHub via Intune / SCCM (signed installer is a hard requirement)
- Windows Defender / Bitdefender / Norton stop flagging the installer as "unknown publisher"
- VCs reviewing your shipping cadence see a real publisher name on each release

## Rotating the service principal

The Entra app secret expires after **2 years** by default. To rotate:

```powershell
az ad sp credential reset --id <appId>
```

Then paste the new password into the `AZURE_CLIENT_SECRET` GitHub secret. Done.

## When this stops mattering

The day you hire your first employee + want to sell to enterprise, upgrade Trusted Signing from `Basic` → `Premium` ($249/mo) for **EV** (Extended Validation) signing. EV starts with **zero SmartScreen warnings on day one** — no reputation-building period. Until then `Basic` is the right call.
