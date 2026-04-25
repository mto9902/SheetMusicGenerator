import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Play, RotateCcw, Bookmark, ArrowLeft, CheckCircle } from "lucide-react";

import { NotationPanel } from "@/components/NotationPanel";
import { generateExercise } from "@/lib/api";
import { storage } from "@/storage";
import {
  formatGradeStageLabel as formatConfigStageLabel,
  nextSeed,
} from "@shared/options";
import {
  formatDuration,
  formatHandActivityLabel,
  formatHandPositionLabel,
  formatModeLabel,
} from "@shared/format";
import {
  normalizePresetShuffle,
  resolvePresetConfigForRun,
} from "@shared/presetGeneration";
import type {
  AppSettings,
  ExerciseGenerationContext,
  KeySignature,
  PresetShuffleState,
  StoredExercise,
  TimeSignature,
} from "@shared/types";

type LastCreateDraft = {
  selectedTimeSignatures: TimeSignature[];
  selectedKeySignatures: KeySignature[];
  presetMode: boolean;
  presetShuffle?: PresetShuffleState;
};

const LAST_CREATE_DRAFT_KEY = "desktop_last_create_draft";

function ProfileStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[#F5F5F7] last:border-0">
      <span className="text-xs text-[#8E8E93] font-medium">{label}</span>
      <span className="text-sm text-[#1C1C1E] font-semibold">{value}</span>
    </div>
  );
}

interface ExercisePageProps {
  onAudioChange?: (url: string | null, noteEvents: import("@shared/types").NoteEvent[] | null, bpm: number) => void;
}

