using System;
using System.Collections.Concurrent;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;
// AgDR-0025 — zero in-process Roslyn.  Compilation goes through
// ArchHub.Shared.ScriptCompiler (subprocess csc.exe).
using ArchHub.Shared;
using System.Collections.Generic;
using System.Reflection;

[assembly: ExtensionApplication(typeof(AcadMCP.AcadMCPApp))]

namespace AcadMCP
{
    public class AcadScriptContext
    {
        public Document Doc;
        public Database Db;
        public Editor Ed;
        public object result;
    }

    public class AcadMCPApp : IExtensionApplication
    {
        // AgDR-0052 — listener resilience, mirroring RevitMCPCore.CoreEntry.
        // The single hardcoded prefix is widened into a scan range whose
        // FIRST element stays 48885 (the canonical AutoCAD broker port — see
        // acad_broker.PORT_FIRST), so this is additive: 48885 is still tried
        // first, we only fall through to 48886..48899 when it is taken by a
        // stale http.sys reservation or another AutoCAD session.
        private const int PortFirst = 48885;   // canonical port preserved as range start
        private const int PortLast  = 48899;
        private const int HeartbeatSeconds = 10;

        private HttpListener _listener;
        private CancellationTokenSource _cts;
        private int _port;                 // AgDR-0052 — discovered bind port
        private string _sessionFile;       // AgDR-0052 — %LOCALAPPDATA%\ArchHub\sessions\autocad-<pid>.json
        private System.Threading.Timer _heartbeat;   // AgDR-0052 — refreshes session file

        // Inbound work to be executed on the AutoCAD main thread (in the Idle handler).
        private static readonly ConcurrentQueue<WorkItem> Queue = new ConcurrentQueue<WorkItem>();

        public void Initialize()
        {
            try
            {
                Application.Idle += OnIdle;
                _cts = new CancellationTokenSource();
                Task.Run(() => RunListenerAsync(_cts.Token));
                // AgDR-0052 — actual bound port is logged inside
                // RunListenerAsync once the scan succeeds.
                Log("AcadMCP starting. Scanning ports " + PortFirst + ".." + PortLast);
            }
            catch (System.Exception ex)
            {
                Log("Init failed: " + ex);
            }
        }

        public void Terminate()
        {
            try { _cts?.Cancel(); } catch { }
            try { _listener?.Stop(); } catch { }
            // AgDR-0052 — stop the heartbeat + remove the session file so the
            // broker prunes us immediately on a clean unload (mirrors
            // RevitMCPCore.CoreEntry.Stop).
            try { _heartbeat?.Dispose(); } catch { }
            try
            {
                if (!string.IsNullOrEmpty(_sessionFile) && File.Exists(_sessionFile))
                    File.Delete(_sessionFile);
            }
            catch { }
            try { Application.Idle -= OnIdle; } catch { }
        }

        // ------------------------------------------------------------------

