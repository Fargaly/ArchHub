// The one gate on swapping Revit's Core in a running session (/reload).
//
// A reload may load only the installed Core (RevitMCPCore.dll beside the shim,
// the path setup registered) and only when its SHA-256 equals the pin in the
// shipped, reviewed artifact manifest beside it (host-artifacts.json, written
// by installer/build_host_bridges.ps1, activation reviewed-authenticated-broker).
// Any other path, a missing or unreviewed manifest, or a changed file refuses.
// Linked into both the shim (which performs the load) and Core (which answers
// /reload), so neither side alone can be talked into loading other bytes.
// Deliberately C# 5 and dependency-free: the shim carries no JSON library.

using System;
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

        public static bool Verify(string candidatePath, string installedCorePath, out string reason)
        {
            reason = null;
            if (string.IsNullOrEmpty(candidatePath) || string.IsNullOrEmpty(installedCorePath))
            {
                reason = "no installed Core path is known";
                return false;
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
                return false;
            }
            if (!string.Equals(candidate, installed, StringComparison.OrdinalIgnoreCase)
                || !string.Equals(Path.GetFileName(installed), CoreFileName, StringComparison.OrdinalIgnoreCase))
            {
                reason = "only the installed reviewed Core may be loaded: " + installed;
                return false;
            }
            string pinned = PinnedSha256(Path.GetDirectoryName(installed), out reason);
            if (pinned == null) return false;
            string actual;
            try { actual = Sha256OfFile(installed); }
            catch (Exception ex)
            {
                reason = "Core cannot be read: " + ex.Message;
                return false;
            }
            if (!string.Equals(actual, pinned, StringComparison.Ordinal))
            {
                reason = "Core SHA-256 differs from the reviewed pin";
                return false;
            }
            return true;
        }

        /// <summary>The reviewed Core pin from the shipped manifest, or null with the reason.</summary>
        public static string PinnedSha256(string directory, out string reason)
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
            var rows = Regex.Matches(text,
                "\\{[^{}]*\"path\"\\s*:\\s*\"bridges/revit/[0-9]{4}/RevitMCPCore\\.dll\"[^{}]*\\}");
            if (rows.Count != 1)
            {
                reason = "reviewed artifact manifest does not pin exactly one Core";
                return null;
            }
            var pin = Regex.Match(rows[0].Value, "\"sha256\"\\s*:\\s*\"([0-9a-f]{64})\"");
            if (!pin.Success)
            {
                reason = "reviewed artifact manifest carries no Core SHA-256";
                return null;
            }
            return pin.Groups[1].Value;
        }

        public static string Sha256OfFile(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                var bytes = sha.ComputeHash(stream);
                var hex = new StringBuilder(bytes.Length * 2);
                foreach (var b in bytes) hex.Append(b.ToString("x2"));
                return hex.ToString();
            }
        }
    }
}