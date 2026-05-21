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
        public string CompilerPath;   // which csc.exe was used (telemetry)
        public bool   CacheHit;       // true if we skipped the compile
    }

    /// <summary>
    /// Probes for csc.exe + compiles + caches + loads + invokes.
    /// Static methods only — no instance state beyond the cache index.
    /// Thread-safe under add-in concurrent /exec calls.
    /// </summary>
    public static class ScriptCompiler
    {
        // ─── csc probe ─────────────────────────────────────────────

        private static readonly object _probeLock = new object();
        private static string _probedCsc;
        private static bool   _probed;

        /// <summary>
        /// Returns the path of the csc.exe we'll use, or null if none
        /// found. Result cached for the life of the process.
        /// </summary>
        public static string ProbeCsc()
        {
            if (_probed) return _probedCsc;
            lock (_probeLock)
            {
                if (_probed) return _probedCsc;
                _probedCsc = _ProbeOnce();
                _probed = true;
                return _probedCsc;
            }
        }

        private static string _ProbeOnce()
        {
            // 1. Explicit override.
            var env = Environment.GetEnvironmentVariable("ARCHHUB_CSC_PATH");
            if (!string.IsNullOrWhiteSpace(env) && File.Exists(env)) return env;

            // 2. .NET Framework 4.0 csc (single-file Roslyn 1.x — still
            //    handles C# 7.3 with /langversion:7.3). Always present on
            //    any Windows with .NET 4.x installed.
            var sysRoot = Environment.GetFolderPath(Environment.SpecialFolder.System);
            var fxCsc = Path.Combine(sysRoot, "..", "Microsoft.NET",
                                     "Framework64", "v4.0.30319", "csc.exe");
            try { fxCsc = Path.GetFullPath(fxCsc); } catch { }
            if (File.Exists(fxCsc)) return fxCsc;

            // 3. VS BuildTools well-known locations — modern Roslyn 4.x.
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
                if (File.Exists(p)) return p;
            }

            // 4. .NET SDK csc.dll (less common — needs `dotnet exec`).
            //    Skipped here because spawning `dotnet exec csc.dll` adds
            //    JIT overhead; users who only have dotnet SDK can set
            //    ARCHHUB_CSC_PATH explicitly.
            return null;
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
            var csc = ProbeCsc();
            if (csc == null)
            {
                r.Status = "csc_missing";
                r.Error  = "csc.exe not found. Install .NET Framework 4 SDK or "
                         + "Visual Studio Build Tools, or set ARCHHUB_CSC_PATH. "
                         + "See https://aka.ms/vs/17/release/vs_BuildTools.exe";
                return r;
            }
            r.CompilerPath = csc;

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

                // Spawn csc.
                var args = new StringBuilder();
                args.Append("/nologo /target:library /platform:anycpu /optimize+ ");
                args.Append("/langversion:").Append(langVersion).Append(' ');
                args.Append("/out:\"").Append(dllPath).Append("\" ");
                foreach (var rf in references)
                    args.Append("/reference:\"").Append(rf).Append("\" ");
                args.Append("\"").Append(srcPath).Append("\"");

                var psi = new ProcessStartInfo
                {
                    FileName = csc,
                    Arguments = args.ToString(),
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError  = true,
                    CreateNoWindow = true,
                };
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

            // Load + invoke.
            try
            {
                var asm = Assembly.LoadFile(dllPath);
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