export function ExercisePage({ onAudioChange }: ExercisePageProps) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [exercise, setExercise] = useState<StoredExercise | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [presetEditorOpen, setPresetEditorOpen] = useState(false);
  const [ratingOpen, setRatingOpen] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [countingIn, setCountingIn] = useState(false);
  const [countBeat, setCountBeat] = useState(0);
  const [practiceStart, setPracticeStart] = useState<string | null>(null);
  const [practiceSeconds, setPracticeSeconds] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const bpm = exercise?.summary.bpm ?? 92;
  const stageLabel = exercise?.summary.stageLabel || formatConfigStageLabel(exercise?.config.gradeStage);

  useEffect(() => {
    let cancelled = false;

    async function loadExercise() {
      if (!id) {
        setLoading(false);
        return;
      }

      await storage.initialize();
      const [nextExercise, nextSettings] = await Promise.all([
        storage.getExerciseById(id),
        storage.getSettings(),
      ]);

      if (!cancelled) {
        setExercise(nextExercise);
        setSettings(nextSettings);
        setPresetName(nextExercise ? `${nextExercise.title} preset` : "My desktop preset");
        setLoading(false);
        onAudioChange?.(
          nextExercise?.audioUrl ?? null,
          nextExercise?.noteEvents ?? null,
          nextExercise?.summary.bpm ?? 92,
        );
      }
    }

    void loadExercise();

    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!practiceStart) {
      setPracticeSeconds(0);
      return;
    }
    const interval = setInterval(() => {
      setPracticeSeconds(
        Math.floor((Date.now() - new Date(practiceStart).getTime()) / 1000),
      );
    }, 1000);
    return () => clearInterval(interval);
  }, [practiceStart]);

  function beginPracticeNow() {
    setPracticeStart(new Date().toISOString());
    setPracticeSeconds(0);
    setNotice(null);
  }

  function startPractice() {
    if (!exercise || !settings) return;

    if (!settings.countInDefault) {
      beginPracticeNow();
      return;
    }

    const beats = Number(exercise.timeSignature.split("/")[0]) || 4;
    setCountingIn(true);
    setCountBeat(beats);
    const interval = setInterval(() => {
      setCountBeat((current) => {
        if (current <= 1) {
          clearInterval(interval);
          setCountingIn(false);
          beginPracticeNow();
          return 0;
        }
        return current - 1;
      });
    }, Math.max(280, Math.round((60 / bpm) * 1000)));
  }

  async function finishPractice(rating: number) {
    if (!exercise || !practiceStart) return;

    const finishedAt = new Date().toISOString();
    await storage.savePracticeSession({
      id: `session-${new Date(finishedAt).getTime().toString(36)}`,
      exerciseId: exercise.exerciseId,
      presetId: null,
      title: exercise.title,
      startedAt: practiceStart,
      finishedAt,
      selfRating: rating,
      durationSeconds: Math.max(
        1,
        Math.floor(
          (new Date(finishedAt).getTime() - new Date(practiceStart).getTime()) / 1000,
        ),
      ),
    });

    setPracticeStart(null);
    setPracticeSeconds(0);
    setRatingOpen(false);
    setNotice("Practice session saved to desktop history.");
  }

  async function handleSavePreset() {
    if (!exercise) return;
    await storage.savePreset(presetName.trim() || `${exercise.title} preset`, exercise.config);
    setPresetEditorOpen(false);
    setNotice("Preset saved to the desktop library.");
  }

  async function regenerateExercise() {
    if (!exercise) return;

    try {
      setRegenerating(true);
      const seed = nextSeed();
      let requestConfig = exercise.config;
      let nextGenerationContext: ExerciseGenerationContext | null =
        exercise.generationContext ?? null;

      if (!nextGenerationContext) {
        const [lastExerciseId, lastCreateDraft] = await Promise.all([
          storage.getLastExerciseId(),
          storage.getSettingValue<LastCreateDraft>(LAST_CREATE_DRAFT_KEY),
        ]);
        if (
          lastExerciseId === exercise.exerciseId &&
          lastCreateDraft &&
          lastCreateDraft.presetMode
        ) {
          nextGenerationContext = {
            presetMode: true,
            selectedTimeSignatures: lastCreateDraft.selectedTimeSignatures,
            selectedKeySignatures: lastCreateDraft.selectedKeySignatures,
            presetShuffle: lastCreateDraft.presetShuffle ?? {
              timeBag: [],
              keyBag: [],
              lastTimeSignature: null,
              lastKeySignature: null,
            },
          };
        }
      }

      if (nextGenerationContext?.presetMode) {
        const normalizedShuffle = normalizePresetShuffle(
          exercise.config,
          nextGenerationContext.selectedTimeSignatures,
          nextGenerationContext.selectedKeySignatures,
          nextGenerationContext.presetShuffle,
        );
        const resolved = resolvePresetConfigForRun(
          exercise.config,
          seed,
          nextGenerationContext.selectedTimeSignatures,
          nextGenerationContext.selectedKeySignatures,
          normalizedShuffle,
          false,
        );
        requestConfig = resolved.requestConfig;
        nextGenerationContext = {
          ...nextGenerationContext,
          presetShuffle: resolved.nextPresetShuffle,
        };
      }

      const nextExercise = await generateExercise({
        ...requestConfig,
        seed,
      });

      await storage.saveGeneratedExercise({
        ...nextExercise,
        generationContext: nextGenerationContext,
      });

      navigate(`/exercise/${nextExercise.exerciseId}`);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Could not regenerate the exercise.");
    } finally {
      setRegenerating(false);
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-sm text-[#8E8E93]">Loading score...</p>
      </div>
    );
  }

  if (!exercise || !settings) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-4 p-8">
        <h1 className="text-2xl font-bold text-[#1C1C1E]">Exercise not found</h1>
        <p className="text-sm text-[#8E8E93] text-center max-w-sm">
          This score is not in local desktop history yet. Compose a fresh rep first.
        </p>
        <button type="button" className="btn-primary px-5 py-2.5" onClick={() => navigate("/")}>
          Back to Compose
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex relative overflow-hidden">
      {/* Left - Details */}
      <div className="p-4 pb-16 shrink-0 overflow-y-auto scrollbar-hide">
        <div className="w-[260px] flex flex-col gap-3">
          <div className="surface-card p-5">
            <h3 className="text-sm font-semibold text-[#1C1C1E] mb-3">Composition</h3>
            <ProfileStat label="Time" value={exercise.timeSignature} />
            <ProfileStat label="Key" value={exercise.config.keySignature} />
            <ProfileStat label="Measures" value={`${exercise.measureCount}`} />
            <ProfileStat label="Grade" value={`${exercise.grade}${stageLabel ? ` - ${stageLabel}` : ""}`} />
          </div>

          <div className="surface-card p-5">
            <h3 className="text-sm font-semibold text-[#1C1C1E] mb-3">Character</h3>
            <ProfileStat label="Phrase shape" value={exercise.summary.phraseShapeLabel} />
            <ProfileStat label="Cadence" value={exercise.summary.cadenceLabel} />
            <ProfileStat label="Reading focus" value={exercise.summary.rhythmFocus.join(", ")} />
          </div>

          <div className="surface-card p-5">
            <h3 className="text-sm font-semibold text-[#1C1C1E] mb-3">Structure</h3>
            <ProfileStat label="Hand position" value={formatHandPositionLabel(exercise.config.handPosition)} />
            <ProfileStat label="Hand mix" value={formatHandActivityLabel(exercise.config.handActivity)} />
            <ProfileStat label="Seed" value={exercise.summary.seedLabel} />
          </div>
        </div>
      </div>

      {/* Center - Score */}
      <div className="flex-1 p-4 pb-16 min-w-0 overflow-hidden">
        <div className="h-full flex flex-col">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <p className="text-xs text-[#8E8E93] uppercase tracking-widest font-bold mb-1">Score</p>
              <h1 className="text-2xl font-bold text-[#1C1C1E] tracking-tight">{exercise.title}</h1>
              <p className="text-sm text-[#8E8E93] mt-1">
                {formatModeLabel(exercise.config.mode)} | {exercise.timeSignature} | {exercise.measureCount} bars | Grade {exercise.grade}
                {stageLabel ? ` | ${stageLabel}` : ""}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button type="button" className="btn-secondary px-3 py-2 text-xs" onClick={() => navigate("/")}>
                <ArrowLeft size={14} className="inline mr-1" />
                Compose
              </button>
              <button type="button" className="btn-secondary px-3 py-2 text-xs" onClick={() => navigate("/library")}>
                History
              </button>
            </div>
          </div>

          {notice ? <div className="notice mb-4">{notice}</div> : null}

          <div className="flex-1 overflow-y-auto scrollbar-hide">
            <div className="notation-paper">
              <NotationPanel svg={exercise.svg} scale={settings.notationScale} />
            </div>
          </div>
        </div>
      </div>

      {/* Right - Playback & Practice */}
      <div className="p-4 pb-16 shrink-0 overflow-y-auto scrollbar-hide">
        <div className="w-60 flex flex-col gap-3">
          <div className="surface-card p-5">
            <h3 className="text-sm font-semibold text-[#1C1C1E] mb-3">Playback</h3>
            <audio
              className="audio-player mb-3"
              controls
              preload="metadata"
              src={exercise.audioUrl}
            >
              Your browser cannot play this preview.
            </audio>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-primary flex-1 text-xs py-2"
                onClick={regenerateExercise}
                disabled={regenerating}
              >
                <RotateCcw size={14} className="inline mr-1" />
                {regenerating ? "Regenerating..." : "Regenerate"}
              </button>
              <button
                type="button"
                className="btn-secondary px-3 py-2 text-xs"
                onClick={() => setPresetEditorOpen(true)}
              >
                <Bookmark size={14} />
              </button>
            </div>
          </div>

          <div className="surface-card p-5">
            <h3 className="text-sm font-semibold text-[#1C1C1E] mb-3">Practice</h3>
            {countingIn ? (
              <div className="flex flex-col items-center gap-2 py-4">
                <p className="text-xs text-[#8E8E93] uppercase tracking-widest font-bold">Count-in</p>
                <motion.span
                  className="text-5xl font-bold text-[#1C1C1E]"
                  key={countBeat}
                  initial={{ scale: 1.5, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ duration: 0.2 }}
                >
                  {countBeat}
                </motion.span>
              </div>
            ) : practiceStart ? (
              <div className="flex flex-col items-center gap-3 py-2">
                <p className="text-xs text-[#8E8E93] uppercase tracking-widest font-bold">Practice running</p>
                <span className="text-3xl font-bold text-[#1C1C1E]" style={{ fontFamily: '"SF Mono", Monaco, monospace' }}>
                  {formatDuration(practiceSeconds)}
                </span>
                <button
                  type="button"
                  className="btn-primary w-full text-xs py-2"
                  onClick={() => setRatingOpen(true)}
                >
                  <CheckCircle size={14} className="inline mr-1" />
                  Finish session
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 py-2">
                <p className="text-xs text-[#8E8E93] text-center leading-relaxed">
                  Start a timed practice run with count-in and optional pulse.
                </p>
                <button type="button" className="btn-primary w-full text-xs py-2" onClick={startPractice}>
                  <Play size={14} className="inline mr-1" />
                  Start practice
                </button>
              </div>
            )}
          </div>

          <div className="surface-card p-5">
            <h3 className="text-sm font-semibold text-[#1C1C1E] mb-3">Keyboard</h3>
            <div className="flex justify-center">
              <div className="relative flex">
                {["C", "D", "E", "F", "G", "A", "B"].map((note) => (
                  <div
                    key={note}
                    className={`piano-white relative w-7 h-14 flex items-end justify-center pb-1 ${
                      note === exercise.config.handPosition ? "active" : ""
                    }`}
                  >
                    <span className="text-[7px] text-[#C7C7CC]">{note}</span>
                  </div>
                ))}
                <div className="absolute top-0 left-0 flex">
                  {[null, "C#", "D#", null, "F#", "G#", "A#"].map((note, i) => {
                    if (!note) return <div key={`gap-${i}`} className="w-7" />;
                    return (
                      <div
                        key={note}
                        className="piano-black absolute w-[14px] h-9"
                        style={{ left: i * 28 + 18 }}
                      />
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Preset Modal */}
      {presetEditorOpen && (
        <div className="modal">
          <div className="modal__card">
            <div className="flex items-start justify-between gap-4 mb-2">
              <h2 className="text-lg font-bold text-[#1C1C1E]">Save preset</h2>
              <button type="button" className="btn-secondary px-2 py-1 text-xs" onClick={() => setPresetEditorOpen(false)}>
                Close
              </button>
            </div>
            <p className="text-sm text-[#8E8E93] leading-relaxed">
              Give this setup a reusable name so it appears in history.
            </p>
            <input
              className="clean-input w-full h-10 px-3 text-sm"
              value={presetName}
              onChange={(e) => setPresetName(e.target.value)}
              placeholder="Warm-up in 4/4"
            />
            <button type="button" className="btn-primary w-full text-xs py-2.5" onClick={handleSavePreset}>
              Save preset
            </button>
          </div>
        </div>
      )}

      {/* Rating Modal */}
      {ratingOpen && (
        <div className="modal">
          <div className="modal__card">
            <div className="flex items-start justify-between gap-4 mb-2">
              <h2 className="text-lg font-bold text-[#1C1C1E]">How did that feel?</h2>
              <button type="button" className="btn-secondary px-2 py-1 text-xs" onClick={() => setRatingOpen(false)}>
                Close
              </button>
            </div>
            <p className="text-sm text-[#8E8E93] leading-relaxed">
              Save the session with a quick self-rating to keep history useful.
            </p>
            <div className="rating-grid">
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  key={value}
                  type="button"
                  className="pill pill--large"
                  onClick={() => void finishPractice(value)}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
