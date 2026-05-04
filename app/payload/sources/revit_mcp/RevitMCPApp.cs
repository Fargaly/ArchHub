using System;
using System.IO;
using System.Net;
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
    /// </summary>
    [Regeneration(RegenerationOption.Manual)]
    public class RevitMCPApp : IExternalApplication
    {
        private const string ListenPrefix = "http://localhost:48884/";

        private HttpListener _listener;
        private CancellationTokenSource _cts;
        private RevitEventHandler _handler;
        private ExternalEvent _externalEvent;

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                _handler = new RevitEventHandler();
                _externalEvent = ExternalEvent.Create(_handler);
                _handler.AttachEvent(_externalEvent);

                _cts = new CancellationTokenSource();
                Task.Run(() => RunListenerAsync(_cts.Token));

                Log("RevitMCP started. Listening on " + ListenPrefix);
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
            return Result.Succeeded;
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
                Log("HttpListener.Start failed: " + ex);
                return;
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
                    return "{\"status\":\"ok\",\"service\":\"revit-mcp\",\"version\":\"0.2.0\"}";

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
