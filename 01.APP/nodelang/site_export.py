"""Read-only documentation and static asset projection from current catalogues."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path



PUBLICATION_TIER = "T0 PUBLIC"
EXPORT_FORMAT = "archhub-universal-cell-site-v2"


class SiteExportError(ValueError):
    """The graph cannot be projected into a safe public artifact."""



# Documentation is a disposable projection. No copied catalogue or persisted docs.
from types import MappingProxyType
from .base_universal_catalogue import BASE_CATALOGUE
from .clean_host_catalogue_source import HOST_OPERATION_RECORDS



def starter_tutorials(build_id):
    """One how-to per runnable starter in the SAME catalogue that seeds Home."""
    from .starters import _usage_starters
    from .library_engines import library_catalogue
    catalogue = {row["id"]: row for group in library_catalogue() for row in group["items"]}
    operations = {row["op_id"]: row for row in HOST_OPERATION_RECORDS}
    pages = {}
    for item, title, _frequency, children in _usage_starters():
        title = title.replace("\u2192", "to")
        steps = []
        for index, child in enumerate(children, 1):
            row = catalogue[child["item"]]
            params = ", ".join("%s=%s" % pair for pair in child["params"].items()) or "none"
            availability = row.get("reason", "Check the node result after Run.")
            operation = child["params"].get("operation", child["engine"])
            description = operations.get(operation, {}).get("description", row["sub"])
            steps.append("%d. %s: %s Parameters: %s. %s" % (
                index, child["title"], description, params, availability))
        pages["tutorial-" + item.removeprefix("tpl-")] = (
            title, "Open the %s starter from Home and inspect its nodes." % title,
            "Documentation for build %s.\n\n" % build_id
            + "## Open from Home\n\n"
            + "Choose Home, find `%s`, then choose Start. " % title
            + "Start places the wired nodes on the canvas. It does not run them. "
            + "Choose Edit on Home to change the stored template.\n\n"
            + "## Inspect the steps\n\n" + "\n".join(steps)
            + "\n\n## Run and check\n\n"
            + "Check the source connection and parameters before Run. Read each node's result. "
            + "A missing host, account, or engine is a blocker, not a completed result. "
            + "These starters read, sort and display data; they do not issue a whole job.\n\n"
            + "## Installed screenshot\n\n"
            + "The capture below shows Home with all six starter choices and no completed results. "
            + "It proves the entry point, not a successful run of this tutorial.\n")
    return pages


def current_surfaces_markdown():
    """Use application tool and connection catalogues, without probing accounts."""
    from .canvas_documents import thing_items
    from .social_connections import NETWORKS
    from .starters import _usage_starters
    return ("\n\n## Home templates\n\n"
        + "\n".join("- " + title.replace("\u2192", "to") for _, title, _, _ in _usage_starters())
        + "\n\nStart places a template on the canvas; Edit changes the stored template. "
        + "Home shows running work, approvals and completed results when they exist.\n\n"
        + "## Settings and System graph\n\nOpen Settings, then System graph to inspect application nodes.\n\n"
        + "\n".join("- " + row["title"] for row in thing_items())
        + "\n\n## Connections\n\nSettings has a Connections page for provider sign-in. "
        + "The networks listed by this build are: " + ", ".join(NETWORKS.values()) + ". "
        + "A listed provider is not a connected account. Read its state and blocker; "
        + "provider configuration and review may still be required. Agents draft; you approve each send.\n")


def documentation_goose_version(app_dir=None):
    """Read selected package metadata; it is never evidence of a live process."""
    roots = [Path(app_dir) if app_dir is not None else Path(__file__).resolve().parents[1]]
    for root in roots:
        for relative in ("packaging/windows/goose-pin.json", "runtime/goose/manifest.json"):
            try:
                data = json.loads((root / relative).read_text(encoding="utf-8"))
                # the pin is the typed goose.source node (version in its params); the deployed manifest is flat
                value = (data["params"] if data.get("id") == "goose.source" else data)["version"]
                if isinstance(value, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
                    return value
            except (OSError, ValueError, KeyError, TypeError):
                pass
    return "unavailable"


def documentation_build_id(app_dir=None):
    """Use only the selected package; never borrow another installation's stamp."""
    from .quiet_update import installed_build_id
    roots = [Path(app_dir) if app_dir is not None else Path(__file__).resolve().parents[1]]
    for root in roots:
        build = installed_build_id(root)
        if build:
            return build
        try:
            build = json.loads((root / "BUILD_METADATA.json").read_text(encoding="utf-8"))["build_id"]
            if isinstance(build, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,256}", build):
                return build
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return "unavailable"


