"""The /docs pages the public website projects.

Each page is plain text the website build turns into Cells; the text says
what build 20260916-2130-e733a13 does, read from its source.
"""

from types import MappingProxyType


DOCS_PAGES = MappingProxyType({
    "getting-started": (
        "Getting started",
        "Install ArchHub on Windows, let the first open finish setting up, sign in from the app and keep it up to date.",
        """\
ArchHub is a Windows desktop app. This page covers the installer, the first open, signing in and updates as they work in build 20260916-2130-e733a13.

## Install

1. Download `ArchHub-Setup-0.exe` from the ArchHub releases page on GitHub.
2. Run it. It installs for your Windows user only, into `%LOCALAPPDATA%\\ArchHub`, and does not need administrator rights. The install folder cannot be changed.
3. ArchHub needs Python 3.11 or newer. If setup cannot find it, setup downloads Python from python.org for your user only, without changing your PATH. If that download fails or is cancelled, setup stops with a message. If Python asks for a restart, restart Windows and run setup again.
4. Setup adds ArchHub and Uninstall ArchHub to the Start menu, and a desktop shortcut if you tick that option.

The installer is not code-signed. Windows may warn you before it runs, depending on how you got the file and your machine's policy.

## First open

Tick "Open ArchHub now" on the last setup page, or open ArchHub from the Start menu.

The first time, a console window opens before the app. It prints "Preparing this ArchHub build. ArchHub opens by itself when it finishes." While it runs, it:

- creates a private Python environment and installs what ArchHub needs,
- checks that everything loads,
- lists the design applications it finds on this machine, without opening any of them,
- asks once whether to connect ArchHub tools to Claude Code for your Windows user. The default answer is no.

When it prints "ready. ArchHub is opening now." the app window opens.

If a step fails, the window prints REFUSED with the reason, stays open, and marks nothing as ready. Keep that text for support.

If the app itself cannot start, a message box says "ArchHub could not open." and names the log file, `%LOCALAPPDATA%\\ArchHub-Test\\launcher.log`.

Closing the ArchHub window hides it to the system tray. ArchHub keeps running until you quit it from the tray.

## Sign in

You can use the canvas without signing in. Signing in connects your email account to the ArchHub cloud.

1. Click sign in in the status strip, or open Settings and go to Account.
2. Choose Continue with Google or Email me a sign-in link.
3. Finish in the browser window that opens. The dialog updates by itself and shows "signed in" with your email. If you do not finish within five minutes, the attempt times out and you can start again.

The Account page has the details.

## Updates

ArchHub checks the GitHub releases page two minutes after it opens and every thirty minutes after that. You can check at any time with Check for updates now in the tray menu, or Check and download in Settings, About.

When a newer build is published, ArchHub downloads the installer and compares it with the checksum published with that release. A file that does not match is refused, and an older or equal build is never staged. The checksum shows that the file arrived intact; it is not a signature.

To install a downloaded update, choose Restart to install the update in the tray menu, Update and reload in the app, or Restart now when BABOOM offers it. ArchHub closes, keeps a recovery copy, installs the update and opens again.

## Known problems in this build

- If an update fails to install, ArchHub does not open and shows no message; the reason is written only to `%LOCALAPPDATA%\\ArchHub-Test\\launcher.log`.
- Check for updates in the BABOOM menu reports only whether an update is already downloaded. It does not check GitHub.
- After an update, the setup console window may run again before the app opens.
- BABOOM may keep saying an update is ready after it has been installed.
""",
    ),
    "composer-canvas": (
        "The canvas and the composer",
        "Add nodes, wire them, edit their properties, run the graph, and ask the composer to draft changes for you to review.",
        """\
The canvas holds your work: nodes, the wires between them and their properties. The composer drafts changes to the canvas from a request you type. Nothing a model drafts runs until you run it.

## Add a node

- Drag a node from the Nodes panel onto the canvas, or double-click it.
- Or open the Node library from the + button in the toolbar, from Add node in the right-click menu, or from the library button in the composer. Search, then click a node to add it.

Nodes come in nine categories, each with its own colour: Host, Read, Filter, Transform, Annotate, Compose, Logic, AI and Output.

## Connect nodes

Click an output socket, then a compatible input socket. While you choose, the status line tells you which node the wire starts from, and its cancel button stops. Output sockets are filled and input sockets are hollow. A wire takes the colour of the kind of data it carries.

## Select, move and arrange

- Click a node to select it. Shift-click adds or removes nodes. Click empty canvas to clear the selection. Click a wire to select it.
- The right-click menu selects direct neighbours, the connected group, or everything, and clears the selection. Shift+F10 opens the same menu from the keyboard.
- Drag nodes to move them. Positions are saved when you release the mouse, and the status line shows "Saving positions" while that happens. You can move or arrange up to 256 nodes at a time.
- Undo last layout in the right-click menu puts positions back. It covers positions only.

## Zoom and pan

Use the mouse wheel to zoom around the pointer, or the zoom buttons and Fit in the toolbar. Drag empty canvas to pan. The right-click menu also has Fit selection, Fit all, Arrange selection and Arrange all, and a minimap shows the whole graph. Zoom and pan are not kept after a restart.

## Properties

Selecting a node opens the Properties panel on the right. It shows what the node receives and sends, and its parameters.

Every parameter edit is saved as you make it; there is no Save button. If an edit cannot be saved, the panel says "not saved" and offers Retry unsaved edits. Each row can be reverted on its own, and Revert all reverts every row.

To delete a node or a wire, use the delete control in the Properties panel and confirm.

## Run the graph

Press Run graph in the Properties panel. ArchHub waits for pending parameter saves, runs every node in the graph along its wires, and shows each result on its node. One run happens at a time. If something fails, the panel says so, for example "Graph execution failed." or that some nodes did not complete.

## Where your work is saved

Your graph, with its node positions, parameters and wires, is saved on this machine under `%LOCALAPPDATA%\\ArchHub` and survives a restart. The last model the composer used is saved with it. The last run result is not kept.

## The composer

Type into the box at the bottom of the canvas, or start from Home with Start a new session. With an AI node selected, you can also ask it from its Properties panel.

The composer sends your request to the model you picked and turns the reply into draft changes on the canvas: placing and grouping nodes, wiring them and setting properties. It applies up to twelve changes per request and stops at the first one that fails. Its reply ends with "Draft updated on the canvas. Review its nodes, connections and parameters." or tells you what needs attention.

A draft stays a draft. If the model asks to run it, nothing runs; the graph runs only when you press Run graph.

If no model is picked, the composer answers "No model chosen" and asks you to pick one.

## Pick a model

Open the model picker from the model button in the header or on Home. It lists models in three groups: CLOUD, through your ArchHub account; BYO, through OpenRouter with your own key; and LOCAL, from LM Studio or Ollama running on this machine. You can search, refresh or clear the choice. With an AI node selected, picking a model sets that node's model.

To use your own OpenRouter key, open Settings, Providers, paste the key into OpenRouter API key and press Save OpenRouter key. The key is stored on this machine, protected with Windows DPAPI for your user. Saving does not test the connection. A key set in the OPENROUTER_API_KEY environment variable takes priority.

For free models, pick a model whose route ends in `:free`, or the `openrouter/free` route. In free mode ArchHub refuses routes that are not free and rejects any reply that reports a cost.

If a provider limits requests, you see "The model provider is rate-limiting requests (HTTP 429)." ArchHub does not retry by itself. Wait, or pick another model.

## Not working in this build

- Most keyboard shortcuts listed in Settings do nothing.
- There is no undo or redo for graph edits. Undo last layout covers positions only.
- Save as skill and Fork in the Properties panel do nothing.
- The table in Settings, Model routing is fixed, and its buttons do nothing.
- Ollama routes cannot take images.
""",
    ),
    "brain": (
        "The brain and cloud sync",
        "What the ArchHub brain is in this build, how cloud sync works, what it uploads and what it keeps.",
        """\
The brain is ArchHub's memory: facts and skills learned from your work. This page describes what runs in build 20260916-2130-e733a13, and says plainly where the brain is not finished.

## What runs today

ArchHub has no separate brain service. The brain is part of the application: its facts and skills live in the ArchHub graph on this machine, next to your work. The earlier brain service, which listened on this machine and kept its own database, is retired; its facts, skills and setup notes are carried into the graph once, and nothing listens for it any more.

## Skills

Skills are meant to be learned from finished work and promoted only with evidence. In this build the app sets up an empty skill library, but nothing in the app creates or promotes a skill yet, and Save as skill does nothing.

## Cloud sync

When cloud sync is on, ArchHub keeps a copy of your brain on our servers so it can reach your other devices and your firm. That copy is not end-to-end encrypted, and ArchHub's systems can read it. Recognised API-key formats are blocked from upload. Deleting your cloud brain removes your personal copy; entries you shared with a firm are not removed.

How that works in this build:

- Sync ran through the retired brain service, so it does not run in this build. The rules below describe how it works when it returns.
- Your personal facts and skills upload to your own space on the ArchHub cloud. Entries shared with a firm go to a shared copy that every member of that firm reads.
- Before upload, recognised keys inside an entry are replaced with `<redacted-secret>` and the rest of the entry uploads. An entry that is still a bare key is dropped. The cloud refuses them too. Recognised formats include keys that start with `sk-`, `sk_live_`, `AKIA` or `AIza`, GitHub and Slack tokens, and web tokens that start with `eyJ`.
- Deleting your cloud brain removes your personal copy. Shared firm copies stay, because other members rely on them.

## Firms and community

Sharing is designed so nothing arrives unreviewed. Items from a peer wait in quarantine until you admit or reject them. A group has one owner, who issues join codes that work once. Only the owner of a fact can share it, and only as a redacted version.

In this build these features are not reachable from the app window, and public community sharing is not open.

## Not working in this build

- There is no screen for browsing your facts, and the Brain and Team tabs in Settings show "not available".
- Skills cannot be created or promoted from the app.
- There is no button in the app to delete your cloud brain, and deleting it does not yet revoke your sign-in tokens.
""",
    ),
    "account-web": (
        "Your account",
        "Sign in with your email account, sign out, see your tier, and what the archhub.io website does and does not do.",
        """\
## Your identity is your email

An ArchHub account is an email address, not a machine. Sign in on another computer with the same email and it is the same account.

## Sign in

1. In the app, click sign in in the status strip, or open Settings and go to Account.
2. Choose Continue with Google or Email me a sign-in link.
3. Your browser opens on the ArchHub sign-in page. Finish there. The app waits for up to five minutes and updates by itself. When it is done, the app shows "signed in" with your email and the browser tab says "You are signed in".

The app listens on a temporary local address for a one-time code from the cloud and exchanges it for a session using PKCE. The session is saved on this machine in `%APPDATA%\\ArchHub\\brain\\cloud.json`.

If sign-in fails, the reason appears in red under the buttons and the browser tab says "Sign-in failed".

## Sign out

Settings, Account, Sign out clears the saved session on this machine straight away and tells the cloud in the background.

## What needs an account

The canvas, the composer with your own key or a local model, and connectors on this machine work without signing in. Signing in is needed for the CLOUD models in the model picker and for brain cloud sync.

## Tiers and the offer

Each account has a tier: free, pro, firm or founder. New accounts start on free. Your tier is shown in Settings, Account. In this build the tier does not change what the app lets you do.

ArchHub is Free during beta.

## The archhub.io website

The website describes ArchHub. It has no sign-in form and keeps no session; you sign in from the app. The installer is published on the ArchHub releases page on GitHub.

## Not working in this build

- The saved session's expiry is not checked, so the app can show you as signed in after the cloud session has expired.
- The sign-up screen shown after you sign out lists sample host names and mentions a credit card; neither reflects your machine or the beta offer.
- Usage limits show "not available", and the spend-limit buttons are not enforced.
- The Brain and Team tabs in Settings show "not available".
""",
    ),
    "connectors": (
        "Connectors",
        "Which applications ArchHub can reach in this build, what each one needs, and which are not available yet.",
        """\
A connector lets ArchHub read from, or act in, an application you already use. This page lists what works in build 20260916-2130-e733a13 and what does not yet.

## At a glance

| Application | Status in this build | What it needs |
| --- | --- | --- |
| Word, Excel, PowerPoint | Works, read only | The application already open; setup installs the Windows component ArchHub uses |
| Revit | Needs an add-in this build does not install | The ArchHub Revit add-in and a Revit document open |
| Rhino | Bridge included | Load the included bridge in Rhino 8 (Python 3) |
| Blender | Bridge included | Install the included add-on in Blender 3.6 or newer |
| AutoCAD | Not available yet | Source code only |
| 3ds Max | Not available yet | A plug-in this build does not ship |
| Outlook, Notion, Dropbox | Checked for setup only | An Outlook account, a Notion token, or a local Dropbox folder |
| LinkedIn, Facebook Pages, Instagram | Built, not live yet | Not yet accepted for use |

During the first open, setup lists the design applications it finds on this machine without opening any of them.

## Word, Excel and PowerPoint

ArchHub joins an application you already opened. It does not start one to read from it. It can read the open documents, workbooks, worksheets, presentations, slides and paragraphs, and refuses anything else. It does not change your files. If you use Open host in ArchHub for an Office application, that application starts in a visible window.

## Revit

ArchHub finds each running Revit session that has the ArchHub add-in loaded, by checking local ports 48884 to 48899, and needs a document open in that session. This build does not install the add-in; setup reports that it has no connector payload for Revit.

The current Revit add-in accepts requests without authenticating them. Install it only on a machine you trust.

## Rhino and Blender

Their bridges are included with the installer. Load the Rhino bridge in Rhino 8 with Python 3; ArchHub looks for it on port 9879. Install the Blender add-on in Blender 3.6 or newer; ArchHub looks for it on port 9876.

## AutoCAD and 3ds Max

Not available in this build. The AutoCAD bridge exists only as source code, and 3ds Max needs a plug-in that this build does not ship.

## Outlook, Notion and Dropbox

ArchHub checks whether each one is set up: an Outlook account, a Notion token, or a local Dropbox folder.

## LinkedIn, Facebook Pages and Instagram

These connectors use the official APIs and are built, but not live. Every action they take needs your approval, a one-use grant and a receipt, and the approval screen for them is not finished.

## How connector actions are recorded

When a connector action is recorded in your graph, the graph keeps the request, the exact permission it used, a one-use grant and a redacted outcome. Credentials and what the application returns stay with the connector on your machine.
""",
    ),
})
