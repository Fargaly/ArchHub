// AgDR-0027 — hot-reload Core loader · reflection-only ABI.
//
// IMPORTANT — no shared interface types are exchanged between shim
// and Core.  Earlier draft used ICoreEntryPoint compiled into BOTH
// assemblies via <Link>, which created TWO distinct CLR types with
// the same name → IsAssignableFrom returned false → Core was never
// discovered → shim silently failed → listener never bound.  Fix:
// bind by name + invoke through reflection, using only BCL types
// (Func, Action, IDictionary) for parameters.
//
// Convention every Core DLL must follow:
//   * Public class named `*.CoreEntry` (exactly one in the assembly).
//   * Method:  int Start(
//                Func<Func<object,string>, Task<string>> submit,
//                Action<string> log,
//                IDictionary<string,string> hostInfo)
//   * Method:  void Stop()
//   * Property (settable): Action<string> ReloadTriggerForShim
//
// All three of those parameter/return types are BCL — single
// runtime identity across all assemblies.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;

#if NET8_0_OR_GREATER
using System.Runtime.Loader;
#endif

namespace ArchHub.Shared
{
    public class CoreLoader
    {
        public string CurrentCorePath { get; private set; }
        public string CurrentCoreSha  { get; private set; }
        public int    BoundPort       { get; private set; }
        public bool   CanHotReload    { get; }

#if NET8_0_OR_GREATER
        private AssemblyLoadContext _alc;
#endif
        private object _coreInstance;

        /// <summary>
        /// The verified dependency bytes of the Core loaded last from a reviewed
        /// closure (null otherwise). The shim's AppDomain resolver serves these
        /// before any path, so a dependency is loaded from the bytes that were
        /// hashed (shared/ReviewedCore.cs), never re-read from disk.
        /// </summary>
        public static IDictionary<string, byte[]> VerifiedDependencies { get; private set; }
        private MethodInfo _stopMethod;
        private Action<string> _log;

        public CoreLoader(Action<string> log)
        {
            _log = log ?? (s => { });
#if NET8_0_OR_GREATER
            CanHotReload = true;
#else
            CanHotReload = false;
#endif
        }