def documentation_host_artifacts(app_dir=None):
    roots = [Path(app_dir) if app_dir is not None else Path(__file__).resolve().parents[1]]
    for root in roots:
        try:
            data = json.loads((root / "HOST_ARTIFACTS.json").read_text(encoding="utf-8"))
            if data.get("schema") == "archhub-host-artifacts-index/v1":
                return data
        except (OSError, ValueError, AttributeError):
            pass
    return {}


def _documentation_nodes(catalogue=None):
    entries = BASE_CATALOGUE if catalogue is None else catalogue
    return [
        {"id": str(row.get("id") or row.get("root") or row.get("name") or row.get("title") or ""),
         "category": str(row.get("category") or "Nodes"),
         "title": str(row.get("name") or row.get("title") or ""),
         "detail": str(row.get("description") or row.get("sub") or row.get("detail") or "")}
        for row in entries
    ]


def catalogue_docs_markdown(catalogue=None):
    groups = {}
    for row in _documentation_nodes(catalogue):
        groups.setdefault(row["category"], []).append(row)
    return "\n\n".join(
        "### %s\n\n%s" % (category, "\n".join(
            "- `%s` - %s" % (row["title"], row["detail"]) for row in rows))
        for category, rows in groups.items())


def connector_docs_markdown(host_artifacts=None):
    artifacts = documentation_host_artifacts() if host_artifacts is None else host_artifacts
    counts = {}
    for row in HOST_OPERATION_RECORDS:
        counts[row["host"]] = counts.get(row["host"], 0) + 1
    labels = {"revit": "Revit", "autocad": "AutoCAD", "max": "3ds Max",
              "excel": "Excel", "word": "Word", "powerpoint": "PowerPoint"}
    lines = ["| Application | Catalogue operations | Packaged artifact evidence |",
             "| --- | --- | --- |"]
    for host in dict.fromkeys([*counts, *(k for k,v in artifacts.items() if isinstance(v, dict))]):
        versions = artifacts.get(host, {})
        reviewed = sorted(str(year) for year, record in versions.items()
                          if isinstance(record, dict) and record.get("reviewed") is True)
        status = ("Reviewed artifacts: " + ", ".join(reviewed) if reviewed else
                  "Reviewed startup script" if versions.get("reviewed") is True else
                  "No reviewed artifact recorded")
        lines.append("| %s | %s | %s |" % (labels.get(host, host), counts.get(host, 0), status))
    return "\n".join(lines)


def documentation_pages(*, build_id=None, host_artifacts=None, catalogue=None):
    stamp = documentation_build_id() if build_id is None else build_id
    replacements = {"{build}": stamp, "{catalogue}": catalogue_docs_markdown(catalogue),
                    "{connectors}": connector_docs_markdown(host_artifacts),
                    "{operations}": "\n".join("- %s: %s" % (row["label"], row["description"])
                                              for row in HOST_OPERATION_RECORDS)}
    def render(value):
        for key, replacement in replacements.items():
            value = value.replace(key, replacement)
        return value
    pages = {key: tuple(render(value) for value in values)
             for key, values in _DOCS_TEMPLATES.items()}
    title, description, body = pages["getting-started"]
    pages["getting-started"] = (title, description, body + current_surfaces_markdown())
    title, description, body = pages["brain"]
    pages["brain"] = (title, description, body + "\n\n## BABOOM\n\n"
        + "BABOOM uses the packaged Goose %s runtime. " % documentation_goose_version()
        + "Startup checks its package and digest. A missing or changed package is a blocker; repair ArchHub. "
        + "BABOOM accepts free OpenRouter routes or local Ollama models. Its tool can read connected-host state. "
        + "Presence starts in the tray. Settings > BABOOM > Shows as selects Screen, Tray or Hidden. "
        + "Screen uses a small edge sprite that yields to your work. Connection status is a dot and tooltip; "
        + "Open ArchHub is in the tray menu. With ArchHub open, click BABOOM beside the composer. "
        + "Type your message in the composer and read the reply in BABOOM's panel. "
        + "The number on BABOOM counts the items under Needs you on Home. "
        + "Direct Brain, host and file writes are not exposed by this runtime. "
        + "Outside changes still need the existing Approve flow.\n")
    pages.update(starter_tutorials(stamp))
    if tuple(pages) != DOCS_KEYS:
        raise SiteExportError("tutorial routes differ from the starter catalogue")
    return pages


