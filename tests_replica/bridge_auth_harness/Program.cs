// Court fixture: the shipped BridgeAuth behind a real HttpListener, called the
// way RevitMCPCore.HandleAsync and AcadMCPApp.ProcessRequestAsync call it.
// Args: <port> <credential service> <credential user>. Serves until stdin closes.
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using ArchHub.Shared;

internal static class Program
{
    private static int Main(string[] args)
    {
        int port = int.Parse(args[0]);
        string service = args[1], user = args[2];
        BridgeAuth.SecretReader = () => BridgeAuth.ReadSecret(service, user);
        var listener = new HttpListener();
        listener.Prefixes.Add("http://localhost:" + port + "/");
        listener.Start();
        Console.WriteLine("READY");
        Console.Out.Flush();
        Task.Run(() =>
        {
            while (listener.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = listener.GetContext(); } catch { break; }
                var path = (ctx.Request.Url.AbsolutePath ?? "/").TrimEnd('/');
                if (path.Length == 0) path = "/";
                int status;
                string reason;
                string json;
                var body = BridgeAuth.ReadBody(ctx.Request);
                if (body == null)
                {
                    status = 413;
                    json = "{\"status\":\"error\",\"error\":\"request body is too large\"}";
                }
                else if (BridgeAuth.Refuse(ctx.Request, body, path != "/" && path != "/ping", out status, out reason))
                    json = "{\"status\":\"error\",\"error\":\"" + reason + "\"}";
                else
                {
                    status = 200;
                    json = path == "/exec" ? "{\"status\":\"ok\",\"result\":\"ran\"}"
                                           : "{\"status\":\"ok\",\"service\":\"bridge-auth-harness\"}";
                }
                var bytes = Encoding.UTF8.GetBytes(json);
                ctx.Response.StatusCode = status;
                ctx.Response.ContentType = "application/json; charset=utf-8";
                ctx.Response.ContentLength64 = bytes.Length;
                ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
                ctx.Response.OutputStream.Close();
            }
        });
        Console.In.ReadToEnd();
        listener.Stop();
        return 0;
    }
}
