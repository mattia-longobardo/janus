import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

import httpx

from app.notify.render import Message
from app.notify.store import NotifySettings


class NotifyError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class GotifyChannel:
    def __init__(self, url: str, token: str, *, http: httpx.Client | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self._http = http or httpx.Client(timeout=10.0)

    def ready(self, ns: NotifySettings) -> bool:
        return bool(self.url and self.token)

    def send(self, message: Message, ns: NotifySettings) -> None:
        body: dict[str, Any] = {"title": message.title, "message": message.body, "priority": message.priority}
        if message.url:
            body["extras"] = {"client::notification": {"click": {"url": message.url}}}
        try:
            response = self._http.post(f"{self.url}/message", headers={"X-Gotify-Key": self.token}, json=body)
        except httpx.HTTPError as exc:
            raise NotifyError(f"Gotify unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise NotifyError(
                f"Gotify rejected the message: HTTP {response.status_code}",
                permanent=400 <= response.status_code < 500 and response.status_code not in (408, 429),
            )


class EmailChannel:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        *,
        security: str = "ssl",
        smtp_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender
        self.security = security
        self._factory = smtp_factory or (smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP)

    def ready(self, ns: NotifySettings) -> bool:
        return bool(self.host and self.sender and ns.email_recipient)

    def send(self, message: Message, ns: NotifySettings) -> None:
        mail = EmailMessage()
        mail["Subject"] = f"[Janus] {message.title}"
        mail["From"] = self.sender
        mail["To"] = ns.email_recipient
        mail.set_content(message.body + (f"\n\n{message.url}" if message.url else ""))
        try:
            with self._factory(self.host, self.port, timeout=15) as smtp:
                if self.security == "starttls":
                    smtp.starttls()
                if self.user:
                    smtp.login(self.user, self.password)
                smtp.send_message(mail)
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
            raise NotifyError(f"email rejected: {exc}", permanent=True) from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise NotifyError(f"email failed: {exc}") from exc