        private async Task RunListenerAsync(CancellationToken ct)
        {
            // AgDR-0052 — scan + retry the 48885..48899 range instead of the
            // old single-port bind that returned (gave up) on the first
            // HttpListenerException (e.g. 183 from a stale http.sys URL
            // reservation), which forced a manual NETLOAD. Mirrors
            // RevitMCPCore.CoreEntry.Start lines 103-110. Non-destructive:
            // 48885 is still attempted first.
            for (int p = PortFirst; p <= PortLast; p++)
            {
                if (ct.IsCancellationRequested) return;
                var lis = new HttpListener();
                lis.Prefixes.Add("http://localhost:" + p + "/");
                try { lis.Start(); _listener = lis; _port = p; break; }
                catch (System.Exception ex)
                {
                    Log("Listener.Start on " + p + " failed (trying next): " + ex.Message);
                    try { lis.Close(); } catch { }
                }
            }
            if (_listener == null)
            {
                Log("Listener.Start failed: no free port in ["
                    + PortFirst + ".." + PortLast + "]");
                return;
            }
            Log("AcadMCP listening on http://localhost:" + _port + "/");

            // AgDR-0052 — session registry + heartbeat, mirroring
            // RevitMCPCore.CoreEntry. acad_broker.list_sessions reads
            // autocad-<pid>.json (port/pid/version/heartbeat) and prunes
            // entries silent > 30s, so the 10s cadence keeps us live.
            try
            {
                _sessionFile = WriteSessionFile(_port);
                _heartbeat = new System.Threading.Timer(_ => HeartbeatTick(), null,
                    TimeSpan.FromSeconds(HeartbeatSeconds),
                    TimeSpan.FromSeconds(HeartbeatSeconds));
            }
            catch (System.Exception ex) { Log("session reg failed: " + ex.Message); }

            while (!ct.IsCancellationRequested)
            {
                HttpListenerContext context;
                try { context = await _listener.GetContextAsync().ConfigureAwait(false); }
                catch { break; }
                _ = ProcessRequestAsync(context);
            }
        }

        private async Task ProcessRequestAsync(HttpListenerContext context)
        {
            string responseJson;
            try
            {
                var path = (context.Request.Url.AbsolutePath ?? "/").TrimEnd('/');
                if (string.IsNullOrEmpty(path)) path = "/";
                string body = string.Empty;
                if (context.Request.HasEntityBody)
                {
                    using (var reader = new StreamReader(context.Request.InputStream, context.Request.ContentEncoding ?? Encoding.UTF8))
                        body = await reader.ReadToEndAsync().ConfigureAwait(false);
                }
                responseJson = await RouteAsync(path, body).ConfigureAwait(false);
            }
            catch (System.Exception ex)
            {
                responseJson = JsonError("Server error: " + ex.Message);
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
            catch (System.Exception ex) { Log("Response write failed: " + ex); }
        }

        private Task<string> RouteAsync(string path, string body)
        {
            switch (path)
            {
                case "/":
                case "/ping":
                    {
                        // AgDR-0025 — broadcast subprocess_csc + csc probe state
                        // so the broker logs which compiler we use.
                        var cscPath = ScriptCompiler.ProbeCsc();
                        var cscStatus = cscPath != null ? "ok" : "missing";
                        // AgDR-0052 — port + pid added so acad_broker's
                        // port-range discovery can populate Session metadata
                        // for instances found without a session file.
                        return Task.FromResult(
                            "{\"status\":\"ok\",\"service\":\"acad-mcp\",\"version\":\"0.3.0\","
                            + "\"port\":" + _port + ","
                            + "\"pid\":" + System.Diagnostics.Process.GetCurrentProcess().Id + ","
                            + "\"compiler\":\"subprocess_csc\","
                            + "\"csc_status\":\"" + cscStatus + "\","
                            + "\"csc_path\":\"" + JsonEscape(cscPath ?? "") + "\"}");
                    }

                case "/info":
                    return EnqueueAsync(WorkKind.Info, null, null);

                case "/exec":
                    {
                        string code; string txName;
                        try
                        {
                            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(body) ? "{}" : body);
                            code = doc.RootElement.TryGetProperty("code", out var c) ? c.GetString() : null;
                            txName = doc.RootElement.TryGetProperty("transaction_name", out var t) ? t.GetString() : "MCP exec";
                        }
                        catch (System.Exception ex)
                        {
                            return Task.FromResult(JsonError("Bad JSON: " + ex.Message));
                        }
                        if (string.IsNullOrEmpty(code))
                            return Task.FromResult(JsonError("Missing 'code'."));
                        return EnqueueAsync(WorkKind.CSharpScript, code, txName);
                    }

                default:
                    return Task.FromResult(JsonError("Unknown route: " + path));
            }
        }

