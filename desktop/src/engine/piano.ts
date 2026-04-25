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

export function schedulePlayback(
  events: NoteEvent[],
  bpm: number,
  onNote?: (index: number) => void,
): () => void {
  const ctx = getAudioContext();
  const inst = piano;
  if (!inst) throw new Error("Piano not initialized");

  const quarterSec = 60 / bpm;
  const startTime = ctx.currentTime + 0.1;
  const timeouts: number[] = [];

  events.forEach((event, index) => {
    if (event.isRest || !event.pitches?.length) return;

    const time = startTime + event.offset * quarterSec;
    const duration = event.quarterLength * quarterSec;
    const velocity = 80;

    event.pitches.forEach((midi) => {
      inst.start({
        note: midiToName(midi),
        time,
        duration: Math.max(0.05, duration),
        velocity,
      });
    });

    if (onNote) {
      const delayMs = Math.max(0, (time - ctx.currentTime) * 1000);
      timeouts.push(
        window.setTimeout(() => onNote(index), delayMs),
      );
    }
  });

  return () => {
    timeouts.forEach((id) => clearTimeout(id));
    inst.stop();
  };
}
