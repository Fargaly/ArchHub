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
using Autodesk.AutoCAD.Runtime;
using Microsoft.CodeAnalysis.CSharp.Scripting;
using Microsoft.CodeAnalysis.Scripting;

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
        private const string ListenPrefix = "http://localhost:48885/";

        private HttpListener _listener;
        private CancellationTokenSource _cts;

        // Inbound work to be executed on the AutoCAD main thread (in the Idle handler).
        private static readonly ConcurrentQueue<WorkItem> Queue = new ConcurrentQueue<WorkItem>();

        public void Initialize()
        {
            try
            {
                Application.Idle += OnIdle;
                _cts = new CancellationTokenSource();
                Task.Run(() => RunListenerAsync(_cts.Token));
                Log("AcadMCP started. Listening on " + ListenPrefix);
            }
            catch (Exception ex)
            {
                Log("Init failed: " + ex);
            }
        }

        public void Terminate()
        {
            try { _cts?.Cancel(); } catch { }
            try { _listener?.Stop(); } catch { }
            try { Application.Idle -= OnIdle; } catch { }
        }

        // ------------------------------------------------------------------

        private async Task RunListenerAsync(CancellationToken ct)
        {
            try
            {
                _listener = new HttpListener();
                _listener.Prefixes.Add(ListenPrefix);
                _listener.Start();
            }
            catch (Exception ex)
            {
                Log("Listener.Start failed: " + ex);
                return;
            }

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
            catch (Exception ex)
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
            catch (Exception ex) { Log("Response write failed: " + ex); }
        }

        private Task<string> RouteAsync(string path, string body)
        {
            switch (path)
            {
                case "/":
                case "/ping":
                    return Task.FromResult("{\"status\":\"ok\",\"service\":\"acad-mcp\",\"version\":\"0.2.0\"}");

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
                        catch (Exception ex)
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
                catch (Exception ex)
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

        private string RunCSharpScript(WorkItem item)
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return JsonError("No active document.");

            using (DocumentLock lockDoc = doc.LockDocument())
            using (Transaction tr = doc.Database.TransactionManager.StartTransaction())
            {
                var ctx = new AcadScriptContext { Doc = doc, Db = doc.Database, Ed = doc.Editor };

                var options = ScriptOptions.Default
                    .WithReferences(
                        typeof(Application).Assembly,                 // acmgd
                        typeof(DBObject).Assembly,                    // acdbmgd
                        typeof(System.Linq.Enumerable).Assembly)
                    .WithImports(
                        "System",
                        "System.Collections.Generic",
                        "System.Linq",
                        "Autodesk.AutoCAD.ApplicationServices",
                        "Autodesk.AutoCAD.DatabaseServices",
                        "Autodesk.AutoCAD.EditorInput",
                        "Autodesk.AutoCAD.Geometry",
                        "Autodesk.AutoCAD.Runtime");

                try
                {
                    var task = CSharpScript.RunAsync(item.Code, options, ctx);
                    task.Wait();
                    tr.Commit();

                    var resultJson = SerializeResult(ctx.result);
                    return "{\"status\":\"ok\",\"result\":" + resultJson + "}";
                }
                catch (Exception ex)
                {
                    try { tr.Abort(); } catch { }
                    var inner = ex.InnerException?.Message ?? ex.Message;
                    return JsonError("Script error: " + inner);
                }
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
