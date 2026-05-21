// AgDR-0027 — hot-reloadable Core for RevitMCP.
//
// Loaded by the shim's CoreLoader into a collectible ALC on net8.
// Implements ICoreEntryPoint.Start/Stop so the shim can swap a
// new build of THIS file in without restarting Revit.
//
// What lives here (hot-reloadable):
//   * HTTP listener + route dispatch
//   * Session-registry file writer + heartbeat
//   * /info /exec /screenshot /reload route handlers
//   * ScriptCompiler invocation (AgDR-0025 subprocess csc)
//   * Per-Core sha256 reported via /ping
//
// What stays in the shim (NOT hot-reloadable):
//   * IExternalApplication (Revit's lifecycle)
//   * IExternalEventHandler (UI-thread work pump)
//   * The CoreLoader itself

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ArchHub.Shared;

namespace RevitMCPCore
{
    /// <summary>
    /// Script-side context handed to compiled /exec scripts.
    /// Defined HERE so the shim never references it — when Core
    /// reloads, the type vanishes cleanly with the ALC.
    /// </summary>
    public class ScriptContext
    {
        public UIApplication UIApp;
        public UIDocument UIDoc;
        public Document Doc;
        public object result;
    }

    /// <summary>
    /// CoreEntry — reflection-discovered by ArchHub.Shared.CoreLoader.
    /// Method signatures must EXACTLY match the convention documented in
    /// shared/CoreLoader.cs: Start(submit, log, hostInfo) → int port,
    /// Stop(), and ReloadTriggerForShim settable property.  No interface
    /// implements — shim discovers by NAME, invokes by reflection.  This
    /// keeps type identity simple (BCL-only) across the shim/Core ALC
    /// boundary.
    /// </summary>
    public class CoreEntry
    {
        private const int PortFirst = 48884;
        private const int PortLast  = 48899;
        private const int HeartbeatSeconds = 10;

        private HttpListener _listener;
        private CancellationTokenSource _cts;
        private System.Threading.Timer _heartbeat;
        private int _port;
        private string _sessionFile;
        private string _revitVersion = "";
        private string _corePath = "";
        private string _coreSha  = "";
        // Submit a function for UI-thread execution.  Returns Task<string>
        // (JSON response).  Set by the shim via Start().
        private Func<Func<object, string>, Task<string>> _submit;
        private Action<string> _log = s => { };

        // Allows /reload to ping the shim back so it loads a new Core
        // DLL.  Wired in by reflection from the shim BEFORE Start().
        public Action<string> ReloadTriggerForShim { get; set; }

        public int Start(Func<Func<object, string>, Task<string>> submit,
                         Action<string> log,
                         IDictionary<string, string> hostInfo)
        {
            _submit = submit;
            _log = log ?? (s => { });
            _revitVersion = hostInfo.TryGetValue("host_version", out var v) ? v : "";
            _corePath = hostInfo.TryGetValue("core_path", out var p) ? p : "";
            _coreSha  = hostInfo.TryGetValue("core_sha",  out var s) ? s : "";
            // The shim drops a callable into hostInfo so /reload can
            // tell the shim to swap Cores.  Key is documented in the
            // shim's RevitMCPApp.cs.
            if (hostInfo.TryGetValue("__reload_trigger_id", out var _))
            {
                // Reload-trigger plumbing handled via ReloadTriggerForShim
                // setter below (shim sets it after construction).  The
                // hostInfo key is just a sentinel for debugging.
            }

            _cts = new CancellationTokenSource();
            // Bind first free port.
            for (int p2 = PortFirst; p2 <= PortLast; p2++)
            {
                if (_cts.IsCancellationRequested) break;
                var lis = new HttpListener();
                lis.Prefixes.Add("http://localhost:" + p2 + "/");
                try { lis.Start(); _listener = lis; _port = p2; break; }
                catch { /* port taken, try next */ }
            }
            if (_listener == null)
                throw new InvalidOperationException(
                    "no free port in [" + PortFirst + ".." + PortLast + "]");
            _log("Core HTTP listening on " + _port);

            // Session registry.
            try
            {
                _sessionFile = WriteSessionFile(_port, _revitVersion);
                _heartbeat = new System.Threading.Timer(_ => HeartbeatTick(), null,
                    TimeSpan.FromSeconds(HeartbeatSeconds),
                    TimeSpan.FromSeconds(HeartbeatSeconds));
            }
            catch (Exception ex) { _log("session reg failed: " + ex.Message); }

            Task.Run(() => AcceptLoopAsync(_cts.Token));
            return _port;
        }

