import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { NotationPanel } from "@/components/NotationPanel";
import { generateExercise } from "@/lib/api";
import { storage } from "@/storage";
import {
  formatDuration,
  formatHandActivityLabel,
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

function ProfileStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="profile-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
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
      <div className="studio-empty">
        <p>Loading score...</p>
      </div>
    );
  }

  if (!exercise || !settings) {
    return (
      <div className="studio-empty">
        <h1>Exercise not found</h1>
        <p>This score is not in local desktop history yet. Compose a fresh rep first.</p>
        <button type="button" className="compose-button" onClick={() => navigate("/")}>
          Back to Compose
        </button>
      </div>
    );
  }

  return (
    <div className="exercise-workbench">
      <aside className="studio-rail studio-rail--left" aria-label="Score details">
        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Composition</h2>
          </div>
          <ProfileStat label="Time" value={exercise.timeSignature} />
          <ProfileStat label="Key" value={exercise.config.keySignature} />
          <ProfileStat label="Measures" value={`${exercise.measureCount}`} />
          <ProfileStat label="Grade" value={`${exercise.grade}${stageLabel ? ` - ${stageLabel}` : ""}`} />
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Character</h2>
          </div>
          <ProfileStat label="Phrase shape" value={exercise.summary.phraseShapeLabel} />
          <ProfileStat label="Cadence" value={exercise.summary.cadenceLabel} />
          <ProfileStat label="Reading focus" value={exercise.summary.rhythmFocus.join(", ")} />
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Structure</h2>
          </div>
          <ProfileStat label="Hand position" value={formatHandPositionLabel(exercise.config.handPosition)} />
          <ProfileStat label="Hand mix" value={formatHandActivityLabel(exercise.config.handActivity)} />
          <ProfileStat label="Seed" value={exercise.summary.seedLabel} />
        </section>
      </aside>

      <section className="score-stage" aria-label="Generated score">
        <header className="score-stage__header">
          <div>
            <p className="eyebrow">Score</p>
            <h1>{exercise.title}</h1>
            <p>
              {formatModeLabel(exercise.config.mode)} | {exercise.timeSignature} |{" "}
              {exercise.measureCount} bars | Grade {exercise.grade}
              {stageLabel ? ` | ${stageLabel}` : ""}
            </p>
          </div>
          <div className="score-stage__actions">
            <button type="button" className="button button--ghost" onClick={() => navigate("/")}>
              Compose
            </button>
            <button type="button" className="button button--ghost" onClick={() => navigate("/library")}>
              History
            </button>
          </div>
        </header>

        {notice ? <div className="notice">{notice}</div> : null}

        <div className="score-paper">
          <NotationPanel svg={exercise.svg} scale={settings.notationScale} />
        </div>
      </section>

      <aside className="studio-rail studio-rail--right" aria-label="Playback and practice">
        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Instrument</h2>
          </div>
          <ProfileStat label="Patch" value={formatModeLabel(exercise.config.mode)} />
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Mix</h2>
          </div>
          <div className="mix-dial">
            <span>{exercise.config.handActivity === "both" ? "70%" : "50%"}</span>
          </div>
          <ProfileStat label="Hands" value={formatHandActivityLabel(exercise.config.handActivity)} />
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Tempo</h2>
          </div>
          <div className="tempo-stepper tempo-stepper--readonly">
            <strong>{bpm}</strong>
          </div>
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Playback</h2>
          </div>
          <audio className="audio-player" controls preload="metadata" src={exercise.audioUrl}>
            Your browser cannot play this preview.
          </audio>
          <div className="button-row">
            <button type="button" className="button button--primary" onClick={regenerateExercise} disabled={regenerating}>
              {regenerating ? "Regenerating..." : "Regenerate"}
            </button>
            <button type="button" className="button button--ghost" onClick={() => setPresetEditorOpen(true)}>
              Save preset
            </button>
          </div>
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Practice</h2>
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
                Start a timed practice run with count-in and optional pulse.
              </p>
              <button type="button" className="button button--primary" onClick={startPractice}>
                Start practice
              </button>
            </>
          )}
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Keyboard</h2>
          </div>
          <div className="keyboard-preview" aria-label={`${exercise.config.handPosition} position`}>
            {["C", "D", "E", "F", "G", "A", "B"].map((note) => (
              <span
                key={note}
                className={`white-key ${note === exercise.config.handPosition ? "white-key--active" : ""}`}
              >
                {note}
              </span>
            ))}
            <span className="black-key black-key--1" />
            <span className="black-key black-key--2" />
            <span className="black-key black-key--4" />
            <span className="black-key black-key--5" />
            <span className="black-key black-key--6" />
          </div>
        </section>
      </aside>

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
              Give this setup a reusable name so it appears in history.
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
      ) : null}
    </div>
  );
}
