# ArchHub — Azure Trusted Signing setup helper.
#
# Runs every Azure CLI command needed to spin up a fresh Trusted Signing
# resource from scratch. Pre-flight: user is signed in to `az`, owns or
# co-owns a subscription, and has passed Microsoft's identity verification
# (individual: $40 one-time, organisation: $359). Identity verification
# is the ONE step that can't be automated — Azure portal click-through.
#
# What this script does (in order):
#
#   1. Verifies `az` is installed + signed in
#   2. Creates / selects the subscription + resource group
#   3. Registers the `Microsoft.CodeSigning` resource provider
#   4. Creates a Trusted Signing account (SKU = Basic, $9.99/mo)
#   5. Creates a Certificate Profile bound to the verified identity
#   6. Creates an Entra service principal scoped to the account
#   7. Prints the 6 env var values to paste into GitHub Actions secrets
#
# Usage:
#   ./scripts/setup_azure_trusted_signing.ps1                        # interactive
#   ./scripts/setup_azure_trusted_signing.ps1 -Subscription <id>     # non-interactive
#
# Idempotent — re-running with the same -ResourceGroup / -AccountName is safe.

[CmdletBinding()]
param(
    [string]$Subscription          = "",
    [string]$ResourceGroup          = "archhub-signing-rg",
    [string]$Location               = "eastus",
    [string]$AccountName            = "archhub-trusted-signing",
    [string]$ProfileName            = "archhub-default-profile",
    [string]$ServicePrincipalName   = "archhub-signing-sp",
    [ValidateSet("PublicTrust", "PrivateTrust", "PublicTrustTest")]
    [string]$ProfileType            = "PublicTrust"
)

$ErrorActionPreference = "Stop"

function Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n] $msg" -ForegroundColor Cyan
}

function Done($msg) {
    Write-Host "    OK $msg" -ForegroundColor Green
}

# ----- 1. Verify az is installed + signed in ---------------------------------
Step 1 "Verifying Azure CLI is installed and signed in"
try {
    $azv = az version --output json 2>$null | ConvertFrom-Json
    Done "az CLI $($azv.'azure-cli')"
} catch {
    Write-Error "Azure CLI not found. Install: winget install -e --id Microsoft.AzureCLI"
    exit 1
}

$account = az account show --output json 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "    Not signed in. Running az login..."
    az login --output none
    $account = az account show --output json | ConvertFrom-Json
}
$signedAs = $account.user.name
$tenantId = $account.tenantId
Done "signed in as $signedAs (tenant $tenantId)"

# ----- 2. Subscription -------------------------------------------------------
if ($Subscription) {
    Step 2 "Switching to subscription $Subscription"
    az account set --subscription $Subscription --output none
    Done "subscription set"
} else {
    Step 2 "Using current subscription: $($account.id) ($($account.name))"
}
$subscriptionId = (az account show --query id -o tsv)

# ----- 3. Register resource provider -----------------------------------------
Step 3 "Registering Microsoft.CodeSigning resource provider"
$rpState = (az provider show --namespace "Microsoft.CodeSigning" --query "registrationState" -o tsv 2>$null)
if ($rpState -ne "Registered") {
    az provider register --namespace "Microsoft.CodeSigning" --output none
    Write-Host "    Registration submitted (can take 1-2 minutes; continuing)..."
} else {
    Done "already registered"
}

# ----- 4. Resource group -----------------------------------------------------
Step 4 "Resource group $ResourceGroup in $Location"
$rgExists = az group exists --name $ResourceGroup
if ($rgExists -eq "true") {
    Done "exists"
} else {
    az group create --name $ResourceGroup --location $Location --output none
    Done "created"
}

