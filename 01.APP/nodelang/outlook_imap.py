"""Read-only Yahoo/Turbify IMAP transport for ArchHub's existing host broker.

No Microsoft authentication, Outlook process, mail writes or credential arguments.
The Windows Credential Manager holds account-bound app passwords.
"""
from __future__ import annotations

import email
from email import policy
import hashlib
import imaplib
import json
import re
import ssl
import subprocess
import sys
from pathlib import Path

HOST = "imap.mail.yahoo.com"
PORT = 993
ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = {"status", "inbox", "message", "probe"}


def failure(state, reason):
    return {"ok": False, "state": state, "reason": reason, "out": []}


def account_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", value) or len(value) > 254:
        raise ValueError("Enter the full primary business email address")
    return value.lower()


def credential_target(account):
    return "ArchHub/imap/" + hashlib.sha256((HOST + "/" + account_name(account)).encode()).hexdigest()


def load_password(account):
    import win32cred
    try:
        item = win32cred.CredRead(credential_target(account), win32cred.CRED_TYPE_GENERIC)
    except Exception as exc:
        if getattr(exc, "winerror", None) == 1168:
            return None
        raise OSError("Windows Credential Manager could not be read") from None
    if item["UserName"] != account_name(account):
        raise OSError("Credential account mismatch")
    return item["CredentialBlob"].decode("utf-16-le")


def save_password(account, password):
    import win32cred
    win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC,
                        "TargetName": credential_target(account),
                        "UserName": account_name(account),
                        "CredentialBlob": password,
                        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)


def _validate(operation, params):
    if operation not in OPERATIONS:
        raise ValueError("Only probe, status, inbox and message reads are supported")
    allowed = {"account", "count", "uid", "uidvalidity", "transport"}
    if set(params) - allowed:
        raise ValueError("Unknown IMAP parameter; credentials must be entered in the local sign-in window")
    if operation == "probe":
        return {}
    request = {"account": account_name(params.get("account"))}
    if operation == "inbox":
        count = params.get("count", 20)
        if type(count) is not int or not 1 <= count <= 50:
            raise ValueError("Inbox count must be an integer from 1 to 50")
        request["count"] = count
    if operation == "message":
        for key in ("uid", "uidvalidity"):
            value = str(params.get(key, ""))
            if not re.fullmatch(r"[1-9][0-9]{0,9}", value):
                raise ValueError("Select a message with its UID and UIDVALIDITY from the inbox read")
            request[key] = value
    return request


def _connect():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return imaplib.IMAP4_SSL(HOST, PORT, ssl_context=context, timeout=12)


def _checked(result):
    if result[0] != "OK":
        raise imaplib.IMAP4.error("Operation refused")
    return result[1]


