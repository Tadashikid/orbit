"""The voice bridge (backend/voice.py) against a fake Gemini Live session: no network, no microphone."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from starlette.websockets import WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import main  # noqa: E402
import voice  # noqa: E402

LOCAL = {"origin": "http://127.0.0.1:4173"}


class FakeLive:
    """Hears one request, asks Orbit, then speaks the answer."""

    def __init__(self):
        self.audio, self.ended, self.responses = [], False, []
        self.answered = asyncio.Event()
        self.turns = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_realtime_input(self, audio=None, audio_stream_end=None):
        if audio:
            self.audio.append(audio.data)
        self.ended = self.ended or bool(audio_stream_end)

    async def send_tool_response(self, function_responses):
        self.responses += function_responses
        self.answered.set()

    async def receive(self):
        self.turns += 1
        if self.turns == 1:
            yield types.LiveServerMessage(server_content=types.LiveServerContent(
                input_transcription=types.Transcription(text="Book a Goa trip next weekend")))
            yield types.LiveServerMessage(tool_call=types.LiveServerToolCall(function_calls=[types.FunctionCall(
                id="c1", name="ask_orbit", args={"request": "Book a Goa trip next weekend"})]))
            await self.answered.wait()
            yield types.LiveServerMessage(server_content=types.LiveServerContent(
                model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b"\x01\x02", mime_type="audio/pcm"))]),
                output_transcription=types.Transcription(text="Two flights are held for your OK."), turn_complete=True))
        else:
            await asyncio.Event().wait()  # nothing more to say


@pytest.fixture
def client():
    c = TestClient(main.app)
    assert c.post("/login", json={"email": main.DEMO_EMAIL, "password": main.DEMO_PASSWORD}).status_code == 200
    return c


def test_voice_asks_orbit_through_the_browser_and_speaks_the_answer(client, monkeypatch):
    fake = FakeLive()
    monkeypatch.setattr(voice, "connect", lambda: fake)
    with client.websocket_connect("/voice", headers=LOCAL) as ws:
        ws.send_bytes(b"\x00\x01")  # the mic
        assert ws.receive_json() == {"type": "heard", "text": "Book a Goa trip next weekend"}
        # Live doesn't run anything itself: the browser runs the request like a typed question
        assert ws.receive_json() == {"type": "ask", "id": "c1", "request": "Book a Goa trip next weekend"}
        ws.send_json({"type": "result", "id": "c1", "text": "2 flights and a stay are on hold for your OK."})
        assert ws.receive_bytes() == b"\x01\x02"  # Orbit's voice
        assert ws.receive_json() == {"type": "said", "text": "Two flights are held for your OK."}
        assert ws.receive_json() == {"type": "turn_done"}
    assert fake.audio == [b"\x00\x01"]
    assert [(r.id, r.name, r.response) for r in fake.responses] == [
        ("c1", "ask_orbit", {"result": "2 flights and a stay are on hold for your OK."})]


def test_voice_has_no_tool_that_approves_or_pays():
    assert [main.agent.VOICE_TOOL["name"]] == ["ask_orbit"]
    assert "tap Approve" in main.agent.VOICE
    assert "Can I buy a table?" in main.agent.VOICE  # purchases go to Orbit, not "I can't check that"


def test_voice_needs_the_login_and_a_local_page(client, monkeypatch):
    monkeypatch.setattr(voice, "connect", FakeLive)
    with pytest.raises(WebSocketDisconnect) as signed_out:
        with TestClient(main.app).websocket_connect("/voice", headers=LOCAL) as ws:
            ws.receive_json()
    assert signed_out.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as elsewhere:  # another website can't open your mic session
        with client.websocket_connect("/voice", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert elsewhere.value.code == 4401


def test_a_request_heard_with_the_wake_word_goes_to_live_as_text(client, monkeypatch):
    fake = FakeLive()
    sent = []

    async def send_client_content(turns, turn_complete):
        sent.append((turns.parts[0].text, turn_complete))

    fake.send_client_content = send_client_content
    monkeypatch.setattr(voice, "connect", lambda: fake)
    with client.websocket_connect("/voice", headers=LOCAL) as ws:
        ws.send_json({"type": "text", "text": "can I buy a table"})
        assert ws.receive_json()["type"] == "heard"  # the fake carries on as if it heard it
    assert sent == [("can I buy a table", True)]
