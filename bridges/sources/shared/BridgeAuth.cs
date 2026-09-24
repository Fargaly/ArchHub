// The caller check every ArchHub .NET host bridge runs before it answers.
//
// The Revit and AutoCAD bridges compile and run C# posted to a localhost
// port. Before this check any local process -- and any web page that could
// reach 127.0.0.1 -- could post code into an open model. Now:
//
//   * a request that carries a browser header (Origin, Sec-Fetch-Mode) is
//     refused with 403 and no CORS header is ever sent, so a page cannot read
//     an answer or pass a preflight;
//   * every route except /ping needs the header X-ArchHub-Bridge-Token equal
//     to this install's bridge secret, compared in constant time (401);
//   * with no secret provisioned the bridge refuses everything but /ping (503).
//
// The secret is created by the ArchHub application (nodelang/host_bridge_auth.py)
// and kept in its credential store, which on Windows is the Credential Locker
// through keyring. It is read here the way keyring wrote it: target "ArchHub"
// when its user is archhub-host-bridge, otherwise the compound target
// "archhub-host-bridge@ArchHub"; the blob is UTF-16LE. Nothing is written to a
// file a web page could fetch. C# 7.3 only: this file builds for net47/net48.

using System;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;

namespace ArchHub.Shared
{
    public static class BridgeAuth
    {
        public const string TokenHeader = "X-ArchHub-Bridge-Token";
        public const string SecretService = "ArchHub";
        public const string SecretUser = "archhub-host-bridge";
        private const int MinimumSecretLength = 32;

        // Tests and nothing else replace the reader; production reads the
        // Credential Locker on every request so a rotated secret takes effect.
        public static Func<string> SecretReader = () => ReadSecret(SecretService, SecretUser);

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

        /// <summary>
        /// True when the request must be refused; status and reason say why.
        /// requireToken is false only for the identity route (/ping).
        /// </summary>
        public static bool Refuse(string origin, string fetchMode, string token, bool requireToken,
                                  out int status, out string reason)
        {
            status = 200;
            reason = null;
            if (origin != null || fetchMode != null)
            {
                status = 403;
                reason = "browser requests are refused; ArchHub calls this bridge directly";
                return true;
            }
            if (!requireToken)
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
            if (!FixedTimeEquals(token, secret))
            {
                status = 401;
                reason = "caller is not authenticated";
                return true;
            }
            return false;
        }

        public static bool Refuse(HttpListenerRequest request, bool requireToken, out int status, out string reason)
        {
            return Refuse(request.Headers["Origin"], request.Headers["Sec-Fetch-Mode"],
                          request.Headers[TokenHeader], requireToken, out status, out reason);
        }
    }
}