def project_documentation(catalogue=None):
    return {"nodes": _documentation_nodes(catalogue),
            "tutorials": [{"id": key, "title": title, "description": description, "text": body}
                          for key, (title, description, body) in documentation_pages(catalogue=catalogue).items()]}


def project_tutorial_documentation():
    return project_documentation()["tutorials"]


BANNED_PUBLIC_CLAIMS = (
    "needs an add-in this build does not install",
    "this build does not install the add-in", "save any thread as a skill",
    "nothing happens that you can't see, trace, or undo", "tower-a",
    "plotted on friday", "manual restarts", "median recovery",
    "no revit add-in installed", "undo anything",
    "bring your own key", "bring your own api key", "paste your api key",
    "paste an api key", "goose is running",
)


def validate_public_claims(document):
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", document))).lower().replace("\u2019", "'")
    for phrase in BANNED_PUBLIC_CLAIMS:
        if phrase in text:
            raise SiteExportError("untrue public claim: " + phrase)


_DOCS_TEMPLATES = MappingProxyType({'getting-started': ('Getting started',
                     'Install ArchHub on Windows, let the first open finish setting up, sign in from the app '
                     'and keep it up to date.',
                     'Documentation for build {build}.\n'
                     '\n'
                     '## What is ArchHub?\n'
                     '\n'
                     'ArchHub is a Windows desktop app. On the canvas, connect nodes with wires to build '
                     'a workflow. Use the composer to draft changes from a request you type.\n'
                     '\n'
                     'آرك هب تطبيق سطح مكتب لنظام ويندوز. في لوحة العمل، صِل العقد ببعضها لبناء سير عمل. '
                     'استخدم مربع الكتابة لاقتراح تغييرات من طلب تكتبه.\n'
                     '\n'
                     '## Install\n'
                     '\n'
                     '1. Download the Windows installer from archhub.io (`ArchHub-Setup-0.exe` on the '
                     'ArchHub releases page on GitHub).\n'
                     '2. Run it. It installs for your Windows user only, into `%LOCALAPPDATA%\\ArchHub`, and '
                     'does not need administrator rights. The install folder cannot be changed.\n'
                     '3. ArchHub needs 64-bit CPython 3.14. If Setup cannot find it, it downloads Python 3.14.7 '
                     'from python.org for your user only, without changing your PATH. If that download fails '
                     'or is cancelled, setup stops with a message. If Python asks for a restart, restart '
                     'Windows and run setup again.\n'
                     '4. Setup adds ArchHub and Uninstall ArchHub to the Start menu, and a desktop shortcut '
                     'if you tick that option.\n'
                     '\n'
                     'The installer is not code-signed. Windows may warn you before it runs, depending on '
                     "how you got the file and your machine's policy.\n"
                     '\n'
                     '## First open\n'
                     '\n'
                     'Tick "Open ArchHub now" on the last setup page, or open ArchHub from the Start menu.\n'
                     '\n'
                     'ArchHub runs setup in the background on first open. It opens the app after setup completes.\n'
                     '\n'
                     'عند فتح آرك هب لأول مرة، يجري الإعداد في الخلفية. يفتح التطبيق عند اكتمال الإعداد.\n'
                     '\n'
                     '## Startup logs\n'
                     '\n'
                     'If setup fails, look for the newest `archhub-setup-*.log` file in the ArchHub logs folder. '
                     'On a standard installation, the launcher log is `%LOCALAPPDATA%\\ArchHub\\logs\\launcher.log`.\n'
                     '\n'
                     'إذا فشل الإعداد، راجع أحدث ملف `archhub-setup-*.log` في مجلد سجلات آرك هب. '
                     'في التثبيت العادي، تجد سجل تشغيل التطبيق في `%LOCALAPPDATA%\\ArchHub\\logs\\launcher.log`.\n'
                     '\n'
                     '## Close or quit\n'
                     '\n'
                     'When the tray is available, closing the window with X sends ArchHub to the tray. '
                     'Choose Quit to exit ArchHub.\n'
                     '\n'
                     'عندما تكون منطقة الإعلام متاحة، يؤدي إغلاق النافذة بزر X إلى نقل آرك هب إليها. '
                     'اختر Quit لإنهاء تشغيل آرك هب.\n'
                     '\n'
                     '## Studio\n'
                     '\n'
                     'The strip at the bottom of Studio shows the connected program, document, running work, waiting work, and the command hint. The model a chat uses is named once, on the chip above the chat box.\n'
                     '\n'
                     '## Sign in\n'
                     '\n'
                     'Desktop work needs an internet connection and a verified ArchHub account. On first open, choose Sign in with your browser and finish signing in there, then return to ArchHub to open your workspace. You can also sign in from Settings > Account.\n'
                     '\n'
                     'A brief connection failure keeps a verified sign-in. An explicit account refusal locks the workspace.\n'
                     '\n'
                     'If ArchHub says it could not open the browser, check the default browser in Windows Settings, then choose Retry in ArchHub. If the connection drops, your saved .archhub files stay on this computer. Reconnect and choose Retry. If prompted, sign in again with the same account, then reopen your saved file. For an older unsaved draft, open Settings > Account > Recover local work and choose the draft if it is listed.\n'
                     '\n'
                     'يحتاج العمل على سطح المكتب إلى اتصال بالإنترنت وحساب ArchHub موثّق. يبقى تسجيل الدخول الموثّق قائمًا أثناء انقطاع قصير، أما رفض الحساب صراحةً فيقفل مساحة العمل. اختر Sign in with your browser وأكمل تسجيل الدخول في المتصفح. إذا تعذّر فتحه، تحقق من المتصفح الافتراضي في إعدادات ويندوز ثم اختر Retry في آرك هب.\n'
                     '\n'
                     'تبقى ملفات \u200e.archhub\u200e المحفوظة على جهازك. إذا انقطع الاتصال، أعد الاتصال واختر Retry. عند الطلب سجّل الدخول بالحساب نفسه وافتح ملفك. للبحث عن مسودة قديمة لم تحفظها، افتح Settings > Account > Recover local work واخترها إن ظهرت.\n'
                     '\n'
                     '## Updates\n'
                     '\n'
                     'ArchHub checks the GitHub releases page two minutes after it opens and every thirty '
                     'minutes after that. You can check at any time with Check for updates now in the tray '
                     'menu, or Check and download in Settings, About.\n'
                     '\n'
                     'When a newer build is published, ArchHub downloads the installer and compares it with '
                     'the checksum published with that release. A file that does not match is refused, and '
                     'an older or equal build is never staged. The checksum shows that the file arrived '
                     'intact; it is not a signature.\n'
                     '\n'
                     'To install a downloaded update, choose Restart to install the update in the tray menu, '
                     'Update and reload in the app, or Restart now when BABOOM offers it. ArchHub closes, '
                     'keeps a recovery copy, installs the update and opens again.\n'
                     '\n'
                     '## Known problems in this build\n'
                     '\n'
                     '- Check for updates in the BABOOM menu reports only whether an update is already '
                     'downloaded. It does not check GitHub.\n'
                     '- BABOOM may keep saying an update is ready after it has been installed.\n'),
 'composer-canvas': ('The canvas and the composer',
                     'Nodes, typed wires, properties, graph runs and composer drafts as they exist in build '
                     '{build}.',
                     'Documentation for build {build}.\n'
                     '\n'
                     'The canvas holds your work: nodes, the wires between them and their properties. The '
                     'composer drafts changes to the canvas from a request you type. A model draft stays '
                     'inert until the graph run path starts it.\n'
                     '\n'
                     '## Node catalogue\n'
                     '\n'
                     'The Node library is the one catalogue for placeable nodes. The toolbar, canvas menu '
                     'and composer all use that same catalogue, so the list and details stay aligned with '
                     'what this build can run.\n'
                     '\n'
                     'The catalogue below describes the definitions shipped with this source tree. Build identity is read from package metadata.\n'
                     '\n'
                     '{catalogue}\n'
                     '\n'
                     '## Connect nodes\n'
                     '\n'
                     'Typed sockets define valid wires. While a connection is being formed, the status line '
                     'names the source node and offers cancel. Output sockets are filled and input sockets '
                     'are hollow. A wire takes the colour of the kind of data it carries.\n'
                     '\n'
                     '## Select, move and arrange\n'
                     '\n'
                     '- Selection supports one node, multiple nodes, empty-canvas clear and individual '
                     'wires.\n'
                     '- The right-click menu selects direct neighbours, the connected group, or everything, '
                     'and clears the selection. Shift+F10 opens the same menu from the keyboard.\n'
                     '- Moving nodes saves positions when the pointer is released, and the status line shows '
                     '"Saving positions" while that happens. You can move or arrange up to 256 nodes at a '
                     'time.\n'
                     '- Undo last layout in the right-click menu puts positions back. It covers positions '
                     'only.\n'
                     '\n'
                     '## Zoom and pan\n'
                     '\n'
                     'Canvas zoom can follow the pointer, the toolbar controls or Fit. Canvas pan, Fit '
                     'selection, Fit all, Arrange selection and Arrange all are also available from the '
                     'graph controls, and a minimap shows the whole graph. Zoom and pan are not kept after a '
                     'restart.\n'
                     '\n'
                     '## Properties\n'
                     '\n'
                     'Selecting a node opens the Properties panel on the right. It shows what the node '
                     'receives and sends, and its parameters.\n'
                     '\n'
                     'Every parameter edit is saved as you make it; there is no Save button. If an edit '
                     'cannot be saved, the panel says "not saved" and offers Retry unsaved edits. Each row '
                     'can be reverted on its own, and Revert all reverts every row.\n'
                     '\n'
                     'To delete a node or a wire, use the delete control in the Properties panel and '
                     'confirm.\n'
                     '\n'
                     '## Run the graph\n'
                     '\n'
                     'The Properties panel starts graph execution. ArchHub waits for pending parameter '
                     'saves, runs every node in the graph along its wires, and shows each result on its '
                     'node. One run happens at a time. If something fails, the panel says so, for example '
                     '"Graph execution failed." or that some nodes did not complete.\n'
                     '\n'
                     '## Where your work is saved\n'
                     '\n'
                     'Choose New in the Canvas actions menu to start a blank session. Choose Save (Ctrl+S) '
                     'to save the current session. A new session is saved in your Sessions folder. Your graph '
                     'survives a restart. '
                     'To choose a different name or folder, choose Save as… and, in the Save session dialog, '
                     'choose a local .archhub filename and click Save. The original stays in place. To reopen '
                     'either file, choose Open… in the Canvas actions menu and select the .archhub file.\n'
                     '\n'
                     '## The composer\n'
                     '\n'
                     'Type into the box at the bottom of the canvas, or start from Home with Start a new '
                     'session. With an AI node selected, you can also ask it from its Properties panel.\n'
                     '\n'
                     'The composer sends your request to the model you picked and turns the reply into draft '
                     'changes on the canvas: placing and grouping nodes, wiring them and setting properties. '
                     'It applies up to twelve changes per request and stops at the first one that fails. Its '
                     'reply ends with "Draft updated on the canvas. Review its nodes, connections and '
                     'parameters." or tells you what needs attention.\n'
                     '\n'
                     'A draft stays a draft. If the model asks to run it, nothing runs; graph execution '
                     "starts only from the app's governed run path.\n"
                     '\n'
                     'If no model is picked, the composer answers "No model chosen" and asks you to pick '
                     'one.\n'
                     '\n'
                     '## Pick a model\n'
                     '\n'
                     'Open the model picker from the model button in the header or on Home. It lists models '
                     'in three groups: CLOUD, through your ArchHub account; PROVIDER, through connected '
                     'providers; and LOCAL, from LM Studio or Ollama running on this machine. You can '
                     'search, refresh or clear the choice. With an AI node selected, picking a model sets '
                     "that node's model.\n"
                     '\n'
                     'Provider accounts are connected from Settings, Providers. Credentials stay on this '
                     'machine and are never written into a project file.\n'
                     '\n'
                     'For free models, pick a model whose route ends in `:free`, or the `openrouter/free` '
                     'route. In free mode ArchHub refuses routes that are not free and rejects any reply '
                     'that reports a cost.\n'
                     '\n'
                     'If a provider limits requests, you see "The model provider is rate-limiting requests '
                     '(HTTP 429)." ArchHub does not retry by itself. Wait, or pick another model.\n'
                     '\n'
                     '## Limits in this build\n'
                     '\n'
                     '- Undo last layout restores node positions only. Graph edits have no undo or redo.\n'
                     '- The app does not create or promote skills from a conversation.\n'
                     '- Settings > Agents lists only free or local model routes that the app can route in '
                     'this build.\n'
                     '- Ollama routes cannot take images.\n'),
 'brain': ('The brain and cloud sync',
           'Local graph memory and the limits of skills and sharing in this build.',
           'Documentation for build {build}.\n'
           '\n'
           '## The local brain\n'
           '\n'
           'Brain entries live in the application graph. The app has no separate brain service.\n'
           '\n'
           '## Skills\n'
           '\n'
           'The app does not create or promote a skill from a conversation.\n'
           '\n'
           '## Cloud sync and community\n'
           '\n'
           'Brain cloud sync is not active in this build. Firm sharing and peer review are not available '
           'from the app window. These are not offered as working features.\n'),
 'account-web': ('Your account',
                 'Sign in with your email account, sign out, see your tier, and what the archhub.io website '
                 'does and does not do.',
                 'Documentation for build {build}.\n'
                 '\n'
                 '## Your identity is your email\n'
                 '\n'
                 'An ArchHub account is an email address, not a machine. Sign in on another computer with '
                 'the same email and it is the same account.\n'
                 '\n'
                 '## Sign in\n'
                 '\n'
                 'Choose Sign in with your browser on first open or in Settings > Account, complete sign-in there and return to ArchHub. If ArchHub says it could not open the browser, check the default browser in Windows Settings and choose Retry in ArchHub.\n'
                 '\n'
                 '## Sign out and return\n'
                 '\n'
                 'Use Settings > Account to sign out. Your saved .archhub files stay in their folders on this computer. Signing in on another computer does not transfer those files.\n'
                 '\n'
                 'A brief connection failure keeps a verified sign-in. If ArchHub loses its connection for longer, reconnect and choose Retry. If asked to sign in again, use the same account. Reopen your saved file. For older unsaved drafts on this Windows profile, use Settings > Account > Recover local work and select a draft if it appears.\n'
                 '\n'
                 '## What needs an account\n'
                 '\n'
                 'Desktop work needs an internet connection and a verified account; an explicit account refusal locks the workspace. Cloud model routes require sign-in.\n'
                 '\n'
                 '## Tiers and the offer\n'
                 '\n'
                 'Each account has a tier: free, pro, firm or founder. New accounts start on free. Your tier '
                 'is shown in Settings, Account. In this build the tier does not change what the app lets '
                 'you do.\n'
                 '\n'
                 'ArchHub is Free during beta.\n'
                 '\n'
                 '## The archhub.io website\n'
                 '\n'
                 'Start desktop sign-in from ArchHub and finish in the browser it opens. The installer '
                 'is published on the ArchHub releases page on GitHub.\n'
                 '\n'
                 '## Not working in this build\n'
                 '\n'
                 '- Usage limits show "not available", and the spend-limit buttons are not enforced.\n'
                 '- Brain and cloud sync, in Settings > Account, shows "not available".\n'),
 'connectors': ('Connectors',
                'Catalogue operations and reviewed packaged host artifacts; availability is separate from a '
                'running connection.',
                'Documentation for build {build}.\n'
                '\n'
                '## Connector catalogue\n'
                '\n'
                "This table comes from the operation catalogue and the selected build's host artifact index. "
                'Packaged artifacts do not prove a running connection. Open the host with its connector '
                'loaded before using its operations.\n'
                '\n'
                '{connectors}\n'
                '\n'
                '## Connect a host\n'
                '\n'
                "Use the app's host list to check the current connection. ArchHub reports the host's actual "
                'state; a missing host or document is unavailable. Reviewed add-ins are registered by setup '
                'only when its artifact and local host checks pass. Restart an already open host after setup '
                'so it can load the connector.\n'
                '\n'
                '## Add a tool server\n'
                '\n'
                'In Settings, open Connections and find Tool servers (MCP). Enter a server address, a command or an MCP JSON snippet, then choose Add tool server.\n'
                'Choose Check to test the connection. Switch off a server to keep its configuration and prevent its tools from running.\n'
                '\n'
                'في الإعدادات، افتح الاتصالات وابحث عن خوادم الأدوات (MCP). '
                'أدخل عنوان الخادم أو أمرًا أو مقطع MCP JSON، ثم اختر إضافة خادم أدوات.\n'
                '\n'
                'In Canvas, press Ctrl K, choose MCP tools and select Discover tools. Use Import on the tool you want to add to the open canvas.\n'
                '\n'
                '## Operation catalogue\n'
                '\n'
                '{operations}\n'),
 'workshop': ('The Workshop',
                'Task conversations, subtasks and the people and agents doing the work.',
                'Documentation for build {build}.\n'
                '\n'
                'ArchHub opens on Home. Select a task on the map to see its Properties.\n'
                '\n'
                '## Add a subtask\n'
                '\n'
                'In Properties, enter a title in New subtask and choose Add subtask. The child stays in the same project and has its own .archhub file.\n'
                '\n'
                'في الخصائص، أدخل عنوانًا في مهمة فرعية جديدة واختر إضافة مهمة فرعية. '
                'تبقى المهمة الفرعية في المشروع نفسه ويكون لها ملف ArchHub خاص بها.\n'
                '\n'
                '## Reach an agent\n'
                '\n'
                'Open the Workshop dock to see the people and agents in the workspace. Use Show on a task conversation to bring it into the composer. Choose the recipient before sending.\n'
                'Replies appear in that conversation. A direct message to an agent is delivered to its connected session.\n'
                '\n'
                '## Find a command\n'
                '\n'
                'Press Ctrl K to find an agent, a workflow, a program or a setting by name.\n'),
 'tasks': ('Tasks: who is doing what',
                'One agent per task, so no work is done twice.',
                'Documentation for build {build}.\n'
                '\n'
                "A task is one job in the Workshop's Work column.\n"
                '\n'
                "- When an agent takes a task, the task is claimed: it shows as Working, under In progress, with that agent's name, and no other agent can take it.\n"
                '- An agent holds a task for 15 minutes at a time and renews it while it works. If it goes quiet, the hold runs out and the task is free for the next agent. Nothing is lost.\n'
                '- When the agent finishes, the task moves to Completed.\n'
                '\n'
                'The hold time is a parameter of the Workshop tasks node (lease_seconds, 30 seconds to 24 hours).\n'),
 'approvals': ('Approvals: how much agents may do without asking',
                'One setting decides when an agent asks you first.',
                'Documentation for build {build}.\n'
                '\n'
                'Open Settings > Hooks.\n'
                '\n'
                '## Run mode (for every agent)\n'
                '\n'
                "- Accept edits (the default): agents work without prompting you. This is today's behaviour.\n"
                '- Ask first: an agent asks you before it deletes, publishes or sends anything, and before it changes anything outside your own folders.\n'
                '- Plan only: agents may read and plan, but every change is refused.\n'
                '\n'
                'Routine work in your own folders (reading, writing, running commands) never prompts you in any mode.\n'
                '\n'
                '## Per tool\n'
                '\n'
                'For any tool you can choose Off, Ask or Allowed. A tool set to Off is never used.\n'
                '\n'
                '## What is always stopped\n'
                '\n'
                'Some things are refused whatever the mode, for example a secret or client data about to be published or sent. The reason is shown in plain words.\n'),
 'routines': ('Routines: work that runs by itself',
                'A Schedule or File change node runs a workflow for you and reports in the Workshop.',
                'Documentation for build {build}.\n'
                '\n'
                'A routine is a workflow with a trigger node at its start.\n'
                '\n'
                '1. On the canvas, add a Schedule node (runs at the times you set) or a File change node (runs when a file in a folder changes).\n'
                '2. Wire it to the nodes it should run, and save the workflow.\n'
                '3. While ArchHub is open, the routine fires by itself. The nodes after the trigger run once, with the usual approval rules, and the results are saved into the same workflow file.\n'
                '\n'
                'Each time it fires, a message is posted in the Workshop. Set "to" on the trigger node to send it straight to an agent, so that agent picks up the work.\n'
                '\n'
                'Options on the trigger node:\n'
                '- concurrency: skip (ignore a fire while the last run is still going) or queue (run it after).\n'
                '- catch_up: skip, or run_once (a schedule missed while ArchHub was closed runs once when it opens).\n'
                '\n'
                'Routines run only while ArchHub is open. Triggers from host-program events (Revit and others) are not active yet.\n')})


