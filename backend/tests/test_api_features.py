from app import features


def test_features_collects_every_registered_provider(client, monkeypatch):
    monkeypatch.setattr(features, "FEATURE_PROVIDERS", {
        "notify": lambda db: {"email": True, "gotify": False},
        "guests": lambda db: {"enabled": False},
    })
    assert client.get("/api/features").json() == {
        "notify": {"email": True, "gotify": False},
        "guests": {"enabled": False},
    }


def test_a_broken_provider_does_not_hide_the_others(client, monkeypatch):
    def boom(db):
        raise RuntimeError("down")
    monkeypatch.setattr(features, "FEATURE_PROVIDERS", {"notify": boom, "guests": lambda db: {"enabled": True}})
    assert client.get("/api/features").json() == {"notify": {}, "guests": {"enabled": True}}


def test_features_require_the_internal_token(client):
    assert client.get("/api/features", headers={"X-Janus-Internal-Token": "wrong"}).status_code == 401
