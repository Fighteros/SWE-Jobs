from contextlib import contextmanager
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import routes_imessage as inbound
from bot import imessage_commands
from core import config, db, imessage


HEADERS = {"Authorization": "Bearer test-secret"}
EVENT = {"from": "+15550000000", "text": "/alert add", "message_id": "event-1"}
URL = "/imessage/inbound"


def client_for(monkeypatch, mode="imessage", secret="test-secret"):
    monkeypatch.setattr(config, "DELIVERY_CHANNEL", mode)
    monkeypatch.setattr(config, "IMESSAGE_WEBHOOK_SECRET", secret)
    app = FastAPI()
    app.include_router(inbound.router)
    return TestClient(app)


def test_webhook_requires_sidecar_secret(monkeypatch):
    with client_for(monkeypatch) as client:
        assert client.post(URL, json=EVENT).status_code == 401
        assert client.post(URL, json=EVENT, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.post(URL, json=[], headers=HEADERS).status_code == 400
        assert client.post(URL, json={"from": "a", "text": "/help"}, headers=HEADERS).status_code == 400
    with client_for(monkeypatch, secret="") as client:
        assert client.post(URL, json=EVENT, headers=HEADERS).status_code == 401
    with client_for(monkeypatch, mode="telegram") as client:
        assert client.post(URL, json=EVENT, headers=HEADERS).status_code == 404


def test_webhook_retries_failed_reply_without_reprocessing(monkeypatch):
    state = {}

    class Cursor:
        def execute(self, query, args):
            key = tuple(args[-2:])
            if query.startswith("INSERT"):
                self.row = None if key in state else (1,)
                state.setdefault(key, None)
            elif query.startswith("SELECT"):
                self.row = (state[key],)
            elif "SET reply = NULL" in query:
                state[key] = None
            else:
                state[key] = args[0]

        def fetchone(self):
            return self.row

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

    @contextmanager
    def connection():
        snapshot = state.copy()
        try:
            yield Connection()
        except Exception:
            state.clear()
            state.update(snapshot)
            raise

    monkeypatch.setattr(db, "_get_conn", connection)
    process = Mock(side_effect=[RuntimeError("command failed"), "saved"])
    monkeypatch.setattr(imessage_commands, "handle_inbound_sync", process)
    send = Mock(side_effect=[RuntimeError("send failed"), None])
    monkeypatch.setattr(imessage, "send_text", send)
    with client_for(monkeypatch) as client:
        def post():
            return client.post(URL, json=EVENT, headers=HEADERS)

        assert post().status_code == 503  # command rolls back
        assert post().status_code == 503  # command commits, reply fails
        assert post().status_code == 200  # retry sends cached reply
        assert post().status_code == 200  # successfully sent reply is not repeated
    assert process.call_count == 2
    assert send.call_count == 2
