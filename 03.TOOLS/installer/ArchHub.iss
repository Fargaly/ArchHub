; ArchHub installer -- one double-click for a colleague.
;
; It carries the application, fetches Python 3.14.7 from python.org (pinned
; SHA-256, per-user, no PATH change) when the machine has no usable Python,
; and leaves a Start-menu and Desktop entry. It does NOT install the
; Python packages: the FIRST open of either shortcut runs ArchHub.bat, which
; runs colleague_setup.py against requirements.txt (the DESKTOP list; server
; packages are in requirements-cloud.txt and never ship) in a window the
; person can read, installing from the wheelhouse this installer carries, so
; no internet or proxy is needed, and only then opens the application. Saying the installer installed
; them sent colleagues looking for a broken install when the real work had
; simply not run yet.
; Not signed (code-signing is geo-blocked for the founder's region);
; distributed on the firm share. The setup never runs a bare-named program.

#ifndef InstalledManifestPath
#error Build with installer/build_release.ps1: InstalledManifestPath is required.
#endif
#ifndef InstalledManifestSha256
#error Build with installer/build_release.ps1: InstalledManifestSha256 is required.
#endif
#define AppName "ArchHub"
#define AppVersion "0"
; Every build has its own identity even though the beta ships under one label:
; the launcher compares BUILD_ID with the latest release to update quietly.
#ifndef BuildId
#error Build with installer/build_release.ps1: BuildId is required.
#endif
#ifndef RequirementsSha256
#error Build with installer/build_release.ps1: RequirementsSha256 is required.
#endif
#ifndef BuildMetadataPath
#error Build with installer/build_release.ps1: BuildMetadataPath is required.
#endif
#ifndef NodeRuntimePath
#error Build with installer/build_release.ps1: pinned NodeRuntimePath is required.
#endif
#ifndef NodeLicensePath
#error Build with installer/build_release.ps1: NodeLicensePath is required.
#endif
#ifndef GoosePayloadPath
#error Build with installer/build_release.ps1: pinned GoosePayloadPath is required.
#endif
#ifndef BetterleaksPayloadPath
#error Build with installer/build_release.ps1: pinned BetterleaksPayloadPath is required.
#endif
#ifndef CompilerPayloadPath
#error Build with installer/build_release.ps1: verified CompilerPayloadPath is required.
#endif
; Every desktop wheel for CPython 3.14 win_amd64, fetched by build_release.ps1
; from requirements.txt; colleague_setup.py installs from it with --no-index.
#ifndef WheelhousePath
#error Build with installer/build_release.ps1: WheelhousePath is required.
#endif
; The authenticated Revit add-in, compiled per Revit year by
; installer/build_host_bridges.ps1 (bridges/revit|autocad/<year>/ + HOST_ARTIFACTS.json).
; Setup registers a Revit year, and the AutoCAD bundle, only when the build
; carries the broker review (build_release.ps1 -BrokerReviewPath).
#ifndef HostPayloadPath
#error Build with installer/build_release.ps1: HostPayloadPath is required.
#endif
#ifndef PreflightFilesPath
#error Build with installer/build_release.ps1: PreflightFilesPath is required.
#endif
#ifndef PreflightCodePath
#error Build with installer/build_release.ps1: PreflightCodePath is required.
#endif
#define BundledNodeSha256 GetSHA256OfFile(NodeRuntimePath)
#define PayloadExcludes "__pycache__\*,*.pyc,*.pyo,.env,.env.*,*.sqlite3,*.sqlite3-*,*.db,*.db-*,*.key,*.pem"
#define AppPublisher "Fargaly"
; Every shortcut opens ArchHub.vbs: it resolves the installed pythonw itself
; (a bare pythonw fails wherever Python was installed without Add-to-PATH)
; and hands a first run to ArchHub.bat, whose window stays open if setup
; refuses. ArchHub.bat is never a shortcut target.
#define AppExe "ArchHub.vbs"

[Setup]
; The AppId of the install already on every machine (v1.7.0), so Windows
; and Inno treat this as an UPGRADE of that entry -- one ArchHub in
; Apps & Features, same folder -- rather than a second product beside it.
AppId={{B6C0E10F-1F8E-4AAB-9A8F-4F2E3A2C4BAE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\ArchHub
; The folder is fixed: a chooser would let one user aim the launcher at a
; folder another user can write to.
DisableDirPage=yes
DefaultGroupName=ArchHub
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ArchHub-Setup-{#AppVersion}
Compression=lzma2/max
CompressionThreads=1
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
; ArchHub owns its explicit update handoff. Restart Manager must not close
; or restart other applications when this installer runs silently.
CloseApplications=no
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"
; Ticked by default; choosing it is the person's consent (colleague_setup.py reads
; the marker once). Unticked writes no marker, so no assistant setting is touched.
Name: "connectassistants"; Description: "Connect my AI assistants to ArchHub (adds ArchHub's end-of-turn check to Claude Code, Codex and Gemini CLI and the Workshop plugin to OpenCode; your other settings are kept)"; GroupDescription: "Assistants:"

[Files]
Source: "{#InstalledManifestPath}"; DestDir: "{app}"; DestName: "source-manifest.tsv"; Flags: ignoreversion
; Setup preflights assistant connections before replacing application code.
#include PreflightFilesPath
Source: "{#NodeRuntimePath}"; DestDir: "{app}\runtime"; DestName: "node.exe"; Flags: ignoreversion; Check: NodeRuntimeNeedsInstall
Source: "{#NodeLicensePath}"; DestDir: "{app}\runtime"; DestName: "Node-LICENSE.txt"; Flags: ignoreversion
Source: "{#GoosePayloadPath}\*"; DestDir: "{app}\runtime\goose"; Flags: recursesubdirs ignoreversion
Source: "{#BetterleaksPayloadPath}\betterleaks.exe"; DestDir: "{app}\runtime\betterleaks"; DestName: "betterleaks.exe"; Flags: ignoreversion
Source: "{#BetterleaksPayloadPath}\manifest.json"; DestDir: "{app}\runtime\betterleaks"; Flags: ignoreversion
Source: "..\packaging\windows\licenses\Betterleaks-MIT.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\SPEC.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\packaging\windows\licenses\Goose-Apache-2.0.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\packaging\windows\licenses\Hermes-MIT.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\nodelang\*"; DestDir: "{app}\nodelang"; Excludes: "{#PayloadExcludes}"; Flags: recursesubdirs ignoreversion
; The connector runtime packed by packaging\pack_runtime.py: one file read per start, not hundreds.
Source: "..\packed\*"; DestDir: "{app}\packed"; Flags: ignoreversion
Source: "{#CompilerPayloadPath}\archhub-compiler.exe"; DestDir: "{app}\runtime\acompiler"; Flags: ignoreversion
Source: "{#CompilerPayloadPath}\provenance.json"; DestDir: "{app}\runtime\acompiler"; Flags: ignoreversion
Source: "{#CompilerPayloadPath}\rules.json"; DestDir: "{app}\runtime\acompiler"; Flags: ignoreversion
Source: "{#CompilerPayloadPath}\NOTICE"; DestDir: "{app}\runtime\acompiler"; Flags: ignoreversion
Source: "{#CompilerPayloadPath}\LICENSES.txt"; DestDir: "{app}\runtime\acompiler"; Flags: ignoreversion
Source: "..\tools\__init__.py"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\tools\ratchet.py"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\tools\pipeline\__init__.py"; DestDir: "{app}\tools\pipeline"; Flags: ignoreversion
Source: "..\tools\pipeline\strict_check.py"; DestDir: "{app}\tools\pipeline"; Flags: ignoreversion
Source: "..\tools\pipeline\pre_commit.py"; DestDir: "{app}\tools\pipeline"; Flags: ignoreversion
Source: "..\tools\pipeline\install_hooks.py"; DestDir: "{app}\tools\pipeline"; Flags: ignoreversion
Source: "..\tools\pipeline\record_observation.py"; DestDir: "{app}\tools\pipeline"; Flags: ignoreversion
Source: "..\tools\pipeline\build.py"; DestDir: "{app}\tools\pipeline"; Flags: ignoreversion
Source: "..\tools\pipeline\land.py"; DestDir: "{app}\tools\pipeline"; Flags: ignoreversion
; The graph owner task is re-registered from the installed copy (RefreshCleanCoordinationTask).
; Generated once for this exact build; pairs with BUILD_ID after installation.
Source: "{#BuildMetadataPath}"; DestDir: "{app}"; DestName: "BUILD_METADATA.json"; Flags: ignoreversion
; Public credential-store code only. Every user's protected data stays local.
Source: "..\app\secrets_store.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\credential_lock.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\__init__.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\packaging\windows\licenses\ArchHub-components-MIT.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\bridges\rhino\archhub_mcp.py"; DestDir: "{app}\bridges\rhino"; Flags: ignoreversion
Source: "..\bridges\blender\archhub_mcp\__init__.py"; DestDir: "{app}\bridges\blender\archhub_mcp"; Flags: ignoreversion
Source: "..\bridges\sources\max_mcp\max_mcp_startup.py"; DestDir: "{app}\bridges\max"; Flags: ignoreversion
; Compiled add-in closure per Revit / AutoCAD year the build machine carries; none when it carries none.
Source: "{#HostPayloadPath}\bridges\revit\*"; DestDir: "{app}\bridges\revit"; Flags: recursesubdirs createallsubdirs ignoreversion skipifsourcedoesntexist
Source: "{#HostPayloadPath}\bridges\autocad\*"; DestDir: "{app}\bridges\autocad"; Flags: recursesubdirs createallsubdirs ignoreversion skipifsourcedoesntexist
Source: "{#HostPayloadPath}\HOST_ARTIFACTS.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\colleague_setup.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#WheelhousePath}\*.whl"; DestDir: "{app}\wheelhouse"; Flags: ignoreversion
Source: "ArchHub.bat"; DestDir: "{app}"; Flags: ignoreversion
; Replaces the previous launcher of the same name. User state is preserved;
; product code is reconciled against the build manifest after copying.
Source: "ArchHub.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\archhub.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\nodelang\studio\atlas-cockpit.jsx"
Type: files; Name: "{app}\nodelang\studio\atlas-engine.jsx"
Type: files; Name: "{app}\nodelang\studio\atlas-panels.jsx"
Type: files; Name: "{app}\nodelang\studio\atlas-runtime.jsx"
Type: files; Name: "{app}\nodelang\studio\atlas-side.jsx"
Type: files; Name: "{app}\nodelang\studio\brain-model.jsx"
Type: files; Name: "{app}\nodelang\studio\cockpit-core.jsx"
Type: files; Name: "{app}\nodelang\studio\design-canvas.jsx"
Type: files; Name: "{app}\nodelang\studio\hub-kit.jsx"
Type: files; Name: "{app}\nodelang\studio\mount.jsx"
Type: files; Name: "{app}\nodelang\studio\node-registry.jsx"
Type: files; Name: "{app}\nodelang\studio\param-types.jsx"
Type: files; Name: "{app}\nodelang\studio\shared-data.jsx"
Type: files; Name: "{app}\nodelang\studio\studio-account.jsx"
Type: files; Name: "{app}\nodelang\studio\studio-lm.jsx"
Type: files; Name: "{app}\nodelang\studio\studio-mobile.jsx"
Type: files; Name: "{app}\nodelang\studio\studio-params.jsx"
Type: files; Name: "{app}\nodelang\studio\studio-suite.jsx"
Type: files; Name: "{app}\nodelang\studio\studio-workshop.jsx"
Type: files; Name: "{app}\nodelang\studio\workshop-board.jsx"
Type: files; Name: "{app}\nodelang\studio\compiled\design-canvas.js"
Type: files; Name: "{app}\nodelang\studio\compiled\shared-data.js"
Type: files; Name: "{app}\nodelang\studio\compiled\studio-suite.js"
Type: files; Name: "{app}\nodelang\studio\compiled\param-types.js"
Type: files; Name: "{app}\nodelang\studio\compiled\studio-params.js"
Type: files; Name: "{app}\nodelang\studio\compiled\studio-mobile.js"
Type: files; Name: "{app}\nodelang\studio\compiled\studio-account.js"
Type: files; Name: "{app}\nodelang\studio\compiled\node-registry.js"
Type: files; Name: "{app}\nodelang\studio\compiled\brain-model.js"
Type: files; Name: "{app}\nodelang\studio\compiled\workshop-board.js"
Type: files; Name: "{app}\nodelang\studio\compiled\studio-workshop.js"
Type: files; Name: "{app}\nodelang\studio\compiled\studio-lm.js"
Type: files; Name: "{app}\nodelang\studio\compiled\mount.js"
Type: files; Name: "{app}\launch_archhub_test.py"
; Retired launchers target app/main.py; supported shortcuts use ArchHub.vbs.
Type: files; Name: "{app}\ArchHub.cmd"
Type: files; Name: "{app}\ArchHub-silent.cmd"
; Superseded installer helpers recreate those retired app/main.py launchers.
; The supported package owns setup and shortcuts directly; no directory sweep.
Type: files; Name: "{app}\installer\install_gui.ps1"
Type: files; Name: "{app}\installer\make_shortcuts.ps1"
Type: files; Name: "{app}\installer\setup.iss"
; Retire the replaced graph website runtime alongside its static exporter.
; unused legacy marketing builder when upgrading an existing installation.
Type: files; Name: "{app}\nodelang\website.py"
Type: files; Name: "{app}\nodelang\website.pyc"
Type: files; Name: "{app}\nodelang\website.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\website.*.pyc"
Type: files; Name: "{app}\nodelang\website_docs_text.py"
Type: files; Name: "{app}\nodelang\website_docs_text.pyc"
Type: files; Name: "{app}\nodelang\website_docs_text.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\website_docs_text.*.pyc"
; Exact retired implementation only. Keep the current connector owner,
; credentials, databases and unrelated installed files intact on upgrade.
Type: files; Name: "{app}\nodelang\cell_baboom_connector_execution.py"
Type: files; Name: "{app}\nodelang\cell_baboom_connector_execution.pyc"
Type: files; Name: "{app}\nodelang\cell_baboom_connector_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_baboom_connector_execution.*.pyc"
; GRAPHOUT: exact retired product code only; no state or journal paths.
Type: files; Name: "{app}\nodelang\agent_session_catalogue.py"
Type: files; Name: "{app}\nodelang\agent_session_catalogue.pyc"
Type: files; Name: "{app}\nodelang\agent_session_catalogue.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\agent_session_catalogue.*.pyc"
Type: files; Name: "{app}\nodelang\app_brain.py"
Type: files; Name: "{app}\nodelang\app_brain.pyc"
Type: files; Name: "{app}\nodelang\app_brain.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\app_brain.*.pyc"
Type: files; Name: "{app}\nodelang\application.py"
Type: files; Name: "{app}\nodelang\application.pyc"
Type: files; Name: "{app}\nodelang\application.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application.*.pyc"
Type: files; Name: "{app}\nodelang\application_machine_transport.py"
Type: files; Name: "{app}\nodelang\application_machine_transport.pyc"
Type: files; Name: "{app}\nodelang\application_machine_transport.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_machine_transport.*.pyc"
Type: files; Name: "{app}\nodelang\application_policy_binding.py"
Type: files; Name: "{app}\nodelang\application_policy_binding.pyc"
Type: files; Name: "{app}\nodelang\application_policy_binding.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_policy_binding.*.pyc"
Type: files; Name: "{app}\nodelang\application_policy_compiler.py"
Type: files; Name: "{app}\nodelang\application_policy_compiler.pyc"
Type: files; Name: "{app}\nodelang\application_policy_compiler.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_policy_compiler.*.pyc"
Type: files; Name: "{app}\nodelang\application_policy_context.py"
Type: files; Name: "{app}\nodelang\application_policy_context.pyc"
Type: files; Name: "{app}\nodelang\application_policy_context.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_policy_context.*.pyc"
Type: files; Name: "{app}\nodelang\application_recovery.py"
Type: files; Name: "{app}\nodelang\application_recovery.pyc"
Type: files; Name: "{app}\nodelang\application_recovery.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_recovery.*.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_close.py"
Type: files; Name: "{app}\nodelang\application_recovery_close.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_close.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_recovery_close.*.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_files.py"
Type: files; Name: "{app}\nodelang\application_recovery_files.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_files.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_recovery_files.*.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_restore.py"
Type: files; Name: "{app}\nodelang\application_recovery_restore.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_restore.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_recovery_restore.*.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_restore_files.py"
Type: files; Name: "{app}\nodelang\application_recovery_restore_files.pyc"
Type: files; Name: "{app}\nodelang\application_recovery_restore_files.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_recovery_restore_files.*.pyc"
Type: files; Name: "{app}\nodelang\application_server.py"
Type: files; Name: "{app}\nodelang\application_server.pyc"
Type: files; Name: "{app}\nodelang\application_server.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_server.*.pyc"
Type: files; Name: "{app}\nodelang\application_update_recovery.py"
Type: files; Name: "{app}\nodelang\application_update_recovery.pyc"
Type: files; Name: "{app}\nodelang\application_update_recovery.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\application_update_recovery.*.pyc"
Type: files; Name: "{app}\nodelang\artifact_verification_court.py"
Type: files; Name: "{app}\nodelang\artifact_verification_court.pyc"
Type: files; Name: "{app}\nodelang\artifact_verification_court.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\artifact_verification_court.*.pyc"
Type: files; Name: "{app}\nodelang\authority_adoption.py"
Type: files; Name: "{app}\nodelang\authority_adoption.pyc"
Type: files; Name: "{app}\nodelang\authority_adoption.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\authority_adoption.*.pyc"
Type: files; Name: "{app}\nodelang\baboom_agent_link.py"
Type: files; Name: "{app}\nodelang\baboom_agent_link.pyc"
Type: files; Name: "{app}\nodelang\baboom_agent_link.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\baboom_agent_link.*.pyc"
Type: files; Name: "{app}\nodelang\baboom_owner_grants.py"
Type: files; Name: "{app}\nodelang\baboom_owner_grants.pyc"
Type: files; Name: "{app}\nodelang\baboom_owner_grants.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\baboom_owner_grants.*.pyc"
Type: files; Name: "{app}\nodelang\baboom_session_interrupt.py"
Type: files; Name: "{app}\nodelang\baboom_session_interrupt.pyc"
Type: files; Name: "{app}\nodelang\baboom_session_interrupt.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\baboom_session_interrupt.*.pyc"
Type: files; Name: "{app}\nodelang\backup_retention.py"
Type: files; Name: "{app}\nodelang\backup_retention.pyc"
Type: files; Name: "{app}\nodelang\backup_retention.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\backup_retention.*.pyc"
Type: files; Name: "{app}\nodelang\brain_cloud_runner.py"
Type: files; Name: "{app}\nodelang\brain_cloud_runner.pyc"
Type: files; Name: "{app}\nodelang\brain_cloud_runner.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\brain_cloud_runner.*.pyc"
Type: files; Name: "{app}\nodelang\brain_cloud_sync.py"
Type: files; Name: "{app}\nodelang\brain_cloud_sync.pyc"
Type: files; Name: "{app}\nodelang\brain_cloud_sync.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\brain_cloud_sync.*.pyc"
Type: files; Name: "{app}\nodelang\brain_community_sync.py"
Type: files; Name: "{app}\nodelang\brain_community_sync.pyc"
Type: files; Name: "{app}\nodelang\brain_community_sync.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\brain_community_sync.*.pyc"
Type: files; Name: "{app}\nodelang\brain_store_port.py"
Type: files; Name: "{app}\nodelang\brain_store_port.pyc"
Type: files; Name: "{app}\nodelang\brain_store_port.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\brain_store_port.*.pyc"
Type: files; Name: "{app}\nodelang\browser_graph_editor_court.cjs"
Type: files; Name: "{app}\nodelang\browser_publish_court.py"
Type: files; Name: "{app}\nodelang\browser_publish_court.pyc"
Type: files; Name: "{app}\nodelang\browser_publish_court.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\browser_publish_court.*.pyc"
Type: files; Name: "{app}\nodelang\browser_scope_locality_court.py"
Type: files; Name: "{app}\nodelang\browser_scope_locality_court.pyc"
Type: files; Name: "{app}\nodelang\browser_scope_locality_court.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\browser_scope_locality_court.*.pyc"
Type: files; Name: "{app}\nodelang\canvas.html"
Type: files; Name: "{app}\nodelang\canvas_graph_owner.py"
Type: files; Name: "{app}\nodelang\canvas_graph_owner.pyc"
Type: files; Name: "{app}\nodelang\canvas_graph_owner.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\canvas_graph_owner.*.pyc"
Type: files; Name: "{app}\nodelang\canvas_placement.py"
Type: files; Name: "{app}\nodelang\canvas_placement.pyc"
Type: files; Name: "{app}\nodelang\canvas_placement.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\canvas_placement.*.pyc"
Type: files; Name: "{app}\nodelang\capabilities.py"
Type: files; Name: "{app}\nodelang\capabilities.pyc"
Type: files; Name: "{app}\nodelang\capabilities.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\capabilities.*.pyc"
Type: files; Name: "{app}\nodelang\cde_operational_storage.py"
Type: files; Name: "{app}\nodelang\cde_operational_storage.pyc"
Type: files; Name: "{app}\nodelang\cde_operational_storage.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cde_operational_storage.*.pyc"
Type: files; Name: "{app}\nodelang\cde_overlay.py"
Type: files; Name: "{app}\nodelang\cde_overlay.pyc"
Type: files; Name: "{app}\nodelang\cde_overlay.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cde_overlay.*.pyc"
Type: files; Name: "{app}\nodelang\cell_accessibility.py"
Type: files; Name: "{app}\nodelang\cell_accessibility.pyc"
Type: files; Name: "{app}\nodelang\cell_accessibility.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_accessibility.*.pyc"
Type: files; Name: "{app}\nodelang\cell_accounts.py"
Type: files; Name: "{app}\nodelang\cell_accounts.pyc"
Type: files; Name: "{app}\nodelang\cell_accounts.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_accounts.*.pyc"
Type: files; Name: "{app}\nodelang\cell_activity.py"
Type: files; Name: "{app}\nodelang\cell_activity.pyc"
Type: files; Name: "{app}\nodelang\cell_activity.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_activity.*.pyc"
Type: files; Name: "{app}\nodelang\cell_adapters.py"
Type: files; Name: "{app}\nodelang\cell_adapters.pyc"
Type: files; Name: "{app}\nodelang\cell_adapters.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_adapters.*.pyc"
Type: files; Name: "{app}\nodelang\cell_agent_body.py"
Type: files; Name: "{app}\nodelang\cell_agent_body.pyc"
Type: files; Name: "{app}\nodelang\cell_agent_body.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_agent_body.*.pyc"
Type: files; Name: "{app}\nodelang\cell_agent_body_catalog.py"
Type: files; Name: "{app}\nodelang\cell_agent_body_catalog.pyc"
Type: files; Name: "{app}\nodelang\cell_agent_body_catalog.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_agent_body_catalog.*.pyc"
Type: files; Name: "{app}\nodelang\cell_agent_cognition.py"
Type: files; Name: "{app}\nodelang\cell_agent_cognition.pyc"
Type: files; Name: "{app}\nodelang\cell_agent_cognition.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_agent_cognition.*.pyc"
Type: files; Name: "{app}\nodelang\cell_application_ui.py"
Type: files; Name: "{app}\nodelang\cell_application_ui.pyc"
Type: files; Name: "{app}\nodelang\cell_application_ui.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_application_ui.*.pyc"
Type: files; Name: "{app}\nodelang\cell_attention.py"
Type: files; Name: "{app}\nodelang\cell_attention.pyc"
Type: files; Name: "{app}\nodelang\cell_attention.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_attention.*.pyc"
Type: files; Name: "{app}\nodelang\cell_attestations.py"
Type: files; Name: "{app}\nodelang\cell_attestations.pyc"
Type: files; Name: "{app}\nodelang\cell_attestations.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_attestations.*.pyc"
Type: files; Name: "{app}\nodelang\cell_authority_view.py"
Type: files; Name: "{app}\nodelang\cell_authority_view.pyc"
Type: files; Name: "{app}\nodelang\cell_authority_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_authority_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_authorization.py"
Type: files; Name: "{app}\nodelang\cell_authorization.pyc"
Type: files; Name: "{app}\nodelang\cell_authorization.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_authorization.*.pyc"
Type: files; Name: "{app}\nodelang\cell_baboom_meeting_note_publication.py"
Type: files; Name: "{app}\nodelang\cell_baboom_meeting_note_publication.pyc"
Type: files; Name: "{app}\nodelang\cell_baboom_meeting_note_publication.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_baboom_meeting_note_publication.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_community.py"
Type: files; Name: "{app}\nodelang\cell_brain_community.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_community.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_community.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_explorer.py"
Type: files; Name: "{app}\nodelang\cell_brain_explorer.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_explorer.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_explorer.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_governance.py"
Type: files; Name: "{app}\nodelang\cell_brain_governance.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_governance.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_governance.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_groups.py"
Type: files; Name: "{app}\nodelang\cell_brain_groups.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_groups.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_groups.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_legacy_import.py"
Type: files; Name: "{app}\nodelang\cell_brain_legacy_import.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_legacy_import.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_legacy_import.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_memory.py"
Type: files; Name: "{app}\nodelang\cell_brain_memory.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_memory.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_memory.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_ownership.py"
Type: files; Name: "{app}\nodelang\cell_brain_ownership.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_ownership.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_ownership.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_recall.py"
Type: files; Name: "{app}\nodelang\cell_brain_recall.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_recall.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_recall.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_reflexion.py"
Type: files; Name: "{app}\nodelang\cell_brain_reflexion.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_reflexion.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_reflexion.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_secrets.py"
Type: files; Name: "{app}\nodelang\cell_brain_secrets.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_secrets.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_secrets.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_skills.py"
Type: files; Name: "{app}\nodelang\cell_brain_skills.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_skills.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_skills.*.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_sync.py"
Type: files; Name: "{app}\nodelang\cell_brain_sync.pyc"
Type: files; Name: "{app}\nodelang\cell_brain_sync.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_brain_sync.*.pyc"
Type: files; Name: "{app}\nodelang\cell_browser_sessions.py"
Type: files; Name: "{app}\nodelang\cell_browser_sessions.pyc"
Type: files; Name: "{app}\nodelang\cell_browser_sessions.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_browser_sessions.*.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_card_view.py"
Type: files; Name: "{app}\nodelang\cell_canvas_card_view.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_card_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_canvas_card_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_heading_view.py"
Type: files; Name: "{app}\nodelang\cell_canvas_heading_view.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_heading_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_canvas_heading_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_interaction_policy.py"
Type: files; Name: "{app}\nodelang\cell_canvas_interaction_policy.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_interaction_policy.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_canvas_interaction_policy.*.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_port_view.py"
Type: files; Name: "{app}\nodelang\cell_canvas_port_view.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_port_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_canvas_port_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_toolbar_view.py"
Type: files; Name: "{app}\nodelang\cell_canvas_toolbar_view.pyc"
Type: files; Name: "{app}\nodelang\cell_canvas_toolbar_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_canvas_toolbar_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_capabilities.py"
Type: files; Name: "{app}\nodelang\cell_capabilities.pyc"
Type: files; Name: "{app}\nodelang\cell_capabilities.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_capabilities.*.pyc"
Type: files; Name: "{app}\nodelang\cell_catalog.py"
Type: files; Name: "{app}\nodelang\cell_catalog.pyc"
Type: files; Name: "{app}\nodelang\cell_catalog.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_catalog.*.pyc"
Type: files; Name: "{app}\nodelang\cell_cde_authority.py"
Type: files; Name: "{app}\nodelang\cell_cde_authority.pyc"
Type: files; Name: "{app}\nodelang\cell_cde_authority.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_cde_authority.*.pyc"
Type: files; Name: "{app}\nodelang\cell_change_history.py"
Type: files; Name: "{app}\nodelang\cell_change_history.pyc"
Type: files; Name: "{app}\nodelang\cell_change_history.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_change_history.*.pyc"
Type: files; Name: "{app}\nodelang\cell_cloud_gate.py"
Type: files; Name: "{app}\nodelang\cell_cloud_gate.pyc"
Type: files; Name: "{app}\nodelang\cell_cloud_gate.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_cloud_gate.*.pyc"
Type: files; Name: "{app}\nodelang\cell_cloud_routes.py"
Type: files; Name: "{app}\nodelang\cell_cloud_routes.pyc"
Type: files; Name: "{app}\nodelang\cell_cloud_routes.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_cloud_routes.*.pyc"
Type: files; Name: "{app}\nodelang\cell_cloud_sessions.py"
Type: files; Name: "{app}\nodelang\cell_cloud_sessions.pyc"
Type: files; Name: "{app}\nodelang\cell_cloud_sessions.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_cloud_sessions.*.pyc"
Type: files; Name: "{app}\nodelang\cell_compliance.py"
Type: files; Name: "{app}\nodelang\cell_compliance.pyc"
Type: files; Name: "{app}\nodelang\cell_compliance.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_compliance.*.pyc"
Type: files; Name: "{app}\nodelang\cell_composer.py"
Type: files; Name: "{app}\nodelang\cell_composer.pyc"
Type: files; Name: "{app}\nodelang\cell_composer.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_composer.*.pyc"
Type: files; Name: "{app}\nodelang\cell_connector_execution.py"
Type: files; Name: "{app}\nodelang\cell_connector_execution.pyc"
Type: files; Name: "{app}\nodelang\cell_connector_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_connector_execution.*.pyc"
Type: files; Name: "{app}\nodelang\cell_content_descriptors.py"
Type: files; Name: "{app}\nodelang\cell_content_descriptors.pyc"
Type: files; Name: "{app}\nodelang\cell_content_descriptors.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_content_descriptors.*.pyc"
Type: files; Name: "{app}\nodelang\cell_control_bindings.py"
Type: files; Name: "{app}\nodelang\cell_control_bindings.pyc"
Type: files; Name: "{app}\nodelang\cell_control_bindings.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_control_bindings.*.pyc"
Type: files; Name: "{app}\nodelang\cell_control_presentations.py"
Type: files; Name: "{app}\nodelang\cell_control_presentations.pyc"
Type: files; Name: "{app}\nodelang\cell_control_presentations.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_control_presentations.*.pyc"
Type: files; Name: "{app}\nodelang\cell_control_view.py"
Type: files; Name: "{app}\nodelang\cell_control_view.pyc"
Type: files; Name: "{app}\nodelang\cell_control_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_control_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_core_values.py"
Type: files; Name: "{app}\nodelang\cell_core_values.pyc"
Type: files; Name: "{app}\nodelang\cell_core_values.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_core_values.*.pyc"
Type: files; Name: "{app}\nodelang\cell_deliberation.py"
Type: files; Name: "{app}\nodelang\cell_deliberation.pyc"
Type: files; Name: "{app}\nodelang\cell_deliberation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_deliberation.*.pyc"
Type: files; Name: "{app}\nodelang\cell_design_tokens.py"
Type: files; Name: "{app}\nodelang\cell_design_tokens.pyc"
Type: files; Name: "{app}\nodelang\cell_design_tokens.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_design_tokens.*.pyc"
Type: files; Name: "{app}\nodelang\cell_device_custody.py"
Type: files; Name: "{app}\nodelang\cell_device_custody.pyc"
Type: files; Name: "{app}\nodelang\cell_device_custody.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_device_custody.*.pyc"
Type: files; Name: "{app}\nodelang\cell_device_enrollment.py"
Type: files; Name: "{app}\nodelang\cell_device_enrollment.pyc"
Type: files; Name: "{app}\nodelang\cell_device_enrollment.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_device_enrollment.*.pyc"
Type: files; Name: "{app}\nodelang\cell_device_keys.py"
Type: files; Name: "{app}\nodelang\cell_device_keys.pyc"
Type: files; Name: "{app}\nodelang\cell_device_keys.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_device_keys.*.pyc"
Type: files; Name: "{app}\nodelang\cell_device_pairing.py"
Type: files; Name: "{app}\nodelang\cell_device_pairing.pyc"
Type: files; Name: "{app}\nodelang\cell_device_pairing.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_device_pairing.*.pyc"
Type: files; Name: "{app}\nodelang\cell_domain_catalog.py"
Type: files; Name: "{app}\nodelang\cell_domain_catalog.pyc"
Type: files; Name: "{app}\nodelang\cell_domain_catalog.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_domain_catalog.*.pyc"
Type: files; Name: "{app}\nodelang\cell_dpop.py"
Type: files; Name: "{app}\nodelang\cell_dpop.pyc"
Type: files; Name: "{app}\nodelang\cell_dpop.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_dpop.*.pyc"
Type: files; Name: "{app}\nodelang\cell_dpop_nonce.py"
Type: files; Name: "{app}\nodelang\cell_dpop_nonce.pyc"
Type: files; Name: "{app}\nodelang\cell_dpop_nonce.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_dpop_nonce.*.pyc"
Type: files; Name: "{app}\nodelang\cell_event_facts.py"
Type: files; Name: "{app}\nodelang\cell_event_facts.pyc"
Type: files; Name: "{app}\nodelang\cell_event_facts.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_event_facts.*.pyc"
Type: files; Name: "{app}\nodelang\cell_evidence_floor_view.py"
Type: files; Name: "{app}\nodelang\cell_evidence_floor_view.pyc"
Type: files; Name: "{app}\nodelang\cell_evidence_floor_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_evidence_floor_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_exclusive_ownership.py"
Type: files; Name: "{app}\nodelang\cell_exclusive_ownership.pyc"
Type: files; Name: "{app}\nodelang\cell_exclusive_ownership.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_exclusive_ownership.*.pyc"
Type: files; Name: "{app}\nodelang\cell_external_graph_binding.py"
Type: files; Name: "{app}\nodelang\cell_external_graph_binding.pyc"
Type: files; Name: "{app}\nodelang\cell_external_graph_binding.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_external_graph_binding.*.pyc"
Type: files; Name: "{app}\nodelang\cell_fastapi_gate.py"
Type: files; Name: "{app}\nodelang\cell_fastapi_gate.pyc"
Type: files; Name: "{app}\nodelang\cell_fastapi_gate.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_fastapi_gate.*.pyc"
Type: files; Name: "{app}\nodelang\cell_federated_identity.py"
Type: files; Name: "{app}\nodelang\cell_federated_identity.pyc"
Type: files; Name: "{app}\nodelang\cell_federated_identity.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_federated_identity.*.pyc"
Type: files; Name: "{app}\nodelang\cell_focus_view.py"
Type: files; Name: "{app}\nodelang\cell_focus_view.pyc"
Type: files; Name: "{app}\nodelang\cell_focus_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_focus_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_icons.py"
Type: files; Name: "{app}\nodelang\cell_icons.pyc"
Type: files; Name: "{app}\nodelang\cell_icons.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_icons.*.pyc"
Type: files; Name: "{app}\nodelang\cell_identity.py"
Type: files; Name: "{app}\nodelang\cell_identity.pyc"
Type: files; Name: "{app}\nodelang\cell_identity.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_identity.*.pyc"
Type: files; Name: "{app}\nodelang\cell_inspector_controls_view.py"
Type: files; Name: "{app}\nodelang\cell_inspector_controls_view.pyc"
Type: files; Name: "{app}\nodelang\cell_inspector_controls_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_inspector_controls_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_inspector_header_view.py"
Type: files; Name: "{app}\nodelang\cell_inspector_header_view.pyc"
Type: files; Name: "{app}\nodelang\cell_inspector_header_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_inspector_header_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_inspector_shell_view.py"
Type: files; Name: "{app}\nodelang\cell_inspector_shell_view.pyc"
Type: files; Name: "{app}\nodelang\cell_inspector_shell_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_inspector_shell_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_interactions.py"
Type: files; Name: "{app}\nodelang\cell_interactions.pyc"
Type: files; Name: "{app}\nodelang\cell_interactions.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_interactions.*.pyc"
Type: files; Name: "{app}\nodelang\cell_interface_view.py"
Type: files; Name: "{app}\nodelang\cell_interface_view.pyc"
Type: files; Name: "{app}\nodelang\cell_interface_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_interface_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_library_definition_view.py"
Type: files; Name: "{app}\nodelang\cell_library_definition_view.pyc"
Type: files; Name: "{app}\nodelang\cell_library_definition_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_library_definition_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_library_primitive_view.py"
Type: files; Name: "{app}\nodelang\cell_library_primitive_view.pyc"
Type: files; Name: "{app}\nodelang\cell_library_primitive_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_library_primitive_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_library_section_view.py"
Type: files; Name: "{app}\nodelang\cell_library_section_view.pyc"
Type: files; Name: "{app}\nodelang\cell_library_section_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_library_section_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_library_shell_view.py"
Type: files; Name: "{app}\nodelang\cell_library_shell_view.pyc"
Type: files; Name: "{app}\nodelang\cell_library_shell_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_library_shell_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_lifecycle.py"
Type: files; Name: "{app}\nodelang\cell_lifecycle.pyc"
Type: files; Name: "{app}\nodelang\cell_lifecycle.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_lifecycle.*.pyc"
Type: files; Name: "{app}\nodelang\cell_logic.py"
Type: files; Name: "{app}\nodelang\cell_logic.pyc"
Type: files; Name: "{app}\nodelang\cell_logic.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_logic.*.pyc"
Type: files; Name: "{app}\nodelang\cell_mcp_broker.py"
Type: files; Name: "{app}\nodelang\cell_mcp_broker.pyc"
Type: files; Name: "{app}\nodelang\cell_mcp_broker.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_mcp_broker.*.pyc"
Type: files; Name: "{app}\nodelang\cell_meeting_notes.py"
Type: files; Name: "{app}\nodelang\cell_meeting_notes.pyc"
Type: files; Name: "{app}\nodelang\cell_meeting_notes.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_meeting_notes.*.pyc"
Type: files; Name: "{app}\nodelang\cell_model_execution.py"
Type: files; Name: "{app}\nodelang\cell_model_execution.pyc"
Type: files; Name: "{app}\nodelang\cell_model_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_model_execution.*.pyc"
Type: files; Name: "{app}\nodelang\cell_model_providers.py"
Type: files; Name: "{app}\nodelang\cell_model_providers.pyc"
Type: files; Name: "{app}\nodelang\cell_model_providers.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_model_providers.*.pyc"
Type: files; Name: "{app}\nodelang\cell_native_auth.py"
Type: files; Name: "{app}\nodelang\cell_native_auth.pyc"
Type: files; Name: "{app}\nodelang\cell_native_auth.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_native_auth.*.pyc"
Type: files; Name: "{app}\nodelang\cell_oidc.py"
Type: files; Name: "{app}\nodelang\cell_oidc.pyc"
Type: files; Name: "{app}\nodelang\cell_oidc.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_oidc.*.pyc"
Type: files; Name: "{app}\nodelang\cell_oidc_discovery.py"
Type: files; Name: "{app}\nodelang\cell_oidc_discovery.pyc"
Type: files; Name: "{app}\nodelang\cell_oidc_discovery.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_oidc_discovery.*.pyc"
Type: files; Name: "{app}\nodelang\cell_permission_requests.py"
Type: files; Name: "{app}\nodelang\cell_permission_requests.pyc"
Type: files; Name: "{app}\nodelang\cell_permission_requests.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_permission_requests.*.pyc"
Type: files; Name: "{app}\nodelang\cell_presentation.py"
Type: files; Name: "{app}\nodelang\cell_presentation.pyc"
Type: files; Name: "{app}\nodelang\cell_presentation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_presentation.*.pyc"
Type: files; Name: "{app}\nodelang\cell_presentation_view.py"
Type: files; Name: "{app}\nodelang\cell_presentation_view.pyc"
Type: files; Name: "{app}\nodelang\cell_presentation_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_presentation_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_presenter.py"
Type: files; Name: "{app}\nodelang\cell_presenter.pyc"
Type: files; Name: "{app}\nodelang\cell_presenter.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_presenter.*.pyc"
Type: files; Name: "{app}\nodelang\cell_properties_view.py"
Type: files; Name: "{app}\nodelang\cell_properties_view.pyc"
Type: files; Name: "{app}\nodelang\cell_properties_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_properties_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_protocols.py"
Type: files; Name: "{app}\nodelang\cell_protocols.pyc"
Type: files; Name: "{app}\nodelang\cell_protocols.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_protocols.*.pyc"
Type: files; Name: "{app}\nodelang\cell_reactions.py"
Type: files; Name: "{app}\nodelang\cell_reactions.pyc"
Type: files; Name: "{app}\nodelang\cell_reactions.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_reactions.*.pyc"
Type: files; Name: "{app}\nodelang\cell_read_memo.py"
Type: files; Name: "{app}\nodelang\cell_read_memo.pyc"
Type: files; Name: "{app}\nodelang\cell_read_memo.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_read_memo.*.pyc"
Type: files; Name: "{app}\nodelang\cell_registry_projection.py"
Type: files; Name: "{app}\nodelang\cell_registry_projection.pyc"
Type: files; Name: "{app}\nodelang\cell_registry_projection.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_registry_projection.*.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_composer.py"
Type: files; Name: "{app}\nodelang\cell_relation_composer.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_composer.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_relation_composer.*.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_composer_view.py"
Type: files; Name: "{app}\nodelang\cell_relation_composer_view.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_composer_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_relation_composer_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_contract.py"
Type: files; Name: "{app}\nodelang\cell_relation_contract.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_contract.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_relation_contract.*.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_exposure_policy.py"
Type: files; Name: "{app}\nodelang\cell_relation_exposure_policy.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_exposure_policy.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_relation_exposure_policy.*.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_forms.py"
Type: files; Name: "{app}\nodelang\cell_relation_forms.pyc"
Type: files; Name: "{app}\nodelang\cell_relation_forms.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_relation_forms.*.pyc"
Type: files; Name: "{app}\nodelang\cell_relations_view.py"
Type: files; Name: "{app}\nodelang\cell_relations_view.pyc"
Type: files; Name: "{app}\nodelang\cell_relations_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_relations_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_replay_policy_authority.py"
Type: files; Name: "{app}\nodelang\cell_replay_policy_authority.pyc"
Type: files; Name: "{app}\nodelang\cell_replay_policy_authority.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_replay_policy_authority.*.pyc"
Type: files; Name: "{app}\nodelang\cell_result_view.py"
Type: files; Name: "{app}\nodelang\cell_result_view.pyc"
Type: files; Name: "{app}\nodelang\cell_result_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_result_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_revision_checkpoint.py"
Type: files; Name: "{app}\nodelang\cell_revision_checkpoint.pyc"
Type: files; Name: "{app}\nodelang\cell_revision_checkpoint.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_revision_checkpoint.*.pyc"
Type: files; Name: "{app}\nodelang\cell_roma_requirements.py"
Type: files; Name: "{app}\nodelang\cell_roma_requirements.pyc"
Type: files; Name: "{app}\nodelang\cell_roma_requirements.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_roma_requirements.*.pyc"
Type: files; Name: "{app}\nodelang\cell_rules.py"
Type: files; Name: "{app}\nodelang\cell_rules.pyc"
Type: files; Name: "{app}\nodelang\cell_rules.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_rules.*.pyc"
Type: files; Name: "{app}\nodelang\cell_run_view.py"
Type: files; Name: "{app}\nodelang\cell_run_view.pyc"
Type: files; Name: "{app}\nodelang\cell_run_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_run_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_runtime_presence.py"
Type: files; Name: "{app}\nodelang\cell_runtime_presence.pyc"
Type: files; Name: "{app}\nodelang\cell_runtime_presence.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_runtime_presence.*.pyc"
Type: files; Name: "{app}\nodelang\cell_secret_keys.py"
Type: files; Name: "{app}\nodelang\cell_secret_keys.pyc"
Type: files; Name: "{app}\nodelang\cell_secret_keys.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_secret_keys.*.pyc"
Type: files; Name: "{app}\nodelang\cell_selfext_intent.py"
Type: files; Name: "{app}\nodelang\cell_selfext_intent.pyc"
Type: files; Name: "{app}\nodelang\cell_selfext_intent.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_selfext_intent.*.pyc"
Type: files; Name: "{app}\nodelang\cell_sequence.py"
Type: files; Name: "{app}\nodelang\cell_sequence.pyc"
Type: files; Name: "{app}\nodelang\cell_sequence.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_sequence.*.pyc"
Type: files; Name: "{app}\nodelang\cell_session_state.py"
Type: files; Name: "{app}\nodelang\cell_session_state.pyc"
Type: files; Name: "{app}\nodelang\cell_session_state.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_session_state.*.pyc"
Type: files; Name: "{app}\nodelang\cell_set_digest.py"
Type: files; Name: "{app}\nodelang\cell_set_digest.pyc"
Type: files; Name: "{app}\nodelang\cell_set_digest.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_set_digest.*.pyc"
Type: files; Name: "{app}\nodelang\cell_signing_authority.py"
Type: files; Name: "{app}\nodelang\cell_signing_authority.pyc"
Type: files; Name: "{app}\nodelang\cell_signing_authority.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_signing_authority.*.pyc"
Type: files; Name: "{app}\nodelang\cell_source_assembly.py"
Type: files; Name: "{app}\nodelang\cell_source_assembly.pyc"
Type: files; Name: "{app}\nodelang\cell_source_assembly.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_source_assembly.*.pyc"
Type: files; Name: "{app}\nodelang\cell_standard_library.py"
Type: files; Name: "{app}\nodelang\cell_standard_library.pyc"
Type: files; Name: "{app}\nodelang\cell_standard_library.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_standard_library.*.pyc"
Type: files; Name: "{app}\nodelang\cell_state_machine.py"
Type: files; Name: "{app}\nodelang\cell_state_machine.pyc"
Type: files; Name: "{app}\nodelang\cell_state_machine.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_state_machine.*.pyc"
Type: files; Name: "{app}\nodelang\cell_status_ledger.py"
Type: files; Name: "{app}\nodelang\cell_status_ledger.pyc"
Type: files; Name: "{app}\nodelang\cell_status_ledger.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_status_ledger.*.pyc"
Type: files; Name: "{app}\nodelang\cell_tenant_authority.py"
Type: files; Name: "{app}\nodelang\cell_tenant_authority.pyc"
Type: files; Name: "{app}\nodelang\cell_tenant_authority.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_tenant_authority.*.pyc"
Type: files; Name: "{app}\nodelang\cell_theme_sets.py"
Type: files; Name: "{app}\nodelang\cell_theme_sets.pyc"
Type: files; Name: "{app}\nodelang\cell_theme_sets.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_theme_sets.*.pyc"
Type: files; Name: "{app}\nodelang\cell_timeline_view.py"
Type: files; Name: "{app}\nodelang\cell_timeline_view.pyc"
Type: files; Name: "{app}\nodelang\cell_timeline_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_timeline_view.*.pyc"
Type: files; Name: "{app}\nodelang\cell_transactions.py"
Type: files; Name: "{app}\nodelang\cell_transactions.pyc"
Type: files; Name: "{app}\nodelang\cell_transactions.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_transactions.*.pyc"
Type: files; Name: "{app}\nodelang\cell_ui.py"
Type: files; Name: "{app}\nodelang\cell_ui.pyc"
Type: files; Name: "{app}\nodelang\cell_ui.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_ui.*.pyc"
Type: files; Name: "{app}\nodelang\cell_users_seats.py"
Type: files; Name: "{app}\nodelang\cell_users_seats.pyc"
Type: files; Name: "{app}\nodelang\cell_users_seats.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_users_seats.*.pyc"
Type: files; Name: "{app}\nodelang\cell_value_graph.py"
Type: files; Name: "{app}\nodelang\cell_value_graph.pyc"
Type: files; Name: "{app}\nodelang\cell_value_graph.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_value_graph.*.pyc"
Type: files; Name: "{app}\nodelang\cell_view_template.py"
Type: files; Name: "{app}\nodelang\cell_view_template.pyc"
Type: files; Name: "{app}\nodelang\cell_view_template.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_view_template.*.pyc"
Type: files; Name: "{app}\nodelang\cell_voice.py"
Type: files; Name: "{app}\nodelang\cell_voice.pyc"
Type: files; Name: "{app}\nodelang\cell_voice.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_voice.*.pyc"
Type: files; Name: "{app}\nodelang\cell_website.py"
Type: files; Name: "{app}\nodelang\cell_website.pyc"
Type: files; Name: "{app}\nodelang\cell_website.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_website.*.pyc"
Type: files; Name: "{app}\nodelang\cell_website_meta.py"
Type: files; Name: "{app}\nodelang\cell_website_meta.pyc"
Type: files; Name: "{app}\nodelang\cell_website_meta.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_website_meta.*.pyc"
Type: files; Name: "{app}\nodelang\cell_work_claim_transfer.py"
Type: files; Name: "{app}\nodelang\cell_work_claim_transfer.pyc"
Type: files; Name: "{app}\nodelang\cell_work_claim_transfer.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_work_claim_transfer.*.pyc"
Type: files; Name: "{app}\nodelang\cell_work_handoff.py"
Type: files; Name: "{app}\nodelang\cell_work_handoff.pyc"
Type: files; Name: "{app}\nodelang\cell_work_handoff.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_work_handoff.*.pyc"
Type: files; Name: "{app}\nodelang\checkpoint_authority_provisioning.py"
Type: files; Name: "{app}\nodelang\checkpoint_authority_provisioning.pyc"
Type: files; Name: "{app}\nodelang\checkpoint_authority_provisioning.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\checkpoint_authority_provisioning.*.pyc"
Type: files; Name: "{app}\nodelang\clean_boot_surface.py"
Type: files; Name: "{app}\nodelang\clean_boot_surface.pyc"
Type: files; Name: "{app}\nodelang\clean_boot_surface.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_boot_surface.*.pyc"
Type: files; Name: "{app}\nodelang\clean_browser_authority.py"
Type: files; Name: "{app}\nodelang\clean_browser_authority.pyc"
Type: files; Name: "{app}\nodelang\clean_browser_authority.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_browser_authority.*.pyc"
Type: files; Name: "{app}\nodelang\clean_coordination_host.py"
Type: files; Name: "{app}\nodelang\clean_coordination_host.pyc"
Type: files; Name: "{app}\nodelang\clean_coordination_host.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_coordination_host.*.pyc"
Type: files; Name: "{app}\nodelang\clean_coordination_service.py"
Type: files; Name: "{app}\nodelang\clean_coordination_service.pyc"
Type: files; Name: "{app}\nodelang\clean_coordination_service.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_coordination_service.*.pyc"
Type: files; Name: "{app}\nodelang\clean_design_catalogue.py"
Type: files; Name: "{app}\nodelang\clean_design_catalogue.pyc"
Type: files; Name: "{app}\nodelang\clean_design_catalogue.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_design_catalogue.*.pyc"
Type: files; Name: "{app}\nodelang\clean_host_boundaries.py"
Type: files; Name: "{app}\nodelang\clean_host_boundaries.pyc"
Type: files; Name: "{app}\nodelang\clean_host_boundaries.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_host_boundaries.*.pyc"
Type: files; Name: "{app}\nodelang\clean_host_execution.py"
Type: files; Name: "{app}\nodelang\clean_host_execution.pyc"
Type: files; Name: "{app}\nodelang\clean_host_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_host_execution.*.pyc"
Type: files; Name: "{app}\nodelang\clean_host_operations.py"
Type: files; Name: "{app}\nodelang\clean_host_operations.pyc"
Type: files; Name: "{app}\nodelang\clean_host_operations.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_host_operations.*.pyc"
Type: files; Name: "{app}\nodelang\clean_runtime_bootstrap.py"
Type: files; Name: "{app}\nodelang\clean_runtime_bootstrap.pyc"
Type: files; Name: "{app}\nodelang\clean_runtime_bootstrap.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_runtime_bootstrap.*.pyc"
Type: files; Name: "{app}\nodelang\clean_scope_interactions.py"
Type: files; Name: "{app}\nodelang\clean_scope_interactions.pyc"
Type: files; Name: "{app}\nodelang\clean_scope_interactions.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_scope_interactions.*.pyc"
Type: files; Name: "{app}\nodelang\clean_subsystem_revision.py"
Type: files; Name: "{app}\nodelang\clean_subsystem_revision.pyc"
Type: files; Name: "{app}\nodelang\clean_subsystem_revision.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_subsystem_revision.*.pyc"
Type: files; Name: "{app}\nodelang\clean_visual_authority.py"
Type: files; Name: "{app}\nodelang\clean_visual_authority.pyc"
Type: files; Name: "{app}\nodelang\clean_visual_authority.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_visual_authority.*.pyc"
Type: files; Name: "{app}\nodelang\clean_visual_projection.py"
Type: files; Name: "{app}\nodelang\clean_visual_projection.pyc"
Type: files; Name: "{app}\nodelang\clean_visual_projection.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\clean_visual_projection.*.pyc"
Type: files; Name: "{app}\nodelang\cloud_application_entrypoint.py"
Type: files; Name: "{app}\nodelang\cloud_application_entrypoint.pyc"
Type: files; Name: "{app}\nodelang\cloud_application_entrypoint.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cloud_application_entrypoint.*.pyc"
Type: files; Name: "{app}\nodelang\cloud_runtime.py"
Type: files; Name: "{app}\nodelang\cloud_runtime.pyc"
Type: files; Name: "{app}\nodelang\cloud_runtime.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cloud_runtime.*.pyc"
Type: files; Name: "{app}\nodelang\cloud_runtime_bootstrap.py"
Type: files; Name: "{app}\nodelang\cloud_runtime_bootstrap.pyc"
Type: files; Name: "{app}\nodelang\cloud_runtime_bootstrap.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cloud_runtime_bootstrap.*.pyc"
Type: files; Name: "{app}\nodelang\commit_intent.py"
Type: files; Name: "{app}\nodelang\commit_intent.pyc"
Type: files; Name: "{app}\nodelang\commit_intent.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\commit_intent.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_archive.py"
Type: files; Name: "{app}\nodelang\conversation_archive.pyc"
Type: files; Name: "{app}\nodelang\conversation_archive.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_archive.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_content.py"
Type: files; Name: "{app}\nodelang\conversation_content.pyc"
Type: files; Name: "{app}\nodelang\conversation_content.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_content.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration.py"
Type: files; Name: "{app}\nodelang\conversation_migration.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_migration.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration_activation.py"
Type: files; Name: "{app}\nodelang\conversation_migration_activation.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration_activation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_migration_activation.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration_binding.py"
Type: files; Name: "{app}\nodelang\conversation_migration_binding.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration_binding.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_migration_binding.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration_publication.py"
Type: files; Name: "{app}\nodelang\conversation_migration_publication.pyc"
Type: files; Name: "{app}\nodelang\conversation_migration_publication.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_migration_publication.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_retention_maintenance.py"
Type: files; Name: "{app}\nodelang\conversation_retention_maintenance.pyc"
Type: files; Name: "{app}\nodelang\conversation_retention_maintenance.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_retention_maintenance.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_trace_receipts.py"
Type: files; Name: "{app}\nodelang\conversation_trace_receipts.pyc"
Type: files; Name: "{app}\nodelang\conversation_trace_receipts.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_trace_receipts.*.pyc"
Type: files; Name: "{app}\nodelang\conversation_trace_shapes.py"
Type: files; Name: "{app}\nodelang\conversation_trace_shapes.pyc"
Type: files; Name: "{app}\nodelang\conversation_trace_shapes.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\conversation_trace_shapes.*.pyc"
Type: files; Name: "{app}\nodelang\coordination_workshop.py"
Type: files; Name: "{app}\nodelang\coordination_workshop.pyc"
Type: files; Name: "{app}\nodelang\coordination_workshop.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\coordination_workshop.*.pyc"
Type: files; Name: "{app}\nodelang\core.py"
Type: files; Name: "{app}\nodelang\core.pyc"
Type: files; Name: "{app}\nodelang\core.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\core.*.pyc"
Type: files; Name: "{app}\nodelang\deployment_evidence.py"
Type: files; Name: "{app}\nodelang\deployment_evidence.pyc"
Type: files; Name: "{app}\nodelang\deployment_evidence.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\deployment_evidence.*.pyc"
Type: files; Name: "{app}\nodelang\desktop.py"
Type: files; Name: "{app}\nodelang\desktop.pyc"
Type: files; Name: "{app}\nodelang\desktop.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\desktop.*.pyc"
Type: files; Name: "{app}\nodelang\desktop_owner.py"
Type: files; Name: "{app}\nodelang\desktop_owner.pyc"
Type: files; Name: "{app}\nodelang\desktop_owner.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\desktop_owner.*.pyc"
Type: files; Name: "{app}\nodelang\domains\cloud.py"
Type: files; Name: "{app}\nodelang\domains\cloud.pyc"
Type: files; Name: "{app}\nodelang\domains\cloud.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\cloud.*.pyc"
Type: files; Name: "{app}\nodelang\domains\cockpit.py"
Type: files; Name: "{app}\nodelang\domains\cockpit.pyc"
Type: files; Name: "{app}\nodelang\domains\cockpit.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\cockpit.*.pyc"
Type: files; Name: "{app}\nodelang\domains\community.py"
Type: files; Name: "{app}\nodelang\domains\community.pyc"
Type: files; Name: "{app}\nodelang\domains\community.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\community.*.pyc"
Type: files; Name: "{app}\nodelang\domains\connectors.py"
Type: files; Name: "{app}\nodelang\domains\connectors.pyc"
Type: files; Name: "{app}\nodelang\domains\connectors.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\connectors.*.pyc"
Type: files; Name: "{app}\nodelang\domains\models.py"
Type: files; Name: "{app}\nodelang\domains\models.pyc"
Type: files; Name: "{app}\nodelang\domains\models.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\models.*.pyc"
Type: files; Name: "{app}\nodelang\domains\monetization.py"
Type: files; Name: "{app}\nodelang\domains\monetization.pyc"
Type: files; Name: "{app}\nodelang\domains\monetization.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\monetization.*.pyc"
Type: files; Name: "{app}\nodelang\domains\orchestration.py"
Type: files; Name: "{app}\nodelang\domains\orchestration.pyc"
Type: files; Name: "{app}\nodelang\domains\orchestration.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\orchestration.*.pyc"
Type: files; Name: "{app}\nodelang\domains\resources.py"
Type: files; Name: "{app}\nodelang\domains\resources.pyc"
Type: files; Name: "{app}\nodelang\domains\resources.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\resources.*.pyc"
Type: files; Name: "{app}\nodelang\domains\sessions.py"
Type: files; Name: "{app}\nodelang\domains\sessions.pyc"
Type: files; Name: "{app}\nodelang\domains\sessions.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\sessions.*.pyc"
Type: files; Name: "{app}\nodelang\domains\users.py"
Type: files; Name: "{app}\nodelang\domains\users.pyc"
Type: files; Name: "{app}\nodelang\domains\users.pyo"
Type: files; Name: "{app}\nodelang\domains\__pycache__\users.*.pyc"
Type: files; Name: "{app}\nodelang\drivers.py"
Type: files; Name: "{app}\nodelang\drivers.pyc"
Type: files; Name: "{app}\nodelang\drivers.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\drivers.*.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_conversation.py"
Type: files; Name: "{app}\nodelang\existing_workshop_conversation.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_conversation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\existing_workshop_conversation.*.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_model_result.py"
Type: files; Name: "{app}\nodelang\existing_workshop_model_result.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_model_result.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\existing_workshop_model_result.*.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_project_execution.py"
Type: files; Name: "{app}\nodelang\existing_workshop_project_execution.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_project_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\existing_workshop_project_execution.*.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_project_revision.py"
Type: files; Name: "{app}\nodelang\existing_workshop_project_revision.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_project_revision.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\existing_workshop_project_revision.*.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_social_execution.py"
Type: files; Name: "{app}\nodelang\existing_workshop_social_execution.pyc"
Type: files; Name: "{app}\nodelang\existing_workshop_social_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\existing_workshop_social_execution.*.pyc"
Type: files; Name: "{app}\nodelang\external_revision_witness.py"
Type: files; Name: "{app}\nodelang\external_revision_witness.pyc"
Type: files; Name: "{app}\nodelang\external_revision_witness.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\external_revision_witness.*.pyc"
Type: files; Name: "{app}\nodelang\governance_policy.py"
Type: files; Name: "{app}\nodelang\governance_policy.pyc"
Type: files; Name: "{app}\nodelang\governance_policy.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\governance_policy.*.pyc"
Type: files; Name: "{app}\nodelang\governance_probe.py"
Type: files; Name: "{app}\nodelang\governance_probe.pyc"
Type: files; Name: "{app}\nodelang\governance_probe.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\governance_probe.*.pyc"
Type: files; Name: "{app}\nodelang\graph_api.py"
Type: files; Name: "{app}\nodelang\graph_api.pyc"
Type: files; Name: "{app}\nodelang\graph_api.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\graph_api.*.pyc"
Type: files; Name: "{app}\nodelang\host_enable.py"
Type: files; Name: "{app}\nodelang\host_enable.pyc"
Type: files; Name: "{app}\nodelang\host_enable.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\host_enable.*.pyc"
Type: files; Name: "{app}\nodelang\inspector_descriptor.py"
Type: files; Name: "{app}\nodelang\inspector_descriptor.pyc"
Type: files; Name: "{app}\nodelang\inspector_descriptor.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\inspector_descriptor.*.pyc"
Type: files; Name: "{app}\nodelang\installed_workshop_coordination.py"
Type: files; Name: "{app}\nodelang\installed_workshop_coordination.pyc"
Type: files; Name: "{app}\nodelang\installed_workshop_coordination.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\installed_workshop_coordination.*.pyc"
Type: files; Name: "{app}\nodelang\installer_closed_profile.py"
Type: files; Name: "{app}\nodelang\installer_closed_profile.pyc"
Type: files; Name: "{app}\nodelang\installer_closed_profile.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\installer_closed_profile.*.pyc"
Type: files; Name: "{app}\nodelang\laws_decision.py"
Type: files; Name: "{app}\nodelang\laws_decision.pyc"
Type: files; Name: "{app}\nodelang\laws_decision.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\laws_decision.*.pyc"
Type: files; Name: "{app}\nodelang\laws_effect.py"
Type: files; Name: "{app}\nodelang\laws_effect.pyc"
Type: files; Name: "{app}\nodelang\laws_effect.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\laws_effect.*.pyc"
Type: files; Name: "{app}\nodelang\laws_relation.py"
Type: files; Name: "{app}\nodelang\laws_relation.pyc"
Type: files; Name: "{app}\nodelang\laws_relation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\laws_relation.*.pyc"
Type: files; Name: "{app}\nodelang\laws_structure.py"
Type: files; Name: "{app}\nodelang\laws_structure.pyc"
Type: files; Name: "{app}\nodelang\laws_structure.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\laws_structure.*.pyc"
Type: files; Name: "{app}\nodelang\laws_surface.py"
Type: files; Name: "{app}\nodelang\laws_surface.pyc"
Type: files; Name: "{app}\nodelang\laws_surface.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\laws_surface.*.pyc"
Type: files; Name: "{app}\nodelang\lazy_application_registry.py"
Type: files; Name: "{app}\nodelang\lazy_application_registry.pyc"
Type: files; Name: "{app}\nodelang\lazy_application_registry.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\lazy_application_registry.*.pyc"
Type: files; Name: "{app}\nodelang\migration.py"
Type: files; Name: "{app}\nodelang\migration.pyc"
Type: files; Name: "{app}\nodelang\migration.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\migration.*.pyc"
Type: files; Name: "{app}\nodelang\model_session_bridge.py"
Type: files; Name: "{app}\nodelang\model_session_bridge.pyc"
Type: files; Name: "{app}\nodelang\model_session_bridge.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\model_session_bridge.*.pyc"
Type: files; Name: "{app}\nodelang\native_agent_session.py"
Type: files; Name: "{app}\nodelang\native_agent_session.pyc"
Type: files; Name: "{app}\nodelang\native_agent_session.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_agent_session.*.pyc"
Type: files; Name: "{app}\nodelang\native_cloud_login.py"
Type: files; Name: "{app}\nodelang\native_cloud_login.pyc"
Type: files; Name: "{app}\nodelang\native_cloud_login.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_cloud_login.*.pyc"
Type: files; Name: "{app}\nodelang\native_contact.py"
Type: files; Name: "{app}\nodelang\native_contact.pyc"
Type: files; Name: "{app}\nodelang\native_contact.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_contact.*.pyc"
Type: files; Name: "{app}\nodelang\native_enrollment_reconciliation.py"
Type: files; Name: "{app}\nodelang\native_enrollment_reconciliation.pyc"
Type: files; Name: "{app}\nodelang\native_enrollment_reconciliation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_enrollment_reconciliation.*.pyc"
Type: files; Name: "{app}\nodelang\native_inbox_recovery.py"
Type: files; Name: "{app}\nodelang\native_inbox_recovery.pyc"
Type: files; Name: "{app}\nodelang\native_inbox_recovery.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_inbox_recovery.*.pyc"
Type: files; Name: "{app}\nodelang\native_session_release.py"
Type: files; Name: "{app}\nodelang\native_session_release.pyc"
Type: files; Name: "{app}\nodelang\native_session_release.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_session_release.*.pyc"
Type: files; Name: "{app}\nodelang\native_work_completion.py"
Type: files; Name: "{app}\nodelang\native_work_completion.pyc"
Type: files; Name: "{app}\nodelang\native_work_completion.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_work_completion.*.pyc"
Type: files; Name: "{app}\nodelang\native_work_configuration.py"
Type: files; Name: "{app}\nodelang\native_work_configuration.pyc"
Type: files; Name: "{app}\nodelang\native_work_configuration.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_work_configuration.*.pyc"
Type: files; Name: "{app}\nodelang\native_work_release_recovery.py"
Type: files; Name: "{app}\nodelang\native_work_release_recovery.pyc"
Type: files; Name: "{app}\nodelang\native_work_release_recovery.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_work_release_recovery.*.pyc"
Type: files; Name: "{app}\nodelang\native_workshop_compliance.py"
Type: files; Name: "{app}\nodelang\native_workshop_compliance.pyc"
Type: files; Name: "{app}\nodelang\native_workshop_compliance.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_workshop_compliance.*.pyc"
Type: files; Name: "{app}\nodelang\native_workshop_execution.py"
Type: files; Name: "{app}\nodelang\native_workshop_execution.pyc"
Type: files; Name: "{app}\nodelang\native_workshop_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\native_workshop_execution.*.pyc"
Type: files; Name: "{app}\nodelang\opencode_native_custody.py"
Type: files; Name: "{app}\nodelang\opencode_native_custody.pyc"
Type: files; Name: "{app}\nodelang\opencode_native_custody.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\opencode_native_custody.*.pyc"
Type: files; Name: "{app}\nodelang\persistence.py"
Type: files; Name: "{app}\nodelang\persistence.pyc"
Type: files; Name: "{app}\nodelang\persistence.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\persistence.*.pyc"
Type: files; Name: "{app}\nodelang\postgres_cell_journal.py"
Type: files; Name: "{app}\nodelang\postgres_cell_journal.pyc"
Type: files; Name: "{app}\nodelang\postgres_cell_journal.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\postgres_cell_journal.*.pyc"
Type: files; Name: "{app}\nodelang\private_root_grants.py"
Type: files; Name: "{app}\nodelang\private_root_grants.pyc"
Type: files; Name: "{app}\nodelang\private_root_grants.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\private_root_grants.*.pyc"
Type: files; Name: "{app}\nodelang\project_work_execution_broker.py"
Type: files; Name: "{app}\nodelang\project_work_execution_broker.pyc"
Type: files; Name: "{app}\nodelang\project_work_execution_broker.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\project_work_execution_broker.*.pyc"
Type: files; Name: "{app}\nodelang\projection_visibility_recovery.py"
Type: files; Name: "{app}\nodelang\projection_visibility_recovery.pyc"
Type: files; Name: "{app}\nodelang\projection_visibility_recovery.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\projection_visibility_recovery.*.pyc"
Type: files; Name: "{app}\nodelang\requirement_graph_import.py"
Type: files; Name: "{app}\nodelang\requirement_graph_import.pyc"
Type: files; Name: "{app}\nodelang\requirement_graph_import.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\requirement_graph_import.*.pyc"
Type: files; Name: "{app}\nodelang\research_owner.py"
Type: files; Name: "{app}\nodelang\research_owner.pyc"
Type: files; Name: "{app}\nodelang\research_owner.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\research_owner.*.pyc"
Type: files; Name: "{app}\nodelang\runtime_activity.py"
Type: files; Name: "{app}\nodelang\runtime_activity.pyc"
Type: files; Name: "{app}\nodelang\runtime_activity.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_activity.*.pyc"
Type: files; Name: "{app}\nodelang\runtime_caller_capability.py"
Type: files; Name: "{app}\nodelang\runtime_caller_capability.pyc"
Type: files; Name: "{app}\nodelang\runtime_caller_capability.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_caller_capability.*.pyc"
Type: files; Name: "{app}\nodelang\runtime_compliance_adapter.py"
Type: files; Name: "{app}\nodelang\runtime_compliance_adapter.pyc"
Type: files; Name: "{app}\nodelang\runtime_compliance_adapter.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_compliance_adapter.*.pyc"
Type: files; Name: "{app}\nodelang\runtime_gateway.py"
Type: files; Name: "{app}\nodelang\runtime_gateway.pyc"
Type: files; Name: "{app}\nodelang\runtime_gateway.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_gateway.*.pyc"
Type: files; Name: "{app}\nodelang\runtime_ownership_records.py"
Type: files; Name: "{app}\nodelang\runtime_ownership_records.pyc"
Type: files; Name: "{app}\nodelang\runtime_ownership_records.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_ownership_records.*.pyc"
Type: files; Name: "{app}\nodelang\runtime_presence_lease_storage.py"
Type: files; Name: "{app}\nodelang\runtime_presence_lease_storage.pyc"
Type: files; Name: "{app}\nodelang\runtime_presence_lease_storage.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_presence_lease_storage.*.pyc"
Type: files; Name: "{app}\nodelang\serve_canvas.py"
Type: files; Name: "{app}\nodelang\serve_canvas.pyc"
Type: files; Name: "{app}\nodelang\serve_canvas.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\serve_canvas.*.pyc"
Type: files; Name: "{app}\nodelang\social_approval.py"
Type: files; Name: "{app}\nodelang\social_approval.pyc"
Type: files; Name: "{app}\nodelang\social_approval.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\social_approval.*.pyc"
Type: files; Name: "{app}\nodelang\social_http_host.py"
Type: files; Name: "{app}\nodelang\social_http_host.pyc"
Type: files; Name: "{app}\nodelang\social_http_host.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\social_http_host.*.pyc"
Type: files; Name: "{app}\nodelang\stability_runtime.py"
Type: files; Name: "{app}\nodelang\stability_runtime.pyc"
Type: files; Name: "{app}\nodelang\stability_runtime.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\stability_runtime.*.pyc"
Type: files; Name: "{app}\nodelang\tool_hub.py"
Type: files; Name: "{app}\nodelang\tool_hub.pyc"
Type: files; Name: "{app}\nodelang\tool_hub.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\tool_hub.*.pyc"
Type: files; Name: "{app}\nodelang\ui_runtime.py"
Type: files; Name: "{app}\nodelang\ui_runtime.pyc"
Type: files; Name: "{app}\nodelang\ui_runtime.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\ui_runtime.*.pyc"
Type: files; Name: "{app}\nodelang\unified_application_lens.py"
Type: files; Name: "{app}\nodelang\unified_application_lens.pyc"
Type: files; Name: "{app}\nodelang\unified_application_lens.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\unified_application_lens.*.pyc"
Type: files; Name: "{app}\nodelang\unified_authority.py"
Type: files; Name: "{app}\nodelang\unified_authority.pyc"
Type: files; Name: "{app}\nodelang\unified_authority.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\unified_authority.*.pyc"
Type: files; Name: "{app}\nodelang\unified_authority_runtime.py"
Type: files; Name: "{app}\nodelang\unified_authority_runtime.pyc"
Type: files; Name: "{app}\nodelang\unified_authority_runtime.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\unified_authority_runtime.*.pyc"
Type: files; Name: "{app}\nodelang\universal_application.py"
Type: files; Name: "{app}\nodelang\universal_application.pyc"
Type: files; Name: "{app}\nodelang\universal_application.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_application.*.pyc"
Type: files; Name: "{app}\nodelang\universal_cell.py"
Type: files; Name: "{app}\nodelang\universal_cell.pyc"
Type: files; Name: "{app}\nodelang\universal_cell.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_cell.*.pyc"
Type: files; Name: "{app}\nodelang\universal_cloud_gateway.py"
Type: files; Name: "{app}\nodelang\universal_cloud_gateway.pyc"
Type: files; Name: "{app}\nodelang\universal_cloud_gateway.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_cloud_gateway.*.pyc"
Type: files; Name: "{app}\nodelang\universal_cloud_listener.py"
Type: files; Name: "{app}\nodelang\universal_cloud_listener.pyc"
Type: files; Name: "{app}\nodelang\universal_cloud_listener.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_cloud_listener.*.pyc"
Type: files; Name: "{app}\nodelang\universal_graphs.py"
Type: files; Name: "{app}\nodelang\universal_graphs.pyc"
Type: files; Name: "{app}\nodelang\universal_graphs.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_graphs.*.pyc"
Type: files; Name: "{app}\nodelang\universal_map_import.py"
Type: files; Name: "{app}\nodelang\universal_map_import.pyc"
Type: files; Name: "{app}\nodelang\universal_map_import.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_map_import.*.pyc"
Type: files; Name: "{app}\nodelang\universal_pipeline.py"
Type: files; Name: "{app}\nodelang\universal_pipeline.pyc"
Type: files; Name: "{app}\nodelang\universal_pipeline.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_pipeline.*.pyc"
Type: files; Name: "{app}\nodelang\universal_presentation_seed.py"
Type: files; Name: "{app}\nodelang\universal_presentation_seed.pyc"
Type: files; Name: "{app}\nodelang\universal_presentation_seed.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_presentation_seed.*.pyc"
Type: files; Name: "{app}\nodelang\universal_view.py"
Type: files; Name: "{app}\nodelang\universal_view.pyc"
Type: files; Name: "{app}\nodelang\universal_view.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\universal_view.*.pyc"
Type: files; Name: "{app}\nodelang\windows_cng_signing_provider.py"
Type: files; Name: "{app}\nodelang\windows_cng_signing_provider.pyc"
Type: files; Name: "{app}\nodelang\windows_cng_signing_provider.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\windows_cng_signing_provider.*.pyc"
Type: files; Name: "{app}\nodelang\work_review_wait.py"
Type: files; Name: "{app}\nodelang\work_review_wait.pyc"
Type: files; Name: "{app}\nodelang\work_review_wait.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\work_review_wait.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_activity.py"
Type: files; Name: "{app}\nodelang\workshop_activity.pyc"
Type: files; Name: "{app}\nodelang\workshop_activity.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_activity.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_conversation.py"
Type: files; Name: "{app}\nodelang\workshop_conversation.pyc"
Type: files; Name: "{app}\nodelang\workshop_conversation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_conversation.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_conversation_catalog.py"
Type: files; Name: "{app}\nodelang\workshop_conversation_catalog.pyc"
Type: files; Name: "{app}\nodelang\workshop_conversation_catalog.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_conversation_catalog.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_founder_sink.py"
Type: files; Name: "{app}\nodelang\workshop_founder_sink.pyc"
Type: files; Name: "{app}\nodelang\workshop_founder_sink.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_founder_sink.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_project_revision.py"
Type: files; Name: "{app}\nodelang\workshop_project_revision.pyc"
Type: files; Name: "{app}\nodelang\workshop_project_revision.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_project_revision.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_retention_guard.py"
Type: files; Name: "{app}\nodelang\workshop_retention_guard.pyc"
Type: files; Name: "{app}\nodelang\workshop_retention_guard.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_retention_guard.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_session_start.py"
Type: files; Name: "{app}\nodelang\workshop_session_start.pyc"
Type: files; Name: "{app}\nodelang\workshop_session_start.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_session_start.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_work_creation.py"
Type: files; Name: "{app}\nodelang\workshop_work_creation.pyc"
Type: files; Name: "{app}\nodelang\workshop_work_creation.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_work_creation.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_workflow.py"
Type: files; Name: "{app}\nodelang\workshop_workflow.pyc"
Type: files; Name: "{app}\nodelang\workshop_workflow.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_workflow.*.pyc"
Type: files; Name: "{app}\nodelang\workspace_roots_owner.py"
Type: files; Name: "{app}\nodelang\workspace_roots_owner.pyc"
Type: files; Name: "{app}\nodelang\workspace_roots_owner.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\workspace_roots_owner.*.pyc"
; The retired personal Brain: its hook observer package and the supervisor
; starter. An upgrade must not keep running either (retire-12-BC).
Type: files; Name: "{app}\personal_brain\__init__.py"
Type: files; Name: "{app}\personal_brain\hook_coverage.py"
Type: files; Name: "{app}\personal_brain\installer.py"
Type: files; Name: "{app}\personal_brain\ambient_policy.py"
Type: files; Name: "{app}\personal_brain\__pycache__\*.pyc"
Type: files; Name: "{app}\nodelang\brain_supervisor_start.py"
Type: files; Name: "{app}\nodelang\__pycache__\brain_supervisor_start.*.pyc"
; Dead code retired from source in 5e6f33e1 (2026-09-30). An upgrade kept the
; installed copies because this package never sweeps directories.
Type: files; Name: "{app}\nodelang\clean_browser_scope_state.py"
Type: files; Name: "{app}\nodelang\clean_scope_layout.py"
Type: files; Name: "{app}\nodelang\serve_reality.py"
Type: files; Name: "{app}\nodelang\studio\studio-language.jsx"
Type: files; Name: "{app}\nodelang\__pycache__\clean_browser_scope_state.*.pyc"
Type: files; Name: "{app}\nodelang\__pycache__\clean_scope_layout.*.pyc"
Type: files; Name: "{app}\nodelang\__pycache__\serve_reality.*.pyc"
; Retired from source in cca61051 (2026-10-01): the machine announcement is a
; signed pointer written by the transport; nothing imports this module now.
Type: files; Name: "{app}\nodelang\runtime_announcement.py"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_announcement.*.pyc"
; AGENTLINK2 retires exact coordination files; user state is never swept.
Type: files; Name: "{app}\nodelang\deferred_codex_binding.py"
Type: files; Name: "{app}\nodelang\__pycache__\deferred_codex_binding.*.pyc"
Type: files; Name: "{app}\nodelang\native_mcp_launcher.py"
Type: files; Name: "{app}\nodelang\__pycache__\native_mcp_launcher.*.pyc"
Type: files; Name: "{app}\nodelang\native_resume_guard.py"
Type: files; Name: "{app}\nodelang\__pycache__\native_resume_guard.*.pyc"
Type: files; Name: "{app}\nodelang\native_session_resume.py"
Type: files; Name: "{app}\nodelang\__pycache__\native_session_resume.*.pyc"
Type: files; Name: "{app}\nodelang\native_start_hook.py"
Type: files; Name: "{app}\nodelang\__pycache__\native_start_hook.*.pyc"
Type: files; Name: "{app}\nodelang\workshop_host.py"
Type: files; Name: "{app}\nodelang\__pycache__\workshop_host.*.pyc"
Type: files; Name: "{app}\nodelang\opencode_coordination_tools.py"
Type: files; Name: "{app}\nodelang\__pycache__\opencode_coordination_tools.*.pyc"
Type: files; Name: "{app}\nodelang\clean_browser_workshop.py"
Type: files; Name: "{app}\nodelang\__pycache__\clean_browser_workshop.*.pyc"
Type: files; Name: "{app}\nodelang\serve.py"
Type: files; Name: "{app}\nodelang\__pycache__\serve.*.pyc"
Type: files; Name: "{app}\nodelang\clean_coordination_mcp.py"
Type: files; Name: "{app}\nodelang\__pycache__\clean_coordination_mcp.*.pyc"
Type: files; Name: "{app}\nodelang\clean_antigravity_hook.py"
Type: files; Name: "{app}\nodelang\__pycache__\clean_antigravity_hook.*.pyc"
Type: files; Name: "{app}\nodelang\workshop\host-attachment.mjs"
Type: files; Name: "{app}\nodelang\workshop\host-worker.mjs"
; The wheelhouse is this build's alone; an older build's wheels never mix in.
; STAGE2B retires executable copies as well as their scheduled registrations.
; Exact paths only: never sweep user state or third-party host files.
Type: files; Name: "{app}\desktop\clean_shell.py"
Type: files; Name: "{app}\desktop\__pycache__\clean_shell.*.pyc"
Type: files; Name: "{app}\nodelang\desktop_supervisor.py"
Type: files; Name: "{app}\nodelang\runtime_supervisor.py"
Type: files; Name: "{app}\nodelang\authority_bridge.py"
Type: files; Name: "{app}\nodelang\remote_native_cloud_login.py"
Type: files; Name: "{app}\nodelang\__pycache__\desktop_supervisor.*.pyc"
Type: files; Name: "{app}\nodelang\__pycache__\runtime_supervisor.*.pyc"
Type: files; Name: "{app}\nodelang\__pycache__\authority_bridge.*.pyc"
Type: files; Name: "{app}\nodelang\__pycache__\remote_native_cloud_login.*.pyc"
Type: files; Name: "{app}\packaging\windows\install_clean_coordination_task.ps1"
Type: files; Name: "{app}\packaging\windows\install_runtime_task.ps1"
Type: files; Name: "{app}\packaging\windows\entrypoint.py"
Type: files; Name: "{app}\packaging\windows\Launch-ArchHub.vbs"
Type: files; Name: "{app}\wheelhouse\*.whl"

[UninstallDelete]
; Host files set aside while a host had them loaded (host_file_staging.iss).
Type: filesandordirs; Name: "{app}\.retired-host-files"

[Icons]
Name: "{group}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"; AppUserModelID: "ArchHub.ArchHub"
Name: "{group}\Uninstall ArchHub"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"; AppUserModelID: "ArchHub.ArchHub"; Tasks: desktopicon

[Run]
; The first open prepares the machine before any window appears; a plain
; "Open ArchHub now" left people staring at a setup window they did not expect.
Filename: "{app}\{#AppExe}"; Description: "Open ArchHub now (the first open installs what it needs, in a window you can read)"; Flags: shellexec postinstall nowait skipifsilent

[Code]


#include "host_registrations.iss"

#include "host_file_staging.iss"

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  HookResult: Integer;
begin
  { Only this user's registrations that load from this install's bridges\revit\. }
  if CurUninstallStep = usUninstall then
  begin
    { Before [Files] go: take out exactly the end-of-turn entries this install
      wrote (matched by its installed path); every other hook stays. }
    if FileExists(ExpandConstant('{app}\.venv\Scripts\python.exe')) then
      Exec(ExpandConstant('{app}\.venv\Scripts\python.exe'),
           '-E -s -B -m nodelang.assistant_registration disconnect-hooks',
           ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, HookResult);
    RemoveOwnRevitRegistrationsIn(ExpandConstant('{userappdata}') + '\Autodesk\Revit\Addins',
                                  ExpandConstant('{app}'));
    { Before [Files] removal deletes the shipped script this compares against. }
    RemoveOwnMaxStartupScriptsIn(ExpandConstant('{localappdata}') + '\Autodesk\3dsMax',
                                 ExpandConstant('{app}') + '\bridges\max\max_mcp_startup.py');
    { Only files this install placed and still byte-identical. }
    RemoveOwnAutocadBundle(ExpandConstant('{userappdata}') + '\Autodesk\ApplicationPlugins\ArchHub.AcadMCP.bundle');
  end;
end;

function NodeRuntimeNeedsInstall(): Boolean;
var
  InstalledRuntime: String;
begin
  InstalledRuntime := ExpandConstant('{app}\runtime\node.exe');
  Result := True;
  if FileExists(InstalledRuntime) then
  begin
    { Workshop may still use this executable after the desktop closes.
      Keep identical bytes in place; an unreadable file fails installation. }
    Result := CompareText(GetSHA256OfFile(InstalledRuntime), '{#BundledNodeSha256}') <> 0;
    if not Result then
      Log('Bundled Node runtime already matches SHA-256; preserving active Workshop processes.');
  end;
end;

function VersionScore(Name: String): Integer;
var
  I, Major, Minor: Integer;
  Digits: String;
  SeenDot: Boolean;
begin
  { "Python314" -> 314, "Python39" -> 39, "pythoncore-3.14-64" -> 314,
    "Python3" -> 3: enough to rank a fresh 3.14 above an older 3.x that
    sorts after it alphabetically (Python39 > Python314 as strings). }
  Major := 0; Minor := 0; Digits := ''; SeenDot := False;
  for I := 1 to Length(Name) do
  begin
    if (Name[I] >= '0') and (Name[I] <= '9') then
      Digits := Digits + Name[I]
    else if (Name[I] = '.') and (Digits <> '') and not SeenDot then
    begin
      Major := StrToIntDef(Digits, 0); Digits := ''; SeenDot := True;
    end
    else if Digits <> '' then
      break;
  end;
  if SeenDot then
    Result := Major * 100 + StrToIntDef(Digits, 0)
  else
    Result := StrToIntDef(Digits, 0);
end;

function PythonRuns(Py: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(Py, '-c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,14) else 1)"',
                 '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function BestPythonUnder(Base, Pattern: String): String;
var
  Rec: TFindRec;
  Best: Integer;
  Candidate: String;
begin
  { Every matching folder is a candidate; the highest version that really
    answers 3.14 wins (the wheelhouse is cp314 only). The old code kept whichever folder FindNext listed
    last, so a fresh Python314 lost to an older sibling (audit 2026-09-06). }
  Result := ''; Best := -1;
  if FindFirst(Base + '\' + Pattern, Rec) then
  begin
    try
      repeat
        if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) then
        begin
          Candidate := Base + '\' + Rec.Name + '\python.exe';
          if FileExists(Candidate) and (VersionScore(Rec.Name) > Best) and PythonRuns(Candidate) then
          begin
            Best := VersionScore(Rec.Name);
            Result := Candidate;
          end;
        end;
      until not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
end;

function FindPython(): String;
begin
  { Absolute paths only. A bare 'py' or 'python' is resolved from the
    installer's own folder first, so a file planted beside the setup on a
    share would run before the person has consented to anything. The three
    places python.org and the Python install manager write to, per user
    first, then all users. }
  Result := BestPythonUnder(ExpandConstant('{localappdata}') + '\Python', 'pythoncore*');
  if Result <> '' then exit;
  Result := BestPythonUnder(ExpandConstant('{localappdata}') + '\Programs\Python', 'Python3*');
  if Result <> '' then exit;
  Result := BestPythonUnder(ExpandConstant('{pf}'), 'Python3*');
end;

function PythonPresent(): Boolean;
begin
  { FindPython only returns a python.exe that already answered 3.14. }
  Result := FindPython() <> '';
end;

const
  CleanCoordinationTask = 'ArchHub Clean Coordination';
  UniversalRuntimeTask = 'ArchHub Universal Runtime';

{ The old task is removed at the next installed upgrade. It must never start
  a second application owner. No task is created or refreshed. }
procedure RemoveRetiredRuntimeTask(TaskName: String);
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN "' + TaskName + '"', '',
       SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN "' + TaskName + '" /F', '',
       SW_HIDE, ewWaitUntilTerminated, Code);
  if Code <> 0 then
    Log('Retired runtime task absent or unavailable (exit ' + IntToStr(Code) + ').');
end;


{ A colleague without Python is not sent away: the setup fetches the
  python.org installer (pinned by SHA-256, over HTTPS) and runs it quietly
  for this user only, no PATH change, no py launcher; FindPython then finds
  it in the per-user Programs\Python folder. Same Python the founder runs. }
const
  PythonUrl = 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.exe';
  PythonFile = 'python-3.14.7-amd64.exe';
  PythonSha256 = '9d9eb2709ef81bf5cd30db3c2096bdbc4ea10087c22e62f27d356b36f6ae9649';
  { CPython's WiX/Burn bootstrapper honors /norestart. The outer Inno
    restart controls do not propagate into this prerequisite process.
    Sources: github.com/wixtoolset/wix3/blob/develop/src/burn/engine/core.cpp
    and github.com/python/cpython/blob/3.14/Tools/msi/bundle/bootstrap/PythonBootstrapperApplication.cpp }
  PythonArgs = '/quiet /norestart InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Shortcuts=0';

var
  PythonPage: TDownloadWizardPage;
  PythonWanted: Boolean;

function OnPythonProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  PythonPage := CreateDownloadPage('Python',
    'ArchHub needs Python and this machine has none: fetching 3.14.7 from python.org.',
    @OnPythonProgress);
end;

function InstallPython(): Boolean;
var
  Code: Integer;
begin
  Result := False;
  PythonPage.Clear;
  PythonPage.Add(PythonUrl, PythonFile, PythonSha256);
  if not WizardSilent() then PythonPage.Show;
  try
    try
      PythonPage.Download;
    except
      if PythonPage.AbortedByUser then
        SuppressibleMsgBox('You stopped the Python download, so ArchHub was not installed.' + #13#10 +
          'Run this setup again when you are ready, or install Python 3.14 from python.org first.',
          mbInformation, MB_OK, IDOK)
      else
        SuppressibleMsgBox('Python could not be fetched from python.org: ' + GetExceptionMessage + #13#10 +
          'Install Python 3.14 from python.org, then run this setup again.',
          mbCriticalError, MB_OK, IDOK);
      exit;
    end;
  finally
    PythonPage.Hide;
  end;
  if not Exec(ExpandConstant('{tmp}\' + PythonFile), PythonArgs, '', SW_SHOW, ewWaitUntilTerminated, Code) then
  begin
    SuppressibleMsgBox('The Python installer would not start.', mbCriticalError, MB_OK, IDOK);
    exit;
  end;
  { CPython returns Windows ERROR_SUCCESS_REBOOT_REQUIRED (3010) or
    ERROR_SUCCESS_REBOOT_INITIATED (1641), not proof of a usable runtime.
    See learn.microsoft.com/en-us/windows/win32/msi/error-codes.
    Never request an outer restart or continue installation on either result. }
  if Code = 3010 then
  begin
    Log('Python prerequisite requires a restart (3010); ArchHub installation cannot continue yet.');
    SuppressibleMsgBox('Python requires a Windows restart to finish installation. ArchHub setup will not continue yet.' + #13#10 +
      'Save your work and restart Windows when you choose, then run this setup again.',
      mbInformation, MB_OK, IDOK);
    exit;
  end;
  if Code = 1641 then
  begin
    Log('Python prerequisite reported restart initiated (1641) despite /norestart; stopping ArchHub installation.');
    SuppressibleMsgBox('The Python installer reported that a Windows restart was initiated despite restart suppression.' + #13#10 +
      'ArchHub setup will not continue. Check the system state before running setup again.',
      mbCriticalError, MB_OK, IDOK);
    exit;
  end;
  if Code <> 0 then
  begin
    SuppressibleMsgBox('The Python installer ended with code ' + IntToStr(Code) + '.', mbCriticalError, MB_OK, IDOK);
    exit;
  end;
  Result := PythonPresent();
  if not Result then
    SuppressibleMsgBox('Python was installed but could not be found afterwards. Install Python 3.14 from python.org, then run this setup again.',
      mbCriticalError, MB_OK, IDOK);
end;

procedure CloseInstallConnectors();
var
  Code: Integer;
begin
  { Agents start the connector supervisor from ArchHub-Runtime; it closes its connector while this marker exists and
    starts it again after, so no agent reconnects. Connectors still started from the install itself (the launch
    before ArchHub-Runtime) are closed here so none of their files is in use. }
  SaveStringToFile(ExpandConstant('{app}\.archhub-installing'), '{#BuildId}', False);
  Sleep(2500);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like ''*native_agent_mcp*'' -and $_.CommandLine -like ''*' +
    ExpandConstant('{app}') + '*'' -and $_.CommandLine -notlike ''*mcp_supervisor.py*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure DeinitializeSetup();
begin
  { An unfinished setup puts back every host file it set aside. }
  RestoreRetiredHostFiles();
  { Connectors come back whether setup finished or not. }
  DeleteFile(ExpandConstant('{app}\.archhub-installing'));
end;

var
  BackupProgress: TOutputMarqueeProgressWizardPage;
  ConnectorWarnings: String;

procedure OnConnectorLog(const S: String; const Error, FirstLine: Boolean);
begin
  Log(S);
  BackupProgress.SetText(S, 'Checking existing assistant connections.');
  BackupProgress.Animate();
  if Pos('Connector warning:', S) > 0 then
    ConnectorWarnings := ConnectorWarnings + S + #13#10;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ReadyPath: String;
  ReadyIdentity: AnsiString;
  ConnectorCode: Integer;
begin
  { Match the private-environment receipt schema used by colleague_setup.py.
    Preserve a same-build receipt; invalidate older setup BEFORE replacing
    application files. The launcher independently validates the environment. }
  if CurStep = ssInstall then
  begin
    CloseInstallConnectors();
    { User data is preserved. Dropped product code is pruned after copying,
      once the complete installed inventory matches this build's manifest. }
    { Bridge DLLs for this build land in bridges\<host>\<year>\{#BuildId}\.
      A running Revit or AutoCAD keeps the DLL it already mapped. This setup
      does not replace that file, move it, or ask Restart Manager to close the host. }
    ReadyPath := ExpandConstant('{app}\.archhub-ready');
    if FileExists(ReadyPath) then
      if (not LoadStringFromFile(ReadyPath, ReadyIdentity)) or
         (Trim(String(ReadyIdentity)) <> 'venv-v1:{#BuildId}:{#RequirementsSha256}') then
        if not DeleteFile(ReadyPath) then
          RaiseException('The previous ArchHub setup marker could not be reset. Close ArchHub and retry setup.');
  end;
  { The installed build's identity, read by setup and the quiet updater. }
  if CurStep = ssPostInstall then
    HostFilesInstalled();
  if CurStep = ssPostInstall then
  begin
    if not SaveStringToFile(ExpandConstant('{app}\BUILD_ID'), '{#BuildId}', False) then
      RaiseException('The ArchHub build identity could not be saved. Run setup again.');
    if not ExecAndLogOutput(FindPython(), '-u -E -s -B "' + ExpandConstant('{app}') + '\nodelang\host_addin_retarget.py" --prune "' + ExpandConstant('{app}') + '" {#InstalledManifestSha256}',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ConnectorCode, @OnConnectorLog) then
      RaiseException('Product prune could not start; installation is incomplete.');
    if ConnectorCode <> 0 then
      RaiseException('Product prune failed; installation is incomplete. See the install log.');
    { Retarget reviewed host payloads and retire unsupported Revit manifests.
      The helper logs third-party manifest hashes before and after its work. }
    if FindPython() <> '' then
    begin
      if not ExecAndLogOutput(FindPython(), '-u -E -s -B "' + ExpandConstant('{app}') + '\nodelang\host_addin_retarget.py" "' + ExpandConstant('{app}') + '"',
          ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ConnectorCode, @OnConnectorLog) then
        Log('Host add-in retarget could not start. Host registration is incomplete; see the install log.')
      else if ConnectorCode <> 0 then
        Log('Host add-in retarget exited ' + IntToStr(ConnectorCode) + '. Host registration is incomplete; see the install log.');
    end;
    { After BUILD_ID: the task script recognises an installed tree by it. }
    RemoveRetiredRuntimeTask(CleanCoordinationTask);
    RemoveRetiredRuntimeTask(UniversalRuntimeTask);
    { The "Connect my AI assistants" choice; the first open honours it once. }
    if WizardIsTaskSelected('connectassistants') then
    begin
      if not SaveStringToFile(ExpandConstant('{app}\.assistant-hooks-consent'), 'connect-assistants-v1', False) then
        RaiseException('The assistant connection choice could not be saved. Run setup again.');
    end
    else
      DeleteFile(ExpandConstant('{app}\.assistant-hooks-consent'));
    BackupProgress.SetText('Updating recognised assistant connections', 'Unrecognised settings are left untouched.');
    ConnectorWarnings := '';
    if not WizardSilent() then BackupProgress.Show();
    try
      if not ExecAndLogOutput(FindPython(), '-u -E -s -B -m nodelang.assistant_registration migrate-connectors',
          ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ConnectorCode, @OnConnectorLog) then
        ConnectorWarnings := 'Assistant migration could not start. Existing client settings were kept; use Settings to Repair.'
      else if ConnectorCode <> 0 then
        ConnectorWarnings := ConnectorWarnings + 'Assistant migration needs Repair in Settings; Setup completed and existing settings were kept.';
    finally
      BackupProgress.Hide();
    end;
    if ConnectorWarnings <> '' then
      Log(ConnectorWarnings);
    { Connector entries now point at ArchHub-Runtime; the supervisors start their connectors again. }
    DeleteFile(ExpandConstant('{app}\.archhub-installing'));

  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BackupCode: Integer;
  ConnectorTemp: String;
begin
  { Before any file is copied, a machine without Python 3.14 (e.g. 3.12 only)
    gets the pinned 3.14.7. If it still has none, the reason is returned: Inno
    then stops Setup showing it, with a dedicated exit code, so the quiet
    updater can tell a missing Python from any other failure. }
  Result := '';
  if PythonWanted and (not PythonPresent()) then
    if not InstallPython() then
      Result := 'ArchHub needs Python 3.14 and it could not be installed on this machine. ' +
                'Install Python 3.14 from python.org, then run this setup again.';
  if Result = '' then
  begin
    { The new classifier checks known retired shapes before deleting old code.
      A tiny extracted package has no application __init__ side effects. }
    ConnectorTemp := ExpandConstant('{tmp}\mainrel-connectors');
    ForceDirectories(ConnectorTemp + '\nodelang');
    SaveStringToFile(ConnectorTemp + '\nodelang\__init__.py', '', False);
#include PreflightCodePath
    BackupProgress := CreateOutputMarqueeProgressPage('Checking assistant connections',
      'Checking existing entries before replacing application files');
    ConnectorWarnings := '';
    if not WizardSilent() then BackupProgress.Show();
    BackupProgress.Animate();
    try
      if not ExecAndLogOutput(FindPython(), '-u -E -s -B -m nodelang.assistant_registration preflight-connectors', ConnectorTemp, SW_HIDE, ewWaitUntilTerminated, BackupCode, @OnConnectorLog) then
        Result := 'Assistant connector preflight could not start. Your installed files were kept.'
      else if BackupCode <> 0 then
        Result := 'Assistant connector preflight refused. Your installed files were kept.';
    finally
      BackupProgress.Hide();
    end;
    if ConnectorWarnings <> '' then
      Log(ConnectorWarnings);
  end;
  if Result <> '' then
    Log('ArchHub Setup refused: ' + Result);
end;

function InitializeSetup(): Boolean;
begin
  { No Python 3.14: PrepareToInstall fetches the pinned one before any file is
    copied. }
  Result := True;
  PythonWanted := not PythonPresent();
  if PythonWanted and (not WizardSilent()) then
    MsgBox('This machine has no Python 3.14.' + #13#10 +
           'Setup will fetch Python 3.14.7 from python.org (about 33 MB) and install it for you only, before it installs ArchHub.',
           mbInformation, MB_OK);
end;