        /// <summary>
        /// Load Core DLL, locate CoreEntry, invoke Start.  Returns the
        /// bound HTTP port.  Throws on any failure (caller logs).
        /// </summary>
        /// <param name="submit">
        ///   Shim's UI-thread work pump.  Core calls
        ///   submit(fn) → Task&lt;string&gt; ; fn receives the live host
        ///   handle (UIApplication for Revit) on the UI thread.
        /// </param>
        /// <param name="verified">
        ///   From ReviewedCore.VerifyAndRead: the exact bytes that were hashed,
        ///   keyed by assembly simple name. When given (every /reload), Core and
        ///   its dependencies are loaded from these bytes, never from a path.
        /// </param>
        public int Load(string corePath,
                        Func<Func<object, string>, Task<string>> submit,
                        IDictionary<string, string> hostInfo,
                        Action<string> coreLog,
                        Action<string> reloadTrigger,
                        IDictionary<string, byte[]> verified = null)
        {
            byte[] coreBytes = null;
            if (verified != null
                && !verified.TryGetValue(Path.GetFileNameWithoutExtension(corePath), out coreBytes))
                throw new InvalidOperationException("Verified closure does not contain Core: " + corePath);
            if (verified == null && !File.Exists(corePath))
                throw new FileNotFoundException("Core DLL missing", corePath);

            // Stop + unload any in-flight Core first.
            UnloadInternal();
            VerifiedDependencies = verified;

            Assembly asm;
#if NET8_0_OR_GREATER
            _alc = new AssemblyLoadContext(
                "ArchHubCore-" + Guid.NewGuid().ToString("N"),
                isCollectible: true);
            _alc.Resolving += (ctx, name) => AlcResolving(ctx, name, corePath, verified);
            asm = coreBytes != null
                ? _alc.LoadFromStream(new MemoryStream(coreBytes))
                : _alc.LoadFromAssemblyPath(corePath);
#else
            asm = coreBytes != null ? Assembly.Load(coreBytes) : Assembly.LoadFrom(corePath);
#endif

            // Find the *.CoreEntry type by NAME (not by interface — see
            // header comment).  There must be exactly one such type.
            var candidates = asm.GetTypes()
                .Where(t => t.IsClass && !t.IsAbstract
                            && t.Name == "CoreEntry"
                            && t.GetMethod("Start") != null
                            && t.GetMethod("Stop") != null)
                .ToList();
            if (candidates.Count == 0)
                throw new InvalidOperationException(
                    "No `CoreEntry` class with Start/Stop in " + corePath);
            if (candidates.Count > 1)
                throw new InvalidOperationException(
                    "Multiple `CoreEntry` classes in " + corePath);
            var type = candidates[0];

            _coreInstance = Activator.CreateInstance(type);

            // Wire the reload trigger BEFORE Start, so /reload calls
            // arriving during Start return a valid trigger.
            var trigProp = type.GetProperty("ReloadTriggerForShim");
            if (trigProp != null && reloadTrigger != null)
                trigProp.SetValue(_coreInstance, reloadTrigger);

            var startMethod = type.GetMethod("Start");
            if (startMethod == null)
                throw new InvalidOperationException(
                    "CoreEntry missing Start method");
            _stopMethod = type.GetMethod("Stop");

            object portObj;
            try
            {
                portObj = startMethod.Invoke(_coreInstance,
                    new object[] { submit, coreLog ?? _log, hostInfo });
            }
            catch (TargetInvocationException tex)
            {
                throw tex.InnerException ?? tex;
            }
            BoundPort = portObj is int i ? i : 0;
            CurrentCorePath = corePath;
            CurrentCoreSha  = hostInfo.TryGetValue("core_sha", out var s) ? s : "";
            _log("Core loaded: " + corePath + " on port " + BoundPort);
            return BoundPort;
        }

#if NET8_0_OR_GREATER
        /// <summary>
        /// Probe Core's sibling directory for transitive deps.  Shared
        /// types are no longer routed here — there ARE no shared types
        /// (everything goes through delegates + BCL types).
        /// </summary>
        private Assembly AlcResolving(AssemblyLoadContext ctx,
                                      AssemblyName name, string corePath,
                                      IDictionary<string, byte[]> verified)
        {
            try
            {
                // A reviewed reload: only the hashed bytes, never the folder.
                if (verified != null)
                {
                    return verified.TryGetValue(name.Name, out var bytes)
                        ? ctx.LoadFromStream(new MemoryStream(bytes))
                        : null;
                }
                var dir = Path.GetDirectoryName(corePath);
                if (string.IsNullOrEmpty(dir)) return null;
                var candidate = Path.Combine(dir, name.Name + ".dll");
                if (File.Exists(candidate))
                    return ctx.LoadFromAssemblyPath(candidate);
            }
            catch { }
            return null;
        }
#endif

        public void Unload() { UnloadInternal(); }

        private void UnloadInternal()
        {
            if (_coreInstance != null && _stopMethod != null)
            {
                try { _stopMethod.Invoke(_coreInstance, null); }
                catch (Exception ex) { _log("Core.Stop ex: " + ex.Message); }
            }
            _coreInstance = null;
            _stopMethod   = null;
#if NET8_0_OR_GREATER
            if (_alc != null)
            {
                try { _alc.Unload(); }
                catch (Exception ex) { _log("ALC.Unload ex: " + ex.Message); }
                _alc = null;
                GC.Collect();
                GC.WaitForPendingFinalizers();
            }
#endif
        }

        public static string Sha256OfFile(string path)
        {
            using (var s = File.OpenRead(path))
            using (var sha = System.Security.Cryptography.SHA256.Create())
            {
                var b = sha.ComputeHash(s);
                var hex = new System.Text.StringBuilder(b.Length * 2);
                foreach (var by in b) hex.Append(by.ToString("x2"));
                return hex.ToString();
            }
        }
    }
}
