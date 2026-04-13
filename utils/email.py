"""Send emails via SMTP (invites, voting notifications, event confirmations)."""

import logging
import smtplib
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

from config import get_settings

logger = logging.getLogger(__name__)


def _send_email(to_email: str, subject: str, text_body: str, html_body: str, attachments: list | None = None) -> bool:
    """Low-level SMTP send. Returns True on success."""
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_user:
        logger.warning("SMTP not configured; skipping email to %s", to_email)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email or settings.smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    for attachment in (attachments or []):
        part = MIMEBase(attachment["maintype"], attachment["subtype"])
        part.set_payload(attachment["data"])
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment["filename"]}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            if settings.smtp_port != 25:
                server.starttls()
                server.ehlo()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


def send_invite_email(
    to_email: str,
    group_name: str,
    inviter_name: str,
    group_id: str,
) -> bool:
    """Send an invitation email. Returns True on success, False otherwise."""
    settings = get_settings()
    frontend_url = settings.frontend_url.rstrip("/")
    accept_url = f"{frontend_url}/invites/{group_id}?action=accept"
    decline_url = f"{frontend_url}/invites/{group_id}?action=decline"

    subject = f'🍅 {inviter_name} invited you to join "{group_name}" on Ketchup'

    text_body = (
        f"Hey!\n\n"
        f'{inviter_name} invited you to join the group "{group_name}" on Ketchup.\n\n'
        f"Accept the invite: {accept_url}\n"
        f"Decline the invite: {decline_url}\n\n"
        f"This invite expires in 24 hours. If you don't respond, "
        f"it will be automatically declined.\n\n"
        f"- The Ketchup Team"
    )

    html_body = f"""\
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1a1a1a;">
        <div style="text-align: center; margin-bottom: 32px;">
            <span style="font-size: 32px;">🍅</span>
            <h1 style="font-size: 22px; color: #c92a2a; margin: 8px 0 0 0;">Ketchup</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6;">
            <strong>{inviter_name}</strong> invited you to join
            <strong>"{group_name}"</strong> on Ketchup.
        </p>
        <p style="font-size: 14px; color: #555; line-height: 1.6;">
            Ketchup helps groups coordinate plans and decisions.
        </p>
        <div style="text-align: center; margin: 32px 0;">
            <a href="{accept_url}"
               style="display: inline-block; background: #c92a2a; color: #fff;
                      padding: 12px 32px; border-radius: 6px; text-decoration: none;
                      font-weight: 600; font-size: 15px; margin-right: 12px;">
                Accept invite
            </a>
            <a href="{decline_url}"
               style="display: inline-block; background: #f1f3f5; color: #495057;
                      padding: 12px 32px; border-radius: 6px; text-decoration: none;
                      font-weight: 600; font-size: 15px;">
                Decline
            </a>
        </div>
        <p style="font-size: 13px; color: #868e96; text-align: center; margin-top: 32px;">
            This invite expires in <strong>24 hours</strong>. If you don't respond,
            it will be automatically declined.
        </p>
    </div>
    """

    return _send_email(to_email, subject, text_body, html_body)


def send_voting_open_email(
    to_email: str,
    group_name: str,
    group_id: str,
    round_id: str,
) -> bool:
    """Notify a group member that a new voting round is open."""
    settings = get_settings()
    frontend_url = settings.frontend_url.rstrip("/")
    vote_url = f"{frontend_url}/groups/{group_id}/vote/{round_id}"

    subject = f"🍅 Time to vote! New plans for \"{group_name}\" on Ketchup"

    text_body = (
        f"Hey!\n\n"
        f"New plans have been generated for \"{group_name}\" on Ketchup.\n"
        f"Head over to vote on your favorites:\n\n"
        f"{vote_url}\n\n"
        f"Voting is open for 24 hours.\n\n"
        f"- The Ketchup Team"
    )

    html_body = f"""\
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1a1a1a;">
        <div style="text-align: center; margin-bottom: 32px;">
            <span style="font-size: 32px;">🍅</span>
            <h1 style="font-size: 22px; color: #c92a2a; margin: 8px 0 0 0;">Ketchup</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6;">
            New plans have been generated for <strong>"{group_name}"</strong>!
        </p>
        <p style="font-size: 14px; color: #555; line-height: 1.6;">
            Rank your top 5 picks so your group can reach a consensus.
        </p>
        <div style="text-align: center; margin: 32px 0;">
            <a href="{vote_url}"
               style="display: inline-block; background: #c92a2a; color: #fff;
                      padding: 12px 32px; border-radius: 6px; text-decoration: none;
                      font-weight: 600; font-size: 15px;">
                Vote now
            </a>
        </div>
        <p style="font-size: 13px; color: #868e96; text-align: center; margin-top: 32px;">
            Voting is open for <strong>24 hours</strong>.
        </p>
    </div>
    """

    return _send_email(to_email, subject, text_body, html_body)


def _build_ics(
    title: str,
    event_date: datetime,
    location: str | None = None,
    description: str | None = None,
) -> str:
    """Build a minimal .ics (iCalendar) string for a single event."""
    from datetime import timedelta
    import uuid as _uuid

    dtstart = event_date.strftime("%Y%m%dT%H%M%SZ")
    dtend = (event_date + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
    uid = f"{_uuid.uuid4()}@ketchup"
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ketchup//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{title}",
    ]
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description[:200]}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def send_event_finalized_email(
    to_email: str,
    group_name: str,
    plan_title: str,
    event_date: datetime,
    location: str | None = None,
    description: str | None = None,
) -> bool:
    """Send event confirmation email with .ics calendar attachment."""
    settings = get_settings()
    date_str = event_date.strftime("%B %d, %Y at %I:%M %p")

    subject = f"🍅 It's a plan! \"{plan_title}\" for {group_name}"

    text_body = (
        f"Hey!\n\n"
        f"Your group \"{group_name}\" has finalized an event:\n\n"
        f"  {plan_title}\n"
        f"  Date: {date_str}\n"
        f"  Location: {location or 'TBD'}\n\n"
        f"A calendar invite (.ics file) is attached.\n\n"
        f"- The Ketchup Team"
    )

    html_body = f"""\
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1a1a1a;">
        <div style="text-align: center; margin-bottom: 32px;">
            <span style="font-size: 32px;">🍅</span>
            <h1 style="font-size: 22px; color: #c92a2a; margin: 8px 0 0 0;">Ketchup</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6;">
            Your group <strong>"{group_name}"</strong> has finalized an event!
        </p>
        <div style="background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 24px 0;">
            <h2 style="font-size: 18px; margin: 0 0 12px 0;">{plan_title}</h2>
            <p style="font-size: 14px; margin: 4px 0; color: #555;">
                📅 {date_str}
            </p>
            <p style="font-size: 14px; margin: 4px 0; color: #555;">
                📍 {location or 'TBD'}
            </p>
        </div>
        <p style="font-size: 14px; color: #555; line-height: 1.6;">
            A calendar invite is attached — add it to your calendar so you don't forget!
        </p>
        <p style="font-size: 13px; color: #868e96; text-align: center; margin-top: 32px;">
            Have fun! 🎉
        </p>
    </div>
    """

    ics_content = _build_ics(plan_title, event_date, location, description)
    attachments = [{
        "maintype": "text",
        "subtype": "calendar",
        "data": ics_content.encode("utf-8"),
        "filename": "ketchup-event.ics",
    }]

    return _send_email(to_email, subject, text_body, html_body, attachments=attachments)
