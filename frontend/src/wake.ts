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
// "hey orbit", "OK Orbit,", "heyorbit": a greeting is required, so the word "orbit" alone in a sentence doesn't wake it.
const WAKE = /\b(?:hey|hi|hello|ok|okay)[\s,]*or ?bits?\b[\s,.!?]*(.*)$/i;
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
  ) {}
  start() {
    const Recognizer = recognition();
    if (this.on) return;
    if (!Recognizer) return this.onError("“Hey Orbit” needs Chrome or Edge.");
    this.on = true;
    const rec = new Recognizer();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = "en-IN";
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const rest = e.results[i].isFinal ? afterWake(e.results[i][0].transcript) : null;
        if (rest !== null) {
          this.stop();
          this.onWake(rest);
          return;
        }
      }
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        this.stop();
        this.onError("Allow the microphone to use “Hey Orbit”.");
      }
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
