# Running ArchHub on multiple devices

One ArchHub source, many machines. Two layers sync independently:

| Layer | What | How |
|-------|------|-----|
| **Code** | The ArchHub app itself | Private GitHub repo (single source of truth) |
| **Skills** | Your saved skill JSONs | OneDrive-symlinked folder (cloud sync) |
| **API keys** | LLM credentials | Stay per-machine (Windows Credential Manager is local) |

This guide walks both layers from scratch on a new device.

---

## 1. Code: GitHub private repo

### One-time, on the first device

```cmd
cd C:\Users\<you>\00.ARCHUB\ArchHub

REM 1. Create the private repo on GitHub (web UI or gh CLI)
REM    https://github.com/new   →   Repository name: ArchHub   →   Private

REM 2. Wire your local repo to GitHub and push
git remote add origin https://github.com/<your-username>/ArchHub.git
git branch -M main
git push -u origin main
```

If you prefer the CLI:

```cmd
winget install GitHub.cli
gh auth login
gh repo create ArchHub --private --source . --remote origin --push
```

### On every other device

```cmd
cd C:\Users\<you>
mkdir 00.ARCHUB
cd 00.ARCHUB
git clone https://github.com/<your-username>/ArchHub.git
cd ArchHub

REM Restore Python deps
pip install -r app/requirements.txt
pip install -r requirements.txt
```

That's it for code. `git pull` from any device picks up changes made on
any other.

### Day-to-day flow

```cmd
git pull                          REM start of day, on each machine
... edit / build / run ...
git add -A
git commit -m "feat: my change"
git push                          REM share with the other devices
```

---

## 2. Skills: OneDrive-symlinked folder

ArchHub stores your Skills at `%LOCALAPPDATA%\ArchHub\workflows\`.
Replace that folder with a symlink to a OneDrive folder so every device
reads and writes the same Skills.

### One-time, on every device

```cmd
REM Choose where in OneDrive the canonical folder lives.
set CANONICAL=%OneDrive%\ArchHub\workflows
mkdir "%CANONICAL%"

REM Wipe the local folder if it has nothing important yet.
rmdir /S /Q "%LOCALAPPDATA%\ArchHub\workflows"

REM Symlink. Run from an Admin terminal — mklink needs SeCreateSymbolicLink.
mklink /D "%LOCALAPPDATA%\ArchHub\workflows" "%CANONICAL%"
```

If you have Skills you want to preserve:

```cmd
robocopy "%LOCALAPPDATA%\ArchHub\workflows" "%CANONICAL%" /MIR
rmdir /S /Q "%LOCALAPPDATA%\ArchHub\workflows"
mklink /D "%LOCALAPPDATA%\ArchHub\workflows" "%CANONICAL%"
```

After this, `/skill save` on Device A is visible to Device B within
seconds (whatever OneDrive's sync delay is).

### Alternatives if OneDrive isn't your thing

- **Dropbox / Google Drive** — same `mklink` pattern, just point at a
  different cloud folder.
- **A second Git repo for skills** — keep Skills under version control
  and review them like code. Set up:
  ```cmd
  cd %OneDrive%\ArchHub
  git init workflows
  cd workflows
  git remote add origin https://github.com/<you>/ArchHub-skills.git
  ```
  Then commit + push whenever a Skill changes. Pull on each device.
- **Network share** — `mklink` to `\\fileserver\ArchHub\skills\`. Good
  for office workstations behind one LAN.

### Ad-hoc per-skill sharing

Even with OneDrive set up, you can still send a single Skill to a
colleague who doesn't share your sync folder:

- In chat: `/skill share <name>` copies the JSON. Paste into Slack /
  email. They run `/skill import`.
- In the Skills panel: hit **Share** (clipboard) or **Export** (file).
  They drag-and-drop the file onto their Skills panel.

---

## 3. API keys

Windows Credential Manager is per-machine. There is no automatic sync.
On each new device:

1. Launch ArchHub.
2. Settings (⚙) → add the keys you have (Anthropic, OpenAI, Google,
   Speckle PAT).
3. (Optional) If you run local Ollama, install Ollama on each device —
   the model files themselves are large, sync via Ollama's own pull
   commands (`ollama pull qwen2.5-coder:7b`), not OneDrive.

---

## 4. Connectors

Connectors detect installed AEC apps on each machine. If your laptop has
Revit 2024 only and your workstation has Revit 2024 + 2025 + AutoCAD,
each device's Connectors panel correctly reflects what is locally
installed. Nothing to sync.

The `payload/sources/<host>` C# / Python sources are checked into the
Git repo, so each device can rebuild the same DLLs locally with the
same `dotnet build` invocation — no need to ship binaries through Git.

---

## Troubleshooting

### `mklink` says "You do not have sufficient privilege"

You need an Admin terminal or Developer Mode enabled
(Settings → System → For developers → Developer Mode). Developer Mode
allows non-admin symlink creation.

### Symlinked folder shows `0 skills`

OneDrive may have downgraded the folder to "online-only". Right-click in
File Explorer → "Always keep on this device".

### `git push` rejects with "permission denied"

Check `git remote -v` matches your fork. Use a Personal Access Token
(PAT) for HTTPS auth, or set up SSH keys: `gh auth login` handles both.

### Skills disappear after sync

If two devices write to the same Skill JSON file at the same instant,
OneDrive may rename one as a "conflict" copy. Open the conflict file,
copy the JSON, run `/skill import` to restore it, and delete the
conflict file. Long-term we'll move to a CRDT-based sync; for now,
saving from one device at a time is the safe pattern.
