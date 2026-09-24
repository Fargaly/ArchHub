// AgDR-0027 — RevitMCP SHIM.  Stable thin loader.  Reflection-only
// ABI to Core (no shared interface types) — see CoreLoader.cs header.
//
// Owns the Revit lifecycle (IExternalApplication) + the UI-thread
// work pump (IExternalEventHandler).  Boots the hot-reloadable
// Core DLL via ArchHub.Shared.CoreLoader.  Updates to Core land
// without restarting Revit (net8 ALC unload).

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using Autodesk.Revit.UI;
using ArchHub.Shared;

namespace RevitMCP
{
    public class RevitMCPApp : IExternalApplication
    {
        private RevitEventHandler _handler;
        private ExternalEvent _externalEvent;
        private CoreLoader _loader;
        private string _revitVersion = "";
        private static bool _resolverInstalled;
        private static readonly object _resolverLock = new object();

        public Result OnStartup(UIControlledApplication app)
        {
            try
            {
                try { _revitVersion = app.ControlledApplication.VersionNumber ?? ""; }
                catch { _revitVersion = ""; }

                InstallAssemblyResolver();
                Log("Shim OnStartup begin; revit_version=" + _revitVersion);

                _handler = new RevitEventHandler();
                _externalEvent = ExternalEvent.Create(_handler);
                _handler.AttachEvent(_externalEvent);

                var addinDir = Path.GetDirectoryName(typeof(RevitMCPApp).Assembly.Location);
                var corePath = Path.Combine(addinDir, "RevitMCPCore.dll");
                if (!File.Exists(corePath))
                {
                    Log("RevitMCPCore.dll missing at " + corePath);
                    return Result.Failed;
                }
                _loader = new CoreLoader(Log);
                LoadCoreInto(corePath);
                Log("Shim OnStartup ok; port=" + _loader.BoundPort);
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                Log("RevitMCP shim startup failed: " + ex);
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication app)
        {
            try { _loader?.Unload(); } catch { }
            try { _externalEvent?.Dispose(); } catch { }
            _loader = null;
            return Result.Succeeded;
        }

        private void LoadCoreInto(string corePath)
        {
            var sha = CoreLoader.Sha256OfFile(corePath);
            var hostInfo = new Dictionary<string, string>
            {
                ["host_family"]  = "revit",
                ["host_version"] = _revitVersion,
                ["pid"]          = System.Diagnostics.Process.GetCurrentProcess().Id.ToString(),
                ["core_path"]    = corePath,
                ["core_sha"]     = sha,
            };
            // Reload trigger — Core stores this delegate so /reload can
            // ask the shim to swap to a new Core DLL.
            Action<string> reloadTrigger = (newPath) =>
            {
                try
                {
                    Log("Hot-reload triggered → " + newPath);
                    _loader.Unload();
                    LoadCoreInto(newPath);
                }
                catch (Exception ex) { Log("Reload failed: " + ex); }
            };

            // Submit-to-UI delegate — Core hands us a Func<object,string>;
            // we hand the live UIApplication on the UI thread.
            Func<Func<object, string>, Task<string>> submit = fn => _handler.SubmitAsync(fn);

            _loader.Load(corePath, submit, hostInfo, Log, reloadTrigger);
        }

        private static void InstallAssemblyResolver()
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
                var addinDir = Path.GetDirectoryName(typeof(RevitMCPApp).Assembly.Location);
                if (string.IsNullOrEmpty(addinDir)) return null;
                var candidate = Path.Combine(addinDir, requested.Name + ".dll");
                if (File.Exists(candidate)) return Assembly.LoadFrom(candidate);
                candidate = Path.Combine(addinDir, requested.Name + ".resources.dll");
                if (File.Exists(candidate)) return Assembly.LoadFrom(candidate);
            }
            catch (Exception ex)
            {
                try
                {
                    File.AppendAllText(
                        Path.Combine(Path.GetTempPath(), "RevitMCP.AssemblyResolve.log"),
                        DateTime.UtcNow.ToString("o") + "  " + args.Name + "  ERR: "
                            + ex.Message + "\n");
                }
                catch { }
            }
            return null;
        }

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
