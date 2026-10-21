// The one gate on swapping Revit's Core in a running session (/reload).
//
// A reload may load only the installed Core (RevitMCPCore.dll beside the shim,
// the path setup registered) and only when its SHA-256 equals the pin in the
// shipped, reviewed artifact manifest beside it (host-artifacts.json, written
// by installer/build_host_bridges.ps1, activation reviewed-authenticated-broker).
// Every DLL in that folder must be pinned there and match too: Core's
// dependencies are loaded with it. VerifyAndRead reads each file ONCE, hashes
// those bytes and returns them, so the loader loads exactly the bytes that were
// checked and never re-reads a path (shared/CoreLoader.cs). Any other path, a
// missing or unreviewed manifest, an unpinned or changed DLL refuses.
// Linked into both the shim (which performs the load) and Core (which answers
// /reload). Deliberately C# 5 and dependency-free: the shim carries no JSON library.

using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace ArchHub.Shared
{
    public static class ReviewedCore
    {
        public const string CoreFileName = "RevitMCPCore.dll";
        public const string ManifestFileName = "host-artifacts.json";
        public const string ShimFileName = "RevitMCP.dll";
        private const long MaxFile = 256L * 1024 * 1024;

        public static bool Verify(string candidatePath, string installedCorePath, out string reason)
        {
            return VerifyAndRead(candidatePath, installedCorePath, out reason) != null;
        }

        /// <summary>
        /// The verified closure keyed by assembly simple name (file name without
        /// .dll): the exact bytes that were hashed. Null, with the reason, on refusal.
        /// </summary>
        public static IDictionary<string, byte[]> VerifyAndRead(string candidatePath, string installedCorePath,
                                                                out string reason)
        {
            reason = null;
            if (string.IsNullOrEmpty(candidatePath) || string.IsNullOrEmpty(installedCorePath))
            {
                reason = "no installed Core path is known";
                return null;
            }
            string candidate, installed;
            try
            {
                candidate = Path.GetFullPath(candidatePath);
                installed = Path.GetFullPath(installedCorePath);
            }
            catch (Exception ex)
            {
                reason = "invalid path: " + ex.Message;
                return null;
            }
            if (!string.Equals(candidate, installed, StringComparison.OrdinalIgnoreCase)
                || !string.Equals(Path.GetFileName(installed), CoreFileName, StringComparison.OrdinalIgnoreCase))
            {
                reason = "only the installed reviewed Core may be loaded: " + installed;
                return null;
            }
            string directory = Path.GetDirectoryName(installed);
            var pins = PinnedFiles(directory, out reason);
            if (pins == null) return null;
            string[] present;
            try { present = Directory.GetFiles(directory, "*.dll"); }
            catch (Exception ex)
            {
                reason = "Core folder cannot be listed: " + ex.Message;
                return null;
            }
            foreach (var path in present)
            {
                if (!pins.ContainsKey(Path.GetFileName(path)))
                {
                    reason = "unpinned DLL beside Core: " + Path.GetFileName(path);
                    return null;
                }
            }
            var closure = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
            foreach (var pin in pins)
            {
                // The shim is already loaded and is not part of what a reload loads.
                if (!pin.Key.EndsWith(".dll", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(pin.Key, ShimFileName, StringComparison.OrdinalIgnoreCase)) continue;
                var path = Path.Combine(directory, pin.Key);
                byte[] bytes;
                try
                {
                    var info = new FileInfo(path);
                    if (!info.Exists || (info.Attributes & FileAttributes.ReparsePoint) != 0 || info.Length > MaxFile)
                    {
                        reason = pin.Key + " is missing, redirected or oversized";
                        return null;
                    }
                    bytes = File.ReadAllBytes(path);
                }
                catch (Exception ex)
                {
                    reason = pin.Key + " cannot be read: " + ex.Message;
                    return null;
                }
                if (!string.Equals(Sha256OfBytes(bytes), pin.Value, StringComparison.Ordinal))
                {
                    reason = string.Equals(pin.Key, CoreFileName, StringComparison.OrdinalIgnoreCase)
                        ? "Core SHA-256 differs from the reviewed pin"
                        : pin.Key + " differs from its reviewed pin";
                    return null;
                }
                closure[Path.GetFileNameWithoutExtension(pin.Key)] = bytes;
            }
            return closure;
        }

        /// <summary>The reviewed Core pin from the shipped manifest, or null with the reason.</summary>
        public static string PinnedSha256(string directory, out string reason)
        {
            var pins = PinnedFiles(directory, out reason);
            return pins == null ? null : pins[CoreFileName];
        }

        /// <summary>File name to pinned SHA-256 for this year's folder, from the reviewed manifest.</summary>
        private static IDictionary<string, string> PinnedFiles(string directory, out string reason)
        {
            reason = null;
            string text;
            try
            {
                var info = new FileInfo(Path.Combine(directory, ManifestFileName));
                if (!info.Exists || info.Length > 1024 * 1024)
                {
                    reason = "reviewed artifact manifest is missing or oversized";
                    return null;
                }
                if ((info.Attributes & FileAttributes.ReparsePoint) != 0)
                {
                    reason = "reviewed artifact manifest is redirected";
                    return null;
                }
                text = File.ReadAllText(info.FullName, Encoding.UTF8);
            }
            catch (Exception ex)
            {
                reason = "reviewed artifact manifest cannot be read: " + ex.Message;
                return null;
            }
            if (!Regex.IsMatch(text, "\"eligibility\"\\s*:\\s*\"reviewed-authenticated-broker\"")
                || !Regex.IsMatch(text, "\"review_sha256\"\\s*:\\s*\"[0-9a-f]{64}\""))
            {
                reason = "Core is not reviewed for activation";
                return null;
            }
            string year = Path.GetFileName(directory);
            var pins = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var rows = Regex.Matches(text, "\\{[^{}]*\"path\"\\s*:\\s*\"bridges/revit/([0-9]{4})/([^\"/\\\\]+)\"[^{}]*\\}");
            foreach (Match row in rows)
            {
                if (row.Groups[1].Value != year) continue;
                var name = row.Groups[2].Value;
                var pin = Regex.Match(row.Value, "\"sha256\"\\s*:\\s*\"([0-9a-f]{64})\"");
                if (!pin.Success || pins.ContainsKey(name))
                {
                    reason = "reviewed artifact manifest pins " + name + " ambiguously";
                    return null;
                }
                pins[name] = pin.Groups[1].Value;
            }
            if (!pins.ContainsKey(CoreFileName))
            {
                reason = "reviewed artifact manifest does not pin exactly one Core";
                return null;
            }
            return pins;
        }

        public static string Sha256OfFile(string path)
        {
            return Sha256OfBytes(File.ReadAllBytes(path));
        }

        public static string Sha256OfBytes(byte[] bytes)
        {
            using (var sha = SHA256.Create())
            {
                var digest = sha.ComputeHash(bytes);
                var hex = new StringBuilder(digest.Length * 2);
                foreach (var b in digest) hex.Append(b.ToString("x2"));
                return hex.ToString();
            }
        }
    }
}