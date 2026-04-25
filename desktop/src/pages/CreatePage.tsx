import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { NotationPanel } from "@/components/NotationPanel";
import { generateExercise } from "@/lib/api";
import { LAST_CREATE_DRAFT_KEY, type DesktopCreateDraft } from "@/lib/createDraft";
import { storage } from "@/storage";
import {
  configForMode,
  DEFAULT_CONFIG,
  DEFAULT_SETTINGS,
  EXERCISE_OPTIONS,
  formatGradeStageLabel,
  GRADE_PRESETS,
  nextSeed,
  normalizeGradeStage,
  tempoPresetToBpm,
  visibleGradeStages,
} from "@shared/options";
import { EMPTY_PRESET_SHUFFLE } from "@shared/presetGeneration";
import type {
  AppSettings,
  ExerciseConfig,
  ExerciseListItem,
  ExerciseMode,
  GradeStage,
  HandActivity,
  KeySignature,
  ReadingFocus,
  StoredExercise,
  TempoPreset,
  TimeSignature,
} from "@shared/types";

const STYLE_OPTIONS: Array<{
  value: ReadingFocus;
  label: string;
  description: string;
}> = [
  { value: "balanced", label: "Classical", description: "Steady, curriculum-friendly reading." },
  { value: "melodic", label: "Melody-first", description: "More phrase contour in the right hand." },
  { value: "harmonic", label: "Harmony focus", description: "More left-hand and interval awareness." },
];

const TEMPO_VALUES = EXERCISE_OPTIONS.tempoPresets.map((tempo) => tempo.value as TempoPreset);

function optionLabel<T extends string | number>(
  options: Array<{ value: T; label: string }>,
  value: T,
) {
  return options.find((option) => option.value === value)?.label ?? String(value);
}

function describeKey(keySignature: ExerciseConfig["keySignature"]) {
  return keySignature.endsWith("m")
    ? `${keySignature.slice(0, -1)} minor`
    : `${keySignature} major`;
}

function keyShortLabel(keySignature: string) {
  return keySignature.endsWith("m") ? keySignature.slice(0, -1) : keySignature;
}

function makeKeyOptions(grade: number) {
  return EXERCISE_OPTIONS.keySignatures
    .filter((candidate) => candidate.minGrade <= grade)
    .map((candidate) => ({
      value: candidate.value as KeySignature,
      label: candidate.label,
      type: candidate.type as "major" | "minor",
    }));
}

function buildSummary(config: ExerciseConfig) {
  const stageLabel = formatGradeStageLabel(config.gradeStage);
  const chips = [
    optionLabel(EXERCISE_OPTIONS.grades, config.grade),
    config.timeSignature,
    `${config.measureCount} bars`,
    describeKey(config.keySignature),
    `${tempoPresetToBpm(config.tempoPreset)} bpm`,
  ];

  if (stageLabel) {
    chips.splice(1, 0, stageLabel);
  }

  return chips;
}

