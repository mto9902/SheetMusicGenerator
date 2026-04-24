import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { NotationPanel } from "@/components/NotationPanel";
import { generateExercise } from "@/lib/api";
import { storage } from "@/storage";
import {
  formatDuration,
  formatHandPositionLabel,
  formatModeLabel,
} from "@shared/format";
import { formatGradeStageLabel as formatConfigStageLabel, nextSeed } from "@shared/options";
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

function beatMs(bpm: number) {
  return Math.max(280, Math.round((60 / bpm) * 1000));
}

function countBeats(timeSignature: string) {
  return Number(timeSignature.split("/")[0]) || 4;
}

export function ExercisePage() {
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
  const [pulseIndex, setPulseIndex] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  const countTimerRef = useRef<number | null>(null);
  const practiceTimerRef = useRef<number | null>(null);
  const pulseTimerRef = useRef<number | null>(null);

  const bpm = exercise?.summary.bpm ?? 92;
  const stageLabel = exercise?.summary.stageLabel || formatConfigStageLabel(exercise?.config.gradeStage);
  const totalCountBeats = exercise ? countBeats(exercise.timeSignature) : 4;
  const pulseDots = useMemo(() => Array.from({ length: totalCountBeats }), [totalCountBeats]);

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
      }
    }

    void loadExercise();

    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    return () => {
      clearAllTimers();
    };
  }, []);

  useEffect(() => {
    if (!practiceStart) {
      if (practiceTimerRef.current) {
        window.clearInterval(practiceTimerRef.current);
        practiceTimerRef.current = null;
      }
      return;
    }

    practiceTimerRef.current = window.setInterval(() => {
      setPracticeSeconds(
        Math.floor((Date.now() - new Date(practiceStart).getTime()) / 1000),
      );
    }, 1000);

    return () => {
      if (practiceTimerRef.current) {
        window.clearInterval(practiceTimerRef.current);
        practiceTimerRef.current = null;
      }
    };
  }, [practiceStart]);

  useEffect(() => {
    if (!practiceStart || !settings?.metronomeDefault) {
      if (pulseTimerRef.current) {
        window.clearInterval(pulseTimerRef.current);
        pulseTimerRef.current = null;
      }
      return;
    }

    setPulseIndex(0);
    pulseTimerRef.current = window.setInterval(() => {
      setPulseIndex((current) => (current + 1) % totalCountBeats);
    }, beatMs(bpm));

    return () => {
      if (pulseTimerRef.current) {
        window.clearInterval(pulseTimerRef.current);
        pulseTimerRef.current = null;
      }
    };
  }, [bpm, practiceStart, settings?.metronomeDefault, totalCountBeats]);

  function clearAllTimers() {
    if (countTimerRef.current) {
      window.clearInterval(countTimerRef.current);
      countTimerRef.current = null;
    }
    if (practiceTimerRef.current) {
      window.clearInterval(practiceTimerRef.current);
      practiceTimerRef.current = null;
    }
    if (pulseTimerRef.current) {
      window.clearInterval(pulseTimerRef.current);
      pulseTimerRef.current = null;
    }
  }

  function beginPracticeNow() {
    setPulseIndex(0);
    setPracticeStart(new Date().toISOString());
    setPracticeSeconds(0);
    setNotice(null);
  }

  function startPractice() {
    if (!exercise || !settings) {
      return;
    }

    if (!settings.countInDefault) {
      beginPracticeNow();
      return;
    }

    setCountingIn(true);
    setCountBeat(totalCountBeats);
    countTimerRef.current = window.setInterval(() => {
      setCountBeat((current) => {
        if (current <= 1) {
          if (countTimerRef.current) {
            window.clearInterval(countTimerRef.current);
            countTimerRef.current = null;
          }
          setCountingIn(false);
          beginPracticeNow();
          return 0;
        }

        return current - 1;
      });
    }, beatMs(bpm));
  }

  async function finishPractice(rating: number) {
    if (!exercise || !practiceStart) {
      return;
    }

    const finishedAt = new Date().toISOString();
    await storage.savePracticeSession({
      id: `session-${Date.now().toString(36)}`,
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
    setPulseIndex(0);
    setRatingOpen(false);
    setNotice("Practice session saved to desktop history.");
  }

  async function handleSavePreset() {
    if (!exercise) {
      return;
    }

    await storage.savePreset(presetName.trim() || `${exercise.title} preset`, exercise.config);
    setPresetEditorOpen(false);
    setNotice("Preset saved to the desktop library.");
  }

  async function regenerateExercise() {
    if (!exercise) {
      return;
    }

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
      <div className="page">
        <div className="card card--centered">
          <p>Loading exercise...</p>
        </div>
      </div>
    );
  }

  if (!exercise || !settings) {
    return (
      <div className="page">
        <div className="card card--centered">
          <h1 className="page__title">Exercise not found</h1>
          <p className="empty-copy">
            This score is not in local desktop history yet. Generate a fresh rep first.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <p className="eyebrow">Exercise</p>
          <h1 className="page__title">{exercise.title}</h1>
          <p className="page__subtitle">
            {formatModeLabel(exercise.config.mode)} | {exercise.timeSignature} | {exercise.measureCount} bars | Grade {exercise.grade}
            {stageLabel ? ` | ${stageLabel}` : ""}
          </p>
        </div>
        <div className="page__actions">
          <button type="button" className="button button--ghost" onClick={() => navigate("/settings")}>
            Settings
          </button>
          <button type="button" className="button button--ghost" onClick={() => navigate("/library")}>
            Library
          </button>
        </div>
      </header>

      {notice ? <div className="notice">{notice}</div> : null}

      <div className="content-grid content-grid--wide">
        <section className="stack">
          <div className="card">
            <NotationPanel svg={exercise.svg} scale={settings.notationScale} />
          </div>

          <div className="card">
            <div className="card__heading">
              <h2>Reading profile</h2>
            </div>
            <div className="stat-grid">
              <div className="stat-card">
                <span>Phrase shape</span>
                <strong>{exercise.summary.phraseShapeLabel}</strong>
              </div>
              <div className="stat-card">
                <span>Cadence</span>
                <strong>{exercise.summary.cadenceLabel}</strong>
              </div>
              <div className="stat-card">
                <span>Harmony focus</span>
                <strong>{exercise.summary.harmonyFocus[0] || exercise.summary.handPositionLabel}</strong>
              </div>
              <div className="stat-card">
                <span>Technique focus</span>
                <strong>
                  {exercise.summary.techniqueFocus[0] ||
                    exercise.summary.rhythmFocus[0] ||
                    exercise.summary.coordinationLabel}
                </strong>
              </div>
            </div>
            <p className="detail-paragraph">
              {exercise.summary.handPositionLabel}
              {stageLabel ? ` | ${stageLabel}` : ""}
              {" | "}
              {exercise.summary.coordinationLabel} |{" "}
              {exercise.summary.rhythmFocus.join(", ")}
            </p>
          </div>
        </section>

        <aside className="stack stack--sticky">
          <section className="card card--accent">
            <p className="eyebrow eyebrow--light">Playback & actions</p>
            <audio className="audio-player" controls preload="metadata" src={exercise.audioUrl}>
              Your browser cannot play this preview.
            </audio>
            <div className="button-row">
              <button type="button" className="button button--light" onClick={regenerateExercise} disabled={regenerating}>
                {regenerating ? "Regenerating..." : "Regenerate"}
              </button>
              <button type="button" className="button button--light" onClick={() => setPresetEditorOpen(true)}>
                Save preset
              </button>
            </div>
          </section>

          <section className="card">
            <div className="card__heading">
              <h2>Practice status</h2>
            </div>
            {countingIn ? (
              <>
                <p className="meter-title">Count-in</p>
                <strong className="count-in-number">{countBeat}</strong>
              </>
            ) : practiceStart ? (
              <>
                <p className="meter-title">Practice running</p>
                <strong className="count-in-number">{formatDuration(practiceSeconds)}</strong>
                {settings.metronomeDefault ? (
                  <div className="pulse-row">
                    {pulseDots.map((_, index) => (
                      <span
                        key={index}
                        className={`pulse-dot ${index === pulseIndex ? "pulse-dot--active" : ""}`}
                      />
                    ))}
                  </div>
                ) : null}
                <button type="button" className="button button--primary" onClick={() => setRatingOpen(true)}>
                  Finish session
                </button>
              </>
            ) : (
              <>
                <p className="detail-paragraph">
                  Start a practice run to log time, use the count-in, and keep the desktop history meaningful.
                </p>
                <button type="button" className="button button--primary" onClick={startPractice}>
                  Start practice
                </button>
              </>
            )}
          </section>

          <section className="card">
            <div className="card__heading">
              <h2>Session defaults</h2>
            </div>
            <div className="summary-list">
              <div className="summary-row">
                <span>Notation scale</span>
                <strong>{settings.notationScale.toFixed(2)}x</strong>
              </div>
              <div className="summary-row">
                <span>Hand position</span>
                <strong>{formatHandPositionLabel(exercise.config.handPosition)}</strong>
              </div>
              {stageLabel ? (
                <div className="summary-row">
                  <span>Grade stage</span>
                  <strong>{stageLabel}</strong>
                </div>
              ) : null}
              <div className="summary-row">
                <span>Seed</span>
                <strong>{exercise.summary.seedLabel}</strong>
              </div>
            </div>
          </section>
        </aside>
      </div>

      {presetEditorOpen ? (
        <div className="modal">
          <div className="modal__card">
            <div className="card__heading">
              <h2>Save preset</h2>
              <button type="button" className="button button--ghost" onClick={() => setPresetEditorOpen(false)}>
                Close
              </button>
            </div>
            <p className="detail-paragraph">
              Give this desktop setup a reusable name so it appears in the library.
            </p>
            <input
              className="text-input"
              value={presetName}
              onChange={(event) => setPresetName(event.target.value)}
              placeholder="Warm-up in 4/4"
            />
            <div className="button-row">
              <button type="button" className="button button--primary" onClick={handleSavePreset}>
                Save preset
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {ratingOpen ? (
        <div className="modal">
          <div className="modal__card">
            <div className="card__heading">
              <h2>How did that feel?</h2>
              <button type="button" className="button button--ghost" onClick={() => setRatingOpen(false)}>
                Close
              </button>
            </div>
            <p className="detail-paragraph">
              Save the session with a quick self-rating to keep the desktop history useful.
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
      ) : null}
    </div>
  );
}