_PRIVATE_PATTERNS = (
    (re.compile(r"(?i)[a-z]:[\\/]+users[\\/]"), "local user path"),
    (re.compile(r"(?i)file://"), "local file URL"),
    (re.compile(
        r"(?i)(?:00\.governance|20\.clients|30\.knowledge|40\.media|"
        r"50\.tooling|60\.personal|70\.handoffs|90\.archive)"
    ), "non-public workspace area"),
    (re.compile(r"(?i)12\.production"), "legacy application path"),
    (re.compile(r"(?i)op://"), "secret capability reference"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)ARCHHUB_GRAND_MAP_PATH|authority\.json|node-native-wip"),
     "private runtime authority"),
)

_ORIGIN = re.compile(
    r"(?i)https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+(?::[0-9]{1,5})?"
)
_WEBSITE_HREF = re.compile(r'href="/website(?:/[A-Za-z0-9-]+)*"')
_LEDE = re.compile(r'<p class="site-(?:page-)?lede">(.*?)</p>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")

# The one script the site serves: the design's interactions (hero canvas drag
# and wire, and host picker), a static file admitted by this
# exact sha256. The graph document stays scriptless; the export adds only this
# tag, and a page with any other script, or a script file with any other
# bytes, is refused.
SITE_SCRIPT = "assets/site.js"
SITE_SCRIPT_SOURCE = "site.js"
SITE_SCRIPT_SHA256 = (
    "b79720a5b81f81d8043a0525d3e09fc04622f658540d45a39d82a006c8e461e5"
)
SITE_SCRIPT_TAG = '<script src="/assets/site.js" defer></script>'

HEAD_LINKS = (
    '<link rel="stylesheet" href="/assets/fonts.css">'
    '<link rel="stylesheet" href="/assets/site.css">'
    '<link rel="icon" href="/favicon.ico" sizes="any">'
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    + SITE_SCRIPT_TAG
)

BRAND_DIR = Path(__file__).resolve().parent / "data" / "website"
BRAND_FILES = ("favicon.ico", "favicon.svg", "og.png")
SHARE_IMAGE = "og.png"

# The three families the graph stylesheet names, served from this site. Each
# woff2 is the Latin subset of an SIL Open Font License 1.1 font (Instrument
# Serif 1.000, Inter 4.001 held at opsz 14 over weights 400 to 600, JetBrains
# Mono 2.211); its licence file travels beside it.
FONT_DIR = "fonts"
FONT_FACES = (
    ("instrument-serif-regular.woff2", "Instrument Serif", "normal", "400"),
    ("instrument-serif-italic.woff2", "Instrument Serif", "italic", "400"),
    ("inter-variable.woff2", "Inter", "normal", "400 600"),
    ("jetbrains-mono-regular.woff2", "JetBrains Mono", "normal", "400"),
)
FONT_LICENCES = (
    "OFL-InstrumentSerif.txt", "OFL-Inter.txt", "OFL-JetBrainsMono.txt",
)
FONTS_CSS = "".join(
    '@font-face{font-family:"%s";font-style:%s;font-weight:%s;'
    'font-display:swap;src:url(/assets/fonts/%s) format("woff2")}\n'
    % (family, style, weight, name)
    for name, family, style, weight in FONT_FACES
)
# Every file the export copies, by its path under dist/ and its source under
# nodelang/data/website.
PUBLIC_FILES = (
    *((name, name) for name in BRAND_FILES),
    (SITE_SCRIPT, SITE_SCRIPT_SOURCE),
    ("assets/tutorials/home-templates.png", "tutorials/home-templates.png"),
    *(
        ("assets/fonts/" + name, FONT_DIR + "/" + name)
        for name in (
            *(face[0] for face in FONT_FACES), *FONT_LICENCES,
        )
    ),
)
_PUBLIC_FILE_SOURCES = dict(PUBLIC_FILES)

# The addresses the retired Astro site answered at, each sent to the live page
# closest to what it held: the docs index to the first docs page (the five
# docs guides are live pages again, at the addresses they had), the brain
# portal to the security page that explains what cloud sync holds, the account
# page to sign-in, and the gallery to the community page.
RETIRED_ADDRESSES = (
    ("/docs/", "/website/docs/getting-started"),
    ("/gallery/", "/website/community"),
    ("/account/", "/website/signin"),
    ("/brain/", "/website/security"),
)
_RETIRED_PATH = re.compile(r"(?:/[a-z0-9-]+)+/")

NOT_FOUND_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta name="color-scheme" content="light">'
    '<title>Not found | ArchHub</title>'
    + HEAD_LINKS + '</head><body>'
    '<main class="site-page-main"><h1 class="site-page-title">Not found</h1>'
    '<p class="site-page-lede">There is no page at this address.</p>'
    '<p><a class="site-nav-link" href="/">Return to ArchHub</a></p>'
    '</main></body></html>'
)



DOCS_KEYS = tuple(_DOCS_TEMPLATES) + tuple("tutorial-" + key for key in ("sheet-register", "model-table", "notion-review", "cad-inventory", "inbox-review", "titleblocks"))
