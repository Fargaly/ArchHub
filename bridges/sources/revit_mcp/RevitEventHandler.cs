// AgDR-0027 — RevitMCP shim's UI-thread work pump.
//
// Revit owns one ExternalEvent per add-in.  Calling Raise() makes
// Revit invoke Execute(UIApplication) on the UI thread.  Every
// /exec /info /screenshot call from Core goes through here: Core
// queues a Func<object,string>, we run it with `app` bound to
// the live UIApplication, return its JSON via TaskCompletionSource.
//
// This file stays in the SHIM (not Core) because Revit references
// the IExternalEventHandler instance.  If it lived in Core, Revit
// would pin the Core ALC → no hot-reload ever.

using System;
using System.Collections.Concurrent;
using System.Threading.Tasks;
using Autodesk.Revit.UI;

namespace RevitMCP
{
    public class RevitEventHandler : IExternalEventHandler
    {
        private readonly ConcurrentQueue<Item> _queue = new ConcurrentQueue<Item>();
        private ExternalEvent _event;

        public void AttachEvent(ExternalEvent ev) { _event = ev; }
        public string GetName() => "RevitMCP";

        /// <summary>Core-facing API: queue work + await the result.</summary>
        public Task<string> SubmitAsync(Func<object, string> fn)
        {
            var tcs = new TaskCompletionSource<string>(
                TaskCreationOptions.RunContinuationsAsynchronously);
            _queue.Enqueue(new Item { Fn = fn, Tcs = tcs });
            try { _event?.Raise(); }
            catch (Exception ex)
            {
                tcs.SetResult("{\"status\":\"error\",\"error\":\"Raise failed: "
                              + Escape(ex.Message) + "\"}");
            }
            return tcs.Task;
        }

        public void Execute(UIApplication app)
        {
            while (_queue.TryDequeue(out var item))
            {
                try
                {
                    var s = item.Fn(app);
                    item.Tcs.SetResult(s ?? "{}");
                }
                catch (Exception ex)
                {
                    item.Tcs.SetResult("{\"status\":\"error\",\"error\":\""
                                       + ex.GetType().Name + ": " + Escape(ex.Message)
                                       + "\"}");
                }
            }
        }

        private static string Escape(string s)
        {
            if (s == null) return "";
            var sb = new System.Text.StringBuilder(s.Length + 4);
            foreach (var c in s)
            {
                if      (c == '\\') sb.Append("\\\\");
                else if (c == '\"') sb.Append("\\\"");
                else if (c == '\n') sb.Append("\\n");
                else if (c == '\r') sb.Append("\\r");
                else                sb.Append(c);
            }
            return sb.ToString();
        }

        private class Item
        {
            public Func<object, string> Fn;
            public TaskCompletionSource<string> Tcs;
        }
    }
}