# ----- 5. Trusted Signing account -------------------------------------------
Step 5 "Trusted Signing account $AccountName"
$acct = az trustedsigning show -g $ResourceGroup -n $AccountName --output json 2>$null
if ($acct) {
    Done "exists"
} else {
    Write-Host "    Creating (SKU=Basic = `$9.99/mo)..."
    az trustedsigning create `
        --resource-group $ResourceGroup `
        --name $AccountName `
        --location $Location `
        --sku-name Basic `
        --output none
    Done "created"
}

# Endpoint is region-derived. Mapping per Microsoft docs.
$regionEndpointMap = @{
    "eastus"     = "https://eus.codesigning.azure.net"
    "westus"     = "https://wus.codesigning.azure.net"
    "westus2"    = "https://wus2.codesigning.azure.net"
    "westeurope" = "https://weu.codesigning.azure.net"
    "northeurope" = "https://neu.codesigning.azure.net"
    "southeastasia" = "https://sea.codesigning.azure.net"
}
$endpoint = $regionEndpointMap[$Location.ToLower()]
if (-not $endpoint) { $endpoint = "https://$($Location.ToLower()).codesigning.azure.net" }

# ----- 6. Certificate profile (Identity Validation MUST be complete) --------
Step 6 "Certificate profile $ProfileName ($ProfileType)"
Write-Host "    NOTE: this fails until you've completed Identity Validation"
Write-Host "          at https://portal.azure.com/#@/resource/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CodeSigning/codeSigningAccounts/$AccountName/identityValidations"
Write-Host "          Individual: ~`$40 one-time. Organisation: ~`$359 one-time."

$profile = az trustedsigning certificate-profile show `
    -g $ResourceGroup --account-name $AccountName `
    -n $ProfileName --output json 2>$null
if ($profile) {
    Done "exists"
} else {
    Write-Host "    Attempting to create profile (will fail if Identity Validation is not complete)..."
    try {
        az trustedsigning certificate-profile create `
            -g $ResourceGroup `
            --account-name $AccountName `
            -n $ProfileName `
            --profile-type $ProfileType `
            --output none
        Done "created"
    } catch {
        Write-Warning "Certificate profile creation failed. Most likely Identity Validation isn't complete yet. Finish the verification then re-run this script."
    }
}

# ----- 7. Service principal for GitHub Actions ------------------------------
Step 7 "Service principal $ServicePrincipalName for GitHub Actions"
$existing = az ad sp list --display-name $ServicePrincipalName --output json | ConvertFrom-Json
if ($existing.Count -gt 0) {
    Done "exists (re-using app id $($existing[0].appId))"
    $appId = $existing[0].appId
    $newSecret = ""
    Write-Warning "Existing SP found. NOT rotating its secret automatically — re-use the one you saved last time, or delete the SP in the portal and re-run this script to get a fresh secret."
} else {
    $rg = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CodeSigning/codeSigningAccounts/$AccountName"
    Write-Host "    Creating SP with 'Trusted Signing Certificate Profile Signer' role scoped to the account..."
    $sp = az ad sp create-for-rbac `
        --name $ServicePrincipalName `
        --role "Trusted Signing Certificate Profile Signer" `
        --scopes $rg `
        --output json | ConvertFrom-Json
    $appId     = $sp.appId
    $newSecret = $sp.password
    Done "created"
}

# ----- 8. Print the GitHub secrets ------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host " GitHub Actions secrets to paste at:"  -ForegroundColor Yellow
Write-Host " https://github.com/Fargaly/ArchHub/settings/secrets/actions" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "AZURE_TENANT_ID                          = $tenantId"
Write-Host "AZURE_CLIENT_ID                          = $appId"
if ($newSecret) {
    Write-Host "AZURE_CLIENT_SECRET                      = $newSecret"
} else {
    Write-Host "AZURE_CLIENT_SECRET                      = <reuse existing or rotate>"
}
Write-Host "AZURE_TRUSTED_SIGNING_ENDPOINT           = $endpoint"
Write-Host "AZURE_TRUSTED_SIGNING_ACCOUNT_NAME       = $AccountName"
Write-Host "AZURE_TRUSTED_SIGNING_CERT_PROFILE       = $ProfileName"
Write-Host ""
Write-Host "After adding all six, the next tag push (git tag vX.Y.Z) will"
Write-Host "produce a signed installer. Verify locally with:"
Write-Host "  signtool verify /pa /v ArchHub-Setup-X.Y.Z.exe"
Write-Host ""
