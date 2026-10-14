from pathlib import Path
from types import SimpleNamespace

from app.api.v1 import discovery
from app.services.youtube_bridge_manager import youtube_bridge_manager

EVENTS_PATH = "/api/v1/discovery/youtube-events"


class FakeContentProvider:
    def get_video(self, video_id):
        return SimpleNamespace(
            title="부산 여행 브이로그",
            channel_title="테스트 채널",
            thumbnail_url="https://example.test/thumb.jpg",
        )


def test_events_websocket_receives_a_pause_event(client, monkeypatch):
    monkeypatch.setattr(discovery, "get_content_provider", FakeContentProvider)

    with client.websocket_connect(EVENTS_PATH) as websocket:
        response = client.post(
            "/api/v1/discovery/youtube-pause",
            json={"event": "pause", "video_id": "abc123", "position_sec": 95},
        )
        assert response.status_code == 200
        message = websocket.receive_json()

    assert message["event"] == "pause"
    assert message["video_id"] == "abc123"
    assert message["position_sec"] == 95
    assert message["title"] == "부산 여행 브이로그"


def test_closed_websocket_is_removed_from_the_bridge(client):
    before = len(youtube_bridge_manager.connections)
    with client.websocket_connect(EVENTS_PATH):
        assert len(youtube_bridge_manager.connections) == before + 1
    assert len(youtube_bridge_manager.connections) == before


def test_requirements_include_a_websocket_server_library():
    # Without it uvicorn rejects the upgrade and answers GET .../youtube-events with 404.
    requirements = Path(__file__).resolve().parents[3] / "requirements.txt"
    names = {
        line.split("==")[0].split("[")[0].strip().lower()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert names & {"websockets", "wsproto"} or "uvicorn[standard]" in requirements.read_text(encoding="utf-8")


def test_pause_event_keeps_the_extension_event_id_and_reports_delivery(client, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(discovery, "get_content_provider", FakeContentProvider)
    with caplog.at_level(logging.INFO, logger="app.youtube_bridge"), client.websocket_connect(EVENTS_PATH) as websocket:
        response = client.post(
            "/api/v1/discovery/youtube-pause",
            json={"event": "pause", "video_id": "abc123", "position_sec": 7,
                  "event_id": "ext-1", "detected_at": "2026-10-13T11:00:00Z"},
        )
        message = websocket.receive_json()
    assert response.status_code == 200
    assert response.json()["event_id"] == "ext-1" and response.json()["delivered_clients"] >= 1
    assert message["event_id"] == "ext-1" and message["detected_at"] == "2026-10-13T11:00:00Z"
    assert message["received_at"]
    logs = [record.getMessage() for record in caplog.records]
    assert any("EVENT_RECEIVED event_id=ext-1" in line for line in logs)
    assert any("EVENT_DELIVERED event_id=ext-1" in line for line in logs)


def test_pause_event_from_an_older_extension_gets_a_server_event_id(client, monkeypatch):
    monkeypatch.setattr(discovery, "get_content_provider", FakeContentProvider)
    with client.websocket_connect(EVENTS_PATH) as websocket:
        client.post("/api/v1/discovery/youtube-pause", json={"event": "pause", "video_id": "abc123", "position_sec": 7})
        first = websocket.receive_json()
        client.post("/api/v1/discovery/youtube-pause", json={"event": "pause", "video_id": "abc123", "position_sec": 7})
        second = websocket.receive_json()
    assert first["event_id"] and second["event_id"] and first["event_id"] != second["event_id"]
