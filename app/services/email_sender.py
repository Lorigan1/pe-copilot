"""Email sender service — sends alert and digest emails via SendGrid.

Gracefully degrades when SendGrid is not configured (logs instead of sending).
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    """Sends transactional emails via the SendGrid API."""

    def __init__(self) -> None:
        self._client = None
        self._configured = False

    def _ensure_client(self) -> bool:
        """Lazily initialise the SendGrid client. Returns True if available."""
        if self._configured:
            return self._client is not None

        self._configured = True
        if not settings.sendgrid_api_key:
            logger.warning("SendGrid API key not set — emails will be logged only")
            return False

        try:
            from sendgrid import SendGridAPIClient

            self._client = SendGridAPIClient(settings.sendgrid_api_key)
            logger.info("SendGrid client initialised")
            return True
        except ImportError:
            logger.warning("sendgrid package not installed — emails will be logged only")
            return False

    async def send_health_alert(
        self,
        recipient_email: str,
        company_name: str,
        previous_status: str,
        new_status: str,
        reasons: list[str],
        fund_name: str = "Meridian Capital Fund III",
    ) -> bool:
        """Send an alert when a company's health status changes.

        Returns True if email was sent (or logged), False on failure.
        """
        subject = f"[PE CoPilot] {company_name} health status: {new_status.upper()}"
        reasons_html = "".join(f"<li>{r}</li>" for r in reasons)

        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #1B4F72; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">PE CoPilot Alert</h2>
                <p style="margin: 5px 0 0; opacity: 0.9;">{fund_name}</p>
            </div>

            <div style="padding: 20px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px;">
                <p><strong>{company_name}</strong> health status has changed:</p>

                <div style="display: flex; align-items: center; gap: 10px; margin: 15px 0;">
                    <span style="background: {self._status_color(previous_status)}; color: white; padding: 4px 12px; border-radius: 12px; font-size: 0.9rem; text-transform: uppercase;">{previous_status}</span>
                    <span style="font-size: 1.2rem;">&#x2192;</span>
                    <span style="background: {self._status_color(new_status)}; color: white; padding: 4px 12px; border-radius: 12px; font-size: 0.9rem; text-transform: uppercase;">{new_status}</span>
                </div>

                <h3 style="margin-bottom: 8px;">Reasons</h3>
                <ul style="padding-left: 20px; line-height: 1.6;">{reasons_html}</ul>

                <p style="margin-top: 20px; color: #666; font-size: 0.85rem;">
                    View the full details on your
                    <a href="#" style="color: #2E75B6;">PE CoPilot dashboard</a>.
                </p>
            </div>
        </div>
        """

        return await self._send(
            to_email=recipient_email,
            subject=subject,
            html_content=html_body,
        )

    async def send_staleness_alert(
        self,
        recipient_email: str,
        stale_companies: list[dict],
        fund_name: str = "Meridian Capital Fund III",
    ) -> bool:
        """Send a summary of companies with stale data.

        stale_companies: list of {"name": str, "days_since": int, "threshold": int}
        """
        if not stale_companies:
            return True

        rows = "".join(
            f'<tr><td style="padding: 8px; border-bottom: 1px solid #eee;">{c["name"]}</td>'
            f'<td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">{c["days_since"]} days</td>'
            f'<td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">{c["threshold"]} days</td></tr>'
            for c in stale_companies
        )

        subject = f"[PE CoPilot] {len(stale_companies)} company/ies with overdue data"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #1B4F72; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">PE CoPilot — Staleness Alert</h2>
                <p style="margin: 5px 0 0; opacity: 0.9;">{fund_name}</p>
            </div>

            <div style="padding: 20px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px;">
                <p>The following companies have not submitted data within their expected reporting window:</p>

                <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                    <thead>
                        <tr style="background: #f5f5f5;">
                            <th style="padding: 8px; text-align: left;">Company</th>
                            <th style="padding: 8px; text-align: center;">Days since update</th>
                            <th style="padding: 8px; text-align: center;">Threshold</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>

                <p style="margin-top: 20px; color: #666; font-size: 0.85rem;">
                    This is an automated alert from PE CoPilot.
                </p>
            </div>
        </div>
        """

        return await self._send(
            to_email=recipient_email,
            subject=subject,
            html_content=html_body,
        )

    async def _send(
        self,
        to_email: str,
        subject: str,
        html_content: str,
    ) -> bool:
        """Send an email via SendGrid, or log it if not configured."""
        if not self._ensure_client():
            logger.info(
                "EMAIL (not sent — SendGrid not configured):\n"
                "  To: %s\n  Subject: %s\n  [HTML body omitted]",
                to_email, subject,
            )
            return True  # Graceful degradation — treat as success

        try:
            from sendgrid.helpers.mail import Content, Email, Mail, To

            message = Mail(
                from_email=Email(settings.sendgrid_from_email, "PE CoPilot"),
                to_emails=To(to_email),
                subject=subject,
                html_content=Content("text/html", html_content),
            )

            response = self._client.send(message)
            logger.info(
                "Email sent to %s (status=%d, subject=%s)",
                to_email, response.status_code, subject,
            )
            return response.status_code in (200, 201, 202)

        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to_email, exc)
            return False

    @staticmethod
    def _status_color(status: str) -> str:
        """Map health status to a background color."""
        return {
            "green": "#27AE60",
            "amber": "#F39C12",
            "red": "#E74C3C",
        }.get(status, "#95A5A6")


# Singleton
email_sender = EmailSender()
