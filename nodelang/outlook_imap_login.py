"""Explicit local, masked IMAP sign-in. No credentials in browser, argv or logs."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from .outlook_imap import account_name, _execute, save_password


def main():
    root = tk.Tk()
    root.title("ArchHub - Company email sign-in")
    root.geometry("550x330")
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Connect Yahoo / Turbify business mail", font=("Segoe UI", 13)).pack(anchor="w")
    ttk.Label(frame, text="Use your primary company email and a Turbify app password.\nThis does not use Microsoft sign-in.").pack(anchor="w", pady=8)
    ttk.Label(frame, text="Company email").pack(anchor="w")
    account = ttk.Entry(frame, width=65)
    account.pack(fill="x")
    ttk.Label(frame, text="App password").pack(anchor="w", pady=(8, 0))
    secret = ttk.Entry(frame, show="*", width=65)
    secret.pack(fill="x")
    notice = tk.StringVar(value="Password stays in Windows Credential Manager after a successful read-only test.")
    ttk.Label(frame, textvariable=notice, wraplength=500).pack(anchor="w", pady=10)
    results = queue.Queue()

    def worker(address, password):
        result = _execute("status", {"account": address}, password=password)
        if result.get("ok"):
            try:
                save_password(address, password)
            except Exception:
                result = {"ok": False, "reason": "Mailbox verified, but Windows could not save the credential. Try again."}
        password = None
        results.put(result)

    def submit():
        try:
            address = account_name(account.get().strip())
        except ValueError as exc:
            notice.set(str(exc))
            return
        password = secret.get()
        secret.delete(0, "end")
        if not password or any(c in password for c in "\r\n\x00"):
            notice.set("Enter the app password, without line breaks.")
            return
        button.config(state="disabled")
        account.config(state="disabled")
        notice.set("Testing encrypted sign-in and read-only Inbox access...")
        threading.Thread(target=worker, args=(address, password), daemon=True).start()

    button = ttk.Button(frame, text="Connect and save securely", command=submit)
    button.pack(anchor="w")
    ttk.Button(frame, text="Open Turbify app-password help", command=lambda: webbrowser.open(
        "https://help.turbify.com/s/article/manage-app-passwords")).pack(anchor="w", pady=6)

    def poll():
        try:
            result = results.get_nowait()
        except queue.Empty:
            root.after(200, poll)
            return
        if result.get("ok"):
            notice.set("Connected. Inbox verified; app password saved securely. You can close this window.")
            button.config(text="Connected")
        else:
            notice.set(result.get("reason", "Connection failed."))
            button.config(state="normal")
            account.config(state="normal")
        root.after(200, poll)

    root.after(200, poll)
    account.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
