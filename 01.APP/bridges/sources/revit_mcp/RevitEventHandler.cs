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
using System.Threading;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using Autodesk.Revit.UI;

namespace RevitMCP
{
    public class RevitEventHandler : IExternalEventHandler
    {
        private readonly ConcurrentQueue<Item> _queue = new ConcurrentQueue<Item>();
        private ExternalEvent _event;
        private int _pending;
        private readonly Action<string> _log;
        public bool HasWork => Volatile.Read(ref _pending) > 0;
        public RevitEventHandler(Action<string> log = null) { _log = log ?? (message => Trace.WriteLine(message)); }

        // Cancel this known warning/open operation; never choose Save, overwrite, or an unknown answer.
        public static int? SafeDialogAnswer(string id) => id == "Dialog_Revit_DocWarnDialog" ? 2 : (int?)null;

        public void AttachEvent(ExternalEvent ev) { _event = ev; }
        public string GetName() => "RevitMCP";

        /// <summary>Core-facing API: queue work + await the result.</summary>
        public Task<string> SubmitAsync(Func<object, string> fn)
        {
            var tcs = new TaskCompletionSource<string>(
                TaskCreationOptions.RunContinuationsAsynchronously);
            var item = new Item { Fn = fn, Tcs = tcs };
            Interlocked.Increment(ref _pending);
            _queue.Enqueue(item);
            try { _event?.Raise(); }
            catch (Exception ex)
            {
                if (Interlocked.CompareExchange(ref item.State, 3, 0) == 0) Interlocked.Decrement(ref _pending);
                tcs.TrySetResult("{\"status\":\"error\",\"error\":\"Raise failed: "
                              + Escape(ex.Message) + "\"}");
            }
            _ = WatchAsync(item);
            return tcs.Task;
        }

        public void Execute(UIApplication app)
        {
            while (_queue.TryDequeue(out var item))
            {
                if (Interlocked.CompareExchange(ref item.State, 1, 0) != 0) continue;
                try
                {
                    var s = item.Fn(app);
                    item.Tcs.TrySetResult(s ?? "{}");
                }
                catch (Exception ex)
                {
                    item.Tcs.TrySetResult("{\"status\":\"error\",\"error\":\""
                                       + ex.GetType().Name + ": " + Escape(ex.Message)
                                       + "\"}");
                }
                finally
                {
                    Interlocked.Exchange(ref item.State, 2);
                    Interlocked.Decrement(ref _pending);
                }
            }
        }

        private async Task WatchAsync(Item item)
        {
            if (await Task.WhenAny(item.Tcs.Task, Task.Delay(30000)).ConfigureAwait(false) == item.Tcs.Task) return;
            var cancelled = Interlocked.CompareExchange(ref item.State, 3, 0) == 0;
            if (cancelled) Interlocked.Decrement(ref _pending);
            string dialog = null;
            try { dialog = BlockingDialogTitle(); }
            catch (Exception ex) { _log("Revit dialog probe unavailable: " + ex.GetType().Name); }
            var error = string.IsNullOrEmpty(dialog) ? "Revit is not reaching its ExternalEvent Idling cycle"
                : "Revit is showing dialog " + dialog;
            _log(error + (cancelled ? "; queued request cancelled" : "; running request must not be retried"));
            item.Tcs.TrySetResult(StallResult(dialog, !cancelled));
        }

        public static string StallResult(string title, bool started)
        {
            var error = string.IsNullOrEmpty(title) ? "Revit is not reaching its ExternalEvent Idling cycle"
                : "Revit is showing dialog " + title;
            return "{\"status\":\"error\",\"error\":\"" + Escape(error) + "\",\"execution_state\":\""
                + (started ? "running" : "not_started") + "\",\"retry_safe\":" + (started ? "false" : "true") + "}";
        }

        private delegate bool WindowVisitor(IntPtr handle, IntPtr parameter);
        [DllImport("user32.dll")] private static extern bool EnumWindows(WindowVisitor visitor, IntPtr parameter);
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr handle);
        [DllImport("user32.dll")] private static extern bool IsWindowEnabled(IntPtr handle);
        [DllImport("user32.dll")] private static extern IntPtr GetWindow(IntPtr handle, uint command);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder text, int count);

        public static string BlockingDialogTitle()
        {
            string title = null;
            var mine = (uint)Process.GetCurrentProcess().Id;
            EnumWindows((handle, _) => {
                GetWindowThreadProcessId(handle, out var pid);
                var owner = GetWindow(handle, 4);
                if (pid != mine || !IsWindowVisible(handle) || owner == IntPtr.Zero || IsWindowEnabled(owner)) return true;
                var text = new StringBuilder(512);
                GetWindowText(handle, text, text.Capacity);
                title = text.ToString();
                return false;
            }, IntPtr.Zero);
            return title;
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
            public int State; // queued, running, completed, cancelled
            public Func<object, string> Fn;
            public TaskCompletionSource<string> Tcs;
        }
    }
}
