"""Voice: a WebSocket between the browser and a Gemini Live session (GET /voice, behind the demo login).

Browser -> server   binary: mic audio, 16-bit PCM, 16 kHz, mono
                    {"type": "end"}: the user stopped talking
                    {"type": "text", "text"}: a request already heard by the wake word ("Hey Orbit, can I buy a table?")
                    {"type": "result", "id", "text"}: what Orbit answered for an "ask"
Server -> browser   binary: Orbit's voice, 16-bit PCM, 24 kHz, mono
                    {"type": "heard" | "said", "text"}: live transcripts of the user and of Orbit
                    {"type": "ask", "id", "request"}: run this through Orbit exactly like a typed question
                    {"type": "interrupted" | "turn_done"}, {"type": "error", "text"}

Gemini Live is only the ears and the voice. Its one tool, ask_orbit, hands the request to the browser, which runs it
through the same agent, Guardian and engine as typing (cards and approval cards included) and sends back a summary
to speak. It has no tool that approves, confirms or pays: that stays a tap on screen.
"""
import asyncio
import json
import os

from google import genai
from google.genai import types

import agent

MODEL = os.getenv("GEMINI_LIVE_MODEL") or "gemini-3.8-live"  # tested: hears the request and calls ask_orbit with it
ASK_TIMEOUT_S = 120  # a booking runs the whole plan plus Duffel holds


def connect():
    """A Gemini Live session (async context manager). Tests pass their own."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY in .env")
    t = agent.VOICE_TOOL
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"], system_instruction=agent.VOICE,
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(
            name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"])])],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    return genai.Client(api_key=key).aio.live.connect(model=MODEL, config=config)


async def bridge(ws):
    """Pump audio both ways until either side closes. Every ask_orbit call goes to the browser and back."""
    pending, tasks = {}, set()
    async with connect() as live:

        async def answer(call):
            if call.name != agent.VOICE_TOOL["name"]:
                response = {"error": "unknown tool"}
            else:
                pending[call.id] = asyncio.get_running_loop().create_future()
                await ws.send_json({"type": "ask", "id": call.id, "request": str((call.args or {}).get("request", ""))[:500]})
                try:
                    response = {"result": await asyncio.wait_for(pending[call.id], ASK_TIMEOUT_S)}
                except TimeoutError:
                    response = {"error": "Orbit didn't answer in time"}
                finally:
                    pending.pop(call.id, None)
            await live.send_tool_response(function_responses=[
                types.FunctionResponse(id=call.id, name=call.name, response=response)])

        async def up():  # browser -> Gemini
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes"):
                    await live.send_realtime_input(audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                elif msg.get("text"):
                    m = json.loads(msg["text"])
                    if m.get("type") == "end":
                        await live.send_realtime_input(audio_stream_end=True)
                    elif m.get("type") == "text" and str(m.get("text", "")).strip():  # "Hey Orbit, <request>" in one go
                        await live.send_client_content(turns=types.Content(
                            role="user", parts=[types.Part(text=str(m["text"])[:500])]), turn_complete=True)
                    elif m.get("type") == "result" and (f := pending.get(m.get("id"))) and not f.done():
                        f.set_result(str(m.get("text", ""))[:2000])

        async def down():  # Gemini -> browser
            while True:  # receive() ends after each turn
                async for r in live.receive():
                    if r.tool_call:
                        for call in r.tool_call.function_calls:
                            task = asyncio.create_task(answer(call))
                            tasks.add(task)
                            task.add_done_callback(tasks.discard)
                    sc = r.server_content
                    if not sc:
                        continue
                    for part in (sc.model_turn.parts if sc.model_turn else []):
                        if part.inline_data and part.inline_data.data:
                            await ws.send_bytes(part.inline_data.data)
                    for kind, t in (("heard", sc.input_transcription), ("said", sc.output_transcription)):
                        if t and t.text:
                            await ws.send_json({"type": kind, "text": t.text})
                    if sc.interrupted:
                        await ws.send_json({"type": "interrupted"})
                    if sc.turn_complete:
                        await ws.send_json({"type": "turn_done"})

        pumps = [asyncio.create_task(up()), asyncio.create_task(down())]
        done, rest = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        for t in [*rest, *tasks]:
            t.cancel()
        for t in done:
            t.result()  # surface an error from either side
