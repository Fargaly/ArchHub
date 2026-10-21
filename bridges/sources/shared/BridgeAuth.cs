// The caller check every ArchHub .NET host bridge runs before it answers.
//
// The Revit and AutoCAD bridges compile and run C# posted to a localhost
// port. Before this check any local process -- and any web page that could
// reach 127.0.0.1 -- could post code into an open model. Now:
//
//   * a request that carries a browser header (Origin, Sec-Fetch-Mode) or a
//     Host that is not a loopback name is refused with 403, and no CORS header
//     is ever sent, so a page cannot read an answer or pass a preflight;
//   * every route except /ping must be signed: X-ArchHub-Bridge-Signature is
//     hex HMAC-SHA256(secret, "METHOD|target|time|nonce|sha256hex(body)"),
//     where target is the raw path and query as sent, time is unix seconds
//     within SkewSeconds of this clock, and the 32-hex nonce has not been seen
//     before (401). The secret never crosses the wire, so a process squatting
//     a bridge port learns one used-up signature, not the key;
//   * with no secret provisioned the bridge refuses everything but /ping (503).
//
// The secret is created by the ArchHub application (nodelang/host_bridge_auth.py,
// which also signs every request) and kept in its credential store, which on
// Windows is the Credential Locker through keyring. It is read here the way
// keyring wrote it: target "ArchHub" when its user is archhub-host-bridge,
// otherwise the compound target "archhub-host-bridge@ArchHub"; the blob is
// UTF-16LE. C# 7.3 only: this file builds for net47/net48.

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace ArchHub.Shared
{
    public static class BridgeAuth
    {
        public const string TimeHeader = "X-ArchHub-Bridge-Time";
        public const string NonceHeader = "X-ArchHub-Bridge-Nonce";
        public const string SignatureHeader = "X-ArchHub-Bridge-Signature";
        public const string SecretService = "ArchHub";
        public const string SecretUser = "archhub-host-bridge";
        public const int SkewSeconds = 60;
        public const int MaxBodyBytes = 16 * 1024 * 1024;
        private const int MinimumSecretLength = 32;
        private const int MaxRememberedNonces = 100000;

        // Tests and nothing else replace the reader or the clock; production reads
        // the Credential Locker on every request so a rotated secret takes effect.
        public static Func<string> SecretReader = () => ReadSecret(SecretService, SecretUser);
        public static Func<long> Clock = () => DateTimeOffset.UtcNow.ToUnixTimeSeconds();

        private static readonly object NonceLock = new object();
        private static readonly Dictionary<string, long> SeenNonces = new Dictionary<string, long>();

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct Credential
        {
            public uint Flags;
            public uint Type;
            public string TargetName;
            public string Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public uint CredentialBlobSize;
            public IntPtr CredentialBlob;
            public uint Persist;
            public uint AttributeCount;
            public IntPtr Attributes;
            public string TargetAlias;
            public string UserName;
        }

        [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);

        [DllImport("advapi32.dll", EntryPoint = "CredFree")]
        private static extern void CredFree(IntPtr credential);

        private static bool TryRead(string target, out string user, out string secret)
        {
            user = null;
            secret = null;
            IntPtr found;
            if (!CredRead(target, 1 /* CRED_TYPE_GENERIC */, 0, out found) || found == IntPtr.Zero)
                return false;
            try
            {
                var cred = (Credential)Marshal.PtrToStructure(found, typeof(Credential));
                var size = (int)cred.CredentialBlobSize;
                if (cred.CredentialBlob == IntPtr.Zero || size <= 0 || size > 4096 || size % 2 != 0)
                    return false;
                var blob = new byte[size];
                Marshal.Copy(cred.CredentialBlob, blob, 0, size);
                user = cred.UserName ?? "";
                secret = Encoding.Unicode.GetString(blob);
                return true;
            }
            catch
            {
                return false;
            }
            finally
            {
                CredFree(found);
            }
        }

        /// <summary>The bridge secret as keyring stored it, or null.</summary>
        public static string ReadSecret(string service, string user)
        {
            string foundUser, secret;
            bool found = TryRead(service, out foundUser, out secret);
            if (!found || foundUser != user)
                found = TryRead(user + "@" + service, out foundUser, out secret);
            if (!found || foundUser != user || secret == null || secret.Length < MinimumSecretLength)
                return null;
            return secret;
        }

        /// <summary>Equal strings, compared without an early exit on content.</summary>
        public static bool FixedTimeEquals(string given, string expected)
        {
            var a = Encoding.UTF8.GetBytes(given ?? "");
            var b = Encoding.UTF8.GetBytes(expected ?? "");
            int diff = a.Length ^ b.Length;
            for (int i = 0; i < b.Length; i++)
                diff |= (i < a.Length ? a[i] : 0) ^ b[i];
            return diff == 0 && b.Length > 0;
        }

        private static string Hex(byte[] bytes)
        {
            var sb = new StringBuilder(bytes.Length * 2);
            foreach (var b in bytes) sb.Append(b.ToString("x2"));
            return sb.ToString();
        }

        /// <summary>The hex HMAC both sides compute for one request.</summary>
        public static string Sign(string secret, string method, string target, string time, string nonce, byte[] body)
        {
            string bodyHash;
            using (var sha = SHA256.Create()) bodyHash = Hex(sha.ComputeHash(body ?? new byte[0]));
            var text = (method ?? "").ToUpperInvariant() + "|" + target + "|" + time + "|" + nonce + "|" + bodyHash;
            using (var mac = new HMACSHA256(Encoding.UTF8.GetBytes(secret)))
                return Hex(mac.ComputeHash(Encoding.UTF8.GetBytes(text)));
        }

        public static bool LoopbackHost(string host)
        {
            var value = (host ?? "").Trim().ToLowerInvariant();
            if (value.StartsWith("["))
                value = value.Substring(0, value.IndexOf(']') + 1);
            else if (value.Contains(":"))
                value = value.Substring(0, value.LastIndexOf(':'));
            return value == "127.0.0.1" || value == "localhost" || value == "[::1]";
        }

        private static bool LowerHex32(string nonce)
        {
            if (nonce == null || nonce.Length != 32) return false;
            foreach (var c in nonce)
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
            return true;
        }

        /// <summary>
        /// True when the request must be refused; status and reason say why.
        /// requireSignature is false only for the identity route (/ping).
        /// </summary>
        public static bool Refuse(string method, string target, string host, string origin, string fetchMode,
                                  string time, string nonce, string signature, byte[] body,
                                  bool requireSignature, out int status, out string reason)
        {
            status = 200;
            reason = null;
            if (origin != null || fetchMode != null)
            {
                status = 403;
                reason = "browser requests are refused; ArchHub calls this bridge directly";
                return true;
            }
            if (!LoopbackHost(host))
            {
                status = 403;
                reason = "only a loopback host name is served";
                return true;
            }
            if (!requireSignature)
                return false;
            string secret;
            try { secret = SecretReader(); }
            catch { secret = null; }
            if (string.IsNullOrEmpty(secret))
            {
                status = 503;
                reason = "ArchHub has not provisioned this bridge's caller secret; open ArchHub once";
                return true;
            }
            status = 401;
            if (!FixedTimeEquals(signature, Sign(secret, method, target, time ?? "", nonce ?? "", body)))
            {
                reason = "caller is not authenticated";
                return true;
            }
            long stamp;
            long now = Clock();
            if (!long.TryParse(time, System.Globalization.NumberStyles.None,
                               System.Globalization.CultureInfo.InvariantCulture, out stamp)
                || Math.Abs(now - stamp) > SkewSeconds)
            {
                reason = "signature time is outside the allowed window";
                return true;
            }
            if (!LowerHex32(nonce))
            {
                reason = "signature nonce is malformed";
                return true;
            }
            lock (NonceLock)
            {
                var expired = new List<string>();
                foreach (var seen in SeenNonces)
                    if (now - seen.Value > 2 * SkewSeconds) expired.Add(seen.Key);
                foreach (var key in expired) SeenNonces.Remove(key);
                if (SeenNonces.ContainsKey(nonce))
                {
                    reason = "signature was already used";
                    return true;
                }
                if (SeenNonces.Count >= MaxRememberedNonces)
                {
                    status = 503;
                    reason = "too many recent requests; retry shortly";
                    return true;
                }
                SeenNonces[nonce] = now;
            }
            status = 200;
            return false;
        }

        /// <summary>The request body, bounded; null when it is larger than MaxBodyBytes.</summary>
        public static byte[] ReadBody(HttpListenerRequest request)
        {
            if (!request.HasEntityBody) return new byte[0];
            if (request.ContentLength64 > MaxBodyBytes) return null;
            using (var copy = new MemoryStream())
            {
                var buffer = new byte[81920];
                int read;
                while ((read = request.InputStream.Read(buffer, 0, buffer.Length)) > 0)
                {
                    copy.Write(buffer, 0, read);
                    if (copy.Length > MaxBodyBytes) return null;
                }
                return copy.ToArray();
            }
        }

        public static bool Refuse(HttpListenerRequest request, byte[] body, bool requireSignature,
                                  out int status, out string reason)
        {
            return Refuse(request.HttpMethod, request.RawUrl, request.Headers["Host"],
                          request.Headers["Origin"], request.Headers["Sec-Fetch-Mode"],
                          request.Headers[TimeHeader], request.Headers[NonceHeader],
                          request.Headers[SignatureHeader], body, requireSignature, out status, out reason);
        }
    }
}
