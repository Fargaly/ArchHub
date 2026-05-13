using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitMCP
{
    /// <summary>
    /// External application that boots an HTTP server on Revit startup.
    /// All API work is marshalled to the Revit UI thread via ExternalEvent.
    ///
    /// MULTI-SESSION (v0.27.5+):
    /// Each Revit instance binds its OWN free port from the range
    /// [48884..48899]. The instance's pid + port + Revit version + active
    /// document title is published to:
    ///
    ///     %LOCALAPPDATA%\ArchHub\sessions\revit-{pid}.json
    ///
    /// ArchHub's revit_broker.py scans this directory and routes calls
    /// to one or many sessions (most-recent by default; pick via
    /// ?session=<pid> query param). Closing one Revit instance only
    /// removes that instance's session file — the broker stays up,
    /// other Revit instances remain reachable.
    ///
    /// Heartbeat: the session file is rewritten every 10 s with the
    /// current heartbeat tick so the broker can prune crashed sessions.
    /// </summary>
    [Regeneration(RegenerationOption.Manual)]
    public class RevitMCPApp : IExternalApplication
    {
        // Port range — first free wins. Old single-instance port was 48884.
        private const int PortFirst = 48884;
        private const int PortLast  = 48899;

        // Heartbeat cadence (rewrites the session file).
        private const int HeartbeatSeconds = 10;

        private HttpListener _listener;
        private CancellationTokenSource _cts;
        private RevitEventHandler _handler;
        private ExternalEvent _externalEvent;

        private int _boundPort;
        private string _sessionFile;
        private string _revitVersion = "";
        private UIControlledApplication _app;
        private System.Threading.Timer _heartbeatTimer;

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                _app = application;
                _revitVersion = SafeRevitVersion(application);

                // Make Roslyn (Microsoft.CodeAnalysis*) + System.Text.Json
                // + their dependencies resolvable when /exec scripts the
                // host. Revit's default probing doesn't include this
                // add-in's own folder — without the handler the CLR
                // throws "FileNotFoundException: Microsoft.CodeAnalysis
                // 4.11.0.0 not found" on the first /exec call.
                InstallAssemblyResolver();

                _handler = new RevitEventHandler();
                _externalEvent = ExternalEvent.Create(_handler);
                _handler.AttachEvent(_externalEvent);

                // Track the active document title so the broker can
                // surface it in the host row tooltip without us holding
                // a UI-thread call inside the heartbeat timer.
                try
                {
                    application.ControlledApplication.DocumentOpened += (s, e) =>
                    {
                        try { _lastDocTitle = e.Document?.Title ?? ""; } catch { }
                    };
                    application.ControlledApplication.DocumentClosing += (s, e) =>
                    {
                        try
                        {
                            if (e.Document?.Title == _lastDocTitle) _lastDocTitle = "";
                        }
                        catch { }
                    };
                }
                catch (Exception ex)
                {
                    Log("Doc event subscribe failed: " + ex.Message);
                }

                _cts = new CancellationTokenSource();
                Task.Run(() => RunListenerAsync(_cts.Token));

                Log("RevitMCP starting; will pick a port in [" + PortFirst + ".." + PortLast + "]");
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                Log("RevitMCP startup failed: " + ex);
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            try { _cts?.Cancel(); } catch { }
            try { _listener?.Stop(); } catch { }
            try { _externalEvent?.Dispose(); } catch { }
            try { _heartbeatTimer?.Dispose(); } catch { }
            try
            {
                if (!string.IsNullOrEmpty(_sessionFile) && File.Exists(_sessionFile))
                    File.Delete(_sessionFile);
            }
            catch { }
            Log("RevitMCP shutdown — released port " + _boundPort);
            return Result.Succeeded;
        }

        // ------------------------------------------------------------------
        // Listener bootstrap — binds to the first free port in our range
        // so multiple Revit instances coexist.

        private async Task RunListenerAsync(CancellationToken ct)
        {
            HttpListener bound = null;
            int port = 0;
            for (int p = PortFirst; p <= PortLast; p++)
            {
                if (ct.IsCancellationRequested) return;
                var prefix = "http://localhost:" + p + "/";
                var listener = new HttpListener();
                listener.Prefixes.Add(prefix);
                try
                {
                    listener.Start();
                    bound = listener;
                    port = p;
                    Log("RevitMCP bound to " + prefix);
                    break;
                }
                catch (HttpListenerException ex)
                {
                    Log("Port " + p + " unavailable (" + ex.ErrorCode + "); trying next.");
                }
                catch (Exception ex)
                {
                    Log("Port " + p + " failed: " + ex.Message + "; trying next.");
                }
            }

            if (bound == null)
            {
                Log("RevitMCP could not bind any port in [" + PortFirst + ".." + PortLast + "]");
                return;
            }

            _listener = bound;
            _boundPort = port;

            // Publish session registry + start heartbeat.
            try
            {
                _sessionFile = WriteSessionFile(_boundPort, _revitVersion);
                _heartbeatTimer = new System.Threading.Timer(_ => HeartbeatTick(), null,
                    TimeSpan.FromSeconds(HeartbeatSeconds), TimeSpan.FromSeconds(HeartbeatSeconds));
            }
            catch (Exception ex)
            {
                Log("Session registry write failed: " + ex);
            }

            while (!ct.IsCancellationRequested)
            {
                HttpListenerContext context;
                try
                {
                    context = await _listener.GetContextAsync().ConfigureAwait(false);
                }
                catch (Exception)
                {
                    break;
                }
                _ = ProcessRequestAsync(context); // fire and forget
            }
        }

        // ------------------------------------------------------------------
        // Session registry — atomic write so the broker never reads a
        // half-written file.

        private string WriteSessionFile(int port, string revitVersion)
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ArchHub", "sessions");
            Directory.CreateDirectory(dir);
            int pid = Process.GetCurrentProcess().Id;
            var path = Path.Combine(dir, "revit-" + pid + ".json");
            WriteSessionJson(path, port, revitVersion, pid, isHeartbeat: false);
            return path;
        }

        private void HeartbeatTick()
        {
            if (string.IsNullOrEmpty(_sessionFile)) return;
            try
            {
                int pid = Process.GetCurrentProcess().Id;
                WriteSessionJson(_sessionFile, _boundPort, _revitVersion, pid, isHeartbeat: true);
            }
            catch
            {
                // Heartbeat failures are non-fatal; broker will prune us
                // if we go silent for >30s.
            }
        }

        private void WriteSessionJson(string path, int port, string revitVersion, int pid, bool isHeartbeat)
        {
            string docTitle = "";
            try
            {
                // Best-effort doc title; UI thread access only safe via
                // event, so we just sample from the application directly.
                docTitle = SafeActiveDocTitle();
            }
            catch { }

            var sb = new StringBuilder(256);
            sb.Append('{');
            sb.Append("\"session_id\":\"revit-").Append(pid).Append("\",");
            sb.Append("\"family\":\"revit\",");
            sb.Append("\"pid\":").Append(pid).Append(',');
            sb.Append("\"port\":").Append(port).Append(',');
            sb.Append("\"version\":\"").Append(JsonEscape(revitVersion)).Append("\",");
            sb.Append("\"doc_title\":\"").Append(JsonEscape(docTitle)).Append("\",");
            sb.Append("\"started_at\":\"").Append(DateTime.UtcNow.ToString("o")).Append("\",");
            sb.Append("\"last_heartbeat\":\"").Append(DateTime.UtcNow.ToString("o")).Append("\",");
            sb.Append("\"heartbeat\":").Append(isHeartbeat ? "true" : "false");
            sb.Append('}');

            // Atomic-ish write: temp file + replace.
            var tmp = path + ".tmp";
            File.WriteAllText(tmp, sb.ToString(), new UTF8Encoding(false));
            try
            {
                if (File.Exists(path)) File.Replace(tmp, path, null);
                else File.Move(tmp, path);
            }
            catch
            {
                // Replace can fail if another process has the file open.
                // Fall back to direct overwrite — content is the same shape.
                File.Copy(tmp, path, overwrite: true);
                try { File.Delete(tmp); } catch { }
            }
        }

        // Last document title we saw via DocumentOpened — refreshed by
        // the event handler. ControlledApplication has no synchronous
        // way to enumerate open documents, so we keep our own cache.
        private volatile string _lastDocTitle = "";

        private string SafeActiveDocTitle() => _lastDocTitle ?? "";

        private string SafeRevitVersion(UIControlledApplication app)
        {
            try { return app.ControlledApplication.VersionNumber ?? ""; }
            catch { return ""; }
        }

        // ------------------------------------------------------------------
        //  Assembly resolver — fixes the "/exec broken: Microsoft.CodeAnalysis
        //  4.11.0.0 not found" error.
        //
        //  Revit hosts the add-in inside its own process. When /exec invokes
        //  Roslyn (Microsoft.CodeAnalysis.CSharp.Scripting.CSharpScript), the
        //  CLR probes (1) Revit.exe's directory, (2) the GAC. Neither contains
        //  the Roslyn DLLs we ship alongside RevitMCP.dll. Default behaviour:
        //  FileNotFoundException, /exec dies.
        //
        //  This handler intercepts AssemblyResolve on the current AppDomain
        //  and looks in the add-in's own directory for the requested DLL,
        //  honouring exact version when present and falling back to name-only
        //  match. Idempotent — guarded by _resolverInstalled so multiple
        //  RevitMCP installations (one per Revit version) don't stack.
        // ------------------------------------------------------------------

        private static bool _resolverInstalled;
        private static readonly object _resolverLock = new object();

        private void InstallAssemblyResolver()
        {
            lock (_resolverLock)
            {
                if (_resolverInstalled) return;
                AppDomain.CurrentDomain.AssemblyResolve += AddinDirResolver;
                _resolverInstalled = true;
            }
        }

        private static Assembly AddinDirResolver(object sender, ResolveEventArgs args)
        {
            try
            {
                var requested = new AssemblyName(args.Name);
                // Add-in folder = where THIS assembly was loaded from.
                var addinDir = Path.GetDirectoryName(
                    typeof(RevitMCPApp).Assembly.Location);
                if (string.IsNullOrEmpty(addinDir)) return null;

                // Try exact name first (most common case for Roslyn DLLs).
                var candidate = Path.Combine(addinDir, requested.Name + ".dll");
                if (File.Exists(candidate))
                {
                    try { return Assembly.LoadFrom(candidate); }
                    catch { /* fall through */ }
                }

                // Some assemblies ship as .resources.dll — try that too.
                candidate = Path.Combine(addinDir, requested.Name + ".resources.dll");
                if (File.Exists(candidate))
                {
                    try { return Assembly.LoadFrom(candidate); }
                    catch { /* fall through */ }
                }
            }
            catch (Exception ex)
            {
                // Best-effort — log once per session to the add-in log file
                // so a missing dep can be diagnosed without crashing Revit.
                try
                {
                    var logPath = Path.Combine(Path.GetTempPath(),
                        "RevitMCP.AssemblyResolve.log");
                    File.AppendAllText(logPath,
                        DateTime.UtcNow.ToString("o") + "  " +
                        args.Name + "  ERR: " + ex.Message + "\n");
                }
                catch { }
            }
            return null;
        }

        // ------------------------------------------------------------------

        private async Task ProcessRequestAsync(HttpListenerContext context)
        {
            string responseJson;
            try
            {
                var path = (context.Request.Url.AbsolutePath ?? "/").TrimEnd('/');
                if (string.IsNullOrEmpty(path)) path = "/";
                var method = context.Request.HttpMethod;

                string body = string.Empty;
                if (context.Request.HasEntityBody)
                {
                    using (var reader = new StreamReader(context.Request.InputStream, context.Request.ContentEncoding ?? Encoding.UTF8))
                    {
                        body = await reader.ReadToEndAsync().ConfigureAwait(false);
                    }
                }

                responseJson = await RouteAsync(path, method, body).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                responseJson = JsonError("Unhandled server error: " + ex.Message);
            }

            try
            {
                var bytes = Encoding.UTF8.GetBytes(responseJson ?? "{}");
                context.Response.ContentType = "application/json; charset=utf-8";
                context.Response.ContentLength64 = bytes.Length;
                context.Response.StatusCode = 200;
                await context.Response.OutputStream.WriteAsync(bytes, 0, bytes.Length).ConfigureAwait(false);
                context.Response.OutputStream.Close();
            }
            catch (Exception ex)
            {
                Log("Response write failed: " + ex);
            }
        }

        private async Task<string> RouteAsync(string path, string method, string body)
        {
            switch (path)
            {
                case "/":
                case "/ping":
                    return "{\"status\":\"ok\",\"service\":\"revit-mcp\",\"version\":\"0.3.0\"," +
                           "\"pid\":" + Process.GetCurrentProcess().Id + "," +
                           "\"port\":" + _boundPort + "," +
                           "\"revit_version\":\"" + JsonEscape(_revitVersion) + "\"}";

                case "/info":
                    return await _handler.RunOnRevitThreadAsync(ctx =>
                    {
                        var doc = ctx.UIApp.ActiveUIDocument?.Document;
                        if (doc == null) return JsonError("No active document.");
                        var view = ctx.UIApp.ActiveUIDocument.ActiveView;
                        var sb = new StringBuilder();
                        sb.Append("{\"status\":\"ok\"");
                        sb.Append(",\"document_title\":\"").Append(JsonEscape(doc.Title)).Append('\"');
                        sb.Append(",\"document_path\":\"").Append(JsonEscape(doc.PathName ?? "")).Append('\"');
                        sb.Append(",\"is_workshared\":").Append(doc.IsWorkshared ? "true" : "false");
                        sb.Append(",\"active_view\":\"").Append(JsonEscape(view?.Name ?? "")).Append('\"');
                        sb.Append(",\"revit_version\":\"").Append(JsonEscape(ctx.UIApp.Application.VersionName)).Append('\"');
                        sb.Append(",\"username\":\"").Append(JsonEscape(ctx.UIApp.Application.Username ?? "")).Append('\"');
                        sb.Append(",\"pid\":").Append(Process.GetCurrentProcess().Id);
                        sb.Append('}');
                        return sb.ToString();
                    }).ConfigureAwait(false);

                case "/exec":
                    return await _handler.ExecuteCSharpAsync(body).ConfigureAwait(false);

                case "/screenshot":
                    return await _handler.ScreenshotAsync(body).ConfigureAwait(false);

                default:
                    return JsonError("Unknown route: " + path);
            }
        }

        // ------------------------------------------------------------------

        public static string JsonEscape(string s)
        {
            if (s == null) return string.Empty;
            var sb = new StringBuilder(s.Length + 8);
            foreach (var c in s)
            {
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '\"': sb.Append("\\\""); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.AppendFormat("\\u{0:X4}", (int)c);
                        else sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }

        public static string JsonError(string msg) =>
            "{\"status\":\"error\",\"error\":\"" + JsonEscape(msg) + "\"}";

        public static void Log(string msg)
        {
            try
            {
                File.AppendAllText(
                    Path.Combine(Path.GetTempPath(), "revit-mcp.log"),
                    DateTime.Now.ToString("u") + "  " + msg + Environment.NewLine);
            }
            catch { }
        }
    }
}
