import { useEffect, useRef, useState, useCallback } from "react";
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
  const autoStopRef = useRef<number | null>(null);
  const playbackTokenRef = useRef(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [noteEvents, setNoteEvents] = useState<NoteEvent[] | null>(null);
  const [bpm, setBpm] = useState<number>(92);
  const [isPlaying, setIsPlaying] = useState(false);

  const clearAutoStop = useCallback(() => {
    if (autoStopRef.current !== null) {
      window.clearTimeout(autoStopRef.current);
      autoStopRef.current = null;
    }
  }, []);

  const stopActivePlayback = useCallback(() => {
    playbackTokenRef.current += 1;
    clearAutoStop();

    if (stopRef.current) {
      stopRef.current();
      stopRef.current = null;
    }

    if (audioRef.current) {
      const audio = audioRef.current;
      audio.pause();
      try {
        audio.currentTime = 0;
      } catch {
        // Some browsers reject seeking before metadata loads.
      }
      audioRef.current = null;
    }

    setIsPlaying(false);
  }, [clearAutoStop]);

  const handleSetAudio = useCallback((url: string | null, events: NoteEvent[] | null, tempo: number) => {
    stopActivePlayback();
    setAudioUrl(url);
    setNoteEvents(events);
    setBpm(tempo);
  }, [stopActivePlayback]);

  const togglePlayback = useCallback(async () => {
    if (isPlaying) {
      stopActivePlayback();
      return;
    }

    stopActivePlayback();
    const playbackToken = playbackTokenRef.current + 1;
    playbackTokenRef.current = playbackToken;

    if (noteEvents && noteEvents.length > 0) {
      try {
        await initPiano();
        if (playbackTokenRef.current !== playbackToken) return;

        const stop = schedulePlayback(noteEvents, bpm, () => {});
        stopRef.current = stop;
        setIsPlaying(true);

        // Auto-stop after estimated duration
        const lastEvent = noteEvents.reduce((max, e) =>
          e.offset + e.quarterLength > max.offset + max.quarterLength ? e : max
        , noteEvents[0]);
        const durationSec = (lastEvent.offset + lastEvent.quarterLength) * (60 / bpm) + 1;
        autoStopRef.current = window.setTimeout(() => {
          if (playbackTokenRef.current !== playbackToken) return;

          if (stopRef.current) {
            stopRef.current();
            stopRef.current = null;
          }
          autoStopRef.current = null;
          setIsPlaying(false);
        }, durationSec * 1000);
        return;
      } catch {
        // fall through to audio url
      }
    }

    if (audioUrl) {
      const audio = new Audio(audioUrl);
      audio.onended = () => {
        if (playbackTokenRef.current !== playbackToken) return;
        audioRef.current = null;
        setIsPlaying(false);
      };
      audio.onpause = () => {
        if (playbackTokenRef.current !== playbackToken) return;
        setIsPlaying(false);
      };
      audio.onplay = () => {
        if (playbackTokenRef.current !== playbackToken) return;
        setIsPlaying(true);
      };
      audioRef.current = audio;
      audio.play().catch(() => {
        if (playbackTokenRef.current !== playbackToken) return;
        audioRef.current = null;
        setIsPlaying(false);
      });
    }
  }, [audioUrl, noteEvents, bpm, isPlaying, stopActivePlayback]);

  useEffect(() => {
    return () => stopActivePlayback();
  }, [stopActivePlayback]);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-[#F1F1F1]">
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
