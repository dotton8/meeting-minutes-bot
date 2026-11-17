"""Endpoint tests with Azure calls stubbed out (real ffmpeg conversion still runs)."""
import io
import subprocess

import pytest

import app as app_module

FAKE_TRANSCRIPT = {"transcript": "Jake, can you update the deck by Friday?", "language": "en-US",
                   "duration_seconds": 3.1, "confidence": 0.93, "words": []}
FAKE_ANALYSIS = {
    "key_phrases": ["deck"],
    "entities": [{"text": "Jake", "category": "Person", "subcategory": None, "offset": 0,
                  "length": 4, "confidence": 0.99},
                 {"text": "Friday", "category": "DateTime", "subcategory": "Date",
                  "offset": 33, "length": 6, "confidence": 0.8}],
    "sentiment": {"label": "neutral", "scores": {"positive": 0.1, "neutral": 0.8, "negative": 0.1}},
    "sentences": [{"text": FAKE_TRANSCRIPT["transcript"], "offset": 0, "length": 40,
                   "sentiment": "neutral"}],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "transcribe_wav", lambda _p: dict(FAKE_TRANSCRIPT))
    monkeypatch.setattr(app_module, "analyze_text", lambda _t: dict(FAKE_ANALYSIS))
    monkeypatch.setattr(app_module, "synthesize", lambda _t, _v: "QUJD")
    return app_module.app.test_client()


@pytest.fixture(scope="module")
def tone_webm(tmp_path_factory):
    path = tmp_path_factory.mktemp("a") / "tone.webm"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1",
                    "-c:a", "libopus", str(path)], check=True)
    return path.read_bytes()


def test_transcribe_converts_webm(client, tone_webm):
    r = client.post("/transcribe", data={"audio": (io.BytesIO(tone_webm), "rec.webm")})
    assert r.status_code == 200 and r.json["confidence"] == 0.93


def test_wrong_extension_is_415(client):
    r = client.post("/transcribe", data={"audio": (io.BytesIO(b"hello"), "notes.txt")})
    assert r.status_code == 415


def test_corrupt_audio_is_415(client):
    r = client.post("/transcribe", data={"audio": (io.BytesIO(b"not really audio"), "x.wav")})
    assert r.status_code == 415


def test_missing_file_is_400(client):
    assert client.post("/transcribe", data={}).status_code == 400


def test_analyze_requires_text(client):
    assert client.post("/analyze", json={}).status_code == 400


def test_process_full_pipeline(client, tone_webm):
    r = client.post("/process", data={"audio": (io.BytesIO(tone_webm), "rec.webm"),
                                      "meeting_date": "2026-11-16"})
    assert r.status_code == 200
    item = r.json["minutes"]["action_items"][0]
    assert (item["owner"], item["due_date"]) == ("Jake", "2026-11-20")
    assert r.json["summary"]["audio_base64"] == "QUJD"
    assert r.json["metrics"]["action_items_count"] == 1
