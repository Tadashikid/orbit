import type { DecisionResult } from "./types";
// Talk to Orbit: mic -> 16 kHz 16-bit PCM -> /api/voice (Gemini Live, backend/voice.py) -> 24 kHz PCM -> speakers.
// Push to talk only: the mic is on between start() and stop(), never otherwise.
export type VoiceEvent =
  | { type: "heard" | "said"; text: string }
  | { type: "ask"; id: string; request: string }
  | { type: "interrupted" | "turn_done" | "closed" }
  | { type: "error"; text: string };
// Runs off the main thread: collects ~40 ms of mic audio (640 samples at 16 kHz) per message.
const WORKLET = `class OrbitMic extends AudioWorkletProcessor {
  constructor() { super(); this.buf = []; this.n = 0; }
  process(inputs) {
    const ch = inputs[0][0];
    if (ch) { this.buf.push(ch.slice(0)); this.n += ch.length; }
    if (this.n >= 640) {
      const out = new Float32Array(this.n); let o = 0;
      for (const b of this.buf) { out.set(b, o); o += b.length; }
      this.port.postMessage(out, [out.buffer]); this.buf = []; this.n = 0;
    }
    return true;
  }
}
registerProcessor("orbit-mic", OrbitMic);`;
export function toPcm16(samples: Float32Array): ArrayBuffer {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}
// What Orbit says back after running a spoken request: the verdict, and that holds wait for a tap.
export function voiceSummary(r: DecisionResult | null): string {
  if (!r) return "Orbit couldn't check that just now. Ask the user to try again.";
  const held = r.approvals.length;
  return [
    r.wire.headline,
    r.explanation && r.explanation !== r.wire.headline ? r.explanation : "",
    held ? `${held} option${held > 1 ? "s are" : " is"} on hold. The user taps Approve on screen to confirm; you can't.` : "",
  ].filter(Boolean).join(" ");
}
export class Voice {
  private ws?: WebSocket;
  private mic?: { ctx: AudioContext; stream: MediaStream };
  private out?: AudioContext;
  private next = 0;
  private playing: AudioBufferSourceNode[] = [];
  constructor(private onEvent: (e: VoiceEvent) => void) {}
  get connected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }
  private async open() {
    if (this.connected) return;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/voice`);
    ws.binaryType = "arraybuffer";
    await new Promise<void>((ok, fail) => {
      ws.onopen = () => ok();
      ws.onclose = (e) => fail(new Error(e.code === 4401 ? "Sign in again to use voice." : "Can't reach Orbit's voice."));
    });
    ws.onmessage = (m) => (typeof m.data === "string" ? this.onEvent(JSON.parse(m.data)) : this.play(m.data));
    ws.onclose = () => {
      this.stopMic();
      this.ws = undefined;
      this.onEvent({ type: "closed" });
    };
    this.ws = ws;
  }
  async start() {
    await this.open();
    this.hush(); // you're talking: Orbit stops
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    // ponytail: the browser resamples the mic to 16 kHz for us (Chrome / Edge); Firefox refuses mixed rates.
    const ctx = new AudioContext({ sampleRate: 16000 });
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })));
    const node = new AudioWorkletNode(ctx, "orbit-mic");
    node.port.onmessage = (m: MessageEvent<Float32Array>) => {
      if (this.connected) this.ws!.send(toPcm16(m.data));
    };
    ctx.createMediaStreamSource(stream).connect(node);
    this.mic = { ctx, stream };
  }
  // A request the wake word already heard ("Hey Orbit, can I buy a table?"): Live takes it as if spoken.
  async say(text: string) {
    await this.open();
    this.hush();
    this.send({ type: "text", text });
  }
  get listening() {
    return Boolean(this.mic);
  }
  // Seconds of Orbit's reply still queued to play (wake listening resumes after it, so Orbit can't wake itself).
  get playbackLeft() {
    return this.out ? Math.max(0, this.next - this.out.currentTime) : 0;
  }
  stop() {
    if (!this.mic) return;
    this.stopMic();
    this.send({ type: "end" });
  }
  result(id: string, text: string) {
    this.send({ type: "result", id, text });
  }
  hush() {
    for (const s of this.playing) {
      try {
        s.stop();
      } catch {
        /* already ended */
      }
    }
    this.playing = [];
    this.next = 0;
  }
  close() {
    this.stopMic();
    this.hush();
    this.ws?.close();
  }
  private stopMic() {
    this.mic?.stream.getTracks().forEach((t) => t.stop());
    void this.mic?.ctx.close();
    this.mic = undefined;
  }
  private send(m: object) {
    if (this.connected) this.ws!.send(JSON.stringify(m));
  }
  private play(data: ArrayBuffer) {
    this.out ??= new AudioContext({ sampleRate: 24000 });
    const pcm = new Int16Array(data);
    const buffer = this.out.createBuffer(1, pcm.length, 24000);
    const ch = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const src = this.out.createBufferSource();
    src.buffer = buffer;
    src.connect(this.out.destination);
    this.next = Math.max(this.next, this.out.currentTime); // queue chunks back to back
    src.start(this.next);
    this.next += buffer.duration;
    this.playing.push(src);
    src.onended = () => (this.playing = this.playing.filter((s) => s !== src));
  }
}
