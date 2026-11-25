// DSYS-083/084/085/086/087: Frame/Nav/P/R row grammar retained; each of
// the Book's 15 pages is now a live projection of the single settings schema.
(() => {
  const WIRE_DS_SETTINGS3_JSX_ACTIONS = {
  "settings.ds_settings3.RouterRefresh": "RouterRefresh",
  "settings.ds_settings3.RouterModel": "RouterModel",
  "settings.ds_settings3.PermissionsSave": "PermissionsSave",
  "settings.ds_settings3.PermissionsRefresh": "PermissionsRefresh",
  "settings.ds_settings3.PermissionsRemove": "PermissionsRemove",
  "settings.ds_settings3.PermissionsAdd": "PermissionsAdd",
  "settings.ds_settings3.ConnectionsAction0": "ConnectionsAction0",
  "settings.ds_settings3.ConnectionsAction1": "ConnectionsAction1",
  "settings.ds_settings3.ConnectionsAction2": "ConnectionsAction2",
  "settings.ds_settings3.EditLocalClient": "EditLocalClient",
  "settings.ds_settings3.SaveProjectRegister": "SaveProjectRegister",
  "settings.ds_settings3.PickProjectRegister": "PickProjectRegister",
  "settings.ds_settings3.WorkspaceRowsAction0": "WorkspaceRowsAction0",
  "settings.ds_settings3.WorkspaceRowsAction1": "WorkspaceRowsAction1",
  "settings.ds_settings3.WorkspaceRowsAction2": "WorkspaceRowsAction2",
  "settings.ds_settings3.WorkspaceRowsAction3": "WorkspaceRowsAction3",
  "settings.ds_settings3.WorkspaceRowsAction4": "WorkspaceRowsAction4",
  "settings.ds_settings3.NewProject": "NewProject",
  "settings.ds_settings3.CreateProject": "CreateProject",
  "settings.ds_settings3.CancelProject": "CancelProject",
  "settings.ds_settings3.PickProjectTemplate": "PickProjectTemplate",
  "settings.ds_settings3.AccountAction0": "AccountAction0",
  "settings.ds_settings3.AccountAction1": "AccountAction1",
  "settings.ds_settings3.AccountAction2": "AccountAction2",
  "settings.ds_settings3.StorageAction0": "StorageAction0",
  "settings.ds_settings3.StorageAction1": "StorageAction1",
  "settings.ds_settings3.StorageAction2": "StorageAction2",
  "settings.ds_settings3.SettingsAction0": "SettingsAction0",
  "settings.ds_settings3.SettingsAction1": "SettingsAction1",
  "settings.ds_settings3.SettingsAction2": "SettingsAction2",
  "settings.ds_settings3.SettingsAction3": "SettingsAction3",
  "settings.ds_settings3.SettingsAction4": "SettingsAction4",
  "settings.ds_settings3.SettingsAction5": "SettingsAction5",
  "settings.ds_settings3.SettingsAction6": "SettingsAction6",
  "settings.ds_settings3.SettingsAction7": "SettingsAction7",
  "settings.ds_settings3.SettingsAction8": "SettingsAction8",
  "settings.ds_settings3.SettingsAction9": "SettingsAction9",
  "settings.ds_settings3.SettingsAction10": "SettingsAction10",
  "settings.ds_settings3.SettingsAction11": "SettingsAction11",
  "settings.ds_settings3.SettingsAction12": "SettingsAction12",
  "settings.ds_settings3.SettingsAction13": "SettingsAction13",
  "settings.ds_settings3.SettingsAction14": "SettingsAction14",
  "settings.ds_settings3.UpdatesAutoInstall": "UpdatesAutoInstall",
  "settings.ds_settings3.UpdatesSettingRetry": "UpdatesSettingRetry",
  "settings.ds_settings3.SettingsAction15": "SettingsAction15",
  "settings.ds_settings3.SettingsAction16": "SettingsAction16",
  "settings.ds_settings3.SettingsAction17": "SettingsAction17",
  "settings.ds_settings3.SettingsAction18": "SettingsAction18",
  "settings.ds_settings3.SettingsAction19": "SettingsAction19",
  "settings.ds_settings3.SettingsAction20": "SettingsAction20",
  "settings.ds_settings3.SettingsAction21": "SettingsAction21",
  "settings.ds_settings3.SettingsAction22": "SettingsAction22",
  "settings.ds_settings3.SettingsAction23": "SettingsAction23",
  "settings.ds_settings3.SettingsAction24": "SettingsAction24",
  "settings.ds_settings3.SettingsAction25": "SettingsAction25"
};
  const {
    A,
    D,
    api,
    useData,
    useApp,
    Btn,
    Card,
    Heading,
    Chip,
    Empty,
    SettingControl,
    Providers
  } = window.UI;
  const doors = {
    'Account': 'account',
    'Connections': 'connections',
    'BABOOM': 'baboom',
    'Agents': 'colleagues',
    'Brain': 'brain',
    'System graph': 'system',
    'Workshop': 'workshop',
    'Library & Mods': 'library',
    'Automations': 'automations',
    'Hooks': 'hooks',
    'Dependencies': 'dependencies',
    'Privacy': 'privacy',
    'Appearance': 'appearance',
    'Updates & About': 'updates',
    'Advanced': 'system'
  };
  const sections = [
    {name:'Account', pages:['Account','Privacy'], tabs:['Profile','Privacy']},
    {name:'Connections', pages:['Connections'], tabs:['Connections']},
    {name:'Automation & Brain', pages:['BABOOM','Agents','Brain','Workshop','Automations'], tabs:['Preferences','Agents','Brain','Workshop','Automations']},
    {name:'Interface', pages:['Appearance'], tabs:['Preferences']},
    {name:'System', pages:['System graph','Library & Mods','Hooks','Dependencies','Updates & About','Advanced'], tabs:['Preferences','Library & Mods','Hooks','Dependencies','Updates & About','Advanced']}
  ];
  // Founder: at most five Settings pages, every setting kept. Each former area is a page inside one of the five.
  const sheetAreas = [
    {label:'Account', target:'Account', pages:['Account','Brain'], icon:'user', description:'Your ArchHub account: the same values in the app and on archhub.io. Change one in either place'},
    {label:'Projects', target:'Projects', pages:['Projects'], icon:'folder', description:'Units, the standard, templates, naming and folders'},
    {label:'Agents', target:'Agents', pages:['Agents','BABOOM','Hooks','Workshop','Automations','Library & Mods'], icon:'users', description:'Who works for you, on which model, what they may do, the Workshop, automations and tools'},
    {label:'Connections', target:'Connections', pages:['Connections'], icon:'link', description:'Accounts, programs, your phone and notifications'},
    {label:'This PC', target:'Appearance', pages:['Appearance','Privacy','Advanced','System graph','Dependencies','Updates & About'], icon:'settings', description:'This PC: how ArchHub looks, workspaces, files, privacy, updates and the app'}
  ];
  const formerPageLabels = {
    Account:'Account, Social, Brain', Agents:'Models, Permissions, Hooks, Workshop, Library & Mods, Automations',
    Connections:'Connections', 'This PC':'Look, Appearance, System, Advanced, Updates & About'
  };
  // Former page names stay valid links: [the page that holds them now, the section to scroll to].
  const formerAreas = {Look:['Appearance'], Interface:['Appearance'], You:['Privacy','Workspaces and files'], System:['System graph','Agents on this PC'], Models:['Agents','Models'], BABOOM:['Agents','BABOOM'], Permissions:['Agents','What agents may do'], Hooks:['Agents','What agents may do'], Workshop:['Agents','Workshop'], Automations:['Agents','Automations'], 'Library & Mods':['Agents','Tools in the Library'], Brain:['Account','Brain and cloud sync'], Social:['Account','Social media'], Providers:['Connections','AI providers','advanced']};
  // Display metadata from the Settings design. Values and writes belong to the settings owners.
  const areaCardSpecs = [
    {area:"Projects", id:"register", title:"Project register", icon:"docs", family:"model", wide:false, rows:[
      ["projNumber", "Project number", "Used in file names, title blocks and the register", "text", ""],
      ["projClient", "Client", "Stays on this PC; never sent with shared items", "text", ""],
      ["projStage", "Stage", "Agents pick checks and deliverables for this stage", "select", ["Concept", "Schematic", "Detailed design", "Construction documents", "Tender", "Construction"]],
      ["projConf", "Confidentiality", "Confidential and Secret never leave this PC", "seg", ["Internal", "Confidential", "Secret"]],
      ["projOverride", "This project overrides office defaults", "Units, templates and naming set here win for this project", "bool", ""],
    ]},
    {area:"Projects", id:"units", title:"Units and precision", icon:"arrange", family:"model", wide:false, rows:[
      ["lenUnit", "Length", "Dimensions, schedules and agent answers", "select", ["Millimetres", "Centimetres", "Metres", "Feet and inches"]],
      ["areaUnit", "Area", "Room areas and schedules", "seg", ["m²", "ft²"]],
      ["lenDecimals", "Length precision", "Decimal places shown", "step", "decimals"],
      ["areaDecimals", "Area precision", "Decimal places shown", "step", "decimals"],
      ["angleDecimals", "Angle precision", "Decimal places shown", "step", "decimals"],
      ["dateFormat", "Dates", "Title blocks, registers and file names", "select", ["DD/MM/YYYY", "YYYY-MM-DD", "MM/DD/YYYY"]],
    ]},
    {area:"Projects", id:"std", title:"Office standard", icon:"docs", family:"check", wide:false, rows:[
      ["stdFolder", "Office standard folder", "Where agents read the office standard", "folder", ""],
      ["stdVersion", "Standard version", "Agents follow and cite this one", "select", ["Office standard, current", "Office standard, previous"]],
      ["stdSite", "Standard website", "Links in agent answers open here", "text", ""],
      ["paramDict", "Parameter names", "The dictionary agents use for parameters", "select", ["buildingSMART Data Dictionary", "Office dictionary"]],
      ["knowsStd", "Knows the Office standard", "His answers cite the standard rule they follow", "bool", ""],
    ]},
    {area:"Projects", id:"tpl", title:"Templates", icon:"canvas", family:"model", wide:false, rows:[
      ["revitTpl", "Revit template", "New models and native details start from it", "folder", ""],
      ["acadTpl", "AutoCAD template", "New drawings start from it", "folder", ""],
      ["titleBlock", "Title block", "Used when agents create sheets", "select", ["Office A1 title block", "Office A0 title block", "Office A3 title block"]],
      ["sheetSize", "Sheet size", "Default for new sheets and PDF sets", "seg", ["A0", "A1", "A3"]],
      ["drawLang", "Drawing labels", "Language of tags, titles and notes on drawings", "select", ["English", "Arabic", "English above Arabic"]],
      ["lod", "Model detail", "Default level of development from the BEP", "select", ["LOD 200", "LOD 300", "LOD 350", "LOD 400"]],
      ["coords", "Coordinates", "How new models are placed", "select", ["Shared coordinates", "Project base point"]],
      ["projTpl", "New project folders", "The folder tree a new project gets", "select", ["ISO 19650 CDE tree", "Office project tree"]],
    ]},
    {area:"Projects", id:"loc", title:"Location", icon:"pin", family:"model", wide:false, rows:[
      ["surveyE", "Survey point east", "Metres, in the project coordinate system", "text", ""],
      ["surveyN", "Survey point north", "Metres, in the project coordinate system", "text", ""],
      ["surveyElev", "Survey point elevation", "Metres above datum", "text", ""],
      ["gridNorth", "Angle to true north", "From project north, clockwise", "range", ""],
    ]},
    {area:"Projects", id:"workshare", title:"Revit worksharing", icon:"users", family:"model", wide:false, rows:[
      ["centralPath", "Central model folder", "Where the central model lives", "folder", ""],
      ["syncEvery", "Sync with central every", "Agents sync on this beat while they work in the model", "range", ""],
      ["relinquish", "Give back borrowed elements on sync", "Others can edit them straight away", "bool", ""],
    ]},
    {area:"Projects", id:"exch", title:"IFC and BCF", icon:"refresh", family:"list", wide:false, rows:[
      ["ifcVersion", "IFC version", "For exports and checks", "select", ["IFC4", "IFC2x3", "IFC4.3"]],
      ["ifcSetup", "IFC export setup", "Property sets and mappings", "select", ["Office IFC export", "Revit default"]],
      ["bcfVersion", "BCF version", "Issues read and written in this version", "select", ["BCF 3.0", "BCF 2.1"]],
    ]},
    {area:"Projects", id:"print", title:"Print and PDF", icon:"docs", family:"effect", wide:false, rows:[
      ["ctb", "Pen table", "Colour to lineweight when printing", "select", ["Office monochrome.ctb", "Office colour.ctb", "None"]],
      ["pdfSet", "Sheet set", "What Publish PDF prints by default", "select", ["Office issue set", "Current sheet only", "Sheets changed since the last issue"]],
      ["defaultScale", "Default scale", "For new views and prints", "select", ["1:50", "1:100", "1:200", "1:500"]],
    ]},
    {area:"Projects", id:"cadstd", title:"CAD", icon:"canvas", family:"list", wide:false, rows:[
      ["layerStd", "Layer standard", "Layer names agents use in DWG", "select", ["Office layers (AIA based)", "ISO 13567"]],
      ["colorWeight", "Colour to lineweight", "How colours print", "select", ["Office colour to lineweight", "AutoCAD default"]],
      ["dwgSetup", "DWG export setup", "Revit to DWG mapping", "select", ["Office DWG export", "Revit default"]],
      ["dwgVer", "DWG version", "For exports", "select", ["2018", "2013"]],
    ]},
    {area:"Projects", id:"naming", title:"File naming", icon:"edit", family:"list", wide:false, rows:[
      ["namePattern", "Name pattern", "Every file agents save follows it", "text", ""],
      ["originator", "Originator code", "Your office code in file names", "text", ""],
      ["revScheme", "Revisions", "How revisions are numbered", "select", ["P01, C01 (ISO 19650)", "A, B, C", "Rev 0, 1, 2"]],
      ["nameCheck", "Check names before saving", "A wrong name is fixed before the file is written", "bool", ""],
    ]},
    {area:"Projects", id:"cde", title:"CDE folders", icon:"folder", family:"list", wide:false, rows:[
      ["cdeRoot", "Projects folder", "Where project folders live", "folder", ""],
      ["cdeOrder", "Folder order", "How the CDE tree nests", "select", ["State, then data type, then discipline (ISO 19650)", "State, then discipline, then data type"]],
      ["disciplines", "Discipline codes", "Codes used in folders and file names", "list", ""],
    ]},
    {area:"Agents", id:"agents", title:"Your agents", icon:"users", family:"agent", wide:true, rows:[
    ]},
    {area:"Agents", id:"models", title:"Models", icon:"brain", family:"agent", wide:false, rows:[
      ["model", "Default model", "New agent sessions start with it", "select", []],
      ["effort", "Effort", "How hard models think before answering", "seg", ["Low", "Medium", "High"]],
      ["composerModel", "Composer model", "Writes the plan when you type a request", "select", []],
      ["preferFree", "Prefer free models", "Paid models only when a free one cannot do the step", "bool", ""],
      ["switchOnLimit", "Switch when a model hits its limit", "Moves to the next model in the fallback order instead of waiting", "bool", ""],
      ["fallback", "Fallback order", "Tried in this order when a model is busy", "list", ""],
      ["maxTokens", "Longest reply", "Tokens per reply before the model stops", "range", ""],
      ["temperature", "Creativity", "0 answers the same way every time; higher varies the wording", "range", "", true],
      ["topP", "Sampling breadth", "1 keeps every likely word; lower narrows the wording", "range", "", true],
      ["localModels", "Run local models", "Ollama on this PC or the office server. On adds local models to every model choice", "bool", ""],
    ]},
    {area:"Agents", id:"perm", title:"What agents may do", icon:"shield", family:"check", wide:false, rows:[
      ["runMode", "Run mode", "Ask first: every write waits for Approve. Accept edits: writes in your workspace run. Plan only: agents plan, nothing changes", "seg", ["Ask first", "Accept edits", "Plan only"]],
      ["toolRules", "Tool rules", "One tool can follow its own mode, whatever the run mode is", "list", ""],
      ["finishReport", "Agents finish and report", "They close the task and post the result instead of stopping halfway", "bool", ""],
      ["agentComputer", "Sandboxed computer for agents", "Off: agents use only the programs and apps listed in Connections", "bool", ""],
      ["scanSkills", "Skills are scanned before install", "Approve, Caution or Reject, from the skill’s own files", "status", ""],
      ["budgetRun", "Budget per run", "A run stops and asks you before it spends more. Shown in your currency; ArchHub never bills you", "range", "", true],
      ["runSecs", "Time per run", "A workflow run stops and asks after this", "range", ""],
      ["runCalls", "Model calls per run", "Above it the run asks before calling again", "range", ""],
      ["elemLimit", "Elements one write may change", "A bigger change waits for your Approve", "range", ""],
      ["dailyTokens", "Daily tokens per agent", "Counted over 24 hours; above it the agent asks you first", "select", ["No cap", "50k tokens", "200k tokens", "1M tokens"]],
      ["budgetWindow", "Token budget counts over", "The window the daily tokens and per-agent caps use", "select", ["24 hours", "7 days", "30 days"]],
      ["budgetCurrency", "Show budgets in", "Token use shown in this currency, at today’s rate", "select", ["US dollars", "Saudi riyals", "Egyptian pounds", "UAE dirhams"]],
      ["questionsDay", "Questions an agent may ask you a day", "Above it the agent decides by your rules and reports", "range", ""],
      ["maxRuns", "Running agents at once", "Above this, a new run waits in line instead of slowing the PC", "step", ""],
      ["loopCap", "Loop rounds", "A loop stops here even if its list is not done", "range", "", true],
      ["gradMinRuns", "Runs before a step can become a script", "Same result this many times, then it may run without a model", "range", "", true],
      ["driftCheck", "Watch agent checks for outside changes", "Each agent runs a check before and after it works. If someone changes one outside ArchHub, it shows below", "bool", ""],
      ["drift", "Checks changed outside ArchHub", "Accept keeps the change; Revert puts back the check you approved", "list", ""],
    ]},
    {area:"Agents", id:"workshop", title:"Workshop", icon:"workshop", family:"agent", wide:false, rows:[
      ["wsWho", "Who may message whom", "Agents message each other directly, only through the coordinator, or only you start a thread", "seg", ["Anyone", "Coordinator", "Only you"]],
      ["wsApprove", "Who approves", "Writes, sends and spending wait for this", "select", ["Only you", "You, or the coordinator for routine work"]],
      ["awayDelegate", "When you are away", "Who answers approvals while you are out", "select", ["Nobody, it waits for me", "The coordinator, for routine work only"]],
      ["autoTo", "Automation messages go to", "Who a scheduled or watching run reports to", "select", ["You", "Coordinator", "BABOOM"]],
      ["wsRelease", "Release a silent claim after", "A task an agent claimed and went quiet on goes back to the queue", "range", ""],
      ["wsArchive", "Archive quiet threads after", "Archived threads stay searchable", "range", ""],
      ["wsTick", "Housekeeping every", "Releases claims and archives threads on this beat", "range", "", true],
    ]},
    {area:"Agents", id:"auto", title:"Automations", icon:"clock", family:"effect", wide:false, rows:[
      ["trigConcurrency", "If it is still running", "A new start is skipped, or waits its turn", "seg", ["Skip", "Queue"]],
      ["trigCatchUp", "Runs missed while closed", "Skip them, or run once when ArchHub opens", "seg", ["Skip", "Run once"]],
    ]},
    {area:"Agents", id:"meet", title:"Meetings", icon:"voice", family:"agent", wide:false, rows:[
      ["meetJoin", "Joins meetings", "Teams meetings he may join for you", "select", ["Ask me each time", "Meetings I organise", "All my Teams meetings"]],
      ["meetName", "Name in the meeting", "What other people see", "text", ""],
      ["meetLang", "Meeting language", "Minutes go to Notion in this language", "select", ["Arabic and English", "English", "Arabic"]],
      ["meetAnswer", "Meeting agent speaks", "In meetings it joins for you", "select", ["Only when asked", "When it knows the answer"]],
      ["meetSilence", "Waits for a pause of", "Before it starts speaking", "range", ""],
    ]},
    {area:"Agents", id:"baboom", title:"BABOOM", icon:"voice", family:"effect", wide:false, rows:[
      ["bbStart", "Start with ArchHub", "He is there when the app opens", "bool", ""],
      ["bbShowsAs", "Shows as", "On screen, in the tray, or hidden", "seg", ["Screen", "Tray", "Hidden"]],
      ["bbPinned", "Pin in place", "He stays where you put him", "bool", ""],
      ["bbPresence", "Presence", "Hidden, a quiet corner, normal, or lively reactions", "seg", ["Hidden", "Quiet", "Normal", "Lively"]],
      ["bbDnd", "Do not disturb", "He stays quiet and waits for a natural break", "select", ["Off", "In meetings", "While I work in Revit or CAD", "Always"]],
      ["bbPersona", "Persona", "How he talks; it never changes what he may do", "text", ""],
      ["bbDisclose", "Says he is an AI assistant", "To other people, in meetings and messages", "status", ""],
      ["bbModel", "His model", "The model BABOOM answers with", "select", []],
      ["bbSpeech", "Speaks at most", "Spoken lines per hour; text always works", "range", ""],
      ["bbVoice", "Voice", "Talk to him and hear him answer", "bool", ""],
      ["sttEngine", "Speech recognition", "The local Egyptian model keeps your voice on this PC", "select", ["Windows speech", "Local Egyptian model (QwenCleo)"]],
      ["sttLang", "He listens for", "Mixed Egyptian Arabic and English works", "select", ["Egyptian Arabic and English", "English", "Arabic"]],
      ["voiceHold", "Hold to talk after", "How long you hold before he listens", "range", ""],
      ["moments", "Reactions", "He casts, presents and waves as work moves. Off keeps him still", "bool", ""],
      ["bbThrottle", "Quiet between reactions", "He waits this long before reacting again", "range", ""],
      ["panes", "Revit and CAD panes", "He docks inside Revit and AutoCAD", "bool", ""],
    ]},
    {area:"Agents", id:"tools", title:"Tools in the Library", icon:"library", family:"list", wide:true, rows:[
    ]},
    {area:"Connections", id:"progs", title:"Programs", icon:"canvas", family:"model", wide:true, rows:[
      ["prog.Revit", "Revit", "Live status. ArchHub works inside it through its broker; its tools appear in the Library", "prog", ""],
      ["prog.AutoCAD", "AutoCAD", "Live status. ArchHub works inside it through its broker; its tools appear in the Library", "prog", ""],
      ["prog.3ds Max", "3ds Max", "Live status. ArchHub works inside it through its broker; its tools appear in the Library", "prog", ""],
      ["prog.Rhino", "Rhino", "Live status. ArchHub works inside it through its broker; its tools appear in the Library", "prog", ""],
      ["prog.Blender", "Blender", "Live status. ArchHub works inside it through its broker; its tools appear in the Library", "prog", ""],
      ["prog.Excel", "Excel", "Live status. ArchHub works inside it through its broker; its tools appear in the Library", "prog", ""],
      ["prog.Outlook", "Outlook", "Live status. ArchHub works inside it through its broker; its tools appear in the Library", "prog", ""],
    ]},
    {area:"Connections", id:"accts", title:"Accounts", icon:"link", family:"model", wide:true, rows:[
      ["acct.Autodesk Construction Cloud", "Autodesk Construction Cloud", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.Procore", "Procore", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.LinkedIn", "LinkedIn", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.Instagram", "Instagram", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.Facebook", "Facebook", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.X", "X", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.TikTok", "TikTok", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.WhatsApp Business", "WhatsApp Business", "Official Cloud API. Drafts wait for your Approve", "conn", ""],
      ["acct.Telegram", "Telegram", "Talk to BABOOM from Telegram, same threads", "conn", ""],
      ["acct.Google", "Google", "Posts and messages wait for your Approve", "conn", ""],
      ["acct.Notion", "Notion", "Posts and messages wait for your Approve", "conn", ""],
    ]},
    {area:"Connections", id:"subs", title:"Subscriptions", icon:"brain", family:"model", wide:false, rows:[
      ["sub.Claude Code", "Claude Code", "Signs in through its own app, in your browser. ArchHub never asks for its key", "sub", ""],
      ["sub.Codex", "Codex", "Signs in through its own app, in your browser. ArchHub never asks for its key", "sub", ""],
      ["sub.GitHub Copilot", "GitHub Copilot", "Signs in through its own app, in your browser. ArchHub never asks for its key", "sub", ""],
      ["sub.Gemini CLI", "Gemini CLI", "Signs in through its own app, in your browser. ArchHub never asks for its key", "sub", ""],
      ["sub.OpenCode", "OpenCode", "Signs in through its own app, in your browser. ArchHub never asks for its key", "sub", ""],
      ["sub.Antigravity", "Antigravity", "Signs in inside its own app", "sub", ""],
      ["sub.Cursor", "Cursor", "Signs in through its own app, in your browser. ArchHub never asks for its key", "sub", ""],
      ["sub.Grok", "Grok", "Signs in through its own app, in your browser. ArchHub never asks for its key", "sub", ""],
    ]},
    {area:"Connections", id:"mcps", title:"Tool servers (MCP)", icon:"link", family:"model", wide:true, rows:[
      ["mcp", "Your MCP servers", "Paste an address, a command or an mcp.json snippet. Its tools become Library nodes every agent can use; keys and sign-ins go to Windows Credential Manager", "mcps", ""],
    ]},
    {area:"Connections", id:"progopt", title:"Program options", icon:"settings", family:"model", wide:false, rows:[
      ["autoConnect", "Connect when a program opens", "ArchHub joins Revit, AutoCAD and Office as they start", "bool", ""],
      ["revitVer", "Revit version", "Used when more than one is installed", "select", ["Newest installed", "2025", "2024"]],
      ["revitPaths", "Revit found on this PC", "Read from the installed programs; the same list as the Programs tiles", "status", ""],
      ["acadVer", "AutoCAD version", "Used when more than one is installed", "select", ["Newest installed", "2025"]],
      ["acadPaths", "AutoCAD found on this PC", "Read from the installed programs; the same list as the Programs tiles", "status", ""],
      ["uiaApps", "Other Windows apps agents may drive", "Driven in the background, never with your mouse or screen", "list", ""],
    ]},
    {area:"Connections", id:"ai", title:"AI providers", icon:"brain", family:"model", wide:false, rows:[
      ["openrouter", "OpenRouter free models", "The free route every agent starts on", "bool", ""],
      ["providerKeys", "Other providers", "Keys go to Windows Credential Manager; ArchHub keeps only a reference", "action", ""],
      ["providerPrefs", "Model per provider", "Each provider starts with this model", "list", ""],
    ]},
    {area:"Connections", id:"phone", title:"Phone and cloud", icon:"link", family:"model", wide:false, rows:[
      ["phone", "ArchHub on your phone", "The same Workshop threads and BABOOM, as an app on your phone", "phone", ""],
      ["cloudReach", "Let your cloud agents reach this PC", "Off until you allow it; withdraw any time", "bool", ""],
      ["cloudPublish", "Publish to ArchHub cloud", "Off until you allow it; lets your phone see your maps", "bool", ""],
    ]},
    {area:"Connections", id:"net", title:"Network", icon:"link", family:"model", wide:false, rows:[
      ["proxy", "Proxy", "Leave empty for a direct connection", "text", ""],
      ["offline", "Work offline", "Uses the cached catalogue and docs; nothing is sent", "bool", ""],
    ]},
    {area:"Connections", id:"notify", title:"Notifications", icon:"bell", family:"model", wide:false, rows:[
      ["notifyNeeds", "Notify when something needs you", "Here and on your phone", "bool", ""],
      ["notifyDone", "Notify when a task finishes", "Here and on your phone", "bool", ""],
      ["notifyEvery", "Every message in my threads", "Off keeps it to what needs you and what finished", "bool", ""],
      ["desktopNotify", "Windows notifications", "Besides the bell in ArchHub", "bool", ""],
      ["sound", "Sound", "A short tone with each notification", "bool", ""],
      ["toastSecs", "Notices stay for", "Before they fade into the bell", "range", ""],
      ["quietFrom", "Quiet hours from", "Only approvals that would block work come through", "select", ["Off", "20:00", "21:00", "22:00", "23:00"]],
      ["quietTo", "Quiet hours until", "Notifications resume", "select", ["06:00", "07:00", "08:00", "09:00"]],
    ]},
    {area:"Account", id:"me", title:"Account", icon:"user", family:"agent", wide:false, rows:[
      ["account", "Account", "One sign-in. The account is the identity, never the machine", "acct", ""],
      ["photo", "Photo", "Shows wherever you appear: header, threads, the You node", "photo", ""],
      ["name", "Name", "How agents address you", "text", ""],
      ["role", "Role", "Agents read it on the You node of every canvas", "text", ""],
      ["firm", "Firm", "Shown on invites and receipts", "text", ""],
      ["email", "Email", "For invites and receipts", "text", ""],
      ["language", "App language", "Menus and labels", "select", ["English", "Arabic"]],
      ["rtl", "Right-to-left layout", "Auto turns it on with Arabic", "seg", ["Auto", "Always", "Never"]],
      ["numerals", "Numbers", "Digits in labels and answers", "seg", ["123", "١٢٣"]],
      ["replyLang", "Agents reply in", "Every agent, every thread", "select", ["English", "Arabic", "Both"]],
      ["timezone", "Time zone", "Schedules and dates use it", "select", ["Asia/Riyadh (GMT+3)", "Africa/Cairo (GMT+2)", "Asia/Dubai (GMT+4)", "UTC"]],
    ]},
    {area:"Account", id:"people", title:"Plan & access", icon:"users", family:"agent", wide:false, rows:[
      ["plan", "Plan", "Free until ArchHub is finished. Studio and Firm add seats and one shared Brain for your team", "select", ["Solo", "Studio", "Firm"]],
      ["devices", "Signed in on", "Every PC and browser using this account. Sign out ends that one only", "list", ""],
      ["office", "Active office", "Whose Library and people you see", "select", ["Personal", "Office"]],
      ["policyLock", "Office policy", "An office admin can lock values for everyone", "select", ["Office defaults, I can change them", "Office policy, locked by the admin"]],
      ["inviteRole", "Role for new invites", "Owner, Admin, Member or Viewer; change it per person after", "select", ["Member", "Viewer", "Admin"]],
      ["accessEnds", "Access ends", "Invites expire on their own", "select", ["Never", "30 days", "90 days", "When the project ends"]],
      ["officeInvites", "Invitations to other offices", "Accept or decline offices that invited you", "action", ""],
    ]},
    {area:"Account", id:"community", title:"Community", icon:"users", family:"list", wide:false, rows:[
      ["commProfile", "Public profile", "Your name and what you publish show on archhub.io › Community", "bool", ""],
      ["commHandle", "Profile address", "archhub.io/u/<this>", "text", ""],
      ["commPublished", "What you published", "Workflows and nodes in the Community. Unpublish keeps your copy", "list", ""],
      ["commNotify", "Tell me about installs and comments", "In the app and by email", "bool", ""],
    ]},
    {area:"Account", id:"social", title:"Social media", icon:"send", family:"effect", wide:false, rows:[
      ["socialAutoSend", "Send replies without asking", "Off: every post and reply waits for your Approve", "bool", ""],
      ["socialDigest", "Inbox digest", "A summary of new messages and leads", "seg", ["Off", "Daily", "Weekly"]],
    ]},
    {area:"Account", id:"memory", title:"Brain and cloud sync", icon:"brain", family:"agent", wide:false, rows:[
      ["memory", "What agents remember about you", "Every agent reads the same Brain. Forget removes a line; BABOOM confirms it in his thread", "list", ""],
      ["brainContext", "Memories in each request", "How many remembered lines an agent reads per request", "range", ""],
      ["syncBrain", "Brain follows your account", "Every PC and archhub.io read the same memories. Off keeps them on this PC", "bool", ""],
      ["syncSettings", "Settings follow your account", "Look, Agents and Connections choices are the same on every PC and on archhub.io. Projects and This PC stay here", "bool", ""],
      ["syncFiles", "Sync .archhub files", "Your tasks on your other PCs", "select", ["Off", "Office server", "OneDrive", "Google Drive"]],
    ]},
  ];
  const SearchCard=React.createContext(null);
  function AreaDesignCards({area,live={},extras={},bodies={},focused}) {
    const s=useData();
    const [expanded,setExpanded]=React.useState({});
    const searchCard=React.useContext(SearchCard);
    const pages=sheetAreas.find(item=>item.label===area).pages;
    const owned=(label,group)=>s.settings.find(row=>pages.includes(row.page)&&row.label===label&&(area!=='Projects'||row.group===group));
    return areaCardSpecs.filter(card=>card.area===area).map(card=>{
      const rows=card.rows;
      const visible=rows.filter(spec=>{
        if(!spec[5]||expanded[card.id]||searchCard===card.id)return true;
        const row=owned(spec[1],card.title);
        return row && row.default!==undefined && JSON.stringify(row.default)!==JSON.stringify(row.value);
      });
      return <section className={'sheet-pc-card sheet-owner-card'+(card.wide?' sheet-card-wide':'')} data-design-section={card.title} key={card.id}>
        <header className="sheet-card-head"><span className={'sheet-card-icon fam-'+card.family}><window.AHIcon name={card.icon} size={12}/></span><h3>{card.title}</h3>{['me','models','perm','workshop'].includes(card.id)&&<window.UI.Soon label={card.id==='me'?'You node':card.id==='workshop'?'Thread node':'Session node › Model'}><span className="sheet-action secondary" aria-disabled="true">{card.id==='me'?'You node':card.id==='workshop'?'Thread node':'Session node › Model'}</span></window.UI.Soon>}</header>
        {bodies[card.id]||<>{visible.map(spec=>{
          const [id,label,description]=spec, owner=owned(label,card.title);
          return <div className="sheet-property-row" data-kind={spec[3]} data-row={id} key={id}>
            <span className="sheet-property-copy">{window.UI.productLabel(label,s.settings)}<small>{window.UI.productLabel(description,s.settings)}</small></span>
            <div className="sheet-property-control">{live[id]??(owner?<SettingControl row={owner} presentation={spec[3]} unit={spec[3]==='step'?spec[4]:undefined}/>:<UpcomingControl spec={spec}/>)}</div>
          </div>;
        })}{visible.length<rows.length&&<Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>setExpanded(state=>({...state,[card.id]:true}))},event)}>{rows.length-visible.length} more</Btn>}</>}
        {extras[card.id]}
        {focused?.title===card.title && focused.content}
      </section>;
    });
  }

  function ProfileField({label,field,value}) {
    const u=useApp(),[draft,setDraft]=React.useState(value);
    function save(){
      const next=draft.trim();
      setDraft(value);
      if(next && next!==value)u.act(()=>api.updateProfile({[field]:next}));
    }
    return <input aria-label={label} maxLength={120} value={draft} placeholder={'Add your '+field}
      onChange={event=>setDraft(event.target.value)} onBlur={save}
      onKeyDown={event=>{if(event.key==='Enter')event.currentTarget.blur();if(event.key==='Escape')setDraft(value);}}/>;
  }

  function AccountDesignCards({checking,focused}) {
    const s=useData(),u=useApp(),profile=s.profile;
    const open=(label,action)=><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:action},event)}>{label}</Btn>;
    const live={
      account:<><span className="sheet-account-state" data-online={profile.signedIn} title={profile.signedIn?profile.email:undefined}>{checking?'Checking…':profile.signedIn?(profile.email?'Signed in as '+profile.email:'Signed in'):'Local session'}</span>
        {profile.signedIn?open('Sign out',()=>u.act(()=>api.signIn(false))):open('Sign in with Google',()=>u.show('Sign in'))}</>,
      name:<ProfileField key={JSON.stringify([profile.id,profile.name])} field="name" label="Name" value={profile.name||''}/>,
      firm:<ProfileField key={JSON.stringify([profile.id,profile.firm])} field="firm" label="Firm" value={profile.firm||''}/>,
      email:<input readOnly aria-label="Email" value={profile.email||''} placeholder="Add an email" title="Browser sign-in manages your email"/>,
      plan:open(profile.plan||'Choose plan',()=>u.go('access')),
      devices:open('Connected devices',()=>u.go('access')),
      memory:window.UI.MemoryRules?<window.UI.MemoryRules/>:undefined
    };
    if(profile.role)live.role=<input readOnly aria-label="Role" value={profile.role}/>;
    if(s.firms?.length)live.office=<select aria-label="Active office" value={s.activeFirm||''} onChange={event=>u.act(()=>api.selectFirm(event.target.value))}>
      {s.firms.map(firm=><option key={firm.id} value={firm.id}>{firm.name}</option>)}</select>;
    if(Array.isArray(s.officeInvitations))live.officeInvites=<div>
      {s.controlErrors?.officeInvitations?<span role="status">{s.controlErrors.officeInvitations}</span>:!s.officeInvitations.length&&<span>No office invitations.</span>}
      {s.officeInvitations.map(invite=><div key={invite.id}><b>{invite.office}</b> · {invite.status}
        {!['Accepted','Declined','Expired'].includes(invite.status)&&<>{open('Accept invitation',()=>u.act(()=>api.acceptOfficeInvitation(invite.id)))}{open('Decline invitation',()=>u.act(()=>api.declineOfficeInvitation(invite.id)))}</>}</div>)}</div>;

    const extras={
      people:open('Open Plan & access',()=>u.go('access')),
      community:open('Open Community',()=>u.go('community')),
      social:open('Open Social media',()=>u.go('social'))
    };
    return <AreaDesignCards area="Account" live={live} extras={extras} focused={focused}/>;
  }

  function ConnectionDesignCards({refresh,programNotice,focused}) {
    const s=useData(),u=useApp();
    const [chosen,setChosen]=React.useState('');
    const open=(label,action)=><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:action},event)}>{label}</Btn>;
    const live={
      mcp:<ToolServers/>,
      providerKeys:open('Add a provider',()=>u.go('settings/Providers')),
      providerPrefs:open('Manage provider models',()=>u.go('settings/Providers'))
    };
    const hosts=s.hosts||[],accounts=(s.connections||[]).filter(row=>!row.host);
    const selected=hosts.find(host=>host.id===chosen);
    function tiles(cardId,records,program) {
      const specs=areaCardSpecs.find(card=>card.id===cardId).rows;
      const byName=new Map(records.filter(row=>row.name).map(row=>[row.name,row]));
      const names=[...new Set([...specs.map(spec=>spec[1]),...byName.keys()])];
      return <div className="sheet-connection-tiles">{names.map(name=>{
        const record=byName.get(name),connected=program?['connected','listening'].includes(record?.state):Boolean(record?.connected);
        const status=record?(program?(record.state||'Status unavailable'):connected?(record.display_name||'Connected'):(record.blocker||'Not connected')):'';
        const activate=()=>program?setChosen(chosen===record.id?'':record.id):record.credential?u.show('My secrets'):u.show(connected?'Connection':'Connect',{id:record.id});
        const button=<button type="button" className="sheet-connection-tile" disabled={!record} data-connected={connected} aria-label={name+' · '+status} title={specs.find(spec=>spec[1]===name)?.[2]} onClick={event=>executeAction('projects.controls.activate',{handler:activate},event)}>
          <span aria-hidden="true">{name[0]}</span><b>{name}</b><small>{record?status:"\u00a0"}</small></button>;
        return record?<React.Fragment key={name}>{button}</React.Fragment>:<window.UI.Soon key={name} label={name}>{button}</window.UI.Soon>;
      })}</div>;
    }
    for(const provider of (s.providers||[]).filter(row=>typeof row.signIn==='boolean')){
      const status=provider.state==='not installed'?'Not installed':provider.signedIn===true?'Signed in':provider.signedIn===false?'Not signed in':'Installed · sign-in not checked';
      if(provider.state==='not supported')continue;
      live['sub.'+provider.name]=<><span>{status}</span>{provider.signIn&&provider.signedIn!==true&&open('Sign in',()=>u.act(()=>api.signInProvider(provider.id)))}</>;
    }
    const extras={
      progs:<>{programNotice}{selected&&<p aria-live="polite">{[selected.name,selected.document||selected.document_name||selected.detail||'No document reported',(selected.agents||[]).map(agent=>agent.name||agent).join(', ')].filter(Boolean).join(' · ')}</p>}</>,
      accts:<>{open('Connect',()=>u.show('Connect'))}{open('Refresh',refresh)}</>,
      ai:focused?.title==='AI providers'?null:open('Open model providers',()=>u.go('settings/Providers')),
      phone:open('Open connected devices',()=>u.go('access')),
      notify:open('Open notification setting',()=>u.go('settings/BABOOM'))
    };
    return <AreaDesignCards area="Connections" focused={focused} live={live} extras={extras} bodies={{progs:tiles('progs',hosts,true),accts:tiles('accts',accounts,false)}}/>;
  }

  // Presentation only: all values and mutations remain with their Settings owners.
  const pcCards = [
    { id:"theme", title:"Theme and colour", icon:"palette", family:"look", rows:[
      ["theme", "Theme", "Choose the application theme", "seg", ["Dark", "Light", "System"]],
      ["themeSet", "Theme set", "Forge, Blueprint or Vellum colours; the Appearance node can author more", "seg", ["Forge", "Blueprint", "Vellum"]],
      ["accent", "Accent", "Primary actions, selection and running state", "color", ""],
      ["highContrast", "High contrast", "Stronger text and lines", "bool", ""],
      ["lookIO", "Share the look", "Copy your colours and sizes; paste them on another PC from the ⋯ menu", "action", "Copy the look"],
      ["bgPanel", "Panels and nodes", "Node cards, inspector and lists", "color", ""],
      ["bgCanvas", "Canvas", "The ground under the nodes", "color", ""],
      ["ink", "Text", "Titles and values", "color", ""]
    ] },
    { id:"size", title:"Size and density", icon:"eye", family:"look", rows:[
      ["uiScale", "UI scale", "Zoom the whole interface. Ctrl + and Ctrl - change it, Ctrl 0 resets", "step", ""],
      ["textSize", "Text size", "Adjust interface text size", "step", ""],
      ["density", "Density", "Space in rows, tabs and buttons", "seg", ["Comfortable", "Compact"]],
      ["reduceMotion", "Reduce motion", "Limit interface animation", "bool", ""]
    ] },
    { id:"layout", title:"Panels", icon:"arrange", family:"look", rows:[
      ["layout", "Layout", "How panels are arranged when a task opens. Save your own from the layout button", "seg", ["Build", "Review", "Meeting"]],
      ["dockL", "Left panel width", "Drag the panel edge or set it here", "step", ""],
      ["dockR", "Right panel width", "Drag the panel edge or set it here", "step", ""],
      ["dockB", "Bottom panel height", "Drag the panel edge or set it here", "step", ""]
    ] },
    { id:"canvas", title:"Canvas", icon:"canvas", family:"look", rows:[
      ["grid", "Grid", "Show the grid when a workflow opens", "bool", ""],
      ["snapGrid", "Snap to grid", "Nodes land on a 16 px grid when you drop them", "bool", ""],
      ["wireVis", "Wires", "Show every wire, only those of the selected node, or none", "seg", ["Always", "On hover", "Hidden"]],
      ["defaultZoom", "Default zoom", "Set the starting zoom for a workflow", "step", ""],
      ["radius", "Node corners", "Corner radius of node cards", "range", "", true],
      ["row", "Socket row height", "Space between sockets", "range", "", true],
      ["wire", "Wire width", "Thickness of wires", "range", "", true],
      ["cyan", "Event", "Task and event sockets", "color", "", true],
      ["warn", "Number", "Number sockets; also \"needs you\"", "color", "", true],
      ["ok", "File", "File sockets and finished steps", "color", "", true],
      ["purple", "Yes / no", "Boolean sockets", "color", "", true]
    ] },
    { id:"keys", title:"Keyboard", icon:"code", family:"look", rows:[
      ["shortcuts", "Keyboard shortcuts", "One shortcut per action, the same in menus and Ctrl K. Change any of them", "action", "Show all"]
    ] },
    { id:"pc", title:"Agents on this PC", icon:"shield", family:"check", rows:[
      ["gate.Claude Code", "Claude Code", "Stop and PreToolUse gates keep it inside your rules", "gate", ""],
      ["gate.Codex", "Codex", "Stop and PreToolUse gates keep it inside your rules", "gate", ""],
      ["gate.OpenCode", "OpenCode", "Stop and PreToolUse gates keep it inside your rules", "gate", ""],
      ["gate.Gemini CLI", "Gemini CLI", "Stop and PreToolUse gates keep it inside your rules", "gate", ""],
      ["gate.BABOOM", "BABOOM", "Stop and PreToolUse gates keep it inside your rules", "gate", ""],
      ["gate.Antigravity", "Antigravity", "Stop and PreToolUse gates keep it inside your rules", "gate", ""],
      ["retireAgents", "Forget idle agents after", "An agent that stopped reporting drops off the list", "range", ""]
    ] },
    { id:"files", title:"Workspaces and files", icon:"folder", family:"model", rows:[
      ["ws", "Workspace folder", "Workflow files travel with you; local paths stay editable", "folder", ""],
      ["sessions", "Tasks folder", "Where .archhub files are saved", "folder", ""],
      ["wsPrivacy", "Workspace privacy", "Confidential and Secret never leave this PC; Secret also keeps learning private", "seg", ["Internal", "Confidential", "Secret"]],
      ["wsReadOnly", "Read-only for agents", "Agents read this workspace but never write to it", "bool", ""],
      ["wsRules", "Workspace rules", "Every agent in this workspace reads them; new Workshop nodes start from them", "text", ""],
      ["canvasWs", "Workspaces a canvas can use", "Folders an agent on any canvas may open", "list", "Add workspace"],
      ["wsShareLearn", "Share what agents learn with the team", "Off when the workspace is Secret", "bool", ""],
      ["settingsScope", "Settings apply to", "Just you, or everyone who works in this workspace", "seg", ["User", "Workspace"]],
      ["activeWs", "Workspace whose settings apply", "Used when Settings apply to a workspace", "select", []]
    ] },
    { id:"privacy", title:"Privacy and keys", icon:"shield", family:"check", rows:[
      ["reviewShare", "Review before sharing", "Anything that leaves your PC waits for your Approve", "bool", ""],
      ["askTranscribe", "Ask before meeting transcription", "The meeting agent asks the room before it records", "bool", ""],
      ["secrets", "Protected connections", "Keys live in Windows Credential Manager, never in .archhub files or prompts", "list", "Add key"],
      ["auditLog", "What agents did", "Every write, send and approval with its receipt", "action", "Open"],
      ["retention", "Conversation retention", "Conversations become knowledge, then the transcript is removed", "select", ["20 days", "30 days", "90 days", "Keep"]],
      ["telemetry", "Send anonymous usage data", "Counts and timings only, never file contents", "bool", ""]
    ] },
    { id:"app", title:"The app", icon:"settings", family:"model", rows:[
      ["updMode", "Updates", "New versions install from main only", "select", ["Install when idle", "Ask me first", "Install when I quit"]],
      ["updChannel", "Channel", "Preview gets builds a day earlier", "seg", ["Stable", "Preview"]],
      ["updCheck", "Check for updates every", "Quietly, in the background", "range", ""],
      ["updIdle", "Install after you are idle for", "Only when no agent is running", "range", ""],
      ["tray", "Keep running in the tray", "Closing the window keeps agents and BABOOM running", "bool", ""],
      ["backups", "Backups kept", "Settings and .archhub files, before every update", "range", ""],
      ["backupTo", "Back up to", "Copies stay off this PC when it is not This PC", "select", ["This PC", "Office server", "OneDrive", "Google Drive"]],
      ["backupDir", "Backup folder", "Used when backing up to this PC", "folder", ""],
      ["backupLimit", "Backup space", "Oldest backups go first above it", "range", ""],
      ["backupNow", "Back up now", "One backup of settings and open files", "action", "Back up now"],
      ["cacheLimit", "Cache size", "Thumbnails, catalogue and docs kept offline", "range", ""],
      ["logKeep", "Keep logs for", "Then they are deleted", "range", ""],
      ["diagExport", "Diagnostics", "One file with logs and app health, no keys and no client data", "action", "Export diagnostics"],
      ["profileIO", "Settings profile", "Move all your settings to another PC", "action", "Export or import"]
    ] },
    { id:"sysgraph", title:"System graph", icon:"link", family:"agent", rows:[
      ["sysgraph", "How the app is wired now", "Read only. Agents, the owners that hold each kind of data, the model routes and the program brokers, wired the way they run right now. Click a node for its owner, file and state", "sysgraph", ""]
    ] }
  ];
  const designSearchRows=[...areaCardSpecs,...pcCards].flatMap(card=>{
    const area=card.area||'This PC', page=sheetAreas.find(item=>item.label===area).target;
    const fields=card.rows.map(([id,label,description,,options,advanced])=>({
      id:'design.'+card.id+'.'+id, field:id, card:card.id, group:card.title, page, area, label, description,
      options:Array.isArray(options)?options:[], advanced:!!advanced
    }));
    return [{id:'card.'+card.id,card:card.id,group:card.title,page,area,label:card.title},...fields];
  });
  const pcAnchors = {Look:'Theme and colour', Privacy:'Workspaces and files', Advanced:'Workspaces and files', System:'Agents on this PC', 'System graph':'Agents on this PC', 'Updates & About':'The app'};
  const pcOwnerLabels = Object.fromEntries([
    ['theme', 'Theme'],
    ['accent', 'Accent colour'],
    ['highContrast', 'High contrast'],
    ['textSize', 'Text scale'],
    ['reduceMotion', 'Reduce motion'],
    ['dockR', 'Inspector width'],
    ['grid', 'Canvas grid'],
    ['defaultZoom', 'Default zoom'],
    ['radius', 'Node radius'],
    ['row', 'Row spacing'],
    ['reviewShare', 'Review before sharing'],
    ['askTranscribe', 'Ask before meeting transcription'],
    ['retention', 'Conversation retention'],
    ['tray', 'Keep running in tray']
  ]);
  function pcOwner(settings, spec) {
    const label=pcOwnerLabels[spec[0]]||spec[1];
    return settings.find(row=>row.label===label && (spec[0] in pcOwnerLabels || row.page==='Appearance'));
  }
  function UpcomingControl({spec}) {
    const [,label,,type,options]=spec;
    let control;
    switch(type){
      case 'seg': control=<span className="sheet-segments">{options.map(option=><span className="sheet-action secondary" aria-disabled="true" key={option}>{option}</span>)}</span>; break;
      case 'select': control=<select disabled aria-label={label}>{options.map(option=><option key={option}>{option}</option>)}</select>; break;
      case 'step': case 'range': control=<input disabled type="range" aria-label={label}/>; break;
      case 'color': control=<input disabled type="color" aria-label={label}/>; break;
      case 'bool': control=<input type="checkbox" role="switch" disabled aria-label={label}/>; break;
      case 'text': control=<input disabled aria-label={label}/>; break;
      default: control=<span className="sheet-action secondary" aria-disabled="true">{options||({gate:'Manage gates',folder:'Choose a folder'}[type])||label}</span>;
    }
    return <window.UI.Soon label={label}>{control}</window.UI.Soon>;
  }
  function PcSettingsCards({page,advanced,setAdvanced,additional}) {
    const s=useData(),u=useApp();
    const workspace=(s.workspaces||[]).find(w=>w.id===s.activeWorkspace);
    const policy=s.workspacePolicies?.[workspace?.id]||workspace||{};
    const [updatesOpen,setUpdatesOpen]=React.useState(page==='Updates & About');
    const destination=s.settingsDestination;
    const scopeDisabled=!destination||s.settingsScopePending;
    const chooseScope=(scope,id=undefined)=>u.act(()=>api.setSettingsScope(scope,destination,id));
    const selectWorkspace=event=>chooseScope('Workspace',event.target.value);
    const actButton=(text,handler,title=undefined)=><Btn sm title={title} onClick={event=>executeAction('projects.controls.activate',{handler},event)}>{text}</Btn>;
    function control(spec) {
      const [id,label,,,options]=spec;
      const owner=pcOwner(s.settings,spec);
      if(id==='accent'&&owner){
        const choose=color=>u.act(()=>api.setSetting(owner.id,color,destination));
        return <div className="sheet-accent-swatches" role="group" aria-label={label} data-setting={owner.id}>
          {['#d97757','#e5b25a','#7ec18e','#5fb3b3','#7898d6','#a98cd6'].map(color=><button type="button" key={color} aria-label={label+' '+color} aria-pressed={String(owner.value).toLowerCase()===color} disabled={scopeDisabled} style={{'--swatch':color}} onClick={event=>executeAction('projects.controls.activate',{handler:()=>choose(color)},event)}/>)}
          <label><input type="color" aria-label={'Pick '+label} value={owner.value} disabled={scopeDisabled} onChange={e=>choose(e.target.value)}/><span>{owner.value}</span></label>
          {isChangedOwner(owner)&&<Btn sm ghost aria-label={'Reset '+label} disabled={scopeDisabled} onClick={event=>executeAction('sharedUI.Reset.21',{api,row:owner,u,destination},event)}>Reset</Btn>}
        </div>;
      }
      if(owner)return <SettingControl row={owner} raw={advanced}/>;
      switch(id) {
        case 'shortcuts': return <details open={advanced||undefined} className="sheet-keybindings"><summary>Show all</summary><KeyboardSettings/></details>;
        case 'sessions': return actButton(shortPath(s.sessionsFolder||'Choose a folder'),()=>u.act(api.chooseSessionsFolder),s.sessionsFolder);
        case 'ws': return actButton(shortPath(workspace?.path||workspace?.folder||'Choose a folder'),()=>u.act(api.addWorkspace),workspace?.path||workspace?.folder);
        case 'wsPrivacy': case 'wsRules': case 'wsShareLearn': {
          const key={wsPrivacy:'privacy',wsRules:'rules',wsShareLearn:'shareLearning'}[id];
          const save=value=>u.act(()=>api.setWorkspaceRules(workspace.id,{[key]:value}));
          const unavailable=!workspace || workspace.builtIn || policy.privacy==='public';
          if(id==='wsPrivacy')return <select disabled={unavailable} aria-label={label} value={policy.privacy||''} onChange={e=>save(e.target.value)}><option value="" disabled>Choose privacy</option>{options.map(item=><option key={item}>{item}</option>)}</select>;
          if(id==='wsRules')return <textarea key={JSON.stringify([workspace?.id,policy.rules])} aria-label={label} disabled={unavailable} defaultValue={policy.rules||''} maxLength={16000} onBlur={e=>{if(e.target.value!==(policy.rules||''))save(e.target.value);}}/>;
          return <input type="checkbox" role="switch" aria-label={label} disabled={unavailable||policy.privacy==='Secret'} checked={!!policy.shareLearning} onChange={e=>save(e.target.checked)}/>;
        }
        case 'canvasWs': return <details><summary>Manage workspaces</summary><WorkspaceRows/></details>;
        case 'settingsScope': return <select aria-label={label} disabled={scopeDisabled} value={s.settingsScope||'User'} onChange={e=>chooseScope(e.target.value)}>{['User','Workspace','Session'].map(item=><option key={item} disabled={item!=='User'&&!s.settingsScopes?.[item]}>{item}</option>)}</select>;
        case 'activeWs': return <select aria-label={label} disabled={scopeDisabled} value={s.settingsScope==='Workspace'?destination?.workspace||'':''} onChange={selectWorkspace}><option value="" disabled>Choose a workspace</option>{(s.workspaces||[]).filter(w=>!w.builtIn&&w.available!==false).map(w=><option value={w.id} key={w.id}>{w.name}</option>)}</select>;
        case 'secrets': return actButton('Manage protected connections',()=>u.go('settings/Connections'));
        case 'auditLog': return actButton('Open',()=>u.go('receipts'));
        case 'profileIO': return <details><summary>Export or import</summary><PreferencesTransfer/></details>;
        case 'sysgraph': return window.UI.SystemGraph?<window.UI.SystemGraph/>:<UpcomingControl spec={spec}/>;
      }
      if(id.startsWith('gate.')){
        const agent=(s.agents||[]).find(a=>a.name===label);
        if(agent?.gate==='live')return <span>Gates on</span>;
        if(agent?.gate==='missing')return actButton('Manage gates',()=>u.go('dependencies'));
      }
      return <UpcomingControl spec={spec}/>;
    }
    const isChangedOwner=row=>row && row.default!==undefined && JSON.stringify(row.value)!==JSON.stringify(row.default);
    return pcCards.map(card=>{
      const visible=card.rows.filter(spec=>!spec[5]||advanced||isChangedOwner(pcOwner(s.settings,spec)));
      return <section key={card.id} data-design-section={card.title} className={'sheet-pc-card sheet-owner-card pc-'+card.id+(card.id==='sysgraph'?' sheet-card-wide':'')}><header className="sheet-card-head"><span className={'sheet-card-icon fam-'+card.family}><window.AHIcon name={card.icon} size={12}/></span><h3>{card.title}</h3></header>
        {visible.map(spec=><div className={'sheet-property-row'+(['theme','themeSet','accent','density','layout'].includes(spec[0])?' sheet-property-visual':'')} data-row={spec[0]} key={spec[0]}><span className="sheet-property-copy">{spec[1]}<small>{spec[2]}</small></span><div className="sheet-property-control">{control(spec)}</div></div>)}
        {visible.length<card.rows.length&&actButton((card.rows.length-visible.length)+' more',()=>setAdvanced(true))}
        {card.id==='app'&&<details open={updatesOpen} onToggle={event=>setUpdatesOpen(event.currentTarget.open)}><summary>Updates &amp; About</summary>{updatesOpen&&<UpdatesPage/>}</details>}
        {card.id==='pc'&&actButton('Open dependencies',()=>u.go('dependencies'))}
        {additional[card.title]?.length>0&&<details open={advanced||undefined}><summary>More controls</summary>{additional[card.title].map(row=><SettingControl key={row.id} row={row} raw={advanced}/>)}</details>}
        {card.id==='sysgraph'&&<details><summary>Tools &amp; diagnostics</summary>{[['Agents','settings/Agents'],['Router','settings/BABOOM'],['Workshop','workshop'],['Programs','settings/Connections'],['Hooks','settings/Hooks'],['Updates','settings/Updates & About'],['Diagnostics','receipts']].map(([title,route])=><Btn sm key={route} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.go(route)},event)}>{title}</Btn>)}</details>}
      </section>;
    });
  }
  const pageLabels = {BABOOM:'Models & BABOOM', Appearance:'Look', Privacy:'Workspaces & privacy', 'System graph':'System'};
  function requestGroups(requests, agents, providers) {
    const groups = new Map();
    for (const row of requests) {
      const identity = [...agents,...providers].find(agent => agent.id === row.agent || agent.name === row.agent || agent.sessions?.some(session=>session.root===row.agent));
      const agent = identity?.name || row.agent_name || (/^(BABOOM|Claude Code|Codex|OpenCode|Gemini|Goose)$/i.test(row.agent||'') ? row.agent : 'Unidentified agent');
      const key = JSON.stringify([identity?.id||row.agent||agent,row.model,row.provider]);
      if (!groups.has(key)) groups.set(key,{key,agent,model:row.model,provider:row.provider,count:0,tokens:0,measuredTokens:0,ms:0,measuredTime:0});
      const group = groups.get(key); group.count++;
      if (Number.isFinite(row.tokens)) {group.tokens+=row.tokens;group.measuredTokens++;}
      if (Number.isFinite(row.ms) && row.ms > 0) {group.ms+=row.ms;group.measuredTime++;}
    }
    return [...groups.values()];
  }
  function RouterSettings() {
    const s=useData(),u=useApp();
    const [model,setModel]=React.useState('');
    const [attempt,setAttempt]=React.useState(0),[load,setLoad]=React.useState({status:'waiting'});
    React.useEffect(()=>{
      let current=true;setLoad({status:'waiting'});
      api.refreshRouter(attempt>0).then(r=>{if(current){setModel(r.default_model);setLoad({status:r.requests.length?'loaded':'empty'});}},
        error=>{if(current)setLoad({status:'error',message:error.message});});
      return()=>{current=false;};
    },[attempt]);
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS,{
      RouterRefresh:()=>setAttempt(value=>value+1),
      RouterModel:value=>u.act(()=>api.setRouterSettings({default_model:value}))
    });
    if(load.status==='waiting')return <p role="status">Reading router settings…</p>;
    if(load.status==='error')return <div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.ds_settings3.RouterRefresh',event)}>Retry router</Btn></div>;
    const r=s.router;
    const models=[...new Set([r.default_model,...r.fallback_models,...r.models])];
    const groups=requestGroups(r.requests,s.agents||[],s.providers||[]);
    const total=groups.reduce((sum,row)=>({count:sum.count+row.count,tokens:sum.tokens+row.tokens,ms:sum.ms+row.ms,measuredTokens:sum.measuredTokens+row.measuredTokens,measuredTime:sum.measuredTime+row.measuredTime}),{count:0,tokens:0,ms:0,measuredTokens:0,measuredTime:0});
    const time=row=>row.measuredTime ? `${row.ms.toLocaleString()} ms${row.measuredTime<row.count ? ' (partial)' : ''}` : 'Not measured';
    const tokens=row=>row.measuredTokens ? `${row.tokens.toLocaleString()}${row.measuredTokens<row.count ? ' (partial)' : ''}` : 'Not reported';
    return <Card style={{padding:18}}><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><h2>Models &amp; request profiling</h2><label>Default free model<select aria-label="Default free model" value={model} onChange={e=>{setModel(e.target.value);runAction('settings.ds_settings3.RouterModel',e.target.value);}}>{models.map(m=><option key={m}>{m}</option>)}</select></label><p className="muted">Free first · no paid fallbacks · request metadata kept for 20 days</p><Btn sm onClick={event=>runAction('settings.ds_settings3.RouterRefresh',event)}>Refresh models and requests</Btn><div className="router-table-scroll"><table className="router-requests" aria-label="Router requests"><thead><tr><th scope="col">Agent</th><th scope="col">Model</th><th scope="col">Provider</th><th scope="col">Requests</th><th scope="col">Tokens</th><th scope="col">Measured time</th></tr></thead><tbody>{groups.map(row=><tr key={row.key}><th scope="row">{row.agent}</th><td>{row.model}</td><td>{row.provider}</td><td>{row.count}</td><td>{tokens(row)}</td><td>{time(row)}</td></tr>)}</tbody><tfoot><tr><th scope="row" colSpan={3}>Total</th><td>{total.count}</td><td>{tokens(total)}</td><td>{time(total)}</td></tr></tfoot></table></div>{load.status==='empty'&&<p>No model requests yet.</p>}{load.status==='loaded'&&<p>{r.requests.length} recent requests</p>}<h3>Live agent processes</h3><p>{r.live_agents.complete?'Observed processes':'Process observation incomplete'}</p>{r.live_agents.processes.map(p=><p key={p.pid}>{p.runtime} · PID {p.pid}</p>)}</Card>;
  }
  // Run mode and per-tool modes: parameters of the one decision every agent's hook runs.
  function Permissions({rulesOnly=false}) {
    const [saving,setSaving]=React.useState(false);
    const [p,setP]=React.useState(null),[tool,setTool]=React.useState('');
    const [attempt,setAttempt]=React.useState(0),[load,setLoad]=React.useState({status:'waiting'});
    React.useEffect(()=>{
      let current=true;setLoad({status:'waiting'});
      api.readPermissions().then(r=>{if(current){setP(r);setLoad({status:Object.keys(r.tools||{}).length?'loaded':'empty'});}},
        error=>{if(current)setLoad({status:'error',message:error.message});});
      return()=>{current=false;};
    },[attempt]);
    const save=async values=>{
      setSaving(true);
      try {
        const result=await api.setPermissions(values);
        setP(result);
        setLoad({status:Object.keys(result.tools||{}).length?'loaded':'empty'});
        return result;
      } finally {setSaving(false);}
    };
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS,{
      PermissionsRefresh:()=>setAttempt(value=>value+1),
      PermissionsSave:values=>save(values),
      PermissionsRemove:name=>{const next={...p.tools};delete next[name];return save({tools:next});},
      PermissionsAdd:()=>save({tools:{...p.tools,[tool.trim()]:'Ask'}}).then(r=>{setTool('');return r;})
    });
    if(load.status==='waiting')return <p role="status">Reading permissions…</p>;
    if(load.status==='error')return <div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.ds_settings3.PermissionsRefresh',event)}>Retry permissions</Btn></div>;
    const ruleModes=p.ruleModes||[];
    const rules=<fieldset className="sheet-workspace-rules"><legend>Workspace rules</legend>
      {Object.entries(p.rules||{}).map(([id,saved])=>{
        const schema=p.ruleCatalogue?.[id], title=schema?.title||p.ruleTitles?.[id]||id.replaceAll('-',' ');
        const rule=typeof saved==='string'?{state:saved}:saved;
        const change=patch=>runAction('settings.ds_settings3.PermissionsSave',{rules:{[id]:patch}});
        const textField=(label,value,patch,maxLength)=><label className="sheet-property-row" key={label}><span>{label}</span>
          <input key={value} aria-label={label} defaultValue={value} maxLength={maxLength} disabled={saving}
            onKeyDown={event=>{if(event.key==='Escape')event.currentTarget.value=value;if(event.key==='Enter')event.currentTarget.blur();}}
            onBlur={event=>{const next=event.currentTarget.value;event.currentTarget.value=value;if(next!==value)change(patch(next));}}/></label>;
        return <fieldset key={id}><legend>{schema?.standard&&<small>STD {schema.standard} · </small>}{title}</legend>
          <label className="sheet-property-row"><span>State</span><select aria-label={title} disabled={saving||!ruleModes.length} value={rule.state}
            onChange={event=>change(schema?{state:event.target.value}:event.target.value)}>
            {ruleModes.map(choice=><option key={choice}>{choice}</option>)}</select></label>
          {schema&&<><label className="sheet-property-row"><span>When broken</span><select disabled={saving} value={rule.onViolation}
            onChange={event=>change({onViolation:event.target.value})}>{(p.ruleViolations||[]).map(choice=><option key={choice}>{choice}</option>)}</select></label>
            {textField('Applies to',rule.appliesTo||'All agents',value=>({appliesTo:value}),400)}
            {Object.entries(schema.params||{}).map(([name,fallback])=>textField(name,rule.params?.[name]??fallback,value=>({params:{[name]:value}}),1000))}
          </>}
        </fieldset>;
      })}
      {!Object.keys(p.rules||{}).length&&<p>No workspace rules reported.</p>}
    </fieldset>;
    if(rulesOnly)return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction}/>{rules}</>;
    return <Card style={{padding:18}}><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><h2>Permissions</h2>
      <label>Run mode<select aria-label="Run mode" value={p.runMode} onChange={e=>runAction('settings.ds_settings3.PermissionsSave',{runMode:e.target.value})}>{p.runModes.map(m=><option key={m}>{m}</option>)}</select></label>
      <p className="muted">Routine work in your own folders never asks. Plan only: agents read and plan, nothing changes.</p>
      {load.status==='empty'&&<p>No tool modes yet: every tool follows the run mode.</p>}
      {load.status==='loaded'&&<table aria-label="Tool modes"><thead><tr><th>Tool</th><th>Mode</th><th /></tr></thead><tbody>{Object.entries(p.tools).map(([name,mode])=><tr key={name}><td>{name}</td><td><select aria-label={'Mode for '+name} value={mode} onChange={e=>runAction('settings.ds_settings3.PermissionsSave',{tools:{...p.tools,[name]:e.target.value}})}>{p.toolModes.map(m=><option key={m}>{m}</option>)}</select></td><td><Btn sm ghost aria-label={'Remove '+name} onClick={()=>runAction('settings.ds_settings3.PermissionsRemove',name)}>×</Btn></td></tr>)}</tbody></table>}
      <div className="flex"><input aria-label="Tool name or pattern" placeholder="Tool name, e.g. WebFetch or mcp__slack__*" value={tool} onChange={e=>setTool(e.target.value)} /><Btn sm disabled={!tool.trim()} onClick={event=>runAction('settings.ds_settings3.PermissionsAdd',event)}>Add tool</Btn></div>{rules}</Card>;
  }
  function Connections() {
    const s = useData(),
      u = useApp();
    const [filter, setFilter] = React.useState('All');
    const [attempt, setAttempt] = React.useState(0), [load, setLoad] = React.useState({status:'waiting'});
    React.useEffect(()=>{
      let current=true;
      setLoad({status:'waiting'});
      Promise.allSettled([api.refreshSocialConnections,api.readHostAvailability,api.refreshSettingsControls].map(read=>read())).then(results=>{
        if(!current)return;
        const errors=results.filter(r=>r.status==='rejected').map(r=>r.reason.message);
        setLoad({status:errors.length?'error':'loaded',message:errors.join(' ')});
      });
      return()=>{current=false;};
    },[s.profile?.id,attempt]);
    const connections = [...(s.hosts||[]).map(c=>({...c,id:'host:'+c.id,host:true,connected:['connected','listening'].includes(c.state)})), ...s.connections,
      ...s.secrets.filter(c=>!s.connections.some(row=>row.vault_entry===c.vault_entry&&c.vault_entry)).map(c=>({...c,id:'credential:'+c.id,credential:true}))];
    const status=load.status==='loaded'&&!connections.length?'empty':load.status;
    const group = c => c.host || ['Revit', 'AutoCAD', 'Rhino', '3ds Max', 'Office'].includes(c.name) ? 'Programs' : ['Instagram', 'Facebook', 'WhatsApp Business', 'LinkedIn', 'X', 'TikTok', 'YouTube'].includes(c.name) ? 'Social' : 'Work apps';
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {ConnectionsAction0: (g, event) => (() => setFilter(g))(event),
ConnectionsAction1: (c, event) => (() => c.host ? u.go(c.connected?'watcher':'settings/Dependencies') : c.credential ? u.show('My secrets') : c.connected ? u.show('Connection', {
              id: c.id
            }) : u.show('Connect', {
              id: c.id
            }))(event),ConnectionsAction2:()=>setAttempt(value=>value+1)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div className="grid">{status==='waiting'&&<p role="status">Reading programs and accounts…</p>}{s.hostsProbing&&status!=='waiting'&&<p role="status">Checking programs…</p>}{s.hostError&&<p role="alert">{s.hostError}</p>}{status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.ds_settings3.ConnectionsAction2',event)}>Retry Connections</Btn></div>}<div className="flex">{['All', 'Programs', 'Social', 'Work apps'].map(g => <Btn sm ghost key={g} aria-pressed={filter === g} onClick={event => runAction('settings.ds_settings3.ConnectionsAction0', g, event)}>{g}</Btn>)}</div><Card>{status==='loaded'&&<div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 130px',
          padding: '14px 16px 8px',
          fontSize: 'calc(11px * var(--text-scale,1))',
          color: A.inkSoft
        }}><span>PROGRAM OR ACCOUNT</span><span /></div>}{connections.filter(c => filter === 'All' || group(c) === filter).map((c, i) => <div key={c.id} style={{
          display: 'grid',
          gridTemplateColumns: '1fr 130px',
          alignItems: 'center',
          padding: '8px 16px',
          borderTop: '1px solid ' + A.lineSoft
        }}><div className="flex"><span style={{
              width: 36,
              height: 36,
              borderRadius: 9,
              background: [A.blue, A.ok, A.purple, A.accent][i % 4],
              color: '#fff',
              display: 'grid',
              placeItems: 'center',
              fontWeight: 800
            }}>{c.name[0]}</span><div><h3>{c.name}</h3><span className="muted" style={{
                fontSize: 'calc(12px * var(--text-scale,1))'
              }}>{c.host ? c.detail||c.state : c.credential ? 'Saved in Windows Credential Manager' : c.connected ? c.display_name||'Connected to your account' : c.blocker||'Connect this account to use it'}{c.checked ? ' · checked' : ''}</span></div></div><div style={{
            justifySelf: 'end'
          }}><Btn sm onClick={event => runAction('settings.ds_settings3.ConnectionsAction1', c, event)}>{c.credential ? 'Details' : c.connected ? 'Open' : c.host?'Manage':'Connect'}</Btn></div></div>)}</Card>{status==='empty'&&<Empty>Connect an account or start a program with its ArchHub bridge, then refresh Connections.</Empty>}</div></>;
  }
  function ProjectRegister({workspace}) {
    const s = useData(), u = useApp();
    const register = workspace?.register;
    const [number, setNumber] = React.useState(register?.number || '');
    const [override, setOverride] = React.useState(register?.override || false);
    React.useEffect(()=>setNumber(register?.number||''),[register?.number]);
    React.useEffect(()=>setOverride(Boolean(register?.override)),[register?.override]);
    const [saving, setSaving] = React.useState(false);
    const [naming, setNaming] = React.useState(register?.namingRegister || '');
    const [issued, setIssued] = React.useState(register?.issuedRegister || '');
    const [destination, setDestination] = React.useState(register?.issuedDestination || '');
    const pickedProject = React.useRef(workspace?.id);
    pickedProject.current = workspace?.id;
    // A saved or switched register shows its owner value (a picked path comes back project-relative).
    React.useEffect(() => { setNaming(register?.namingRegister || ''); setIssued(register?.issuedRegister || ''); setDestination(register?.issuedDestination || ''); },
      [workspace?.id, register?.namingRegister, register?.issuedRegister, register?.issuedDestination]);
    const changed = register && (number !== register.number || override !== register.override
      || naming !== (register.namingRegister || '') || issued !== (register.issuedRegister || '') || destination !== (register.issuedDestination || ''));
    const saveRegister = async () => {
      if (saving) return;
      setSaving(true);
      try { await u.act(()=>api.updateProjectRegister(workspace,number,override,{namingRegister:naming.trim(),issuedRegister:issued.trim(),issuedDestination:destination.trim()})); } finally { setSaving(false); }
    };
    // A picked file fills the field; a cancelled pick leaves it as it was. Saving still goes through the owner.
    const [pick, setPick] = React.useState({state: 'empty', error: '', result: null, last: null});
    const pickRegister = async (key, title) => {
      setPick({state: 'waiting', error: '', result: null, last: [key, title]});
      try {
        const id = workspace?.id;
        const result = await api.pickProjectRegister(title, key === 'issuedDestination');
        if (id !== pickedProject.current) { setPick({state:'empty',error:'',result:null,last:null}); return null; }
        if (result.path) (key === 'namingRegister' ? setNaming : key === 'issuedDestination' ? setDestination : setIssued)(result.path);
        setPick({state: result.note ? 'error' : 'loaded', error: result.note || '', result, last: [key, title]});
        return result;
      } catch (failure) {
        setPick({state: 'error', error: failure.message || String(failure), result: null, last: [key, title]});
        return null;
      }
    };
    pick.retry = () => pick.last && pickRegister(...pick.last);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {SaveProjectRegister:saveRegister, PickProjectRegister:pickRegister, EditLocalClient:()=>u.act(()=>api.editLocalProjectClient(workspace.id))});
    const files = workspace?.registerFiles || {};
    const fileState = (key, value) => !value ? '' : value !== (register[key] || '') ? 'Checked when you save.'
      : files[key] === 'usable' ? 'Found in this project.' : files[key] === 'missing' ? 'File not found in this project folder.' : 'No longer a valid register path; choose it again.';
    const registerField = (key, label, value, setValue) => <div className="grid" data-register-field={key}>
      <label>{label}<input aria-label={label} value={value} maxLength={240} placeholder={key === 'issuedDestination' ? 'Optional folder inside this project' : 'A file inside this project folder'} onChange={event=>setValue(event.target.value)}/></label>
      <button type="button" className="sheet-action" aria-label={'Choose ' + label.toLowerCase()} onClick={event=>runAction('settings.ds_settings3.PickProjectRegister', key, 'Choose the ' + label.toLowerCase(), event)}>Choose…</button>
      {value && key !== 'issuedDestination' && <small role="status" data-register-state={value !== (register[key] || '') ? 'pending' : files[key] || 'refused'}>{fileState(key, value)}</small>}</div>;
    const fields=areaCardSpecs.find(card=>card.id==='register').rows;
    const controls={
      projNumber:<input aria-label="Project number" disabled={!register} value={number} maxLength={80} onChange={event=>setNumber(event.target.value)}/>,
      projOverride:<D.Toggle label="This project overrides office defaults" disabled={!register} checked={override} onCheckedChange={setOverride}/>,
      projClient:workspace?.nativeClientEditor?<Btn sm aria-label="Edit local client" onClick={event=>runAction('settings.ds_settings3.EditLocalClient',event)}>Edit client on this PC</Btn>:null
    };
    return <form aria-label="Edit project register" onSubmit={event=>{event.preventDefault();if(changed)runAction('settings.ds_settings3.SaveProjectRegister',event);}}>
      <window.UI.RegisteredActionStatus state={actionState} retry={retryAction}/>
      {fields.map(spec=><div key={spec[0]} className="sheet-property-row"><span className="sheet-property-copy">{spec[1]}<small>{spec[2]}</small></span>
        <div className="sheet-property-control">{controls[spec[0]]||<UpcomingControl spec={spec}/>}</div></div>)}
      <details><summary>Registered project</summary>
      <label>Registered project<select aria-label="Registered project" value={workspace?.id || ''} onChange={event=>u.act(()=>api.selectWorkspace(event.target.value))}>
        <option value="" disabled>Choose a project</option>{s.workspaces.filter(row=>!row.builtIn && row.available !== false).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      {register&&<>        {registerField('namingRegister', 'Naming register', naming, setNaming)}
        {registerField('issuedRegister', 'Issued register', issued, setIssued)}
        {registerField('issuedDestination', 'Issued destination folder', destination, setDestination)}
        <small>The naming and issued-containers registers this project has adopted. ArchHub keeps only where they are, never their contents.</small>
        <div aria-live="polite">{pick.state === 'waiting' && <p role="status">Choose the file in the window that opened…</p>}
          {pick.state === 'error' && <div role="alert"><p>{pick.error}</p><window.UI.RegisteredActionStatus state={{status:'error',message:pick.error}} retry={()=>pick.retry()}/></div>}
          {pick.state === 'empty' && <span className="visually-hidden">No file chosen.</span>}
          {pick.state === 'loaded' && <span className="visually-hidden">{pick.result?.path ? 'Register chosen; save to keep it.' : 'Nothing chosen; the register is unchanged.'}</span>}</div>
</>}</details>
      {register&&<button type="submit" className="sheet-action" disabled={saving||!changed}>Save register</button>}
    </form>;
  }
  function WorkspaceRows() {
    const s = useData(),
      u = useApp();
    const [newProject,setNewProject]=React.useState(false), [projectName,setProjectName]=React.useState(''),
      [projectParent,setProjectParent]=React.useState(''), [projectTemplate,setProjectTemplate]=React.useState(''), [templateSource,setTemplateSource]=React.useState(''), [creating,setCreating]=React.useState(false);
    const createProject=async()=>{
      if(creating)return;
      setCreating(true);
      try {
        const result=await u.act(()=>api.addWorkspace({create:true,parent:projectParent,name:projectName,template:projectTemplate,templateSource:projectTemplate?templateSource:''}));
        if(result?.root){setNewProject(false);setProjectName('');setTemplateSource('');setProjectTemplate('');}
      } finally {setCreating(false);}
    };
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {WorkspaceRowsAction0: (event) => (() => u.pickWorkspace())(event),
WorkspaceRowsAction1: (w, event) => (async () => {
            const opened=await u.act(() => api.selectWorkspace(w.id));
            if(opened?.ok)u.go('home');
          })(event),
WorkspaceRowsAction2: (w, event) => (() => u.show('Workspace rules', {
            id: w.id
          }))(event),
WorkspaceRowsAction3: (w, event) => (() => u.confirm('Remove this workspace from the list?', () => api.removeWorkspace(w.id)))(event),
WorkspaceRowsAction4: (event) => (() => u.act(api.listWorkspaces))(event),
NewProject:()=>setNewProject(value=>!value), CreateProject:createProject, CancelProject:()=>setNewProject(false), PickProjectTemplate:async()=>{const picked=await u.act(()=>api.chooseProjectTemplate());if(picked?.path)setTemplateSource(picked.path);}});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><Card><div className="spread" style={{
        padding: 16
      }}><div><h2>Workspaces</h2><small className="muted">Choose the folders ArchHub and your agents work in.</small></div><div className="flex"><Btn sm onClick={event=>runAction('settings.ds_settings3.NewProject',event)}>New project</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction0', event)}>Add workspace</Btn></div></div>{newProject&&<form className="row grid" aria-label="New project" onSubmit={event=>{event.preventDefault();runAction('settings.ds_settings3.CreateProject',event);}}><label>Project name<input aria-label="Project name" value={projectName} disabled={creating} onChange={event=>setProjectName(event.target.value)}/></label><label>Parent workspace<select aria-label="Parent workspace" value={projectParent} disabled={creating} onChange={event=>setProjectParent(event.target.value)}><option value="">Choose a registered folder</option>{s.workspaces.filter(w=>!w.builtIn&&w.available!==false).map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label><label>New project folders<select aria-label="New project folders" value={projectTemplate} disabled={creating} onChange={event=>setProjectTemplate(event.target.value)}><option value="">{s.workspaces.find(w=>w.id===projectParent)?.projectTemplate||'Parent default'}</option><option value="ISO 19650 CDE tree" disabled>ISO 19650 CDE tree — approved source unavailable</option><option value="Office project tree">Office project tree</option></select></label>{projectTemplate&&<div><Btn sm disabled={creating} onClick={event=>runAction('settings.ds_settings3.PickProjectTemplate',event)}>Choose template folder</Btn><span role="status">{templateSource?'Template folder selected.':'Choose the approved template folder.'}</span><p>Copies folders only, outside the ArchHub workspace. Files and the source stay unchanged.</p></div>}<p>Existing folders stay as they are.</p><div className="flex"><button type="submit" className="sheet-action" onClick={event=>{event.preventDefault();runAction('settings.ds_settings3.CreateProject',event);}} disabled={creating||!projectName.trim()||!projectParent||Boolean(projectTemplate&&!templateSource)}>{creating?'Creating…':'Create project'}</button><Btn sm ghost disabled={creating} onClick={event=>runAction('settings.ds_settings3.CancelProject',event)}>Cancel</Btn></div></form>}<div className="row muted" role={s.workspaceHealth?.state === 'error' ? 'alert' : 'status'}>{s.workspaceHealth?.message || 'Reading workspaces…'}{s.workspaceHealth?.state === 'error' && <Btn sm ghost onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction4', event)}>Retry</Btn>}</div>{s.workspaceHealth?.recovery && <div className="row muted">{s.workspaceHealth.recovery.message}</div>}{s.workspaces.map(w => <div key={w.id} className="spread row"><D.Toggle label={'Use ' + w.name} checked={(s.graph.workspaceIds || []).includes(w.id)} onCheckedChange={v => u.act(() => api.setGraphWorkspaces(v ? [...new Set([...(s.graph.workspaceIds || []), w.id])] : (s.graph.workspaceIds || []).filter(id => id !== w.id)))} /><div className="fill"><h3>{w.name}</h3><span className="muted" style={{
            fontSize: 'calc(12px * var(--text-scale,1))'
          }}>{w.folder} · {w.available === false ? 'Folder unavailable' : (s.workspaceHealth?.state === 'ready' || (s.workspaceHealth?.state === 'idle' && w.builtIn)) ? 'Ready' : 'Checking…'}</span></div><div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction1', w, event)}>Open</Btn><Btn sm ghost aria-label={'Privacy ' + w.name} title="Workspace privacy" onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction2', w, event)}><window.AHIcon name="shield" size={16} /></Btn>{!w.builtIn && w.removable !== false && <Btn sm ghost onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction3', w, event)}>Remove</Btn>}</div></div>)}{!s.workspaces.some(w => !w.builtIn) && <Empty>No other workspaces yet.</Empty>}</Card></>;
  }
  function Account() {
    const s = useData(),
      u = useApp();
    const initials = window.UI.profileInitials(s.profile);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {AccountAction0: (event) => (() => u.act(api.syncAccount))(event),
AccountAction1: (event) => (() => s.profile.signedIn ? u.act(() => api.signIn(false)) : u.show('Sign in'))(event),
AccountAction2: (label, event) => (() => u.show(label))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div className="account-overview">
      <section className="account-identity" aria-label="Your identity">
        <div className="account-avatar">{initials}</div>
        <div className="fill"><div className="flex"><h2>{s.profile.name}</h2><Chip c={s.profile.signedIn ? A.ok : A.inkSoft}>{s.profile.signedIn ? 'Signed in' : 'Signed out'}</Chip></div><p className="muted">{s.profile.email}</p><div className="account-sync"><span className="status-dot" /><span>{s.sync}</span><Btn sm ghost onClick={event => runAction('settings.ds_settings3.AccountAction0', event)}>Sync</Btn></div></div>
        <Btn sm ghost onClick={event => runAction('settings.ds_settings3.AccountAction1', event)}>{s.profile.signedIn ? 'Sign out' : 'Sign in with your browser'}</Btn>
      </section>
      <div className="account-shortcuts">{[['My profile','user','How you appear to your team'],['My secrets','shield','Your protected connections'],['My files','docs',s.files.length+' project files']].map(([label, icon, detail]) => <button className="account-shortcut" key={label} aria-label={label} onClick={event => runAction('settings.ds_settings3.AccountAction2', label, event)}><span className="account-shortcut-icon"><window.AHIcon name={icon} size={20} /></span><span className="fill"><b>{label}</b><small>{detail}</small></span><window.AHIcon name="arrow" size={15} /></button>)}</div>
      <window.UI.AccountIdentity />
      <WorkspaceRows />
    </div></>;
  }
  function Storage() {
    const s = useData(),
      u = useApp();
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {StorageAction0: (event) => (() => u.act(api.archiveActivity))(event),
StorageAction1: (event) => (() => u.act(api.backUpNow))(event),
StorageAction2: (b, event) => (() => u.confirm('Prepare this verified backup for recovery?', () => api.rollBack(b.id)))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><Card style={{
      padding: 16,
      display: 'grid',
      gap: 12
    }}><h2>Where your work lives</h2><p className="muted">Workflows and settings stay with your account. Client work stays on this machine.</p><div className="flex">{api.supportsAction?.('archiveActivity') !== false && <Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction0', event)}>Archive old activity</Btn>}<window.UI.Soon label="Cloud backup — coming"><Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction1', event)}>Back up now</Btn></window.UI.Soon></div>{s.backups.map(b => <div className="spread" key={b.id}><span>{b.name}</span><Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction2', b, event)}>Roll back</Btn></div>)}</Card></>;
  }
  // The one update card: current build, update state and Check for updates (api.checkForUpdates).
  function UpdateCard({runAction, autoInstall}) {
    const s = useData();
    return <Card style={{
            padding: 16
          }}><div className="spread"><div><h2>ArchHub</h2><p className="muted">{s.update.installed || 'Installed build unavailable'}</p></div>{s.update.available ? <Btn p onClick={event => runAction('settings.ds_settings3.SettingsAction8', event)}>Update</Btn> : <Chip c={s.update.state === 'idle' ? A.ok : A.warn}>{s.update.state === 'idle' ? s.update.detail : s.update.detail || 'Update status unavailable'}</Chip>}</div>
          {s.update.restartRefusal && <p role="alert">{s.update.restartRefusal}</p>}
          {autoInstall !== undefined && <label className="spread" data-setting="Updates.Install automatically" style={{marginTop: 12}}><span>Install updates automatically when I am away or ArchHub is in the tray</span><input type="checkbox" aria-label="Install updates automatically" disabled={autoInstall === null} checked={!!autoInstall} onChange={event => runAction('settings.ds_settings3.UpdatesAutoInstall', event.target.checked, event)} /></label>}
          {s.update.updatedTo && <div role="status" className="spread"><span>Updated {s.update.updatedFrom || 'ArchHub'} → {s.update.updatedTo}</span><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction9', event)}>Dismiss update confirmation</Btn></div>}
          <div className="flex" style={{
              marginTop: 12,
              flexWrap: 'wrap'
            }}><Btn sm disabled={s.update.state === 'checking' || s.update.state === 'restarting'} onClick={event => runAction('settings.ds_settings3.SettingsAction10', event)}>Check for updates</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction11', event)}>What’s new</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction12', event)}>First run</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction13', event)}>Docs</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction14', event)}>Feedback</Btn></div></Card>;
  }
  // Settings → System → Updates: the update card with its own action owner, so its failure shows here.
  function UpdatesPage() {
    const u = useApp();
    // The same stored value the Workshop node's update_auto_apply_on_quit parameter edits; the update policy reads it.
    const [autoInstall, setAutoInstall] = React.useState(null);
    const [load, setLoad] = React.useState('waiting');
    const readSaved = React.useCallback(() => {
      setLoad('waiting');
      return api.getApplicationSettings().then(saved => {
        setAutoInstall(saved.update_auto_apply_on_quit !== false);
        setLoad(Object.keys(saved).length ? 'loaded' : 'empty');
      }, error => {
        setAutoInstall(null);
        setLoad('error');
        throw error;
      });
    }, []);
    React.useEffect(() => { readSaved().catch(error => console.warn('Update setting unreadable:', error.message)); }, [readSaved]);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {
      UpdatesSettingRetry: () => u.act(readSaved),
      UpdatesAutoInstall: next => u.act(async () => {
        const saved = await api.setApplicationSetting('update_auto_apply_on_quit', next);
        setAutoInstall(saved.update_auto_apply_on_quit !== false);
        return saved;
      }),
      SettingsAction8: () => u.show('Update'),
      SettingsAction9: () => u.act(api.acknowledgeUpdate),
      SettingsAction10: () => u.act(api.checkForUpdates),
      SettingsAction11: () => u.show('What’s new'),
      SettingsAction12: () => u.go('first-run'),
      SettingsAction13: () => u.go('docs'),
      SettingsAction14: () => u.go('feedback')
    });
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} />
      {load === 'waiting' && <p className="muted">Reading your update setting…</p>}
      {load === 'error' && <p role="alert">Your update setting could not be read. <Btn sm onClick={event => runAction('settings.ds_settings3.UpdatesSettingRetry', event)}>Retry</Btn></p>}
      {load === 'empty' && <p className="muted">Automatic updates use the default (on) until you change them below.</p>}
      {load === 'loaded' && <p className="muted">Automatic updates are {autoInstall ? 'on' : 'off'}.</p>}
      <UpdateCard runAction={runAction} autoInstall={load === 'loaded' || load === 'empty' ? autoInstall : undefined} /></>;
  }
  function AdvancedSettings({
    page = 'Account',
    full = false
  }) {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState(''),
      [changed, setChanged] = React.useState(false);
    const actual = s.pages.includes(page) ? page : sections.find(section=>section.name===page)?.pages[0] || 'Account';
    const section = sections.find(section=>section.pages.includes(actual));
    const matched = [...s.settings, ...s.capabilities.map(c => ({
      id: c.id,
      page: c.page,
      label: c.name,
      group: 'Capabilities',
      capability: true
    }))].filter(r => `${r.label} ${r.group} ${r.page}`.toLowerCase().includes(query.toLowerCase()));
    const visible = s.settings.filter(r => r.page === actual && (!r.advanced || u.advanced || actual === 'Advanced') && (!changed || JSON.stringify(r.value) !== JSON.stringify(r.default)));
    const groups = [...new Set(visible.map(r => r.group))];
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {SettingsAction0: (r, event) => (() => {
            setQuery('');
            if (r.capability) {
              u.show('Capability', {
                id: r.id
              });
              return;
            }
            u.go('settings/' + r.page);
            requestAnimationFrame(() => document.querySelector(`[data-setting="${r.id}"]`)?.scrollIntoView({
              block: 'center'
            }));
          })(event),
SettingsAction1: (p, event) => (() => u.go('settings/' + p))(event),
SettingsAction2: (event) => (() => u.go(doors[actual]))(event),
SettingsAction3: (event) => (() => u.act(() => api.resetPage(actual)))(event),
SettingsAction4: (event) => (() => u.go('colleagues'))(event),
SettingsAction5: (event) => (() => u.go('settings/BABOOM'))(event),
SettingsAction6: (event) => (() => u.go('community'))(event),
SettingsAction7: (event) => (() => u.go('dependencies'))(event),
SettingsAction8: (event) => (() => u.show('Update'))(event),
SettingsAction9: (event) => (() => u.act(api.acknowledgeUpdate))(event),
SettingsAction10: (event) => (() => u.act(api.checkForUpdates))(event),
SettingsAction11: (event) => (() => u.show('What’s new'))(event),
SettingsAction12: (event) => (() => u.go('first-run'))(event),
SettingsAction13: (event) => (() => u.go('docs'))(event),
SettingsAction14: (event) => (() => u.go('feedback'))(event),
SettingsAction15: (event) => (() => u.download('Brain'))(event),
SettingsAction16: (event) => (() => u.act(api.syncAccount))(event),
SettingsAction17: (event) => (() => u.go('library'))(event),
SettingsAction18: (event) => (() => u.go('skills'))(event),
SettingsAction19: (event) => (() => u.go('home'))(event),
SettingsAction20: (event) => (() => u.show('Install mod'))(event),
SettingsAction21: (event) => (() => u.go('receipts'))(event),
SettingsAction22: (event) => (() => u.download('Receipts'))(event),
SettingsAction23: (event) => (() => u.go('receipts'))(event),
SettingsAction24: (event) => (() => u.go('docs'))(event),
SettingsAction25: () => u.act(api.listAgentsWorking)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div data-screen={'settings/' + actual} style={{
      display: 'grid',
      gridTemplateColumns: full ? 'minmax(0,1fr)' : 'var(--layout-settings-sidebar-width) minmax(0,1fr)',
      minHeight: 0
    }}>
  {!full && <aside className="pane settings-side" style={{
        padding: '18px 12px'
      }}><h1 style={{
          fontSize: 'calc(20px * var(--text-scale,1))',
          padding: '0 10px 12px'
        }}>Settings</h1><input aria-label="Find a setting" placeholder="⌕ Find a setting" value={query} onChange={e => setQuery(e.target.value)} style={{
          width: '100%',
          height: 34
        }} /><div className="spread" style={{
          padding: '12px 6px 8px',
          fontSize: 'calc(13px * var(--text-scale,1))',
          color: A.inkSoft
        }}><span>Show advanced</span><D.Toggle variant="settings" label="Show advanced" checked={u.advanced} onCheckedChange={u.setAdvanced} /></div>
   {query ? <div className="grid">{matched.map(r => <button key={r.id} className="listbutton" onClick={event => runAction('settings.ds_settings3.SettingsAction0', r, event)}><b>{r.label}</b><p className="muted" style={{
              fontSize: 'calc(11px * var(--text-scale,1))'
            }}>{r.page} › {r.group}</p></button>)}{!matched.length && <Empty>No matching setting.</Empty>}</div> : sections.map(group => <button className="listbutton flex settings-section" key={group.name} aria-selected={section===group} onClick={event => runAction('settings.ds_settings3.SettingsAction1', group.pages[0], event)}>{group.name}</button>)}
  <div className="settings-subpages">{section.pages.map((p,i)=><button className="listbutton" key={p} aria-selected={actual===p} onClick={event=>runAction('settings.ds_settings3.SettingsAction1',p,event)}>{p==='System graph'?'Live wiring':p}</button>)}</div>
  </aside>}
  <main className={'page penpot-settings' + (actual === 'Account' ? ' account-settings' : '')} style={{
        padding: '22px 32px'
      }}><nav className="settings-tabs" aria-label={section.name}>{section.pages.map((p,i)=><button className="tab-button" aria-current={actual===p?'page':undefined} key={p} onClick={event=>runAction('settings.ds_settings3.SettingsAction1',p,event)}>{section.tabs[i]}</button>)}{actual==='Account'&&<><button className="tab-button" onClick={event=>runAction('settings.ds_settings3.SettingsAction2',event)}>Plan &amp; access</button><button className="tab-button" onClick={event=>runAction('settings.ds_settings3.SettingsAction12',event)}>First run</button></>}{actual==='Appearance'&&<button className="tab-button" onClick={()=>u.go('interface')}>Interface studio</button>}</nav><div className="settings-title"><span className="settings-page-header-icon"><window.AHIcon name={["user", "link", "voice", "users", "brain", "canvas", "workshop", "library", "clock", "shield", "code", "shield", "palette", "update", "settings"][s.pages.indexOf(actual)]} size={21} /></span><Heading title={actual==='System graph'?'Live wiring':actual} sub={{
          Account: 'Your identity, workspaces and project files.',
          Connections: 'The programs and accounts your agents can work with.',
          BABOOM: 'Your companion’s providers, voice, presence and boundaries.',
          Agents: 'How your agents choose, finish and hand over work.',
          Brain: 'What your agents remember, and how they learn.',
          Appearance: 'Make ArchHub comfortable for the way you work.',
          Advanced: 'Fine control over loading, performance and connection limits.',
          Privacy: 'Control what stays local and what can leave your workspace.',
          'Updates & About': 'One update, with your work kept intact.'
        }[actual] || 'Your preferences for ' + actual.toLowerCase() + '.'}><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction2', event)}>{actual === 'System graph' ? 'Open workflow' : actual === 'BABOOM' ? 'Open BABOOM' : 'Show as node'}</Btn><Btn sm ghost onClick={event => runAction('settings.ds_settings3.SettingsAction3', event)}>Reset preferences</Btn></Heading></div>
   {u.advanced && <div className="flex settings-scope" style={{
          marginBottom: 14
        }}><label className="flex muted">Scope<select disabled={!s.settingsDestination||s.settingsScopePending} aria-busy={Boolean(s.settingsScopePending)} aria-label="Settings scope" value={s.settingsScope} onChange={e => {const value=e.target.value,destination=s.settingsDestination;return u.act(() => api.setSettingsScope(value,destination));}}><option>User</option><option>Workspace</option></select></label><span className="fill" /><span className="muted">{s.settingsScope === 'Workspace' ? s.workspaces.find(w => w.id === s.activeWorkspace)?.name : 'Your account'}</span></div>}<div className="settings-health"><span className="status-dot" /><span>{actual === 'Connections' ? (s.connections.filter(c => c.connected).length+(s.hosts||[]).filter(c=>['connected','listening'].includes(c.state)).length) + ' accounts and programs connected' : actual === 'BABOOM' ? s.providers.filter(p => p.enabled && p.signedIn).length + ' providers ready' : actual === 'Agents' ? s.agentHealth||'Checking running agents…' : actual === 'Account' ? s.profile.firm + ' · ' + s.workspaces.length + ' workspace' : actual === 'Updates & About' ? s.update.available ? 'An update is ready' : s.update.detail || 'Update status unavailable' : 'Preferences'}</span></div><div className="flex settings-filter" style={{
          marginBottom: 14
        }}><D.Toggle label="Changed only" checked={changed} onCheckedChange={setChanged} /><span className="muted" style={{
            fontSize: 'calc(12px * var(--text-scale,1))'
          }}>Changed only</span>{full && <><span className="fill" /><span>Show advanced</span><D.Toggle label="Show advanced" checked={u.advanced} onCheckedChange={u.setAdvanced} /></>}</div>
   <div className="grid">
    {actual === 'System graph' && <window.UI.SystemGraph />}
    {actual === 'Account' && <Account />}<window.UI.CapabilityRows page={actual} />
    {actual === 'Connections' && <Connections />}
    {actual === 'Agents' && <RouterSettings />}
    {actual === 'Hooks' && <Permissions />}
    {actual === 'BABOOM' && <Providers />}{actual === 'Agents' && <><Card style={{
            padding: 18
          }}><div className="spread"><h2>Agents at work</h2><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction4', event)}>Open</Btn></div><p role="status">{s.agentSummary||'Checking running agents…'}</p><p className="muted">{s.agentHealth||'Checking running agents…'}</p><Btn sm onClick={event=>runAction('settings.ds_settings3.SettingsAction25',event)}>{s.agentSummary==='Agent status is incomplete.'?'Check again':'Refresh'}</Btn>{(s.agents||[]).filter(p=>p.kind!=='observation').map(p => <div className="spread row" key={p.id}><span className="flex"><window.UI.Av id={p.id} size={24} /><span><b>{p.name}</b><small className="muted" style={{display:'block'}}>{p.title} · {p.model}</small><small style={{display:'block'}}>{p.task}</small>{p.detail&&<small className="muted" style={{display:'block'}}>{p.detail}</small>}</span></span><Chip c={p.presence === 'working' ? A.ok : p.presence === 'unknown' ? A.warn : A.inkSoft}>{p.status_text||'Idle'}</Chip></div>)}<button className="listbutton flex" onClick={event => runAction('settings.ds_settings3.SettingsAction5', event)}>Manage providers<window.AHIcon name="arrow" size={15} /></button></Card><Providers /></>}
    {actual === 'Brain' && <><window.UI.MemoryRules /><Btn onClick={event => runAction('settings.ds_settings3.SettingsAction6', event)}>Community</Btn></>}
    {actual === 'Automations' && <window.UI.Automations embedded />}
    {actual === 'Dependencies' && <Card style={{
            padding: 22
          }}><div className="spread"><div><h2>Managed tools</h2><p className="muted">Versions, health, resources and the features that use each tool.</p></div><Btn p onClick={event => runAction('settings.ds_settings3.SettingsAction7', event)}>Open dependencies</Btn></div><div className="dependency-mini">{s.dependencies.slice(0, 5).map(d => <div className="row spread" key={d.id}><span>{d.name}</span><Chip c={d.state === 'Ready' ? A.ok : A.warn}>{d.state}</Chip></div>)}</div></Card>}
{actual === 'Updates & About' && <UpdateCard runAction={runAction} />}
    <div className="settings-grid">{groups.map(group => <Card key={group} style={{
              padding: '10px 14px 8px'
            }}><h3 style={{
                marginBottom: 8,
                fontSize: 'calc(14.5px * var(--text-scale,1))'
              }}>{group}</h3>{visible.filter(r => r.group === group).map(r => <SettingControl key={r.id} row={r} raw={u.advanced || actual === 'Advanced'} />)}</Card>)}</div>
    {actual === 'Account' && <Storage />}
    {actual === 'Brain' && <div className="flex"><Chip c={A.ok}>{s.brain.length} facts</Chip><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction15', event)}>Export</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction16', event)}>Sync to cloud</Btn></div>}
    {actual === 'Library & Mods' && <window.UI.HostSkills />}{actual === 'Library & Mods' && <div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction17', event)}>Open Library</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction18', event)}>Open Sessions</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction19', event)}>Open Templates</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction20', event)}>Install from folder</Btn></div>}
    {actual === 'BABOOM' && <div className="spread"><h3>Receipts · {s.receipts.length} actions</h3><div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction21', event)}>Open receipts</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction22', event)}>Export</Btn></div></div>}
    {actual === 'Advanced' && <div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction23', event)}>Open log</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction24', event)}>Docs &amp; website</Btn></div>}
   </div>
  </main>
 </div></>;
  }
  const SHEET_ACTIONS = {'settings.sheet.Refresh':'Refresh'};
  function executeAction(...args) {return window.executeAction(...args);}
  // Board r1963: one-line value box; the full value lives in the tooltip.
  function SheetField({label,value,children,onClick,description,title,unit,named}) {
    const full=title ?? (typeof value==='string'?value:undefined);
    return <div className="sheet-field" data-unit={unit||undefined} data-named={named||undefined}><span>{label}{description&&<small>{description}</small>}</span><div>{children || (onClick ? <button className="button-reset sheet-value" title={full} onClick={event=>executeAction('projects.controls.activate',{handler:onClick},event)}>{value}</button> : <span className="sheet-value" title={full}>{value ?? 'Not reported'}</span>)}</div></div>;
  }
  const shortPath=folder=>{const parts=String(folder).split(/[\\/]/).filter(Boolean);return parts.length>2?'…\\'+parts.slice(-2).join('\\'):folder;};
  function SheetPreference({label,match,raw=false}) {
    const s=useData(),row=s.settings.find(match || (r=>r.label===label));
    // Every element acts or goes: a preference with no settings-owner row is not shown.
    if(!row)return null;
    const unit=row.id==='Appearance.Default zoom'?'%':'';const named=row.id==='Appearance.Text scale'&&row.value===100?'Default':'';
    return <SheetField label={label} unit={unit} named={named} description={({Theme:row.value==='System'?'Follow the operating system':'Choose the application theme','Text size':'Adjust interface text size','Reduce motion':'Limit interface animation',Grid:'Show the grid when a workflow opens','Default zoom':'Set the starting zoom for a workflow','Review before sharing':'Check anything before it leaves this computer','Ask before meeting transcription':'Ask before a meeting is transcribed'})[label]}><SettingControl row={row} raw={raw} /></SheetField>;
  }
  // Subscriptions he already pays for: each signs in through its own app or CLI, never a key typed here.
  // The person's own MCP servers: one field takes an address, a command or an mcp.json snippet.
  function ToolServers() {
    const s=useData(),u=useApp(),[text,setText]=React.useState(''),[load,setLoad]=React.useState({status:'waiting'}),[attempt,setAttempt]=React.useState(0);
    React.useEffect(()=>{let current=true;setLoad({status:'waiting'});api.refreshMcpServers().then(rows=>{if(current)setLoad({status:rows?.length?'loaded':'empty'});},error=>{if(current)setLoad({status:'error',message:error?.message||'Could not read tool servers.'});});return()=>{current=false;};},[attempt]);
    const rows=s.mcpServers||[];
    const row=r=><div className="spread row" key={r.id}><span><b>{r.name}</b><small className="muted" style={{display:'block'}}>{r.where}{r.secrets?' · '+r.secrets+(r.secrets>1?' keys':' key')+' in Credential Manager':''}</small><small style={{display:'block'}}>{r.status}</small></span><span className="flex">{r.status==='Sign in needed'&&<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.signInMcpServer(r.id))},event)}>Sign in</Btn>}<Btn sm ghost disabled={!r.enabled} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.discoverMcpTools(r.id))},event)}>Check</Btn><D.Toggle label={(r.enabled?'Switch off ':'Switch on ')+r.name} checked={r.enabled} onCheckedChange={on=>u.act(()=>api.setMcpServerEnabled(r.id,on))} /><Btn sm ghost aria-label={'Remove '+r.name} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.removeMcpServer(r.id))},event)}>Remove</Btn></span></div>;
    return <div className="sheet-tool-servers">{load.status==='waiting'&&<p role="status">Reading tool servers…</p>}{load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAttempt(value=>value+1)},event)}>Retry tool servers</Btn></div>}{load.status==='empty'&&<p>No tool servers yet.</p>}{load.status==='loaded'&&<div className="sheet-fields">{rows.map(row)}</div>}<textarea aria-label="Add a tool server" rows={3} placeholder={'https://… · npx -y @scope/server · {"mcpServers": {…}}'} value={text} onChange={event=>setText(event.target.value)} /><Btn sm disabled={!text.trim()} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(async()=>{const result=await api.addMcpServer(text);setText('');setLoad({status:'loaded'});return result;})},event)}>Add tool server</Btn></div>;
  }
  function PreferencesTransfer() {
    const s=useData(),u=useApp(),input=React.useRef(null),last=React.useRef(null);
    const [load,setLoad]=React.useState({status:'empty'});
    const destination=s.settingsDestination,scope=s.settingsScope||'User',label={User:'Everywhere',Workspace:'Current workspace',Session:'Current session'}[scope];
    const run=action=>{last.current=action;setLoad({status:'waiting'});return u.act(async()=>{try{const result=await action();setLoad({status:'loaded'});return result;}catch(error){setLoad({status:'error',message:error.message||String(error)});throw error;}});};
    return <section aria-label="Transfer settings"><div className="flex">
      <Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(async()=>{
        const {content}=await api.exportData('Settings','All');
        await navigator.clipboard.writeText(content);
        u.setToast('Settings copied.');
      })},event)}>Copy all settings</Btn>
      <Btn sm ghost disabled={!destination||s.settingsScopePending} onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(async()=>{
        const {content}=await api.exportData('Settings',scope);
        u.show('Paste settings',{text:content,destination,label});
      })},event)}>Paste settings…</Btn>
      <Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.download('Settings',scope)},event)}>Export {label}</Btn>
      <Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.download('Settings','All')},event)}>Export all scopes</Btn>
      <Btn sm ghost disabled={!destination||s.settingsScopePending||load.status==='waiting'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>input.current?.click()},event)}>Import into {label}</Btn>
      <input ref={input} type="file" accept=".json,application/json" aria-label="Import settings file" hidden onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(!file)return;executeAction('projects.controls.activate',{handler:()=>run(async()=>{if(file.size>1048576)throw Error('Choose a settings export up to 1 MiB.');return api.importPreferences(JSON.parse(await file.text()),destination);})},event);}} />
      <Btn sm ghost disabled={!destination||s.settingsScopePending||load.status==='waiting'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.confirm('Reset all settings in '+label+'? Other scopes stay as they are.',()=>run(()=>api.resetPreferences(destination)))},event)}>Reset {label}</Btn>
    </div><p className="muted">Transfers Look, project and keyboard preferences. Accounts, sign-ins, permissions and layouts stay with their own controls. Import applies only to {label}.</p>
    {load.status==='waiting'&&<p role="status">Applying settings...</p>}{load.status==='empty'&&<span className="visually-hidden">No settings transfer requested.</span>}{load.status==='loaded'&&<p role="status">Settings applied to {label}.</p>}{load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(last.current)},event)}>Retry settings transfer</Btn></div>}
    </section>;
  }

  function PasteSettings({initial, destination, label, close}) {
    const [text,setText]=React.useState(initial), [error,setError]=React.useState(''), [busy,setBusy]=React.useState(false);
    const submit=async copy=>{
      setError('');
      setBusy(true);
      try {
        if(copy) {
          await navigator.clipboard.writeText(text);
        } else {
          if(new Blob([text]).size>1048576) throw Error('Paste a settings export up to 1 MiB.');
          await api.importPreferences(JSON.parse(text),destination);
          close();
        }
      } catch(e) { setError(e.message||String(e)); }
      finally { setBusy(false); }
    };
    return <div className="grid"><p>Apply these settings to {label}.</p>
      <textarea aria-label="Settings as JSON" rows={12} spellCheck={false} value={text} onChange={e=>setText(e.target.value)}/>
      {error&&<p role="alert">{error}</p>}
      <div className="flex"><Btn p disabled={busy} onClick={event=>executeAction('projects.controls.activate',{handler:()=>submit(false)},event)}>Apply</Btn>
        <Btn disabled={busy} onClick={event=>executeAction('projects.controls.activate',{handler:()=>submit(true)},event)}>Copy</Btn>
        <Btn ghost onClick={event=>executeAction('projects.controls.activate',{handler:close},event)}>Back to rows</Btn></div>
    </div>;
  }
  function KeyboardSettings({changedOnly=false}) {
    const s=useData(),u=useApp(),[capturing,setCapturing]=React.useState('');
    const [load,setLoad]=React.useState({status:'waiting'}),failed=React.useRef(null);
    const destination=s.settingsDestination;
    React.useEffect(()=>{if(s.settingsScopePending||!destination)setCapturing('');},[s.settingsScopePending,destination]);
    const rows=(s.keyboardCommands||[]).filter(row=>!changedOnly||row.changed);
    React.useEffect(()=>{setLoad(s.keyboardPending?{status:'waiting'}:s.keyboardError?{status:'error',message:s.keyboardError}:{status:rows.length?'loaded':'empty'});},[s.keyboardPending,s.keyboardError,s.keyboardCommands,changedOnly]);
    const run=action=>{failed.current=action;setLoad({status:'waiting'});return u.act(async()=>{try{const result=await action();setLoad({status:(result.keyboardCommands||[]).some(row=>!changedOnly||row.changed)?'loaded':'empty'});return result;}catch(error){setLoad({status:'error',message:error.message||String(error)});throw error;}});};
    React.useEffect(()=>{
      if(!capturing)return undefined;
      const capture=event=>{
        event.preventDefault();event.stopImmediatePropagation();
        if(event.key==='Escape'){setCapturing('');return;}
        const chord=window.UI.shortcutFromEvent(event);
        if(!chord)return;
        setCapturing('');run(()=>api.setKeybinding(capturing,chord,destination));
      };
      document.addEventListener('keydown',capture,true);
      return()=>document.removeEventListener('keydown',capture,true);
    },[capturing]);
    const groupOf = row => row.contexts.includes('navigation') ? 'Everywhere' : row.contexts.includes('session') ? 'In a task' : 'Canvas';
    return <div className="sheet-keybindings"><p>Keyboard shortcuts use the selected scope. One shortcut per action, shared by menus and the actual command. Choose a key, then press its replacement. Escape cancels.</p>
      {load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(failed.current||(()=>api.refreshSettingsControls()))},event)}>Retry keyboard shortcuts</Btn></div>}
      {capturing&&<p role="status">Press the new shortcut. Escape cancels.</p>}
      {load.status==='waiting'&&<p role="status">Reading keyboard shortcuts...</p>}{load.status==='empty'&&<p>No keyboard shortcuts to show.</p>}
      {load.status==='loaded'&&['Everywhere','In a task','Canvas'].map(group=>{
        const commands=rows.filter(row=>groupOf(row)===group);
        return commands.length>0 && <section key={group} aria-label={group}><h3>{group}</h3>{commands.map(row=><div className="spread row" key={row.id} data-setting={'Keyboard.'+row.id}><span><b>{row.label}</b></span><div className="flex"><Btn sm disabled={!destination||s.settingsScopePending} aria-label={'Change shortcut for '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setCapturing(row.id)},event)}>{capturing===row.id?'Press keys...':row.value||'Unbound'}</Btn>{row.changed&&<Btn sm ghost disabled={!destination||s.settingsScopePending} aria-label={'Reset shortcut for '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(()=>api.setKeybinding(row.id,null,destination))},event)}>Reset</Btn>}<Btn sm ghost disabled={!destination||s.settingsScopePending||!row.value} aria-label={'Unbind '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(()=>api.setKeybinding(row.id,'',destination))},event)}>Clear</Btn></div></div>)}</section>;
      })}
      <Btn sm ghost disabled={!destination||s.settingsScopePending} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.confirm('Reset all keyboard shortcuts?',()=>run(()=>api.resetKeybindings(destination)))},event)}>Reset all shortcuts</Btn>
      <section aria-label="Fixed"><h3>Fixed</h3><p><kbd>Escape</kbd> Back out</p><p><kbd>Space + drag</kbd> Pan the canvas</p><p><kbd>Wheel</kbd> Zoom at the pointer</p></section>
    </div>;
  }
  function DependenciesLink() {
    const u=useApp();
    const [navigation,setNavigation]=React.useState({status:'waiting'}),[attempt,retry]=React.useReducer(value=>value+1,0);
    React.useEffect(()=>{
      if(typeof u.go!=='function'){setNavigation({status:'empty'});return;}
      let active=true;
      setNavigation({status:'waiting'});
      Promise.resolve().then(()=>u.go('dependencies')).then(
        ()=>{if(active)setNavigation({status:'loaded'});},
        error=>{if(active)setNavigation({status:'error',message:error.message||String(error)});}
      );
      return ()=>{active=false;};
    },[attempt]);
    return <>{navigation.status==='waiting'&&<p role="status">Opening Dependencies…</p>}
      {navigation.status==='empty'&&<p>Dependencies navigation is unavailable.</p>}
      {navigation.status==='loaded'&&<span className="visually-hidden" role="status">Opened Dependencies.</span>}
      {navigation.status==='error'&&<div role="alert">{navigation.message} <Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:retry},event)}>Retry opening Dependencies</Btn></div>}</>;
  }
  function Settings(props) {
    const [page,query]=(props.page||'Account').split('?');
    const find=query?new URLSearchParams(query).get('find'):'';
    return page==='Dependencies'?<DependenciesLink/>:<SettingsSheet {...props} page={page} initialReveal={find}/>;
  }
  function SettingsSheet({page='Account',full=false,initialReveal=''}) {
    const requestedPage=page,former=formerAreas[page],focusSection=pcAnchors[page]||former?.[1]||'';
    page=former?former[0]:page;
    const s=useData(),u=useApp();
    const group=sections.find(section=>section.name===page || section.pages.includes(page)) || sections[0];
    const deep=page==='Advanced' || (page!=='Hooks' && page!=='Updates & About' && group.pages.includes(page) && page!==group.pages[0]);
    const [advancedOpen,setAdvancedOpen]=React.useState(deep||former?.[2]==='advanced');
    React.useEffect(()=>{if(former?.[2]==='advanced')setAdvancedOpen(true);},[focusSection]);
    const [query,setQuery]=React.useState('');
    const searchInput=React.useRef(null);
    React.useEffect(()=>{
      const focusSearch=event=>{
        if(event.key!=='/' || event.ctrlKey || event.metaKey || event.altKey || event.target.closest?.('input,select,textarea,[contenteditable="true"]'))return;
        event.preventDefault();
        searchInput.current?.focus();
      };
      document.addEventListener('keydown',focusSearch);
      return ()=>document.removeEventListener('keydown',focusSearch);
    },[]);
    const [changedOnly,setChangedOnly]=React.useState(false);
    const [router,setRouter]=React.useState(null),[attempt,setAttempt]=React.useState(0),[sources,setSources]=React.useState({});
    const [sessionChoices,setSessionChoices]=React.useState([]);
    const retrySource=React.useRef({});
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(SHEET_ACTIONS,{Refresh:name=>name?retrySource.current[name]?.():setAttempt(value=>value+1)});
    React.useEffect(()=>{
      let current=true;
      setSources({});
      const reads={sessions:()=>api.listSessionModel(),models:()=>api.refreshRouter(),programs:()=>api.readHostAvailability(),agents:()=>api.listAgentsWorking(),
        controls:()=>api.refreshSettingsControls(),folder:()=>api.readSessionsFolder()};
      const read=async name=>{
        try {
          const value=await reads[name]();
          if(!current)return;
          if(name==='models')setRouter(value);
          if(name==='sessions')setSessionChoices((value?.groups||[]).flatMap(group=>group.sessions).filter(row=>row.path && row.state!=='archived' && !window.UI.isHomeRegistration?.({id:row.task})));
          setSources(previous=>({...previous,[name]:{ready:true}}));
        } catch(error) {
          if(current)setSources(previous=>({...previous,[name]:{error:error.message||String(error)}}));
        }
      };
      for(const name of Object.keys(reads)){
        retrySource.current[name]=()=>{
          setSources(previous=>({...previous,[name]:undefined}));
          return read(name);
        };
        read(name);
      }
      return ()=>{current=false;retrySource.current={};};
    },[attempt]);
    // The page's overall read state. It never hides the settings: each source still fills only its own rows.
    const sourceNames=['models','programs','agents','controls','folder'];
    const load=sourceNames.some(name=>sources[name]?.error)?{status:'error'}
      :sourceNames.every(name=>sources[name]?.ready)?{status:(s.settings||[]).length?'loaded':'empty'}:{status:'waiting'};
    const sourceNotice=(name,waiting)=>{
      const result=sources[name];
      if(result?.error)return <span role="alert">{result.error} <Btn sm onClick={()=>runAction('settings.sheet.Refresh',name)}>Retry {name==='controls'?'settings':name}</Btn></span>;
      return result?.ready?null:<span role="status">{waiting}</span>;
    };
    const go=route=>u.go(route),act=fn=>u.act(fn);
    const [reveal,setReveal]=React.useState(initialReveal),[revealedCard,setRevealedCard]=React.useState(null);
    const searchTarget=designSearchRows.find(item=>item.id===reveal);
    // The account check ends: after the account request budget (runtime parameter account_http_ms) the row reads Local session.
    const [checkExpired,setCheckExpired]=React.useState(false);
    React.useEffect(()=>{setCheckExpired(false);if(!s.profile.checking)return undefined;const budget=s.runtimeParameters?.account_http_ms,timer=setTimeout(()=>setCheckExpired(true),Number.isSafeInteger(budget)&&budget>0?budget:0);return()=>clearTimeout(timer);},[s.profile.checking,s.runtimeParameters?.account_http_ms]);
    const area=sheetAreas.find(area=>area.pages.includes(page)||area.label===page) || sheetAreas[0];
    const currentCategory=area.pages.includes(page)?page:area.target;
    const isChanged=row=>row.default!==undefined&&JSON.stringify(row.value)!==JSON.stringify(row.default);
    const changedKeys=(s.keyboardCommands||[]).filter(row=>row.changed);
    const changedForArea=item=>s.settings.filter(row=>item.pages.includes(row.page)&&isChanged(row)).length+(item.pages.includes('Appearance')?changedKeys.length:0);
    const needle=query.trim().toLowerCase().replace(/^(where (is|are|do i (change|set|find))|how do i (change|set)|find|change|set)\s+/, '').replace(/^the\s+/, '');
    const words=needle.split(/\s+/).filter(word=>word&&!['mode','setting','settings','option','my','the','a'].includes(word));
    const settingValue=value=>value==null?'':typeof value==='object'?JSON.stringify(value):String(value);
    const settingText=row=>`${row.label||''} ${row.group||''} ${row.page||''} ${row.description||''} ${(row.options||[]).join(' ')} ${settingValue(row.value)}`.toLowerCase();
    const matched=React.useMemo(()=>{
      if(!needle)return [];
      const represented=new Set();
      const design=designSearchRows.map(spec=>{
        const owner=spec.field&&s.settings.find(row=>sheetAreas.find(area=>area.label===spec.area).pages.includes(row.page) &&
          (row.label===spec.label || spec.area==='This PC'&&row.label===pcOwnerLabels[spec.field]) &&
          (spec.area!=='Projects'||row.group===spec.group));
        if(owner)represented.add(owner.id);
        return {...spec,value:owner?.value,terms:[spec.area,owner?.label,owner?.description].filter(Boolean).join(' ')};
      });
      const keyboard=(s.keyboardCommands||[]).map(row=>({id:'Keyboard.'+row.id,label:row.label+' shortcut',group:'Keyboard',page:'Appearance',value:row.value}));
      const score=row=>words.filter(word=>row.label.toLowerCase().includes(word)).length;
      return [...s.settings.filter(row=>!represented.has(row.id)),...keyboard,...design]
        .filter(row=>words.every(word=>(settingText(row)+' '+(row.terms||'').toLowerCase()).includes(word)))
        .sort((a,b)=>score(b)-score(a));
    },[needle,s.settings,s.keyboardCommands]);
    const revealSetting=row=>{
      setChangedOnly(false);
      setQuery('');
      if(row.page!==page){
        go('settings/'+row.page+'?find='+encodeURIComponent(row.id));
        return;
      }
      setReveal(row.id);
      if(row.advanced)setAdvancedOpen(true);
    };
    React.useEffect(()=>{
      if(!reveal||query)return;
      if((searchTarget?.advanced||s.settings.some(row=>row.id===reveal&&row.advanced))&&!advancedOpen){
        setAdvancedOpen(true);return;
      }
      const inSheet=content.current;
      const card=searchTarget&&[...inSheet.querySelectorAll('[data-design-section]')].find(el=>el.dataset.designSection===searchTarget.group);
      const node=(searchTarget?.field&&card?.querySelector('[data-row="'+window.CSS.escape(searchTarget.field)+'"]')) ||
        (searchTarget?card:inSheet.querySelector('[data-setting="'+window.CSS.escape(reveal)+'"]'));
      if(!node)return;
      for(let ancestor=node.closest('details');ancestor;ancestor=ancestor.parentElement?.closest('details'))ancestor.open=true;
      node.tabIndex=-1;
      node.focus({preventScroll:true});
      if(searchTarget)setRevealedCard(searchTarget.card);
      scrollToSection(node,true);
      setReveal('');
    },[reveal,advancedOpen,page,query,s.settings,searchTarget]);
    const status=(s.agents||[]).map(agent=>`${agent.session_count ?? agent.sessions?.length ?? 0} ${agent.name} sessions ${agent.presence||'unknown'}`).join(' · ');
    const reportedAgents=(s.agents||[]).filter(agent=>agent.kind!=='observation');
    const agentNames=[...new Set(['Claude Code','Codex','OpenCode','Gemini CLI','BABOOM','Antigravity',...reportedAgents.map(row=>row.name)])];
    const preference=(label,match=undefined)=>{const row=s.settings.find(match||(row=>row.label===label));return !row||changedOnly&&JSON.stringify(row.value)===JSON.stringify(row.default)?null:<SheetPreference key={label} label={label} match={match} raw={advancedOpen} />;};
    const ownerPage={Models:'BABOOM',Permissions:'Hooks',Providers:'BABOOM'}[requestedPage]||requestedPage;
    const shownLabels=new Set(currentCategory==='Account'?['Review before sharing','Ask before meeting transcription']:currentCategory==='BABOOM'?['Finish and report','Only notify when action is needed','Conversation retention']:[]);
    // A page shows its own rows; a row whose page is in no area stays on that area's first page so nothing is lost.
    const onThisPage=row=>row.page===currentCategory||(currentCategory===area.target&&!sheetAreas.some(item=>item.pages.includes(row.page)));
    const isPcDesign=!changedOnly&&area.label==='This PC';
    const designArea=currentCategory===area.target && area.label!=='This PC' && !changedOnly;
    const placedOnCard=row=>designArea && areaCardSpecs.some(card=>card.area===area.label && (area.label!=='Projects'||card.title===row.group) && card.rows.some(spec=>spec[1]===row.label));
    const visibleRows=s.settings.filter(row=>!placedOnCard(row) && !(isPcDesign && pcCards.some(card=>card.rows.some(spec=>pcOwner(s.settings,spec)===row))) && (changedOnly?isChanged(row):onThisPage(row)&&!shownLabels.has(row.label))&&(!row.advanced||advancedOpen||changedOnly));
    const extraRows=former && requestedPage!=='Social' && area.label!=='This PC' && !changedOnly
      ? s.settings.filter(row=>row.page===ownerPage && !placedOnCard(row)
          && !['Finish and report','Stale claim after idle minutes','Archive after idle days'].includes(row.label)
          && (!row.advanced||advancedOpen)) : [];
    const focused=former && area.label!=='This PC' ? {title:focusSection,content:<>
      {requestedPage==='Providers'&&<section><h3>Providers and request profiling</h3><Providers/><RouterSettings/></section>}
      {requestedPage==='Automations'&&<window.UI.Automations embedded/>}
      {requestedPage==='Library & Mods'&&<window.UI.HostSkills/>}
      {requestedPage==='Workshop'&&<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('workshop')},event)}>Open Workshop</Btn>}
      {extraRows.map(row=><SettingControl key={row.id} row={row} raw={advancedOpen}/>)}
    </>} : null;
    const lookFamilies={
      'Theme and colour':['Theme','High contrast','Accent colour','Node header colour'],
      'Size and density':['Text scale','Reduce motion','Row spacing'],
      'Panels':['Inspector width'],
      'Canvas':['Canvas grid','Default zoom','Node radius','Zoom percentage'],
      'Keyboard':[]
    };
    const rowFamily=row=>row.page==='Appearance' ? Object.entries(lookFamilies).find(([,labels])=>labels.includes(row.label))?.[0]||row.group||'Canvas' : row.group||'Preferences';
    const groupTitle=row=>(changedOnly?row.page+' \u203a ':'')+rowFamily(row);
    const additional={};
    if(isPcDesign)for(const row of visibleRows){
      const title=groupTitle(row);
      if(pcCards.some(card=>card.title===title))(additional[title]||=[]).push(row);
    }
    const rowGroups=[...new Set(visibleRows.map(groupTitle))].filter(title=>!additional[title]);
    const [outline,setOutline]=React.useState([]);
    const content=React.useRef(null);
    React.useEffect(()=>{
      const cards=[...(content.current?.querySelectorAll('.sheet-columns > section, .sheet-owner-cards > .sheet-owner-card')||[])];
      setOutline(cards.map((node,index)=>{node.id='settings-section-'+index;return {id:node.id,label:node.querySelector('h2,h3')?.textContent||'Preferences'};}));
    },[page,advancedOpen,changedOnly,query,sources,s.settings]);
    const registerWorkspace = (s.workspaces || []).find(row=>row.id===s.activeWorkspace && !row.builtIn && row.available!==false);
    function scrollToSection(node,center=false){
      const pane=content.current;
      if(!node||!pane?.contains(node))return;
      const offset=center?(pane.clientHeight-node.clientHeight)/2:0;
      pane.scrollTop+=node.getBoundingClientRect().top-pane.getBoundingClientRect().top-Math.max(0,offset);
    }
    const jump=id=>scrollToSection(document.getElementById(id));
    // Opens the existing New project form in Project folders (the workspace owner's own control).
    const openNewProject=()=>{const folders=content.current?.querySelector('details:has(form[aria-label="New project"]), [data-design-section="CDE folders"] details');if(folders)folders.open=true;const form=content.current?.querySelector('form[aria-label="New project"]');if(form){scrollToSection(form);return;}const button=[...(content.current?.querySelectorAll('button')||[])].find(node=>node.textContent.trim()==='New project');if(button){button.click();scrollToSection(button);}};
    React.useEffect(()=>{
      if(!focusSection||initialReveal||reveal)return;
      const heading=[...(content.current?.querySelectorAll('h2,h3')||[])].find(node=>node.textContent.trim()===focusSection);
      scrollToSection(heading);
    },[focusSection,page,sources,advancedOpen]);

    return <SearchCard.Provider value={searchTarget?.card||revealedCard}><div data-screen={'settings/'+currentCategory} data-settings-full={full?'1':'0'} className="settings-sheet-stage settings-reference"><section className="settings-sheet" aria-label="Settings"><header><h1>Settings</h1>
      <label className="sheet-settings-scope" title="Which project these settings are for"><window.AHIcon name="folder" size={14}/><select aria-label="Which project" disabled={!s.settingsDestination || s.settingsScopePending}
        value={s.settingsScope==='Workspace' ? s.settingsDestination?.workspace || '' : ''} onChange={event=>{
          const project=event.target.value, destination=s.settingsDestination;
          return act(async()=>{
            await api.setSettingsScope(project?'Workspace':'User',destination,project || undefined);
            if(project){setQuery('');setChangedOnly(false);await go('settings/Projects');}
          });
        }}><option value="">{window.UI.productLabel("All projects",s.settings)}</option>{(s.workspaces||[]).filter(row=>!row.builtIn && row.available!==false).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label className="sheet-settings-scope" title="Settings for one session"><window.AHIcon name="canvas" size={14}/><select aria-label="Which session" value="" disabled={!sessionChoices.length || s.settingsScopePending} onChange={event=>{
        const path=event.target.value;
        return act(async()=>{
          const opened=await u.openSavedSession(path);
          if(opened && !opened.cancelled && api.sessionPathKey(api.getSessionPath())===api.sessionPathKey(path))
            u.setHomeInspector({path:api.getSessionPath(),tab:'Session'});
        });
      }}><option value="">Every session</option>{sessionChoices.map(row=><option key={row.path} value={row.path}>{row.title}</option>)}</select></label>
      {sources.sessions?.error && sourceNotice('sessions','Reading sessions…')}<label className="sheet-find"><window.AHIcon name="search" size={15}/><input ref={searchInput} className="sheet-search" aria-label="Search settings" placeholder={window.UI.productLabel("Search, or ask where something is",s.settings)} value={query} onChange={event=>setQuery(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&matched[0]){event.preventDefault();revealSetting(matched[0]);}if(event.key==='Escape')setQuery('');}} /><kbd>/</kbd></label><div className="sheet-view-filter" aria-label="Settings view"><button type="button" className="sheet-action secondary" aria-pressed={!changedOnly} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{setChangedOnly(false);setQuery('');}},event)}>All</button><button type="button" className="sheet-action secondary" aria-pressed={changedOnly} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{setChangedOnly(true);setQuery('');}},event)}>Changed {s.settings.filter(isChanged).length+changedKeys.length || ''}</button></div><button type="button" className="sheet-action" onClick={event=>executeAction('projects.controls.activate',{handler:()=>go(u.settingsOrigin||'home')},event)}>Back to task</button><details className="sheet-tools-menu"><summary aria-label="Copy, paste or reset all settings" title="Copy, paste or reset all settings"><window.AHIcon name="more" size={16}/></summary><div>{typeof api.setSettingsScope==='function'&&<label className="sheet-settings-scope">Scope<select disabled={!s.settingsDestination||s.settingsScopePending} aria-busy={Boolean(s.settingsScopePending)} aria-label="Settings scope" value={s.settingsScope||'User'} onChange={event=>{const value=event.target.value,destination=s.settingsDestination;return act(()=>api.setSettingsScope(value,destination));}}><option value="User">Everywhere</option><option value="Workspace" disabled={!s.settingsScopes?.Workspace}>Current workspace</option><option value="Session" disabled={!s.settingsScopes?.Session}>Current session</option></select></label>}{!needle&&area.pages.length>1&&!changedOnly&&<nav className="sheet-subpages" aria-label={area.label+' pages'}>{area.pages.map(target=><Btn sm ghost key={target} aria-current={currentCategory===target?'page':undefined} onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/'+target)},event)}>{pageLabels[target]||target}</Btn>)}</nav>}<button type="button" className="sheet-action secondary" aria-expanded={advancedOpen} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAdvancedOpen(value=>!value)},event)}>{advancedOpen?'Hide advanced':'Show advanced'}</button><PreferencesTransfer /></div></details></header><div className="sheet-layout"><nav className="sheet-tabs" aria-label="Settings categories">{sheetAreas.map(item=><button type="button" className="settings-section" aria-label={window.UI.productLabel(item.label,s.settings)} aria-current={!needle&&!changedOnly&&area===item?'page':undefined} key={item.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{setQuery('');setChangedOnly(false);go('settings/'+item.target);}},event)}><window.AHIcon name={item.icon} size={16}/><span><b>{window.UI.productLabel(item.label,s.settings)}</b><small>{item.description}</small>{formerPageLabels[item.label]&&<em className="sheet-nav-former">Was: {formerPageLabels[item.label]}</em>}</span>{changedForArea(item)>0&&<span className="sheet-change-count">{changedForArea(item)}</span>}</button>)}</nav><div className="sheet-content" ref={content}>{s.settingsScopePending&&<p role="status" aria-live="polite">Changing settings scope…</p>}{s.settingsScopeNotice&&<div role="alert">{s.settingsScopeNotice}<Btn sm ghost disabled={s.settingsScopePending} onClick={event=>executeAction('projects.controls.activate',{handler:()=>act(()=>api.refreshPreferences())},event)}>Refresh settings scope</Btn></div>}
      <window.UI.RegisteredActionStatus state={actionState} retry={retryAction}/>
      {load.status==='waiting'&&<span className="visually-hidden" role="status">Reading settings…</span>}
      {load.status==='error'&&<div role="alert">Some settings could not be read; the rest are shown. <Btn sm onClick={()=>runAction('settings.sheet.Refresh','')}>Retry all</Btn></div>}
      {load.status==='empty'&&<span className="visually-hidden" role="status">No settings reported.</span>}
      {load.status==='loaded'&&<span className="visually-hidden" role="status">Settings loaded.</span>}
      {needle&&<><p role="status">{matched.length ? 'Found '+matched.length+'. Enter goes to the first.' :
        /diag|health|wiring|router|status|log/.test(needle) ? 'No matching setting. Search for Diagnostics to find the log controls.' :
        'Nothing matches. Try a word for what it does: dark, panel, model, phone, approve.'}</p>
        <div className="sheet-results" role="listbox" aria-label="Settings results">{matched.map(row=><button type="button" role="option" className="sheet-result" key={row.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>revealSetting(row)},event)}><b>{row.label}</b><span>{settingValue(row.value)}</span><small>{row.area || sheetAreas.find(item=>item.pages.includes(row.page))?.label || row.page} › {row.group||row.page}{row.advanced?' · Advanced':''}</small></button>)}</div></>}
      {!needle&&<div className="sheet-page-heading"><span className="sheet-area-icon"><window.AHIcon name={area.icon} size={20}/></span><div><h2>{changedOnly?'Changed settings':currentCategory==='Projects' && s.settingsScope==='Workspace' && registerWorkspace && registerWorkspace.id===s.settingsDestination?.workspace ? 'Projects · '+registerWorkspace.name : window.UI.productLabel(currentCategory===area.target?area.label:currentCategory,s.settings)}</h2><p>{currentCategory==='Projects' ? (s.settingsScope==='Workspace' && registerWorkspace ? 'What differs for '+registerWorkspace.name+'. A value you change here is kept for this project only; the rest follow the office defaults.' : 'The office defaults every new project starts from. Pick a project at the top to change what differs for it.') : area.description}</p></div><div className="flex">{area.label==='Account'&&!changedOnly&&<a className="sheet-action secondary" href="https://archhub.io/account/" target="_blank" rel="noopener noreferrer">Open on archhub.io</a>}{s.settings.some(row=>row.page===currentCategory)&&api.supportsAction?.('exposeSettingsPage')!==false?<button type="button" className="sheet-action secondary" onClick={event=>executeAction('projects.controls.activate',{handler:()=>act(()=>api.exposeSettingsPage(currentCategory))},event)}>Put on Canvas</button>:<window.UI.Soon label="Put on Canvas"><span className="sheet-action secondary" aria-disabled="true">Put on Canvas</span></window.UI.Soon>}</div></div>}

      <div className="sheet-design-body"><div className="sheet-design-cards"><div className="sheet-columns" hidden={!!needle || changedOnly}>
      {currentCategory==='Account'&&<AccountDesignCards focused={focused} checking={s.profile.checking&&!checkExpired}/>}
      {currentCategory==='Connections'&&<ConnectionDesignCards focused={focused} refresh={()=>setAttempt(value=>value+1)} programNotice={sourceNotice('programs','Reading programs…')}/>}
      {currentCategory==='Agents'&&<AreaDesignCards area="Agents" focused={focused} bodies={{agents:<><div className="sheet-agents" role="list"><p>One row per agent app. State and model are live; Connect opens Dependencies when an app is not running.</p>{agentNames.map(name=>{
          const agent=reportedAgents.find(row=>row.name===name);
          const state=agent?.status_text||agent?.presence||'Status not reported';
          return <div key={name} className="sheet-agent-tile" role="listitem"><span className="sheet-agent-mark" aria-hidden="true">{name.slice(0,1)}</span><div><b>{name}</b><small>{agent?.model||'Model not reported'}</small><small>{state}</small></div>{!agent||['stopped','missing'].includes(agent.presence)?<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('dependencies')},event)}>Connect</Btn>:<span>{state}</span>}</div>;
        })}{sourceNotice('agents','Reading agents…')}{sources.agents?.ready&&!(s.agents||[]).some(agent=>agent.kind!=='observation')&&<p>No agents reported.</p>}</div><p className="sheet-session-summary" role="status">{s.agentSummary||status||'No agent sessions reported.'}</p><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>act(api.listAgentsWorking)},event)}>{s.agentSummary==='Agent status is incomplete.'?'Check again':'Refresh'}</Btn></>,tools:<div className="sheet-library-summary"><span>{s.catalogue?.length!=null?s.catalogue.length+' nodes in the Library':'Library catalogue unavailable'}</span><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('library')},event)}>Manage</Btn><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('Install mod')},event)}>Import</Btn></div>}} live={{
        model:router?<select aria-label="Default model" value={router.default_model} onChange={event=>act(()=>api.setRouterSettings({default_model:event.target.value})).then(result=>{if(result)setRouter(result);})}>{[...new Set([router.default_model,...router.models,...router.fallback_models])].map(model=><option key={model}>{model}</option>)}</select>:sourceNotice('models','Reading models…'),
        preferFree:router?<D.Toggle label="Prefer free models" checked={router.free_first} onCheckedChange={value=>act(()=>api.setRouterSettings({free_first:value})).then(result=>{if(result)setRouter(result);})}/>:sourceNotice('models','Reading models…'),
        fallback:router?(router.fallback_models.join(' → ')||'None'):sourceNotice('models','Reading models…'),
        runMode:focusSection==='What agents may do'?<Permissions/>:<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Hooks')},event)}>Run mode</Btn>,
        toolRules:focusSection==='What agents may do'?<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>content.current?.querySelector('[aria-label="Tool name or pattern"]')?.focus()},event)}>Edit tool rules</Btn>:<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Hooks')},event)}>Tool rules</Btn>,
        finishReport:preference('Finish and report')||undefined,wsRelease:preference('Stale claim after idle minutes')||undefined,wsArchive:preference('Archive after idle days')||undefined
      }} extras={{perm:focusSection==='What agents may do'?null:<Permissions rulesOnly/>,meet:<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('meetings')},event)}>Open Meetings</Btn>,auto:requestedPage==='Automations'?null:<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Automations')},event)}>Open Automations</Btn>}}/>}

      {isPcDesign&&<PcSettingsCards additional={additional} page={currentCategory} advanced={advancedOpen} setAdvanced={setAdvancedOpen}/>}
      {currentCategory==='Projects'&&<AreaDesignCards area="Projects"
        bodies={{register:<ProjectRegister key={registerWorkspace?.id||'office'} workspace={registerWorkspace}/>}}
        live={{projTpl:s.settings.some(row=>row.page==='Projects'&&row.label==='New project folders')?undefined:<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:openNewProject},event)}>Open New project</Btn>}}
        extras={{cde:<details><summary>Project folders</summary><WorkspaceRows /></details>}}/>}
      </div>{!needle&&<div className="sheet-owner-cards">{sources.controls?.error&&sourceNotice('controls','Reading controls…')}{sources.controls?.ready&&<span className="visually-hidden">Settings loaded.</span>}{rowGroups.map(title=><section className="sheet-owner-card" key={title}><h3>{title}</h3>{currentCategory==='Appearance'&&title!=='Keyboard'&&!visibleRows.some(row=>groupTitle(row)===title)&&<p>{sources.controls?.ready?'No settings reported for this group.':!sources.controls?.error&&'Reading settings…'}</p>}{visibleRows.filter(row=>groupTitle(row)===title).map(row=><SettingControl key={row.id} row={row} raw={advancedOpen} />)}</section>)}{changedOnly&&changedKeys.length>0&&<section className="sheet-owner-card"><h3>Look - Keyboard</h3><KeyboardSettings changedOnly /></section>}{changedOnly&&!visibleRows.length&&!changedKeys.length&&<p>No settings differ from their defaults.</p>}</div>}</div>{!needle&&!changedOnly&&(outline.length>0||currentCategory==='Appearance')&&<aside className="sheet-design-side">{currentCategory==='Appearance'&&<section className="sheet-live-preview" aria-label="Live preview"><h3>Live preview</h3>{s.graph?.nodes?.length && window.UI.Canvas ? <>
        <div className="sheet-preview-stage" inert>
          <window.UI.Ctx.Provider value={{...u, libraryOpen:false, selectedNodeId:null}}>
            <window.UI.Canvas key={s.graph.scopeKey||s.graph.id} preview={s.graph} embedded externalInspector docked />
          </window.UI.Ctx.Provider>
        </div>
        <p>Changes apply to this workflow preview immediately.</p>
      </> : <div className="sheet-preview-sample"><div className="sheet-preview-caption">Sample workflow</div><div className="sheet-preview-nodes" role="img" aria-label="Example workflow with Read details index wired to Split per file">
          <div className="sheet-preview-node"><b>Read details index</b><span>rows</span><span>count</span></div>
          <svg viewBox="0 0 36 30" aria-hidden="true"><path d="M0 6C18 6 18 24 36 24" fill="none" stroke="currentColor"/></svg>
          <div className="sheet-preview-node"><b>Split per file</b><span>rows</span></div></div>
          <p>Open a workflow to preview its real nodes here.</p></div>}</section>}<nav className="sheet-outline" aria-label="On this page"><b>On this page</b>{outline.map(row=><button type="button" key={row.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>jump(row.id)},event)}>{row.label}</button>)}</nav></aside>}</div></div></div></section></div></SearchCard.Provider>;
  }
  window.UI.Settings = Settings;
  window.UI.requestGroups = requestGroups;
  window.UI.PasteSettings = PasteSettings;
  window.UI.KeyboardSettings = KeyboardSettings;
  window.UI.Account = Account;
  window.UI.Connections = Connections;
  window.UI.WorkspaceRows = WorkspaceRows;
  window.UI.Storage = Storage;
  window.UI.settingsDoors = doors;
})();
