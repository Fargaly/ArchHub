// AgDR-0025 — Subprocess csc.exe script compiler · shared across every
// .NET ArchHub connector (RevitMCP, AcadMCP, future hosts).
//
// Purpose: NEVER load Microsoft.CodeAnalysis* into the host AppDomain.
// The host (Revit, AutoCAD, etc.) shares its AppDomain with other
// add-ins (pyRevit, Speckle, …) that may have already pinned their
// own Roslyn version. In-process CSharpScript.RunAsync collides →
// FileLoadException. Subprocess csc.exe sidesteps the conflict
// entirely.
//
// Pipeline:
//   1. Hash user code + refs + langVer + tfm.
//   2. Look up in %TEMP%/archhub-csc-cache/<hash>.dll.
//   3. Cache miss: write source.cs to disk + spawn csc.exe to compile.
//   4. Assembly.LoadFile(dll); reflect-invoke the generated entry
//      point with the host's ScriptContext.
//   5. Return the script's `result` value (which the wrapper piped
//      back to `ctx.result`).
//
// Linked into each connector csproj via
//   <Compile Include="..\shared\ScriptCompiler.cs" Link="ScriptCompiler.cs"/>
//
// Per-connector glue (which references to add, which ScriptContext
// type to bind) lives in the connector's event handler.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace ArchHub.Shared
{
    /// <summary>
    /// Outcome of a Compile + Run pair. Status is one of:
    ///   "ok"             — script ran; Result holds the value.
    ///   "compile_error"  — csc emitted diagnostics; Error holds them.
    ///   "csc_missing"    — no csc.exe found on the machine.
    ///   "runtime_error"  — load or invoke threw; Error holds details.
    /// </summary>
    public class ScriptResult
    {
        public string Status;
        public object Result;
        public string Error;
        public string CompilerPath;   // which csc.exe / csc.dll was used (telemetry)
        public bool   CompilerNeedsDotnetExec;  // true if invocation needs `dotnet exec`
        public bool   CacheHit;       // true if we skipped the compile
    }

    /// <summary>
    /// Probes for csc.exe + compiles + caches + loads + invokes.
    /// Static methods only — no instance state beyond the cache index.
    /// Thread-safe under add-in concurrent /exec calls.
    /// </summary>
    public static class ScriptCompiler
    {
        // ─── csc probe (AgDR-0030) ─────────────────────────────────
        //
        // Probe order (Fork A1 — signed 2026-05-21):
        //   0. ARCHHUB_CSC_PATH env override.
        //   1. Bundled `%LOCALAPPDATA%\ArchHub\bin\csc\csc.exe`
        //      (Fork B3 — auto_build drops a pinned Roslyn here).
        //   2. VS BuildTools 2022 well-known paths.
        //   3. .NET SDK `csc.dll` invoked via `dotnet exec`.
        //   4. Framework64 `csc.exe` — GATED by /langversion:? probe.
        //      Caps at C# 5 on .NET 4.8.1 boxes → CS1617 on /langversion:7.3.
        //      Only accepted if it advertises ≥7.3.
        //
        // Every candidate (including bundled, BuildTools, SDK) is run
        // through `_AcceptsLangVersion73` so a future bad bundle can't
        // re-introduce the original bug.
        //
        // `ProbeCsc` is the legacy entrypoint that returns just the path
        // (for backward-compat with /ping JSON).  `ProbeCscDetailed`
        // returns the (path, dotnetExec) pair the CompileAndRun pipeline
        // needs to know whether to prepend `dotnet exec`.

        private static readonly object _probeLock = new object();
        private static string _probedCsc;
        private static bool   _probedDotnetExec;
        private static bool   _probed;

        /// <summary>Reset cached probe state — used by callers that
        /// know the environment changed (e.g. ARCHHUB_CSC_PATH set
        /// after start, bundled csc just downloaded).</summary>
        public static void ResetProbe()
        {
            lock (_probeLock) { _probed = false; _probedCsc = null;
                                 _probedDotnetExec = false; }
        }

        /// <summary>Returns the path of the csc we'll use, or null if
        /// none accepts /langversion:7.3.  Result cached.</summary>
        public static string ProbeCsc()
        {
            string p; bool _;
            (p, _) = ProbeCscDetailed();
            return p;
        }

        public static (string path, bool needsDotnetExec) ProbeCscDetailed()
        {
            if (_probed) return (_probedCsc, _probedDotnetExec);
            lock (_probeLock)
            {
                if (_probed) return (_probedCsc, _probedDotnetExec);
                var (p, dx) = _ProbeOnce();
                _probedCsc = p;
                _probedDotnetExec = dx;
                _probed = true;
                return (_probedCsc, _probedDotnetExec);
            }
        }

        private static (string path, bool needsDotnetExec) _ProbeOnce()
        {
            // 0. Explicit override — still gated by the langversion check.
            var env = Environment.GetEnvironmentVariable("ARCHHUB_CSC_PATH");
            if (!string.IsNullOrWhiteSpace(env) && File.Exists(env))
            {
                var dx = env.EndsWith(".dll", StringComparison.OrdinalIgnoreCase);
                if (_AcceptsLangVersion73(env, dx)) return (env, dx);
            }

            // 1. Bundled csc — `%LOCALAPPDATA%\ArchHub\bin\csc\csc.exe`.
            //    auto_build downloads a pinned Roslyn here on first run.
            var bundleDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ArchHub", "bin", "csc");
            var bundled = Path.Combine(bundleDir, "csc.exe");
            if (File.Exists(bundled) && _AcceptsLangVersion73(bundled, false))
                return (bundled, false);

            // 2. VS BuildTools 2022 well-known paths (modern Roslyn).
            var vsRoots = new[] {
                @"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools",
                @"C:\Program Files\Microsoft Visual Studio\2022\BuildTools",
                @"C:\Program Files\Microsoft Visual Studio\2022\Community",
                @"C:\Program Files\Microsoft Visual Studio\2022\Professional",
                @"C:\Program Files\Microsoft Visual Studio\2022\Enterprise",
            };
            foreach (var root in vsRoots)
            {
                var p = Path.Combine(root, "MSBuild", "Current", "Bin", "Roslyn", "csc.exe");
                if (File.Exists(p) && _AcceptsLangVersion73(p, false))
                    return (p, false);
            }

            // 3. .NET SDK csc.dll via `dotnet exec`.
            var sdk = _FindSdkCsc();
            if (sdk != null && _AcceptsLangVersion73(sdk, true))
                return (sdk, true);

            // 4. Framework64 csc — last resort, gated.  On .NET 4.8.1 +
            //    earlier this caps at C# 5; the gate rejects it.  Some
            //    boxes have Roslyn patched into this path so we still
            //    try it before giving up.
            var sysRoot = Environment.GetFolderPath(Environment.SpecialFolder.System);
            var fxCsc = Path.Combine(sysRoot, "..", "Microsoft.NET",
                                     "Framework64", "v4.0.30319", "csc.exe");
            try { fxCsc = Path.GetFullPath(fxCsc); } catch { }
            if (File.Exists(fxCsc) && _AcceptsLangVersion73(fxCsc, false))
                return (fxCsc, false);

            return (null, false);
        }

        /// <summary>Run `csc /langversion:?` (or `dotnet exec csc.dll
        /// /langversion:?`) and decide if it supports C# 7.3+.  The
        /// AgDR-0025 wrapper compiles with /langversion:7.3 — anything
        /// that caps at C# 5 fails with CS1617.  This gate prevents
        /// that case from ever being picked.</summary>
        private static bool _AcceptsLangVersion73(string cscPath, bool dotnetExec)
        {
            try
            {
                ProcessStartInfo psi;
                if (dotnetExec)
                {
                    psi = new ProcessStartInfo
                    {
                        FileName = "dotnet",
                        Arguments = "exec \"" + cscPath + "\" /langversion:?",
                    };
                }
                else
                {
                    psi = new ProcessStartInfo
                    {
                        FileName = cscPath,
                        Arguments = "/langversion:?",
                    };
                }
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError  = true;
                psi.CreateNoWindow = true;

                using (var p = Process.Start(psi))
                {
                    var stdout = p.StandardOutput.ReadToEnd();
                    var stderr = p.StandardError.ReadToEnd();
                    if (!p.WaitForExit(5000))
                    {
                        try { p.Kill(); } catch { }
                        return false;
                    }
                    var all = (stdout + "\n" + stderr).ToLowerInvariant();
                    // Reject the .NET 4.8.1 single-file csc that caps at C# 5.
                    if (all.Contains("only supports language versions up to c# 5")
                     || all.Contains("up to c# 5")
                     || all.Contains("up to c#5"))
                        return false;
                    // Accept if it advertises 7.3 / 8+ / latest.
                    return all.Contains("7.3")
                        || all.Contains(" 8.0") || all.Contains(" 9.0")
                        || all.Contains(" 10.0") || all.Contains(" 11.0")
                        || all.Contains(" 12.0") || all.Contains("latest");
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>Locate the highest-versioned .NET SDK's csc.dll, or
        /// null if no SDK is installed.</summary>
        private static string _FindSdkCsc()
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "dotnet",
                    Arguments = "--list-sdks",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError  = true,
                    CreateNoWindow = true,
                };
                string stdout;
                using (var p = Process.Start(psi))
                {
                    stdout = p.StandardOutput.ReadToEnd();
                    if (!p.WaitForExit(5000)) { try { p.Kill(); } catch { } return null; }
                }
                // Lines look like:  "8.0.405 [C:\Program Files\dotnet\sdk]"
                string bestPath = null;
                Version bestVer = null;
                foreach (var raw in stdout.Split('\n'))
                {
                    var line = raw.Trim();
                    if (line.Length == 0) continue;
                    var br = line.IndexOf('[');
                    if (br < 0) continue;
                    var verStr = line.Substring(0, br).Trim();
                    var pathStr = line.Substring(br + 1).TrimEnd(']', ' ', '\r');
                    // SDK version may have a "-rc.1" pre-release suffix.
                    var verCore = verStr.Split('-')[0];
                    Version v;
                    if (!Version.TryParse(verCore, out v)) continue;
                    if (bestVer == null || v > bestVer)
                    {
                        bestVer = v;
                        bestPath = Path.Combine(pathStr, verStr, "Roslyn", "bincore", "csc.dll");
                    }
                }
                return bestPath != null && File.Exists(bestPath) ? bestPath : null;
            }
            catch { return null; }
        }

        // ─── cache ────────────────────────────────────────────────

        private static readonly object _cacheLock = new object();
        private static string _cacheRoot;

        private static string CacheRoot()
        {
            if (_cacheRoot != null) return _cacheRoot;
            lock (_cacheLock)
            {
                if (_cacheRoot != null) return _cacheRoot;
                var root = Path.Combine(Path.GetTempPath(), "archhub-csc-cache");
                try { Directory.CreateDirectory(root); } catch { }
                _PruneCache(root);
                _cacheRoot = root;
                return root;
            }
        }

        /// <summary>Delete entries older than 7 days. Best-effort.</summary>
        private static void _PruneCache(string root)
        {
            try
            {
                var cutoff = DateTime.UtcNow.AddDays(-7);
                foreach (var f in Directory.EnumerateFiles(root, "*.*"))
                {
                    try { if (File.GetLastWriteTimeUtc(f) < cutoff) File.Delete(f); }
                    catch { }
                }
            }
            catch { }
        }

        private static string Hash(string source, IList<string> refs,
                                   string langVersion, string tfm)
        {
            var sb = new StringBuilder(source.Length + 256);
            sb.Append(source).Append("");
            foreach (var r in refs.OrderBy(x => x, StringComparer.Ordinal))
                sb.Append(r).Append("");
            sb.Append(langVersion).Append("").Append(tfm);
            using (var sha = SHA256.Create())
            {
                var b = sha.ComputeHash(Encoding.UTF8.GetBytes(sb.ToString()));
                var hex = new StringBuilder(b.Length * 2);
                foreach (var by in b) hex.Append(by.ToString("x2"));
                return hex.ToString();
            }
        }

        // ─── wrapping ─────────────────────────────────────────────

        /// <summary>
        /// Wrap the user's script in a generated entry class so csc can
        /// compile it as a real assembly. The wrapper binds `UIApp`,
        /// `UIDoc`, `Doc`, and `result` as locals (mirroring the
        /// CSharpScript globals contract), then pipes `result` to
        /// `ctx.result` after the body.
        /// </summary>
        public static string WrapSource(string userCode,
                                        string scriptContextFullName,
                                        IEnumerable<string> usings,
                                        string genNamespace)
        {
            var sb = new StringBuilder();
            sb.AppendLine("// AUTO-GENERATED by ArchHub.Shared.ScriptCompiler");
            sb.AppendLine("namespace " + genNamespace + " {");
            foreach (var u in usings) sb.Append("  using ").Append(u).AppendLine(";");
            sb.AppendLine("  public static class Entry {");
            sb.Append("    public static object Run(").Append(scriptContextFullName)
              .AppendLine(" ctx) {");
            sb.AppendLine("      var UIApp = ctx.UIApp;");
            sb.AppendLine("      var UIDoc = ctx.UIDoc;");
            sb.AppendLine("      var Doc   = ctx.Doc;");
            sb.AppendLine("      object result = null;");
            sb.AppendLine("      // --- user code start ---");
            sb.AppendLine(userCode);
            sb.AppendLine("      // --- user code end ---");
            sb.AppendLine("      ctx.result = result;");
            sb.AppendLine("      return result;");
            sb.AppendLine("    }");
            sb.AppendLine("  }");
            sb.AppendLine("}");
            return sb.ToString();
        }

        // ─── compile + run ────────────────────────────────────────

        /// <summary>
        /// Compile (or fetch from cache) and run user code against the
        /// given ScriptContext. References list = full paths to API
        /// DLLs (RevitAPI.dll, RevitAPIUI.dll, the host assembly, etc.)
        /// plus mscorlib / System / System.Core / System.Linq.
        /// </summary>
        public static ScriptResult CompileAndRun(
            string userCode,
            object ctx,
            string scriptContextFullName,
            IList<string> references,
            IEnumerable<string> usings,
            string langVersion = "7.3")
        {
            var r = new ScriptResult();
            // AgDR-0030 — detailed probe returns whether we need
            // `dotnet exec csc.dll` instead of running csc.exe directly.
            var (csc, needsDotnetExec) = ProbeCscDetailed();
            if (csc == null)
            {
                r.Status = "csc_missing";
                r.Error  = "No C# compiler (csc) supporting C# 7.3+ found.  "
                         + "Install the .NET 8 SDK (https://dot.net/8) or "
                         + "Visual Studio Build Tools "
                         + "(https://aka.ms/vs/17/release/vs_BuildTools.exe).  "
                         + "ArchHub auto-bundles a pinned csc on first connector "
                         + "build at %LOCALAPPDATA%\\ArchHub\\bin\\csc\\csc.exe; "
                         + "delete that file or set ARCHHUB_CSC_PATH to override.";
                return r;
            }
            r.CompilerPath = csc;
            r.CompilerNeedsDotnetExec = needsDotnetExec;

            // Hash + cache lookup.
            var tfm = "net48";  // wrapper is langver 7.3 / net48 compat
            var hash = Hash(userCode + "||" + scriptContextFullName,
                            references, langVersion, tfm);
            var ns = "ArchHub.Generated_" + hash.Substring(0, 16);
            var srcPath = Path.Combine(CacheRoot(), hash + ".cs");
            var dllPath = Path.Combine(CacheRoot(), hash + ".dll");
            r.CacheHit = File.Exists(dllPath);

            if (!r.CacheHit)
            {
                var wrapped = WrapSource(userCode, scriptContextFullName,
                                         usings, ns);
                try { File.WriteAllText(srcPath, wrapped, Encoding.UTF8); }
                catch (Exception ex)
                {
                    r.Status = "runtime_error";
                    r.Error  = "Cannot write source: " + ex.Message;
                    return r;
                }

                // Spawn csc — direct csc.exe, or `dotnet exec csc.dll`
                // when ProbeCscDetailed picked an SDK Roslyn (AgDR-0030
                // Fork A1 step 3).
                //
                // AgDR-0031 — all options + every /reference: go into a csc
                // response file (`@<path>`).  AppDomain.GetAssemblies() can
                // hand us hundreds of refs which blow past Windows' 32 K
                // command-line limit when expanded inline.  csc reads the
                // response file fine — same effect, no length cap.
                var rspBody = new StringBuilder();
                rspBody.Append("/nologo /target:library /platform:anycpu /optimize+ ");
                rspBody.Append("/langversion:").Append(langVersion).Append(' ');
                rspBody.Append("/out:\"").Append(dllPath).Append("\"\r\n");
                foreach (var rf in references)
                    rspBody.Append("/reference:\"").Append(rf).Append("\"\r\n");
                rspBody.Append("\"").Append(srcPath).Append("\"\r\n");
                var rspPath = Path.Combine(CacheRoot(), hash + ".rsp");
                try { File.WriteAllText(rspPath, rspBody.ToString(), Encoding.UTF8); }
                catch (Exception ex)
                {
                    r.Status = "runtime_error";
                    r.Error  = "Cannot write response file: " + ex.Message;
                    return r;
                }

                ProcessStartInfo psi;
                if (needsDotnetExec)
                {
                    psi = new ProcessStartInfo
                    {
                        FileName = "dotnet",
                        Arguments = "exec \"" + csc + "\" @\"" + rspPath + "\"",
                    };
                }
                else
                {
                    psi = new ProcessStartInfo
                    {
                        FileName = csc,
                        Arguments = "@\"" + rspPath + "\"",
                    };
                }
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError  = true;
                psi.CreateNoWindow = true;
                string stdout = "", stderr = "";
                int code = -1;
                try
                {
                    using (var p = Process.Start(psi))
                    {
                        stdout = p.StandardOutput.ReadToEnd();
                        stderr = p.StandardError.ReadToEnd();
                        if (!p.WaitForExit(60_000))
                        {
                            try { p.Kill(); } catch { }
                            r.Status = "compile_error";
                            r.Error  = "csc.exe timed out after 60s";
                            return r;
                        }
                        code = p.ExitCode;
                    }
                }
                catch (Exception ex)
                {
                    r.Status = "compile_error";
                    r.Error  = "csc.exe failed to start: " + ex.Message;
                    return r;
                }
                if (code != 0 || !File.Exists(dllPath))
                {
                    r.Status = "compile_error";
                    r.Error  = (stdout + "\n" + stderr).Trim();
                    // Don't keep a half-baked output around.
                    try { if (File.Exists(dllPath)) File.Delete(dllPath); } catch { }
                    return r;
                }
            }

            // Load + invoke.  Use Core's ALC so the generated DLL's
            // /reference: to RevitMCPCore-hotfix* resolves against the
            // SAME assembly identity Core lives under.  Default ALC
            // can't see types in a collectible ALC → FileLoadException
            // 0x80131515 ("Operation is not supported").
            try
            {
#if NET8_0_OR_GREATER
                System.Reflection.Assembly asm;
                var coreAlc = System.Runtime.Loader.AssemblyLoadContext
                                  .GetLoadContext(ctx.GetType().Assembly);
                if (coreAlc != null) asm = coreAlc.LoadFromAssemblyPath(dllPath);
                else                  asm = Assembly.LoadFile(dllPath);
#else
                var asm = Assembly.LoadFile(dllPath);
#endif
                var t = asm.GetType(ns + ".Entry", throwOnError: true);
                var m = t.GetMethod("Run", BindingFlags.Public | BindingFlags.Static);
                if (m == null)
                {
                    r.Status = "runtime_error";
                    r.Error  = "Generated assembly missing Entry.Run";
                    return r;
                }
                var ret = m.Invoke(null, new object[] { ctx });
                r.Status = "ok";
                r.Result = ret;
                return r;
            }
            catch (TargetInvocationException tex)
            {
                r.Status = "runtime_error";
                var inner = tex.InnerException;
                r.Error  = (inner != null ? inner.GetType().Name + ": " + inner.Message : tex.Message);
                return r;
            }
            catch (Exception ex)
            {
                r.Status = "runtime_error";
                r.Error  = ex.GetType().Name + ": " + ex.Message;
                return r;
            }
        }
    }
}