        public void Stop()
        {
            try { _cts?.Cancel(); } catch { }
            try { _listener?.Stop(); } catch { }
            try { _listener?.Close(); } catch { }
            try { _heartbeat?.Dispose(); } catch { }
            try
            {
                if (!string.IsNullOrEmpty(_sessionFile) && File.Exists(_sessionFile))
                    File.Delete(_sessionFile);
            }
            catch { }
            _listener = null;
            _heartbeat = null;
            _log("Core stopped + port " + _port + " released");
        }

        // ─── HTTP loop ───────────────────────────────────────────

        private async Task AcceptLoopAsync(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                HttpListenerContext ctx;
                try { ctx = await _listener.GetContextAsync().ConfigureAwait(false); }
                catch { break; }
                _ = HandleAsync(ctx);
            }
        }

        private async Task HandleAsync(HttpListenerContext ctx)
        {
            string respJson;
            try
            {
                var path = (ctx.Request.Url.AbsolutePath ?? "/").TrimEnd('/');
                if (string.IsNullOrEmpty(path)) path = "/";
                string body = "";
                if (ctx.Request.HasEntityBody)
                {
                    using (var r = new StreamReader(ctx.Request.InputStream,
                                                    ctx.Request.ContentEncoding ?? Encoding.UTF8))
                        body = await r.ReadToEndAsync().ConfigureAwait(false);
                }
                respJson = await RouteAsync(path, body, ctx.Request.HttpMethod)
                              .ConfigureAwait(false);
            }
            catch (Exception ex) { respJson = JsonError("server: " + ex.Message); }

            try
            {
                var b = Encoding.UTF8.GetBytes(respJson ?? "{}");
                ctx.Response.ContentType = "application/json; charset=utf-8";
                ctx.Response.ContentLength64 = b.Length;
                ctx.Response.StatusCode = 200;
                await ctx.Response.OutputStream.WriteAsync(b, 0, b.Length).ConfigureAwait(false);
                ctx.Response.OutputStream.Close();
            }
            catch (Exception ex) { _log("resp write: " + ex.Message); }
        }

        // ─── routes ──────────────────────────────────────────────

        private async Task<string> RouteAsync(string path, string body, string method)
        {
            switch (path)
            {
                case "/":
                case "/ping":
                    var cscPath = ScriptCompiler.ProbeCsc();
                    return "{\"status\":\"ok\",\"service\":\"revit-mcp\",\"version\":\"0.5.0\","
                         + "\"pid\":" + Process.GetCurrentProcess().Id + ","
                         + "\"port\":" + _port + ","
                         + "\"revit_version\":\"" + JsonEscape(_revitVersion) + "\","
                         + "\"compiler\":\"subprocess_csc\","
                         + "\"csc_status\":\"" + (cscPath != null ? "ok" : "missing") + "\","
                         + "\"csc_path\":\"" + JsonEscape(cscPath ?? "") + "\","
                         + "\"core_sha\":\"" + JsonEscape(_coreSha) + "\","
                         + "\"hot_reload\":true}";

                case "/info":
                    return await _submit(a =>
                    {
                        var app = (UIApplication)a;
                        var doc = app.ActiveUIDocument?.Document;
                        if (doc == null) return JsonError("No active document.");
                        var view = app.ActiveUIDocument.ActiveView;
                        var sb = new StringBuilder();
                        sb.Append("{\"status\":\"ok\"");
                        sb.Append(",\"document_title\":\"").Append(JsonEscape(doc.Title)).Append('\"');
                        sb.Append(",\"document_path\":\"").Append(JsonEscape(doc.PathName ?? "")).Append('\"');
                        sb.Append(",\"is_workshared\":").Append(doc.IsWorkshared ? "true" : "false");
                        sb.Append(",\"active_view\":\"").Append(JsonEscape(view?.Name ?? "")).Append('\"');
                        sb.Append(",\"revit_version\":\"").Append(JsonEscape(app.Application.VersionName)).Append('\"');
                        sb.Append(",\"username\":\"").Append(JsonEscape(app.Application.Username ?? "")).Append('\"');
                        sb.Append(",\"pid\":").Append(Process.GetCurrentProcess().Id);
                        sb.Append('}');
                        return sb.ToString();
                    }).ConfigureAwait(false);

                case "/exec":
                    return await ExecAsync(body).ConfigureAwait(false);

                case "/screenshot":
                    return await ScreenshotAsync(body).ConfigureAwait(false);

                case "/reload":
                    return await ReloadAsync(body).ConfigureAwait(false);

                default:
                    return JsonError("Unknown route: " + path);
            }
        }

