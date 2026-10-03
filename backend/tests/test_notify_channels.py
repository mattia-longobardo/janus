import json

import httpx
import pytest
import respx

from app.notify.channels import EmailChannel, GotifyChannel, NotifyError
from app.notify.debounce import MemoryDebouncer, RedisDebouncer
from app.notify.render import Message
from app.notify.store import NotifySettings

MESSAGE = Message("New device: pixel-7", "MAC x", 8, "https://janus.example/devices/abc")
NS = NotifySettings(email_recipient="owner@example.org")


@respx.mock
def test_gotify_posts_message_with_click_url():
    route = respx.post("https://gotify.example/message").respond(200, json={"id": 1})
    GotifyChannel("https://gotify.example/", "tok").send(MESSAGE, NS)
    request = route.calls.last.request
    assert request.headers["X-Gotify-Key"] == "tok"
    assert json.loads(request.content) == {
        "title": "New device: pixel-7", "message": "MAC x", "priority": 8,
        "extras": {"client::notification": {"click": {"url": "https://janus.example/devices/abc"}}},
    }


@respx.mock
def test_gotify_errors_become_notify_errors():
    respx.post("https://gotify.example/message").mock(side_effect=[httpx.Response(401), httpx.ConnectError("down")])
    channel = GotifyChannel("https://gotify.example", "tok")
    with pytest.raises(NotifyError, match="HTTP 401") as rejected:
        channel.send(MESSAGE, NS)
    assert rejected.value.permanent is True
    with pytest.raises(NotifyError, match="unreachable") as down:
        channel.send(MESSAGE, NS)
    assert down.value.permanent is False


def test_gotify_ready_needs_url_and_token():
    assert GotifyChannel("https://g", "t").ready(NS)
    assert not GotifyChannel("", "t").ready(NS) and not GotifyChannel("https://g", "").ready(NS)


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.logged_in, self.sent = None, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent.append(message)


def test_email_sends_via_smtp_ssl():
    FakeSMTP.instances.clear()
    EmailChannel("mx.example", 465, "no-reply@example.org", "pw", "no-reply@example.org", smtp_factory=FakeSMTP).send(MESSAGE, NS)
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.logged_in) == ("mx.example", 465, ("no-reply@example.org", "pw"))
    [mail] = smtp.sent
    assert (mail["Subject"], mail["To"], mail["From"]) == ("[Janus] New device: pixel-7", "owner@example.org", "no-reply@example.org")
    assert mail.get_content().strip() == "MAC x\n\nhttps://janus.example/devices/abc"


def test_email_failure_and_readiness():
    def broken(*args, **kwargs):
        raise OSError("connection refused")

    channel = EmailChannel("mx.example", 465, "u", "p", "no-reply@example.org", smtp_factory=broken)
    with pytest.raises(NotifyError, match="connection refused") as down:
        channel.send(MESSAGE, NS)
    assert down.value.permanent is False
    assert channel.ready(NS)
    assert not channel.ready(NotifySettings(email_recipient=""))


def test_memory_debouncer_expires():
    now = [100.0]
    debouncer = MemoryDebouncer(clock=lambda: now[0])
    assert debouncer.first("k", 60) is True
    assert debouncer.first("k", 60) is False
    now[0] += 61
    assert debouncer.first("k", 60) is True


def test_redis_debouncer_uses_set_nx_ex():
    class FakeRedis:
        def __init__(self):
            self.calls = []

        def set(self, key, value, nx, ex):
            self.calls.append((key, nx, ex))
            return len(self.calls) == 1

    redis = FakeRedis()
    debouncer = RedisDebouncer(redis)
    assert debouncer.first("device.new:M", 3600) is True
    assert debouncer.first("device.new:M", 3600) is False
    assert redis.calls[0] == ("janus:notify:device.new:M", True, 3600)


def test_email_auth_failure_is_permanent():
    import smtplib

    class Refusing(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    channel = EmailChannel("mx.example", 465, "u", "p", "no-reply@example.org", smtp_factory=Refusing)
    with pytest.raises(NotifyError) as refused:
        channel.send(MESSAGE, NS)
    assert refused.value.permanent is True


def test_starttls_upgrades_before_login():
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout): calls.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): calls.append(("starttls",))
        def login(self, u, p): calls.append(("login", u))
        def send_message(self, m): calls.append(("send", m["To"]))

    ch = EmailChannel("smtp.example", 587, "u", "p", "janus@example.org", security="starttls", smtp_factory=FakeSMTP)
    ch.send(MESSAGE, NS)
    assert [c[0] for c in calls] == ["connect", "starttls", "login", "send"]
