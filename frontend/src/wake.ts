// "Hey Orbit": listens for the wake phrase with the browser's own speech recognition, only while the switch is on.
// Chrome / Edge send that audio to Google / Microsoft to transcribe. It stops as soon as it hears the phrase, so the
// rest of the conversation goes through Orbit's voice (src/voice.ts) as usual.
interface Recognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  abort(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
const recognition = () => {
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition) as (new () => Recognition) | undefined;
};
export const wakeSupported = () => typeof window !== "undefined" && Boolean(recognition());
// "hey orbit", "OK Orbit,", "heyorbit", or "Orbit, ..." at the very start. The word "orbit" in the middle of a sentence
// doesn't wake it. Browsers often write the name as "Arbit", "or bit", "Orbits": those count too.
const NAME = String.raw`(?:or[ -]?bits?|arbits?|aurbit|orbet|orbid|orbitt)`;
const WAKE = new RegExp(String.raw`(?:^|\b(?:hey|hi|hello|ok|okay)[\s,]*)${NAME}\b[\s,.!?]*(.*)$`, "i");
// What came after the wake phrase ("" if nothing), or null if it wasn't said.
export function afterWake(transcript: string): string | null {
  const m = WAKE.exec(transcript);
  return m ? m[1].trim() : null;
}
export class WakeWord {
  private rec?: Recognition;
  private on = false;
  constructor(
    private onWake: (rest: string) => void,
    private onError: (message: string) => void,
    private onHeard: (transcript: string) => void = () => undefined, // what the browser hears, shown under the switch
  ) {}
  start() {
    const Recognizer = recognition();
    if (this.on) return;
    if (!Recognizer) return this.onError("“Hey Orbit” needs Chrome or Edge.");
    this.on = true;
    const rec = new Recognizer();
    rec.continuous = true;
    rec.interimResults = true; // so the "Heard:" line updates as you speak; only finished phrases can wake it
    rec.lang = "en-IN";
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const said = e.results[i][0].transcript;
        this.onHeard(said);
        const rest = e.results[i].isFinal ? afterWake(said) : null;
        if (rest !== null) {
          this.stop();
          this.onWake(rest);
          return;
        }
      }
    };
    rec.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return; // silence: it just listens again
      this.stop();
      this.onError(e.error === "not-allowed" || e.error === "service-not-allowed"
        ? "Allow the microphone to use “Hey Orbit”."
        : `“Hey Orbit” stopped listening (${e.error}). Turn it on again${e.error === "network" ? ": your browser's speech service is unreachable" : ""}.`);
    };
    rec.onend = () => {
      if (!this.on) return;
      try {
        rec.start(); // the browser stops after a silence: keep listening while the switch is on
      } catch {
        /* already starting */
      }
    };
    this.rec = rec;
    rec.start();
  }
  stop() {
    this.on = false;
    this.rec?.abort();
    this.rec = undefined;
  }
}