        // ─── /exec ───────────────────────────────────────────────

        private async Task<string> ExecAsync(string body)
        {
            string code = null, txName = "MCP exec";
            try
            {
                using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(body) ? "{}" : body);
                code = doc.RootElement.TryGetProperty("code", out var c) ? c.GetString() : null;
                txName = doc.RootElement.TryGetProperty("transaction_name", out var t)
                            ? t.GetString() : "MCP exec";
            }
            catch (Exception ex) { return JsonError("Bad JSON: " + ex.Message); }
            if (string.IsNullOrEmpty(code)) return JsonError("Missing 'code'.");

            return await _submit(a => RunCSharpScript((UIApplication)a, code, txName))
                              .ConfigureAwait(false);
        }

        private string RunCSharpScript(UIApplication app, string code, string txName)
        {
            var ctx = new ScriptContext
            {
                UIApp = app,
                UIDoc = app.ActiveUIDocument,
                Doc   = app.ActiveUIDocument?.Document,
            };
            if (ctx.Doc == null) return JsonError("No active document.");

            var revitDllDir = Path.GetDirectoryName(typeof(Document).Assembly.Location);
            var revitApi   = Path.Combine(revitDllDir, "RevitAPI.dll");
            var revitApiUi = Path.Combine(revitDllDir, "RevitAPIUI.dll");
            var thisAsm    = typeof(ScriptContext).Assembly.Location;
            var sysCore    = typeof(System.Linq.Enumerable).Assembly.Location;
            var sysColl    = typeof(List<>).Assembly.Location;
            var mscorlib   = typeof(object).Assembly.Location;

            var refs = new[] { revitApi, revitApiUi, thisAsm, mscorlib, sysCore, sysColl }
                       .Where(File.Exists)
                       .Distinct(StringComparer.OrdinalIgnoreCase)
                       .ToList();

            var usings = new[] {
                "System", "System.Collections.Generic", "System.Linq",
                "Autodesk.Revit.DB", "Autodesk.Revit.UI",
            };

            using (var tx = new Transaction(ctx.Doc, txName))
            {
                try { tx.Start(); } catch { }
                ScriptResult sr;
                try
                {
                    sr = ScriptCompiler.CompileAndRun(
                        userCode: code,
                        ctx: ctx,
                        scriptContextFullName: "global::RevitMCPCore.ScriptContext",
                        references: refs,
                        usings: usings,
                        langVersion: "7.3");
                }
                catch (Exception ex)
                {
                    try { if (tx.HasStarted()) tx.RollBack(); } catch { }
                    return JsonError("ScriptCompiler crash: " + ex.Message);
                }
                if (sr.Status == "ok")
                {
                    if (tx.HasStarted() && tx.GetStatus() == TransactionStatus.Started)
                        tx.Commit();
                    var resultJson = SerializeResult(ctx.result ?? sr.Result);
                    return "{\"status\":\"ok\",\"result\":" + resultJson
                         + ",\"compiler\":\"subprocess_csc\""
                         + ",\"cache_hit\":" + (sr.CacheHit ? "true" : "false") + "}";
                }
                try { if (tx.HasStarted()) tx.RollBack(); } catch { }
                return "{\"status\":\"error\",\"error_code\":\"" + sr.Status
                     + "\",\"error\":\"" + JsonEscape(sr.Error ?? "unknown") + "\"}";
            }
        }

        // ─── /screenshot ─────────────────────────────────────────

        private async Task<string> ScreenshotAsync(string body)
        {
            string outPath = @"C:\temp\revit_mcp_view.png";
            int width = 1920;
            try
            {
                if (!string.IsNullOrWhiteSpace(body))
                {
                    using var doc = JsonDocument.Parse(body);
                    if (doc.RootElement.TryGetProperty("output_path", out var p)) outPath = p.GetString() ?? outPath;
                    if (doc.RootElement.TryGetProperty("width_px", out var w)) width = w.GetInt32();
                }
            }
            catch (Exception ex) { return JsonError("Bad JSON: " + ex.Message); }

            var capturedOut = outPath;
            var capturedW = width;
            return await _submit(a =>
            {
                var app = (UIApplication)a;
                var doc = app.ActiveUIDocument?.Document;
                var view = app.ActiveUIDocument?.ActiveView;
                if (doc == null || view == null) return JsonError("No active view.");
                var dir = Path.GetDirectoryName(capturedOut);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir)) Directory.CreateDirectory(dir);
                var opts = new ImageExportOptions
                {
                    ExportRange = ExportRange.SetOfViews,
                    HLRandWFViewsFileType = ImageFileType.PNG,
                    ImageResolution = ImageResolution.DPI_300,
                    PixelSize = capturedW,
                    FilePath = capturedOut,
                    ZoomType = ZoomFitType.FitToPage,
                };
                opts.SetViewsAndSheets(new List<ElementId> { view.Id });
                doc.ExportImage(opts);
                return "{\"status\":\"ok\",\"output_path\":\"" + JsonEscape(capturedOut)
                     + "\",\"view_name\":\"" + JsonEscape(view.Name) + "\"}";
            }).ConfigureAwait(false);
        }

        // ─── /reload ─────────────────────────────────────────────

        private async Task<string> ReloadAsync(string body)
        {
            string newCorePath = null;
            try
            {
                if (!string.IsNullOrWhiteSpace(body))
                {
                    using var doc = JsonDocument.Parse(body);
                    if (doc.RootElement.TryGetProperty("core_path", out var p))
                        newCorePath = p.GetString();
                }
            }
            catch (Exception ex) { return JsonError("Bad JSON: " + ex.Message); }
            if (string.IsNullOrEmpty(newCorePath))
                return JsonError("Missing 'core_path' in body.");
            if (!File.Exists(newCorePath))
                return JsonError("core_path not found: " + newCorePath);
            if (ReloadTriggerForShim == null)
                return JsonError("No reload trigger wired (shim too old?)");

            // Schedule the swap AFTER this response is sent — invoking
            // ReloadTriggerForShim now would Stop() us mid-write.  Run
            // it on a thread-pool task with a tiny delay so the HTTP
            // response can flush first.
            var pathCapture = newCorePath;
            var trigger = ReloadTriggerForShim;
            _ = Task.Run(async () =>
            {
                await Task.Delay(150).ConfigureAwait(false);
                try { trigger(pathCapture); }
                catch (Exception ex) { _log("reload trigger ex: " + ex.Message); }
            });
            return "{\"status\":\"reloading\",\"core_path\":\"" + JsonEscape(newCorePath) + "\"}";
        }

        // ─── session registry (heartbeat + atomic file) ──────────

        private string WriteSessionFile(int port, string revitVersion)
        {
            var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                   "ArchHub", "sessions");
            Directory.CreateDirectory(dir);
            int pid = Process.GetCurrentProcess().Id;
            var path = Path.Combine(dir, "revit-" + pid + ".json");
            WriteSessionJson(path, port, revitVersion, pid, false);
            return path;
        }

        private void HeartbeatTick()
        {
            if (string.IsNullOrEmpty(_sessionFile)) return;
            try
            {
                WriteSessionJson(_sessionFile, _port, _revitVersion,
                                 Process.GetCurrentProcess().Id, true);
            }
            catch { }
        }

        private void WriteSessionJson(string path, int port, string ver, int pid, bool hb)
        {
            var sb = new StringBuilder(256);
            sb.Append('{');
            sb.Append("\"session_id\":\"revit-").Append(pid).Append("\",");
            sb.Append("\"family\":\"revit\",");
            sb.Append("\"pid\":").Append(pid).Append(',');
            sb.Append("\"port\":").Append(port).Append(',');
            sb.Append("\"version\":\"").Append(JsonEscape(ver)).Append("\",");
            sb.Append("\"core_sha\":\"").Append(JsonEscape(_coreSha)).Append("\",");
            sb.Append("\"started_at\":\"").Append(DateTime.UtcNow.ToString("o")).Append("\",");
            sb.Append("\"last_heartbeat\":\"").Append(DateTime.UtcNow.ToString("o")).Append("\",");
            sb.Append("\"heartbeat\":").Append(hb ? "true" : "false");
            sb.Append('}');
            var tmp = path + ".tmp";
            File.WriteAllText(tmp, sb.ToString(), new UTF8Encoding(false));
            try
            {
                if (File.Exists(path)) File.Replace(tmp, path, null);
                else File.Move(tmp, path);
            }
            catch
            {
                File.Copy(tmp, path, overwrite: true);
                try { File.Delete(tmp); } catch { }
            }
        }

        // ─── helpers ─────────────────────────────────────────────

        private static string SerializeResult(object value)
        {
            if (value == null) return "null";
            try { return JsonSerializer.Serialize(value,
                new JsonSerializerOptions { WriteIndented = false, MaxDepth = 8 }); }
            catch { return "\"" + JsonEscape(value.ToString()) + "\""; }
        }

        public static string JsonEscape(string s)
        {
            if (s == null) return "";
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
    }
}
