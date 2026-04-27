import { SplendidGrandPiano } from "smplr";
import type { NoteEvent } from "@shared/types";

let piano: SplendidGrandPiano | null = null;
let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext {
  if (!audioCtx) {
    audioCtx = new AudioContext();
  }
  return audioCtx;
}

export async function initPiano(): Promise<SplendidGrandPiano> {
  if (piano) return piano;
  const ctx = getAudioContext();
  piano = new SplendidGrandPiano(ctx);
  await piano.load;
  return piano;
}

function midiToName(midi: number): string {
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const octave = Math.floor(midi / 12) - 1;
  const note = names[midi % 12];
  return `${note}${octave}`;
}

function dynamicToVelocity(dynamic?: string | null, scalar?: number | null): number {
  if (scalar !== undefined && scalar !== null) {
    return Math.max(1, Math.min(127, Math.round(scalar * 127)));
  }
  switch (dynamic) {
    case "pp":
      return 30;
    case "p":
      return 50;
    case "mp":
      return 70;
    case "mf":
      return 90;
    case "f":
      return 105;
    case "ff":
      return 120;
    default:
      return 80;
  }
}

function soundingDuration(event: NoteEvent, baseSec: number): number {
  let scale = 0.98;
  if (event.articulation === "staccato") scale = 0.55;
  else if (event.articulation === "tenuto") scale = 1.05;
  else if (event.articulation === "accent") scale = 0.95;

  // Slurred notes sustain longer
  if (event.slurId && event.slurRole !== "stop") {
    scale = Math.max(scale, 1.02);
  }

  return baseSec * scale;
}

export function schedulePlayback(
  events: NoteEvent[],
  bpm: number,
  onNote?: (index: number) => void,
): () => void {
  const ctx = getAudioContext();
  const inst = piano;
  if (!inst) throw new Error("Piano not initialized");

  const quarterSec = 60 / bpm;
  const startTime = ctx.currentTime + 0.12;
  const timeouts: number[] = [];
  const stopFns: Array<(time?: number) => void> = [];
  let stopped = false;

  events.forEach((event, index) => {
    if (event.isRest || !event.pitches?.length) return;

    const time = startTime + event.offset * quarterSec;
    const baseDuration = event.quarterLength * quarterSec;
    const duration = soundingDuration(event, baseDuration);
    const velocity = dynamicToVelocity(event.dynamic, event.dynamicScalar);

    event.pitches.forEach((midi) => {
      const stop = inst.start({
        note: midiToName(midi),
        time,
        duration: Math.max(0.04, duration),
        velocity,
      });
      stopFns.push(stop);
    });

    if (onNote) {
      const delayMs = Math.max(0, (time - ctx.currentTime) * 1000);
      timeouts.push(window.setTimeout(() => onNote(index), delayMs));
    }
  });

  return () => {
    if (stopped) return;
    stopped = true;

    timeouts.forEach((id) => clearTimeout(id));
    const stopAt = ctx.currentTime;
    stopFns.forEach((stop) => {
      try {
        stop(stopAt);
      } catch {
        // A voice may already have ended; keep stopping the rest.
      }
    });
    inst.stop();
  };
}