def _execute(operation, params, password=None):
    """Internal worker; secrets never cross the JSON transport."""
    client = None
    try:
        params = _validate(operation, params)
        account = params.get("account")
        if operation != "probe":
            password = password if password is not None else load_password(account)
            if not password:
                return failure("credentials-required", "Enter a Turbify app password in the local sign-in window")
        client = _connect()
        if operation == "probe":
            return {"ok": True, "state": "server-reachable", "host": HOST,
                    "reason": "Verified TLS and IMAP greeting; mailbox authentication has not been tested", "out": []}
        try:
            _checked(client.login(account, password))
        except imaplib.IMAP4.error:
            return failure("authentication-failed", "Provider rejected sign-in. Use the primary business address and a current Turbify app password")
        data = _checked(client.select("INBOX", readonly=True))
        total = int(data[0])
        validity = client.response("UIDVALIDITY")[1][0].decode("ascii")
        result = {"ok": True, "state": "authenticated", "account": account,
                  "host": HOST, "folder": "INBOX", "uidvalidity": validity,
                  "total": total, "read_only": True, "out": []}
        if operation == "status":
            return result
        if operation == "message":
            if params["uidvalidity"] != validity:
                return failure("stale-message", "Mailbox identity changed; refresh the inbox before reading")
            fetched = _checked(client.uid("FETCH", params["uid"], "(UID RFC822.SIZE BODY.PEEK[]<0.1048576>)"))
        elif total:
            start = max(1, total - params["count"] + 1)
            fetched = _checked(client.fetch(str(start) + ":" + str(total),
                "(UID FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)]<0.32768>)"))
        else:
            fetched = []
        for item in fetched:
            if not isinstance(item, tuple):
                continue
            metadata, raw = item
            uid_match = re.search(rb"\bUID (\d+)", metadata)
            if not uid_match:
                raise ValueError("Server omitted message identity")
            if operation == "message" and uid_match[1].decode() != params["uid"]:
                raise ValueError("Server returned a different message")
            msg = email.message_from_bytes(raw, policy=policy.default)
            row = {"uid": uid_match[1].decode(), "subject": str(msg.get("Subject", "")),
                   "sender": str(msg.get("From", "")), "date": str(msg.get("Date", "")),
                   "message_id": str(msg.get("Message-ID", ""))}
            if operation == "message":
                size = re.search(rb"RFC822.SIZE (\d+)", metadata)
                row.update(raw_mime=raw.decode("utf-8", errors="replace"),
                           truncated=not size or int(size[1]) > len(raw))
            else:
                row.update(unread=b"\\Seen" not in metadata,
                           header_truncated=len(raw) >= 32768)
            result["out"].append(row)
        if operation == "inbox":
            result["out"].reverse()
            result["has_more"] = total > len(result["out"])
        elif not result["out"]:
            return failure("message-missing", "The selected message no longer exists in Inbox")
        return result
    except ssl.SSLCertVerificationError:
        return failure("tls-failed", "Mail server certificate verification failed")
    except (TimeoutError, OSError, imaplib.IMAP4.error):
        return failure("connection-failed", "Secure mailbox read failed; check connection and credential availability")
    except Exception:
        return failure("read-failed", "Mailbox response could not be verified")
    finally:
        password = None
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                pass


def invoke(operation, params):
    try:
        request = _validate(operation, params)
    except ValueError as exc:
        return failure("invalid-request", str(exc))
    if getattr(sys, "frozen", False):
        return failure("runtime-unavailable", "This IMAP transport has not been admitted in the frozen runtime")
    try:
        run = subprocess.run([sys.executable, "-B", "-m", "nodelang.outlook_imap", "--worker"],
                             cwd=ROOT, input=json.dumps({"operation": operation, "params": request}),
                             capture_output=True, text=True, encoding="utf-8", timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = json.loads(run.stdout)
        if run.returncode or type(result) is not dict or type(result.get("ok")) is not bool:
            raise ValueError()
        return result
    except subprocess.TimeoutExpired:
        return failure("timeout", "IMAP read exceeded its 30-second budget")
    except Exception:
        return failure("runtime-unavailable", "IMAP worker failed; no mailbox result was accepted")


def inbox(params, feeds):
    result = invoke("inbox", params)
    return result, result.get("reason", "%d inbox item(s) via direct IMAP" % len(result.get("out", [])))


def status(params, feeds):
    result = invoke("status", params)
    return result, result.get("reason", result["state"])


def message(params, feeds):
    result = invoke("message", params)
    return result, result.get("reason", "Read selected message via direct IMAP")


def open_sign_in():
    if getattr(sys, "frozen", False):
        return failure("runtime-unavailable", "IMAP sign-in is not yet admitted in the frozen runtime")
    try:
        child = subprocess.Popen([sys.executable, "-B", "-m", "nodelang.outlook_imap_login"],
                                 cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True, "state": "sign-in-started", "process_id": child.pid,
                "reason": "Enter the company mailbox and app password in the local window; this is not yet a verified connection"}
    except OSError:
        return failure("runtime-unavailable", "The local IMAP sign-in window could not open")


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    try:
        request = json.loads(sys.stdin.read(4096))
        output = _execute(request["operation"], request["params"])
    except Exception:
        output = failure("invalid-request", "Invalid worker request")
    print(json.dumps(output, ensure_ascii=True))