        private static Task<string> EnqueueAsync(WorkKind kind, string code, string txName)
        {
            var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            Queue.Enqueue(new WorkItem { Kind = kind, Code = code, TxName = txName ?? "MCP exec", Tcs = tcs });
            return tcs.Task;
        }

        // Runs on the AutoCAD main thread.
        private void OnIdle(object sender, EventArgs e)
        {
            while (Queue.TryDequeue(out var item))
            {
                try
                {
                    string result = item.Kind switch
                    {
                        WorkKind.Info => RunInfo(),
                        WorkKind.CSharpScript => RunCSharpScript(item),
                        _ => JsonError("Unknown work kind."),
                    };
                    item.Tcs.SetResult(result);
                }
                catch (System.Exception ex)
                {
                    item.Tcs.SetResult(JsonError(ex.GetType().Name + ": " + ex.Message));
                }
            }
        }

        // ------------------------------------------------------------------

        private string RunInfo()
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return JsonError("No active document.");
            var sb = new StringBuilder();
            sb.Append("{\"status\":\"ok\"");
            sb.Append(",\"document_name\":\"").Append(JsonEscape(doc.Name)).Append('\"');
            sb.Append(",\"document_path\":\"").Append(JsonEscape(doc.Database.Filename ?? "")).Append('\"');
            sb.Append(",\"acad_version\":\"").Append(JsonEscape(Application.Version.ToString())).Append('\"');
            sb.Append('}');
            return sb.ToString();
        }

        // AgDR-0025 — subprocess csc.exe (zero in-process Roslyn).
        // Previously CSharpScript.RunAsync collided with any other AutoCAD
        // add-in (or ObjectARX product) that loaded a different Roslyn
        // version first.  Now compilation runs out-of-process; the AcadMCP
        // AppDomain stays clean.
        private string RunCSharpScript(WorkItem item)
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return JsonError("No active document.");

