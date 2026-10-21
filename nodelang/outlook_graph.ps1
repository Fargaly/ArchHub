# Physical transport only. Fixed endpoints; category writes are explicit.
# The Microsoft SDK retains tokens in its protected CurrentUser cache, never here.
param([switch]$InteractiveSignIn, [switch]$CategoryAccess)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Emit($value) { $value | ConvertTo-Json -Depth 12 -Compress }
try {
    $request = if ($InteractiveSignIn) { @{operation='connect'} } else { [Console]::In.ReadToEnd() | ConvertFrom-Json }
    $operation = [string]$request.operation
    if ($operation -notin @('prerequisites', 'status', 'connect', 'inbox', 'disconnect', 'categories', 'categorize')) {
        Emit @{ok=$false;state='unsupported';reason='Unsupported operation';out=@()}; exit
    }
    if ($PSVersionTable.PSVersion.Major -lt 7) {
        Emit @{ok=$false;state='dependency-missing';reason='PowerShell 7 is required for Microsoft Graph';out=@()}; exit
    }
    if (-not (Get-Module -ListAvailable Microsoft.Graph.Authentication | Where-Object Version -eq '2.39.0')) {
        Emit @{ok=$false;state='dependency-missing';reason='Install Microsoft.Graph.Authentication 2.39.0 for the current Windows user';out=@()}; exit
    }
    # Passive prerequisite discovery stops before importing the SDK or reading
    # an authentication context. It never signs in or contacts Microsoft.
    if ($operation -eq 'prerequisites') {
        Emit @{ok=$true;state='prerequisites-ready';reason='PowerShell 7 and Microsoft Graph Authentication 2.39.0 are available; sign in explicitly before mailbox work';out=@()}; exit
    }
    Import-Module Microsoft.Graph.Authentication -RequiredVersion 2.39.0
    if ($operation -eq 'connect') {
        if (-not $InteractiveSignIn) {
            Emit @{ok=$false;state='sign-in-required';reason='Use the explicit interactive sign-in window';out=@()}; exit
        }
        # User-facing device flow requires no hidden-window WAM handle and does
        # not change the user's global authentication preferences.
        $WarningPreference = 'Continue'
        $scopes = if ($CategoryAccess) { @('User.Read','Mail.ReadWrite','MailboxSettings.ReadWrite') } else { @('User.Read','Mail.ReadBasic') }
        Connect-MgGraph -Scopes $scopes -ContextScope CurrentUser -Environment Global -UseDeviceCode -NoWelcome -ClientTimeout 120 | Out-Null
    }
    $context = Get-MgContext
    if ($operation -eq 'disconnect') {
        if ($null -ne $context) { Disconnect-MgGraph | Out-Null }
        Emit @{ok=$true;state='disconnected';out=@()}; exit
    }
    if ($null -eq $context) {
        Emit @{ok=$false;state='sign-in-required';reason='Microsoft Graph sign-in required; an IMAP login does not grant access to Outlook category metadata';out=@()}; exit
    }
    if ($context.AuthType -ne 'Delegated' -or $context.Environment -ne 'Global') {
        Emit @{ok=$false;state='unsupported-context';reason='A delegated Global Microsoft mailbox session is required';out=@()}; exit
    }
    if ($operation -eq 'status') {
        Emit @{ok=$true;state='authenticated';account=$context.Account;transport='microsoft-graph';category_consent=('Mail.ReadWrite' -in $context.Scopes -and 'MailboxSettings.ReadWrite' -in $context.Scopes);mailbox_read_verified=$false;out=@()}; exit
    }
    if ('User.Read' -notin $context.Scopes -or -not (@('Mail.ReadBasic','Mail.Read','Mail.ReadWrite') | Where-Object { $_ -in $context.Scopes })) {
        Emit @{ok=$false;state='consent-required';reason='Microsoft consent for User.Read and Mail.ReadBasic is required';out=@()}; exit
    }
    $profile = Invoke-MgGraphRequest -Method GET -Uri 'https://graph.microsoft.com/v1.0/me?$select=id,mail,userPrincipalName' -OutputType PSObject
    $account = if ($profile.mail) { [string]$profile.mail } else { [string]$profile.userPrincipalName }
    if ($operation -eq 'connect') {
        Emit @{ok=$true;state='authenticated';account=$account;account_id=$profile.id;transport='microsoft-graph';mailbox_read_verified=$false;out=@()}; exit
    }
    if (-not $request.account -or ([string]$request.account -ine $account -and [string]$request.account -ine [string]$profile.userPrincipalName)) {
        Emit @{ok=$false;state='account-mismatch';reason='The signed-in mailbox does not match the requested account';out=@()}; exit
    }
    if ($operation -in @('categories','categorize')) {
        if (-not (@('MailboxSettings.Read','MailboxSettings.ReadWrite') | Where-Object { $_ -in $context.Scopes })) {
            Emit @{ok=$false;state='consent-required';reason='Explicit Microsoft category consent is required';out=@()}; exit
        }
        $catalogUri = 'https://graph.microsoft.com/v1.0/me/outlook/masterCategories'
        $catalog = Invoke-MgGraphRequest -Method GET -Uri $catalogUri -OutputType PSObject
        if ($catalog.'@odata.nextLink') {
            Emit @{ok=$false;state='catalog-incomplete';reason='Category catalog exceeds this bounded operation';out=@()}; exit
        }
        if ($operation -eq 'categories') {
            Emit @{ok=$true;state='categories-read';account=$account;out=@($catalog.value | ForEach-Object { @{id=$_.id;name=$_.displayName;color=$_.color} })}; exit
        }
        if (-not $request.message_id -or -not $request.internet_message_id -or $null -eq $request.categories -or $null -eq $request.expected_categories) { throw 'Invalid category request' }
        $itemUri = 'https://graph.microsoft.com/v1.0/me/messages/' + [Uri]::EscapeDataString([string]$request.message_id)
        $selectUri = $itemUri + '?$select=id,internetMessageId,categories,parentFolderId,isRead,changeKey'
        $before = Invoke-MgGraphRequest -Method GET -Uri $selectUri -OutputType PSObject
        if ([string]$before.internetMessageId -cne [string]$request.internet_message_id) {
            Emit @{ok=$false;state='message-mismatch';reason='Internet message identity does not match';out=@()}; exit
        }
        $baseline = @($before.categories | Sort-Object -CaseSensitive)
        $expected = @($request.expected_categories | Sort-Object -CaseSensitive)
        if (($baseline | ConvertTo-Json -Compress) -cne ($expected | ConvertTo-Json -Compress)) {
            Emit @{ok=$false;state='category-conflict';reason='Categories changed since the caller read them';out=@()}; exit
        }
        $missing = @($request.categories | Where-Object { $_ -cnotin @($catalog.value.displayName) })
        if (-not $request.apply) {
            Emit @{ok=$true;state='preview';account=$account;message_id=$before.id;before=@($before.categories);after=@($request.categories);categories_to_create=$missing;out=@()}; exit
        }
        if ('Mail.ReadWrite' -notin $context.Scopes -or 'MailboxSettings.ReadWrite' -notin $context.Scopes) {
            Emit @{ok=$false;state='consent-required';reason='Mail.ReadWrite and MailboxSettings.ReadWrite are required';out=@()}; exit
        }
        $etag = [string]$before.'@odata.etag'
        if (-not $etag) { Emit @{ok=$false;state='version-unavailable';reason='No message version available for a conditional category write';out=@()}; exit }
        foreach ($name in $missing) {
            $body = @{displayName=$name;color='preset0'} | ConvertTo-Json -Compress
            Invoke-MgGraphRequest -Method POST -Uri $catalogUri -Body $body -ContentType 'application/json' | Out-Null
        }
        $body = @{categories=@($request.categories)} | ConvertTo-Json -Compress
        Invoke-MgGraphRequest -Method PATCH -Uri $itemUri -Headers @{'If-Match'=$etag} -Body $body -ContentType 'application/json' | Out-Null
        $after = Invoke-MgGraphRequest -Method GET -Uri $selectUri -OutputType PSObject
        $actual = @($after.categories | Sort-Object -CaseSensitive)
        $wanted = @($request.categories | Sort-Object -CaseSensitive)
        if (($actual | ConvertTo-Json -Compress) -cne ($wanted | ConvertTo-Json -Compress) -or $after.parentFolderId -cne $before.parentFolderId -or $after.isRead -ne $before.isRead -or $after.internetMessageId -cne $before.internetMessageId) {
            Emit @{ok=$false;state='verification-failed';reason='Category write needs reconciliation; do not retry blindly';out=@()}; exit
        }
        Emit @{ok=$true;state='category-write-verified';account=$account;message_id=$after.id;before=@($before.categories);after=@($after.categories);folder_preserved=$true;read_state_preserved=$true;out=@()}; exit
    }
    $count = [int]$request.count
    if ($count -lt 1 -or $count -gt 50) {
        Emit @{ok=$false;state='invalid-count';reason='Inbox count must be from 1 to 50';out=@()}; exit
    }
    $folder = if ($request.folder) { [string]$request.folder } else { 'inbox' }
    if ($folder -notin @('inbox','sentitems')) { throw 'Invalid folder' }
    $uri = 'https://graph.microsoft.com/v1.0/me/mailFolders/' + $folder + '/messages?$select=id,internetMessageId,categories,subject,from,receivedDateTime,isRead&$orderby=receivedDateTime%20desc&$top=' + $count
    $messages = Invoke-MgGraphRequest -Method GET -Uri $uri -OutputType PSObject
    $rows = @($messages.value | ForEach-Object {
        @{id=$_.id;internet_message_id=$_.internetMessageId;categories=@($_.categories);subject=$_.subject;sender=$_.from.emailAddress.name;sender_address=$_.from.emailAddress.address;received=$_.receivedDateTime;unread=(-not $_.isRead)}
    })
    Emit @{ok=$true;state='connected';account=$account;account_id=$profile.id;transport='microsoft-graph';out=$rows;has_more=[bool]$messages.'@odata.nextLink'}
} catch {
    # SDK exceptions can include private data. Do not serialize exception text.
    $state = if ($operation -eq 'categorize' -and $request.apply) { 'write-outcome-unknown' } else { 'request-failed' }
    Emit @{ok=$false;state=$state;reason='Graph request failed; verify account support and consent. Reconcile any attempted write before retrying';out=@()}
}
