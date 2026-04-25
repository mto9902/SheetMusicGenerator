import { useRef, useState, useCallback } from "react";
import { Route, Routes, Navigate } from "react-router-dom";

import { ChromeBar } from "@/components/ChromeBar";
import { CreatePage } from "@/pages/CreatePage";
import { ExercisePage } from "@/pages/ExercisePage";
import { LibraryPage } from "@/pages/LibraryPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { initPiano, schedulePlayback } from "@/engine/piano";
import type { NoteEvent } from "@shared/types";

export default function App() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const stopRef = useRef<(() => void) | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [noteEvents, setNoteEvents] = useState<NoteEvent[] | null>(null);
  const [bpm, setBpm] = useState<number>(92);
  const [isPlaying, setIsPlaying] = useState(false);

  const handleSetAudio = useCallback((url: string | null, events: NoteEvent[] | null, tempo: number) => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (stopRef.current) {
      stopRef.current();
      stopRef.current = null;
    }
    setAudioUrl(url);
    setNoteEvents(events);
    setBpm(tempo);
    setIsPlaying(false);
  }, []);

  const togglePlayback = useCallback(async () => {
    if (isPlaying) {
      if (stopRef.current) {
        stopRef.current();
        stopRef.current = null;
      }
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setIsPlaying(false);
      return;
    }

    if (noteEvents && noteEvents.length > 0) {
      try {
        await initPiano();
        const stop = schedulePlayback(noteEvents, bpm, () => {});
        stopRef.current = stop;
        setIsPlaying(true);

        // Auto-stop after estimated duration
        const lastEvent = noteEvents.reduce((max, e) =>
          e.offset + e.quarterLength > max.offset + max.quarterLength ? e : max
        , noteEvents[0]);
        const durationSec = (lastEvent.offset + lastEvent.quarterLength) * (60 / bpm) + 1;
        window.setTimeout(() => {
          if (stopRef.current) {
            stopRef.current();
            stopRef.current = null;
            setIsPlaying(false);
          }
        }, durationSec * 1000);
        return;
      } catch {
        // fall through to audio url
      }
    }

    if (audioUrl) {
      const audio = new Audio(audioUrl);
      audio.onended = () => setIsPlaying(false);
      audio.onpause = () => setIsPlaying(false);
      audio.onplay = () => setIsPlaying(true);
      audioRef.current = audio;
      audio.play().catch(() => {});
    }
  }, [audioUrl, noteEvents, bpm, isPlaying]);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-[#F5F5F7]">
      <ChromeBar
        audioUrl={audioUrl}
        isPlaying={isPlaying}
        onPlayPause={togglePlayback}
      />
      <main className="flex-1 relative overflow-hidden">
        <Routes>
          <Route path="/" element={<CreatePage onAudioChange={handleSetAudio} />} />
          <Route path="/create" element={<CreatePage onAudioChange={handleSetAudio} />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/exercise/:id" element={<ExercisePage onAudioChange={handleSetAudio} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
