using System;
using System.Net;
using System.Reflection;
using System.Text.Json;
using System.Threading.Tasks;
using ArchHub.Shared;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevitMCP;
using RevitMCPCore;

internal static class Program
{
    private static CoreEntry Create(UIApplication app)
    {
        var core = new CoreEntry();
        var handler = new RevitEventHandler();
        handler.AttachEvent(new ExternalEvent());
        Func<Func<object, string>, Task<string>> submit = fn => {
            var pending = handler.SubmitAsync(fn);
            UIApplication.InExternalEvent = true;
            try { handler.Execute(app); } finally { UIApplication.InExternalEvent = false; }
            return pending;
        };
        typeof(CoreEntry).GetField("_submit", BindingFlags.NonPublic | BindingFlags.Instance).SetValue(core, submit);
        return core;
    }

    private static async Task Main(string[] args)
    {
        var app = new UIApplication();
        if (args.Length > 0)
        {
            // Real Core.HandleAsync + BridgeAuth, on a court-owned random port.
            BridgeAuth.SecretReader = () => "revit-open-fixture-only-not-a-credential";
            var core = Create(app);
            var listener = new HttpListener();
            listener.Prefixes.Add("http://localhost:" + args[0] + "/"); listener.Start();
            Console.WriteLine("READY");
            var handle = typeof(CoreEntry).GetMethod("HandleAsync", BindingFlags.NonPublic | BindingFlags.Instance);
            _ = Task.Run(async () => {
                while (listener.IsListening)
                {
                    HttpListenerContext request;
                    try { request = await listener.GetContextAsync(); } catch { break; }
                    await (Task)handle.Invoke(core, new object[] { request });
                }
            });
            await Console.In.ReadToEndAsync(); listener.Stop(); return;
        }
        var input = JsonDocument.Parse(await Console.In.ReadToEndAsync()).RootElement;
        if (input.TryGetProperty("active", out var active) && active.GetBoolean())
            app.ActiveUIDocument = new UIDocument { Document = new Document() };
        if (input.TryGetProperty("modifiable", out var modifiable) && app.ActiveUIDocument != null)
            app.ActiveUIDocument.Document.IsModifiable = modifiable.GetBoolean();
        app.FailOpen = input.TryGetProperty("fail_open", out var fail) && fail.GetBoolean();
        Transaction.RefuseStart = input.TryGetProperty("fail_start", out var start) && start.GetBoolean();
        Transaction.StartResult = input.TryGetProperty("start_status", out var ss) ? Enum.Parse<TransactionStatus>(ss.GetString()) : TransactionStatus.Started;
        Transaction.CommitResult = input.TryGetProperty("commit_status", out var cs) ? Enum.Parse<TransactionStatus>(cs.GetString()) : TransactionStatus.Committed;
        var route = typeof(CoreEntry).GetMethod("RouteAsync", BindingFlags.NonPublic | BindingFlags.Instance);
        var task = (Task<string>)route.Invoke(Create(app), new object[] {
            input.GetProperty("route").GetString(), input.GetProperty("body").GetRawText(),
            input.TryGetProperty("method", out var method) ? method.GetString() : "POST" });
        var answer = JsonDocument.Parse(await task).RootElement;
        Console.WriteLine(JsonSerializer.Serialize(new { answer, app.Opens, ModelPathUtils.LastPath,
            Transaction.Starts, Transaction.Commits, Transaction.Rollbacks, ScriptCompiler.Calls }));
    }
}
