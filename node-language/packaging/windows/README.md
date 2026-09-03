# ArchHub Windows packaging

This directory is the reproducible packaging source, not an artifact directory.
Generated virtual environments, PyInstaller bundles, installers, and checksums
go under `%LOCALAPPDATA%\ArchHub\packaging` by default and must not be committed.

## Contract

- `ArchHub.spec` creates a windowed, x64 PyInstaller `onedir` bundle containing
  Python, PyQt6 WebEngine, cryptography, the opt-in Windows speech adapter, and
  the node-native runtime. Speech recognition begins only after the founder
  presses `Talk`; the adapter holds no background listener or retained audio.
- The package includes the transparent BABOOM animation atlas. The companion is
  assembled only through its explicit runtime handoff path; packaging it does
  not create a second holder or enable a background desktop overlay.
- `setup.iss` wraps that bundle in a per-user Inno Setup 6 installer and creates
  Start Menu and optional Desktop shortcuts.
- `Launch-ArchHub.vbs` resolves only the bundled `ArchHub.exe`, launches hidden,
  and fixes the WIP graph at
  `%LOCALAPPDATA%\ArchHub\node-native-wip.json.gz`.
- The install directory is `%LOCALAPPDATA%\Programs\ArchHub`. Uninstall removes
  application files but deliberately preserves the WIP directory.
- The desktop runtime's `QLockFile` remains the single-instance authority.
- `package-manifest.json` is the version/schema contract. A schema change makes
  `build.ps1` fail until the manifest is updated deliberately.

## Commands

```powershell
.\packaging\windows\build.ps1 -ValidateOnly
.\packaging\windows\build.ps1 -SkipInstaller
.\packaging\windows\build.ps1
.\packaging\windows\build.ps1 -Sign
```

`-Sign` requires `signtool.exe` and `ARCHHUB_SIGN_CERT_SHA1`, referencing a
code-signing certificate already held in the Windows certificate store. No
certificate file or password belongs in this repository or on the command line.

The build stops before packaging when source contains private or machine-bound
absolute paths. That currently protects the public package from accidentally
embedding the private Grand Map authority.
