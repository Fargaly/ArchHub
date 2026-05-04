using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Microsoft.CodeAnalysis.CSharp.Scripting;
using Microsoft.CodeAnalysis.Scripting;

namespace RevitMCP
{
    public class ScriptContext
    {
        public UIApplication UIApp;
        public UIDocument UIDoc;
        public Document Doc;
        // Scripts can stash any JSON-serialisable value here to return it.
        public object result;
    }

    /// <summary>
    /// Holds work items and runs them on the Revit UI thread when ExternalEvent.Raise()
    /// triggers Execute. HTTP handlers wait via TaskCompletionSource.
    /// </summary>
    public class RevitEventHandler : IExternalEventHandler
    {
        private readonly ConcurrentQueue<WorkItem> _queue = new ConcurrentQueue<WorkItem>();
        private ExternalEvent _event;

        public void AttachEvent(ExternalEvent ev) { _event = ev; }

        public string GetName() => "RevitMCP";

        // Public scheduling API ---------------------------------------------

        public Task<string> RunOnRevitThreadAsync(Func<ScriptContext, string> fn)
        {
            var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            _queue.Enqueue(new WorkItem { Kind = WorkKind.Native, Native = fn, Tcs = tcs });
            _event.Raise();
            return tcs.Task;
        }

        public Task<string> ExecuteCSharpAsync(string requestBody)
        {
            var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            string code; string txName;
            try
            {
                using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(requestBody) ? "{}" : requestBody);
                code = doc.RootElement.TryGetProperty("code", out var c) ? c.GetString() : null;
                txName = doc.RootElement.TryGetProperty("transaction_name", out var t) ? t.GetString() : "MCP exec";
            }
            catch (Exception ex)
            {
                tcs.SetResult(RevitMCPApp.JsonError("Bad JSON body: " + ex.Message));
                return tcs.Task;
            }
            if (string.IsNullOrEmpty(code))
            {
                tcs.SetResult(RevitMCPApp.JsonError("Missing 'code' in body."));
                return tcs.Task;
            }
            _queue.Enqueue(new WorkItem { Kind = WorkKind.CSharpScript, Code = code, TxName = txName ?? "MCP exec", Tcs = tcs });
            _event.Raise();
            return tcs.Task;
        }

        public Task<string> ScreenshotAsync(string requestBody)
        {
            var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            string outPath = @"C:\temp\revit_mcp_view.png";
            int width = 1920;
            try
            {
                if (!string.IsNullOrWhiteSpace(requestBody))
                {
                    using var doc = JsonDocument.Parse(requestBody);
                    if (doc.RootElement.TryGetProperty("output_path", out var p)) outPath = p.GetString() ?? outPath;
                    if (doc.RootElement.TryGetProperty("width_px", out var w)) width = w.GetInt32();
                }
            }
            catch (Exception ex)
            {
                tcs.SetResult(RevitMCPApp.JsonError("Bad JSON: " + ex.Message));
                return tcs.Task;
            }
            _queue.Enqueue(new WorkItem { Kind = WorkKind.Screenshot, OutputPath = outPath, Width = width, Tcs = tcs });
            _event.Raise();
            return tcs.Task;
        }

        // Revit calls this on the UI thread ---------------------------------

        public void Execute(UIApplication app)
        {
            while (_queue.TryDequeue(out var item))
            {
                try
                {
                    string result = item.Kind switch
                    {
                        WorkKind.Native => RunNative(app, item),
                        WorkKind.CSharpScript => RunCSharpScript(app, item),
                        WorkKind.Screenshot => RunScreenshot(app, item),
                        _ => RevitMCPApp.JsonError("Unknown work kind."),
                    };
                    item.Tcs.SetResult(result);
                }
                catch (Exception ex)
                {
                    item.Tcs.SetResult(RevitMCPApp.JsonError(ex.GetType().Name + ": " + ex.Message));
                }
            }
        }

        // Work runners ------------------------------------------------------

