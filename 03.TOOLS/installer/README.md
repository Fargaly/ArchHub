Windows installation, upgrade and release orchestration.

Fresh-machine court: run `python 03.TOOLS/tools/fresh_machine_check.py --out
05.EVIDENCE/freshmachine/latest` through the machine's heavy-work queue. It
downloads GitHub Latest with `gh`, redirects profile variables, removes external
tools from PATH, installs silently, and launches the installed shortcut headlessly.
Use a disposable Windows account with no existing ArchHub state: changing
USERPROFILE/LOCALAPPDATA does not isolate Inno shell-folder constants, HKCU,
Credential Manager, or machine-wide scheduled-task names. The court refuses a
protected account before executing the installer. `--inventory-only` is safe in
the builder account; `--installer` selects an already downloaded setup.

Installed agent governance uses `nodelang.agent_onboard`, generated from the
shipped specification and the existing hook renderers. No private workspace
ledger, global rulesync install, founder keys, or scheduled task is its source.
Claude, Codex and Gemini have portable adapters; other agents' native governance
remains explicitly unsupported until their product adapters are provided.
