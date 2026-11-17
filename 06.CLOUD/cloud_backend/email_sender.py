"""Thin wrapper around Resend for transactional email.

Falls back to stdout-logging when RESEND_API_KEY is unset (local dev
+ smoke tests). Production deploys MUST set the key; otherwise company
invites fail silently.

Templates:
  send_company_invite — the link to a company invite. It is not a
                        sign-in: accepting needs a Google session on the
                        invited address (founder 2026-09-28: Google is
                        the only sign-in, no magic link).
"""
from __future__ import annotations

import httpx

import config


RESEND_URL = "https://api.resend.com/emails"


ACCEPTED, REFUSED, UNKNOWN = "accepted", "refused", "unknown"


async def _send(*, to: str, subject: str, text: str, html: str) -> bool:
    """POST one email to Resend. Returns True on accepted (2xx); exactly what
    it always returned (send_outcome() == ACCEPTED)."""
    return await send_outcome(to=to, subject=subject, text=text, html=html) == ACCEPTED


async def send_outcome(*, to: str, subject: str, text: str, html: str) -> str:
    """POST one email to Resend and say what is known about it:
    ACCEPTED (2xx), REFUSED (a definite answer: a 4xx whose body parses, or
    production without a provider key), or UNKNOWN (a transport error, a
    timeout, a 5xx, a body that does not parse: the provider may have taken it).

    Delivery-key handling (gap 5, 2026-05-31):
      - PRODUCTION (ENV=production) with no RESEND_API_KEY → return FALSE.
        We never pretend an email was sent in prod when no provider is
        wired.
        (The startup gate in config.assert_production_ready already
        refuses to boot in this state — this is belt-and-suspenders for
        any path that reaches send with the key unset.)
      - DEV (ENV unset) with no RESEND_API_KEY → log to stdout and return
        True so local sign-in still flows. The log line is loud + tagged
        UNDELIVERED so it's unmistakable that nothing actually went out.
    """
    if not config.RESEND_API_KEY:
        if config.is_production():
            print(
                f"[email] PRODUCTION send ABORTED — RESEND_API_KEY unset; "
                f"NOT delivered to {to}: {subject}",
                flush=True,
            )
            return REFUSED
        print(
            f"[email] DEV stub — NOT actually sent (RESEND_API_KEY unset). "
            f"Would deliver to {to}: {subject}",
            flush=True,
        )
        return ACCEPTED
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {config.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": config.FROM_EMAIL,
                    "to": [to],
                    "subject": subject,
                    "text": text,
                    "html": html,
                },
            )
    except Exception as ex:
        print(f"[email] send failed to {to}: {type(ex).__name__}: {ex}",
              flush=True)
        return UNKNOWN
    if 200 <= r.status_code < 300:
        return ACCEPTED
    if 400 <= r.status_code < 500:
        try:
            r.json()
            return REFUSED
        except Exception:
            return UNKNOWN
    return UNKNOWN


def _wrap(body_html: str) -> str:
    """Wrap inner HTML in a brand-coherent, email-client-safe shell —
    light background, terra accent, inline styles only."""
    return (
        "<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:480px;margin:0 auto;padding:32px 28px;color:#1d1d22;"
        "background:#ffffff;\">"
        "<div style=\"font-family:Georgia,serif;font-style:italic;"
        "font-size:26px;color:#d97757;margin-bottom:18px;\">ArchHub</div>"
        + body_html +
        "<hr style=\"border:none;border-top:1px solid #e8e6dc;"
        "margin:26px 0 14px;\">"
        "<div style=\"color:#9b938a;font-size:12px;line-height:1.5;\">"
        "ArchHub — talk to your AEC stack. "
        "<a href=\"https://archhub.io/security\" "
        "style=\"color:#9b938a;\">Trust Center</a></div>"
        "</div>"
    )


async def send_company_invite(*, to: str, link: str) -> bool:
    """Send a company invite link. Returns True on accepted."""
    return await send_company_invite_outcome(to=to, link=link) == ACCEPTED


async def send_company_invite_outcome(*, to: str, link: str) -> str:
    """Send a company invite link; ACCEPTED, REFUSED or UNKNOWN (see send_outcome)."""
    subject = "You're invited to a team on ArchHub"
    text = (
        f"You've been invited to a company workspace on ArchHub.\n\n"
        f"{link}\n\n"
        f"Open the link and continue with Google on this email address "
        f"to accept. If you weren't expecting this, ignore the email."
    )
    html = _wrap(
        "<p style=\"font-size:15px;line-height:1.55;\">You've been "
        "invited to a company workspace on ArchHub.</p>"
        f"<p><a href=\"{link}\" style=\"display:inline-block;"
        "background:#d97757;color:#ffffff;text-decoration:none;"
        "padding:12px 22px;border-radius:8px;font-size:15px;"
        "font-weight:500;\">Open the invite</a></p>"
        "<p style=\"color:#9b938a;font-size:12px;\">Continue with Google "
        "on this email address to accept. If you weren't expecting this, "
        "ignore the email.</p>"
    )
    return await send_outcome(to=to, subject=subject, text=text, html=html)