        private string RunNative(UIApplication app, WorkItem item)
        {
            var ctx = BuildContext(app);
            return item.Native(ctx);
        }

        private string RunCSharpScript(UIApplication app, WorkItem item)
        {
            var ctx = BuildContext(app);
            if (ctx.Doc == null)
                return RevitMCPApp.JsonError("No active document.");

            var options = ScriptOptions.Default
                .WithReferences(
                    typeof(Autodesk.Revit.DB.Document).Assembly,
                    typeof(Autodesk.Revit.UI.UIApplication).Assembly,
                    typeof(System.Linq.Enumerable).Assembly,
                    typeof(System.Collections.Generic.List<>).Assembly)
                .WithImports(
                    "System",
                    "System.Collections.Generic",
                    "System.Linq",
                    "Autodesk.Revit.DB",
                    "Autodesk.Revit.UI");

            using (var tx = new Transaction(ctx.Doc, item.TxName))
            {
                try { tx.Start(); } catch { /* nested or already started */ }

                try
                {
                    var task = CSharpScript.RunAsync(item.Code, options, ctx);
                    task.Wait();
                    if (tx.HasStarted() && tx.GetStatus() == TransactionStatus.Started)
                        tx.Commit();

                    var resultJson = SerializeResult(ctx.result);
                    return "{\"status\":\"ok\",\"result\":" + resultJson + "}";
                }
                catch (Exception ex)
                {
                    try { if (tx.HasStarted()) tx.RollBack(); } catch { }
                    var inner = ex.InnerException?.Message ?? ex.Message;
                    return RevitMCPApp.JsonError("Script error: " + inner);
                }
            }
        }

        private string RunScreenshot(UIApplication app, WorkItem item)
        {
            var doc = app.ActiveUIDocument?.Document;
            var view = app.ActiveUIDocument?.ActiveView;
            if (doc == null || view == null) return RevitMCPApp.JsonError("No active view.");

            var dir = System.IO.Path.GetDirectoryName(item.OutputPath);
            if (!string.IsNullOrEmpty(dir) && !System.IO.Directory.Exists(dir))
                System.IO.Directory.CreateDirectory(dir);

            var opts = new ImageExportOptions
            {
                ExportRange = ExportRange.SetOfViews,
                HLRandWFViewsFileType = ImageFileType.PNG,
                ImageResolution = ImageResolution.DPI_300,
                PixelSize = item.Width,
                FilePath = item.OutputPath,
                ZoomType = ZoomFitType.FitToPage,
            };
            opts.SetViewsAndSheets(new List<ElementId> { view.Id });
            doc.ExportImage(opts);

            return "{\"status\":\"ok\",\"output_path\":\"" + RevitMCPApp.JsonEscape(item.OutputPath) +
                   "\",\"view_name\":\"" + RevitMCPApp.JsonEscape(view.Name) + "\"}";
        }

        // Helpers -----------------------------------------------------------

        private static ScriptContext BuildContext(UIApplication app)
        {
            return new ScriptContext
            {
                UIApp = app,
                UIDoc = app.ActiveUIDocument,
                Doc = app.ActiveUIDocument?.Document,
            };
        }

        private static string SerializeResult(object value)
        {
            if (value == null) return "null";
            try
            {
                var opts = new JsonSerializerOptions { WriteIndented = false, MaxDepth = 8 };
                return JsonSerializer.Serialize(value, opts);
            }
            catch
            {
                // Fall back to ToString
                return "\"" + RevitMCPApp.JsonEscape(value.ToString()) + "\"";
            }
        }

        // ------------------------------------------------------------------

        private enum WorkKind { Native, CSharpScript, Screenshot }

        private class WorkItem
        {
            public WorkKind Kind;
            public Func<ScriptContext, string> Native;
            public string Code;
            public string TxName;
            public string OutputPath;
            public int Width;
            public TaskCompletionSource<string> Tcs;
        }
    }
}