            using (DocumentLock lockDoc = doc.LockDocument())
            using (Transaction tr = doc.Database.TransactionManager.StartTransaction())
            {
                var ctx = new AcadScriptContext { Doc = doc, Db = doc.Database, Ed = doc.Editor };

                // Build references list — every host DLL plus minimum BCL.
                var acmgd  = typeof(Application).Assembly.Location;     // acmgd
                var acdbmgd = typeof(DBObject).Assembly.Location;        // acdbmgd
                var thisAsm = typeof(AcadMCPApp).Assembly.Location;
                var sysCore = typeof(System.Linq.Enumerable).Assembly.Location;
                var sysColl = typeof(System.Collections.Generic.List<>).Assembly.Location;
                var mscorlib = typeof(object).Assembly.Location;

                var refs = new List<string> {
                    acmgd, acdbmgd, thisAsm,
                    mscorlib, sysCore, sysColl,
                };
                refs = refs.Where(File.Exists)
                           .Distinct(System.StringComparer.OrdinalIgnoreCase)
                           .ToList();

                var usings = new[] {
                    "System",
                    "System.Collections.Generic",
                    "System.Linq",
                    "Autodesk.AutoCAD.ApplicationServices",
                    "Autodesk.AutoCAD.DatabaseServices",
                    "Autodesk.AutoCAD.EditorInput",
                    "Autodesk.AutoCAD.Geometry",
                    "Autodesk.AutoCAD.Runtime",
                };

                ScriptResult sr;
                try
                {
                    sr = ScriptCompiler.CompileAndRun(
                        userCode: item.Code,
                        ctx: ctx,
                        scriptContextFullName: "global::AcadMCP.AcadScriptContext",
                        references: refs,
                        usings: usings,
                        langVersion: "7.3");
                }
                catch (System.Exception ex)
                {
                    try { tr.Abort(); } catch { }
                    return JsonError("ScriptCompiler crash: " + ex.Message);
                }

                if (sr.Status == "ok")
                {
                    tr.Commit();
                    var resultJson = SerializeResult(ctx.result ?? sr.Result);
                    var sb = new StringBuilder();
                    sb.Append("{\"status\":\"ok\",\"result\":").Append(resultJson);
                    sb.Append(",\"compiler\":\"subprocess_csc\"");
                    sb.Append(",\"cache_hit\":").Append(sr.CacheHit ? "true" : "false");
                    sb.Append('}');
                    return sb.ToString();
                }

                try { tr.Abort(); } catch { }
                return "{\"status\":\"error\",\"error_code\":\"" + sr.Status
                     + "\",\"error\":\"" + JsonEscape(sr.Error ?? "unknown")
                     + "\"}";
            }
        }

        // ------------------------------------------------------------------

        private static string SerializeResult(object value)
        {
            if (value == null) return "null";
            try { return JsonSerializer.Serialize(value, new JsonSerializerOptions { MaxDepth = 8 }); }
            catch { return "\"" + JsonEscape(value.ToString()) + "\""; }
        }

        private static string JsonEscape(string s)
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

        private static string JsonError(string msg) =>
            "{\"status\":\"error\",\"error\":\"" + JsonEscape(msg) + "\"}";

        // ─── AgDR-0052 — session registry (atomic file + heartbeat) ──────
        // Mirrors RevitMCPCore.CoreEntry.WriteSessionFile/HeartbeatTick.
        // acad_broker.list_sessions() reads autocad-<pid>.json; the keys
        // here (session_id/family/pid/port/version/doc_title/started_at/
        // last_heartbeat) match acad_broker._read() exactly. Atomic via
        // tmp + File.Replace so the broker never reads a half-written file.

        private static readonly string _startedAtUtc =
            DateTime.UtcNow.ToString("o");

        private string WriteSessionFile(int port)
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ArchHub", "sessions");
            Directory.CreateDirectory(dir);
            int pid = System.Diagnostics.Process.GetCurrentProcess().Id;
            var path = Path.Combine(dir, "autocad-" + pid + ".json");
            WriteSessionJson(path, port, pid);
            return path;
        }

        private void HeartbeatTick()
        {
            if (string.IsNullOrEmpty(_sessionFile)) return;
            try
            {
                WriteSessionJson(_sessionFile, _port,
                    System.Diagnostics.Process.GetCurrentProcess().Id);
            }
            catch { }
        }

        private void WriteSessionJson(string path, int port, int pid)
        {
            // Best-effort active-document title; never throw from the
            // heartbeat thread if the DocumentManager is mid-transition.
            string docTitle = "";
            try
            {
                var d = Application.DocumentManager.MdiActiveDocument;
                if (d != null) docTitle = d.Name ?? "";
            }
            catch { }

            var nowUtc = DateTime.UtcNow.ToString("o");
            var sb = new StringBuilder(256);
            sb.Append('{');
            sb.Append("\"session_id\":\"autocad-").Append(pid).Append("\",");
            sb.Append("\"family\":\"autocad\",");
            sb.Append("\"pid\":").Append(pid).Append(',');
            sb.Append("\"port\":").Append(port).Append(',');
            sb.Append("\"version\":\"0.3.0\",");
            sb.Append("\"doc_title\":\"").Append(JsonEscape(docTitle)).Append("\",");
            sb.Append("\"started_at\":\"").Append(_startedAtUtc).Append("\",");
            sb.Append("\"last_heartbeat\":\"").Append(nowUtc).Append("\",");
            sb.Append("\"heartbeat\":true");
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

        private static void Log(string msg)
        {
            try
            {
                File.AppendAllText(Path.Combine(Path.GetTempPath(), "acad-mcp.log"),
                    DateTime.Now.ToString("u") + "  " + msg + Environment.NewLine);
            }
            catch { }
        }

        private enum WorkKind { Info, CSharpScript }

        private class WorkItem
        {
            public WorkKind Kind;
            public string Code;
            public string TxName;
            public TaskCompletionSource<string> Tcs;
        }
    }
}