export function CreatePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [config, setConfig] = useState<ExerciseConfig>(DEFAULT_CONFIG);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [activeExercise, setActiveExercise] = useState<StoredExercise | null>(null);
  const [recentExercises, setRecentExercises] = useState<ExerciseListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const keyOptions = useMemo(() => makeKeyOptions(config.grade), [config.grade]);
  const minorKeys = useMemo(() => keyOptions.filter((key) => key.type === "minor"), [keyOptions]);
  const measureOptions = useMemo(() => {
    const gradeMeta = GRADE_PRESETS.find((preset) => preset.grade === config.grade);
    const maxBars = gradeMeta?.piano.maxBars ?? DEFAULT_CONFIG.measureCount;
    return EXERCISE_OPTIONS.measureCounts.filter((value) => value <= maxBars);
  }, [config.grade]);
  const stageOptions = useMemo(
    () => visibleGradeStages(config.mode, config.grade),
    [config.grade, config.mode],
  );
  const summaryChips = useMemo(() => buildSummary(config), [config]);
  const bpm = tempoPresetToBpm(config.tempoPreset);
  const scaleMode = config.keySignature.endsWith("m") ? "minor" : "major";
  const densityValue =
    config.rightHandMotion === "stepwise" ? 0 : config.rightHandMotion === "small-leaps" ? 1 : 2;
  const activeStyle =
    STYLE_OPTIONS.find((style) => style.value === config.readingFocus) ?? STYLE_OPTIONS[0];

  useEffect(() => {
    let cancelled = false;

    async function loadState() {
      await storage.initialize();
      const appSettings = await storage.getSettings();
      const lastConfig = await storage.getLastGeneratorConfig();
      const lastExerciseId = await storage.getLastExerciseId();
      const lastDraft = await storage.getSettingValue<DesktopCreateDraft>(LAST_CREATE_DRAFT_KEY);
      const recent = await storage.getRecentExercises(5);

      const modeParam = searchParams.get("mode");
      const presetId = searchParams.get("presetId");
      const resume = searchParams.get("resume") === "1";
      const fresh = searchParams.get("fresh") === "1";

      let nextConfig: ExerciseConfig = {
        ...DEFAULT_CONFIG,
        handPosition: appSettings.preferredHandPosition,
        grade: appSettings.defaultGrade,
        readingFocus: appSettings.defaultReadingFocus,
      };

      if (modeParam === "rhythm") {
        nextConfig = {
          ...configForMode("rhythm"),
          handPosition: appSettings.preferredHandPosition,
          grade: appSettings.defaultGrade,
          readingFocus: appSettings.defaultReadingFocus,
        };
      } else if (resume && lastDraft) {
        nextConfig = lastDraft.config;
      } else if (presetId) {
        const preset = await storage.getPresetById(presetId);
        if (preset) {
          nextConfig = preset.config;
        }
      } else if (!fresh && lastDraft) {
        nextConfig = lastDraft.config;
      } else if (!fresh && lastConfig) {
        nextConfig = lastConfig;
      } else if (modeParam === "piano") {
        nextConfig = {
          ...nextConfig,
          mode: "piano",
        };
      }

      const normalized = normalizeConfig(nextConfig);
      const lastExercise =
        !fresh && lastExerciseId ? await storage.getExerciseById(lastExerciseId) : null;

      if (!cancelled) {
        setSettings(appSettings);
        setConfig(normalized);
        setActiveExercise(lastExercise);
        setRecentExercises(recent);
        setLoading(false);
      }
    }

    void loadState();

    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  function normalizeConfig(next: ExerciseConfig) {
    const normalized = { ...next };
    const gradeMeta =
      GRADE_PRESETS.find((preset) => preset.grade === normalized.grade) ?? GRADE_PRESETS[0];
    normalized.gradeStage = normalizeGradeStage(
      normalized.mode,
      normalized.grade,
      normalized.gradeStage,
    );

    if (normalized.measureCount > gradeMeta.piano.maxBars) {
      normalized.measureCount = gradeMeta.piano.maxBars;
    }

    if (!EXERCISE_OPTIONS.measureCounts.includes(normalized.measureCount)) {
      normalized.measureCount = Math.min(gradeMeta.piano.maxBars, DEFAULT_CONFIG.measureCount);
    }

    if (normalized.mode === "rhythm" || normalized.grade < 4) {
      normalized.allowAccidentals = false;
    }

    if (normalized.mode !== "piano") {
      normalized.gradeStage = undefined;
      normalized.keySignature = "C";
    }

    if (normalized.mode === "piano" && normalized.grade === 1) {
      if (normalized.gradeStage === "g1-pocket") {
        normalized.rightHandMotion = "stepwise";
      }
      if (normalized.leftHandPattern === "simple-broken") {
        normalized.leftHandPattern = "repeated";
      }
    }

    const availableKeys = makeKeyOptions(normalized.grade);
    if (!availableKeys.some((candidate) => candidate.value === normalized.keySignature)) {
      normalized.keySignature = availableKeys[0]?.value ?? "C";
    }

    return normalized;
  }

  function updateConfig(patch: Partial<ExerciseConfig>) {
    setConfig((current) => normalizeConfig({ ...current, ...patch }));
  }

  function updateMode(mode: ExerciseMode) {
    setConfig((current) =>
      normalizeConfig({
        ...current,
        ...configForMode(mode),
        mode,
        grade: current.grade,
        timeSignature: current.timeSignature,
        measureCount: current.measureCount,
        tempoPreset: current.tempoPreset,
        handPosition: current.handPosition,
        handActivity: current.handActivity,
        readingFocus: current.readingFocus,
        rightHandMotion: current.rightHandMotion,
        leftHandPattern: current.leftHandPattern,
        allowRests: current.allowRests,
      }),
    );
  }

  function updateGrade(grade: number) {
    updateConfig({
      grade,
      gradeStage: normalizeGradeStage(config.mode, grade, config.gradeStage),
    });
  }

  function updateScaleMode(nextMode: "major" | "minor") {
    if (nextMode === scaleMode) {
      return;
    }
    const nextKey = keyOptions.find((key) => key.type === nextMode)?.value;
    if (nextKey) {
      updateConfig({ keySignature: nextKey });
    }
  }

  function adjustTempo(direction: -1 | 1) {
    const currentIndex = TEMPO_VALUES.indexOf(config.tempoPreset);
    const nextIndex = Math.max(0, Math.min(TEMPO_VALUES.length - 1, currentIndex + direction));
    updateConfig({ tempoPreset: TEMPO_VALUES[nextIndex] ?? config.tempoPreset });
  }

  function updateDensity(value: number) {
    updateConfig({
      rightHandMotion:
        value <= 0 ? "stepwise" : value === 1 ? "small-leaps" : "mixed",
      leftHandPattern: value >= 2 && config.grade >= 2 ? "simple-broken" : config.leftHandPattern,
    });
  }

  async function handleGenerate() {
    try {
      setSubmitting(true);
      const normalized = normalizeConfig(config);
      const seed = nextSeed();
      const draft: DesktopCreateDraft = {
        config: normalized,
        presetMode: false,
        selectedTimeSignatures: [normalized.timeSignature],
        selectedKeySignatures: [normalized.keySignature],
        presetShuffle: EMPTY_PRESET_SHUFFLE,
      };
      await storage.setSettingValue(LAST_CREATE_DRAFT_KEY, draft);

      const generated = await generateExercise({ ...normalized, seed });
      const stored = await storage.saveGeneratedExercise(generated);
      const nextRecent = await storage.getRecentExercises(5);
      setConfig(normalized);
      setActiveExercise(stored);
      setRecentExercises(nextRecent);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Generation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function openExerciseInWorkbench(exerciseId: string) {
    const exercise = await storage.getExerciseById(exerciseId);
    if (exercise) {
      setActiveExercise(exercise);
      setConfig(normalizeConfig(exercise.config));
    }
  }

  async function saveActivePreset() {
    if (!activeExercise) {
      return;
    }

    const presetName = window.prompt("Preset name", `${activeExercise.title} preset`);
    if (!presetName) {
      return;
    }

    await storage.savePreset(presetName.trim(), activeExercise.config);
  }

  function resetToDefaults() {
    const nextSettings = settings ?? DEFAULT_SETTINGS;
    setConfig(
      normalizeConfig({
        ...DEFAULT_CONFIG,
        handPosition: nextSettings.preferredHandPosition,
        grade: nextSettings.defaultGrade,
        readingFocus: nextSettings.defaultReadingFocus,
      }),
    );
    setActiveExercise(null);
  }

  if (loading) {
    return (
      <div className="studio-empty">
        <p>Loading composition desk...</p>
      </div>
    );
  }

  return (
    <div className="compose-workbench">
      <aside className="studio-rail studio-rail--left" aria-label="Composition controls">
        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Composition</h2>
          </div>

          <div className="control-group">
            <span className="control-label">Time Signature</span>
            <div className="time-signature-picker" aria-label="Time signature">
              <div className="time-signature-display">
                <strong>{config.timeSignature.split("/")[0]}</strong>
                <strong>{config.timeSignature.split("/")[1]}</strong>
              </div>
              <div className="mini-pill-grid">
                {EXERCISE_OPTIONS.timeSignatures.map((time) => (
                  <button
                    key={time}
                    type="button"
                    className={`mini-pill ${config.timeSignature === time ? "mini-pill--active" : ""}`}
                    onClick={() => updateConfig({ timeSignature: time as TimeSignature })}
                  >
                    {time}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="control-group">
            <span className="control-label">Key</span>
            <div className="key-grid">
              {keyOptions.map((key) => (
                <button
                  key={key.value}
                  type="button"
                  className={`key-button ${config.keySignature === key.value ? "key-button--active" : ""}`}
                  onClick={() => updateConfig({ keySignature: key.value })}
                  title={key.label}
                >
                  {keyShortLabel(key.value)}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Character</h2>
          </div>

          <label className="select-field">
            <span className="control-label">Scale Mode</span>
            <select
              value={scaleMode}
              onChange={(event) => updateScaleMode(event.target.value as "major" | "minor")}
            >
              <option value="major">Major</option>
              <option value="minor" disabled={!minorKeys.length}>
                Minor{minorKeys.length ? "" : " (Grade 2+)"}
              </option>
            </select>
          </label>

          <label className="select-field">
            <span className="control-label">Style</span>
            <select
              value={config.readingFocus}
              onChange={(event) =>
                updateConfig({ readingFocus: event.target.value as ReadingFocus })
              }
            >
              {STYLE_OPTIONS.map((style) => (
                <option key={style.value} value={style.value}>
                  {style.label}
                </option>
              ))}
            </select>
            <small>{activeStyle.description}</small>
          </label>

          {config.mode === "piano" && config.grade === 1 ? (
            <div className="control-group">
              <span className="control-label">Grade 1 Stage</span>
              <div className="stage-switcher">
                {stageOptions.map((stage) => (
                  <button
                    key={stage.value}
                    type="button"
                    className={`stage-pill ${config.gradeStage === stage.value ? "stage-pill--active" : ""}`}
                    onClick={() => updateConfig({ gradeStage: stage.value as GradeStage })}
                    title={stage.hint}
                  >
                    {stage.label.replace("1", "")}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Structure</h2>
          </div>

          <div className="measure-dial" aria-label={`${config.measureCount} measures`}>
            <strong>{config.measureCount}</strong>
            <span>measures</span>
          </div>
          <div className="mini-pill-grid">
            {measureOptions.map((count) => (
              <button
                key={count}
                type="button"
                className={`mini-pill ${config.measureCount === count ? "mini-pill--active" : ""}`}
                onClick={() => updateConfig({ measureCount: count })}
              >
                {count}
              </button>
            ))}
          </div>

          <label className="range-field">
            <span className="control-label">Difficulty</span>
            <input
              type="range"
              min={1}
              max={5}
              step={1}
              value={config.grade}
              onChange={(event) => updateGrade(Number(event.target.value))}
            />
            <span className="range-field__labels">
              <small>Beginner</small>
              <strong>Grade {config.grade}</strong>
              <small>Virtuoso</small>
            </span>
          </label>

          <label className="range-field">
            <span className="control-label">Note Density</span>
            <input
              type="range"
              min={0}
              max={2}
              step={1}
              value={densityValue}
              onChange={(event) => updateDensity(Number(event.target.value))}
              disabled={config.grade === 1 && config.gradeStage === "g1-pocket"}
            />
            <span className="range-field__labels">
              <small>Open</small>
              <strong>{optionLabel(EXERCISE_OPTIONS.rightHandMotions, config.rightHandMotion)}</strong>
              <small>Busy</small>
            </span>
          </label>
        </section>
      </aside>

      <section
        className={`compose-stage ${activeExercise ? "compose-stage--score" : ""}`}
        aria-label="Composition preview"
      >
        {activeExercise ? (
          <div className="compose-score">
            <header className="compose-score__header">
              <div>
                <p className="eyebrow">Composed score</p>
                <h1>{activeExercise.title}</h1>
                <p>
                  {activeExercise.timeSignature} | {activeExercise.measureCount} bars | Grade{" "}
                  {activeExercise.grade}
                  {activeExercise.summary.stageLabel ? ` | ${activeExercise.summary.stageLabel}` : ""}
                </p>
              </div>
              <button
                type="button"
                className="compose-button compose-button--compact"
                onClick={handleGenerate}
                disabled={submitting}
              >
                {submitting ? "Composing..." : "Compose again"}
              </button>
            </header>
            <div className="score-paper score-paper--inline">
              <NotationPanel svg={activeExercise.svg} scale={settings?.notationScale ?? 1} />
            </div>
          </div>
        ) : (
          <div className="compose-stage__empty">
            <span className="compose-stage__note" aria-hidden="true">
              {"\u266a"}
            </span>
            <p>Select parameters and press Compose</p>
            <button
              type="button"
              className="compose-button"
              onClick={handleGenerate}
              disabled={submitting}
            >
              {submitting ? "Composing..." : "Compose"}
            </button>
            <div className="compose-chip-row">
              {summaryChips.map((chip) => (
                <span key={chip}>{chip}</span>
              ))}
            </div>
          </div>
        )}
      </section>

      <aside className="studio-rail studio-rail--right" aria-label="Output controls">
        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Instrument</h2>
          </div>
          <label className="select-field select-field--solo">
            <select
              value={config.mode}
              onChange={(event) => updateMode(event.target.value as ExerciseMode)}
            >
              <option value="piano">Piano</option>
              <option value="rhythm">Piano rhythm</option>
            </select>
          </label>
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Mix</h2>
          </div>
          <div className="mix-dial">
            <span>{config.handActivity === "both" ? "70%" : "50%"}</span>
          </div>
          <div className="segmented-control">
            {EXERCISE_OPTIONS.handActivities.map((activity) => (
              <button
                key={activity.value}
                type="button"
                className={
                  config.handActivity === activity.value ? "segmented-control__item--active" : ""
                }
                onClick={() => updateConfig({ handActivity: activity.value as HandActivity })}
              >
                {activity.value === "right-only"
                  ? "RH"
                  : activity.value === "left-only"
                    ? "LH"
                    : "Both"}
              </button>
            ))}
          </div>
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Tempo</h2>
          </div>
          <div className="tempo-stepper">
            <button type="button" onClick={() => adjustTempo(-1)} disabled={config.tempoPreset === TEMPO_VALUES[0]}>
              -
            </button>
            <strong>{bpm}</strong>
            <button
              type="button"
              onClick={() => adjustTempo(1)}
              disabled={config.tempoPreset === TEMPO_VALUES[TEMPO_VALUES.length - 1]}
            >
              +
            </button>
          </div>
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Output</h2>
          </div>
          <button
            type="button"
            className="output-preview"
            onClick={() => {
              if (!activeExercise && recentExercises[0]) {
                void openExerciseInWorkbench(recentExercises[0].exerciseId);
              }
            }}
          >
            <span />
            <span />
            <small>{activeExercise?.title ?? recentExercises[0]?.title ?? "No score yet"}</small>
          </button>
          {activeExercise ? (
            <div className="output-actions">
              <audio className="audio-player" controls preload="metadata" src={activeExercise.audioUrl}>
                Your browser cannot play this preview.
              </audio>
              <div className="button-row">
                <button
                  type="button"
                  className="button button--primary"
                  onClick={handleGenerate}
                  disabled={submitting}
                >
                  {submitting ? "Composing..." : "Regenerate"}
                </button>
                <button type="button" className="button button--ghost" onClick={saveActivePreset}>
                  Save preset
                </button>
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => navigate(`/exercise/${activeExercise.exerciseId}`)}
                >
                  Focus view
                </button>
              </div>
            </div>
          ) : null}
        </section>

        <section className="studio-card">
          <div className="studio-card__heading">
            <h2>Keyboard</h2>
          </div>
          <div className="keyboard-preview" aria-label={`${config.handPosition} position`}>
            {["C", "D", "E", "F", "G", "A", "B"].map((note) => (
              <span
                key={note}
                className={`white-key ${note === config.handPosition ? "white-key--active" : ""}`}
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
          <label className="select-field select-field--compact">
            <select
              value={config.handPosition}
              onChange={(event) =>
                updateConfig({ handPosition: event.target.value as ExerciseConfig["handPosition"] })
              }
            >
              {EXERCISE_OPTIONS.handPositions.map((position) => (
                <option key={position.value} value={position.value}>
                  {position.label}
                </option>
              ))}
            </select>
          </label>
        </section>
      </aside>

      <section className="history-dock" aria-label="Recent history">
        <button type="button" className="history-dock__tab" onClick={() => navigate("/library")}>
          History
          <span>^</span>
        </button>
        <div className="history-dock__items">
          {recentExercises.map((exercise) => (
            <button
              key={exercise.exerciseId}
              type="button"
              onClick={() => void openExerciseInWorkbench(exercise.exerciseId)}
            >
              <strong>{exercise.title}</strong>
              <span>
                Grade {exercise.grade} | {exercise.config.timeSignature}
              </span>
            </button>
          ))}
        </div>
      </section>

      <button type="button" className="studio-reset" onClick={resetToDefaults}>
        Reset
      </button>
    </div>
  );
}
