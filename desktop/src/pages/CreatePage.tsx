import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ChoicePills, MultiChoicePills, type ChoiceOption } from "@/components/ChoicePills";
import { generateExercise } from "@/lib/api";
import { LAST_CREATE_DRAFT_KEY, type DesktopCreateDraft } from "@/lib/createDraft";
import { storage } from "@/storage";
import {
  configForMode,
  DEFAULT_CONFIG,
  DEFAULT_SETTINGS,
  EXERCISE_OPTIONS,
  GRADE_PRESETS,
  nextSeed,
} from "@shared/options";
import {
  EMPTY_PRESET_SHUFFLE,
  normalizeKeySelections,
  normalizePresetShuffle,
  normalizeTimeSelections,
  recommendedPresetMeasureCount,
  resolvePresetConfigForRun,
} from "@shared/presetGeneration";
import type {
  AppSettings,
  ExerciseConfig,
  ExerciseMode,
  KeySignature,
  PresetShuffleState,
  ReadingFocus,
  TempoPreset,
  TimeSignature,
} from "@shared/types";

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

function toggleItem<T extends string>(items: T[], value: T): T[] {
  if (items.includes(value)) {
    const next = items.filter((item) => item !== value) as T[];
    return next.length ? next : [...items];
  }
  return [...items, value];
}

function buildSummary(config: ExerciseConfig, presetMode: boolean, selectedTimes: TimeSignature[], selectedKeys: KeySignature[]) {
  if (config.mode === "rhythm") {
    return {
      lead: `Desktop rhythm rep in ${config.timeSignature} with ${config.measureCount} bars at ${config.tempoPreset} tempo.`,
      detail: "This keeps pitch fixed so the session can stay on pulse, subdivision, and timing.",
      chips: [`Grade ${config.grade}`, config.timeSignature, `${config.measureCount} bars`, optionLabel(EXERCISE_OPTIONS.tempoPresets, config.tempoPreset)],
    };
  }

  if (presetMode) {
    const times = normalizeTimeSelections(config, selectedTimes).join(", ");
    const keys = normalizeKeySelections(config, selectedKeys).map(describeKey).join(", ");
    return {
      lead: `Guided piano rotation across ${times} and ${keys}.`,
      detail: "Desktop preset mode keeps the grade, tempo, and hand position stable while rotating meter, key, and texture choices for you.",
      chips: [
        `Grade ${config.grade}`,
        `${recommendedPresetMeasureCount(config.grade)} bars`,
        optionLabel(EXERCISE_OPTIONS.tempoPresets, config.tempoPreset),
        `${config.handPosition} position`,
      ],
    };
  }

  return {
    lead: `Custom ${describeKey(config.keySignature)} reading rep with ${config.rightHandMotion} motion.`,
    detail: "Custom setup lets you pin the exact musical shape, coordination style, and left-hand role before generating.",
    chips: [
      `Grade ${config.grade}`,
      config.timeSignature,
      `${config.measureCount} bars`,
      optionLabel(EXERCISE_OPTIONS.tempoPresets, config.tempoPreset),
      `${config.handPosition} position`,
    ],
  };
}

export function CreatePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [config, setConfig] = useState<ExerciseConfig>(DEFAULT_CONFIG);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [presetMode, setPresetMode] = useState(true);
  const [selectedTimeSignatures, setSelectedTimeSignatures] = useState<TimeSignature[]>([
    DEFAULT_CONFIG.timeSignature,
  ]);
  const [selectedKeySignatures, setSelectedKeySignatures] = useState<KeySignature[]>([
    DEFAULT_CONFIG.keySignature,
  ]);
  const [presetShuffle, setPresetShuffle] = useState<PresetShuffleState>(EMPTY_PRESET_SHUFFLE);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const measureOptions = useMemo(() => {
    const gradeMeta = GRADE_PRESETS.find((preset) => preset.grade === config.grade);
    const maxBars = gradeMeta?.piano.maxBars ?? 12;
    return EXERCISE_OPTIONS.measureCounts.filter((value) => value <= maxBars);
  }, [config.grade]);

  const keyOptions = useMemo(
    () =>
      EXERCISE_OPTIONS.keySignatures.filter((candidate) => candidate.minGrade <= config.grade).map(
        (candidate) => ({
          value: candidate.value as KeySignature,
          label: candidate.label,
        }),
      ),
    [config.grade],
  );

  const summary = useMemo(
    () => buildSummary(config, presetMode, selectedTimeSignatures, selectedKeySignatures),
    [config, presetMode, selectedKeySignatures, selectedTimeSignatures],
  );

  useEffect(() => {
    let cancelled = false;

    async function loadState() {
      await storage.initialize();
      const appSettings = await storage.getSettings();
      const lastConfig = await storage.getLastGeneratorConfig();
      const lastDraft = await storage.getSettingValue<DesktopCreateDraft>(LAST_CREATE_DRAFT_KEY);

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
      let nextPresetMode = true;
      let nextTimes: TimeSignature[] = [nextConfig.timeSignature];
      let nextKeys: KeySignature[] = [nextConfig.keySignature];
      let nextShuffle: PresetShuffleState = EMPTY_PRESET_SHUFFLE;

      if (modeParam === "rhythm") {
        nextConfig = {
          ...configForMode("rhythm"),
          handPosition: appSettings.preferredHandPosition,
          grade: appSettings.defaultGrade,
          readingFocus: appSettings.defaultReadingFocus,
        };
        nextPresetMode = false;
      } else if (resume && lastDraft) {
        nextConfig = lastDraft.config;
        nextPresetMode = lastDraft.presetMode;
        nextTimes = lastDraft.selectedTimeSignatures;
        nextKeys = lastDraft.selectedKeySignatures;
        nextShuffle = lastDraft.presetShuffle;
      } else if (presetId) {
        const preset = await storage.getPresetById(presetId);
        if (preset) {
          nextConfig = preset.config;
          nextPresetMode = false;
        }
      } else if (!fresh && lastDraft) {
        nextConfig = lastDraft.config;
        nextPresetMode = lastDraft.presetMode;
        nextTimes = lastDraft.selectedTimeSignatures;
        nextKeys = lastDraft.selectedKeySignatures;
        nextShuffle = lastDraft.presetShuffle;
      } else if (!fresh && lastConfig) {
        nextConfig = lastConfig;
        nextPresetMode = false;
      } else if (modeParam === "piano") {
        nextConfig = {
          ...nextConfig,
          mode: "piano",
        };
      }

      const normalized = normalizeConfig(nextConfig, nextPresetMode);
      const normalizedTimes = normalizeTimeSelections(normalized, nextTimes);
      const normalizedKeys = normalizeKeySelections(normalized, nextKeys);
      const normalizedShuffle = normalizePresetShuffle(
        normalized,
        normalizedTimes,
        normalizedKeys,
        nextShuffle,
      );

      if (!cancelled) {
        setSettings(appSettings);
        setConfig(normalized);
        setPresetMode(normalized.mode === "piano" ? nextPresetMode : false);
        setSelectedTimeSignatures(normalizedTimes);
        setSelectedKeySignatures(normalizedKeys);
        setPresetShuffle(normalizedShuffle);
        setLoading(false);
      }
    }

    void loadState();

    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  function normalizeConfig(next: ExerciseConfig, nextPresetMode = presetMode) {
    const normalized = { ...next };
    const gradeMeta =
      GRADE_PRESETS.find((preset) => preset.grade === normalized.grade) ?? GRADE_PRESETS[0];

    if (normalized.measureCount > gradeMeta.piano.maxBars) {
      normalized.measureCount = gradeMeta.piano.maxBars;
    }

    if (nextPresetMode && normalized.mode === "piano") {
      normalized.measureCount = recommendedPresetMeasureCount(normalized.grade);
    }

    if (normalized.mode === "rhythm" || normalized.grade < 4) {
      normalized.allowAccidentals = false;
    }

    const availableKeys = EXERCISE_OPTIONS.keySignatures.filter(
      (candidate) => candidate.minGrade <= normalized.grade,
    );
    if (!availableKeys.some((candidate) => candidate.value === normalized.keySignature)) {
      normalized.keySignature = "C";
    }

    return normalized;
  }

  function syncSelections(
    nextConfig: ExerciseConfig,
    nextTimes = selectedTimeSignatures,
    nextKeys = selectedKeySignatures,
    nextShuffle = presetShuffle,
  ) {
    const normalizedTimes = normalizeTimeSelections(nextConfig, nextTimes);
    const normalizedKeys = normalizeKeySelections(nextConfig, nextKeys);
    const normalizedShuffle = normalizePresetShuffle(
      nextConfig,
      normalizedTimes,
      normalizedKeys,
      nextShuffle,
    );

    setSelectedTimeSignatures(normalizedTimes);
    setSelectedKeySignatures(normalizedKeys);
    setPresetShuffle(normalizedShuffle);
  }

  function updateConfig(patch: Partial<ExerciseConfig>) {
    const next = normalizeConfig({ ...config, ...patch });
    setConfig(next);
    syncSelections(next);
  }

  function updateMode(mode: ExerciseMode) {
    const next = normalizeConfig(
      {
        ...configForMode(mode),
        grade: config.grade,
        timeSignature: config.timeSignature,
        measureCount: config.measureCount,
        tempoPreset: config.tempoPreset,
        keySignature: mode === "piano" ? config.keySignature : "C",
        handPosition: config.handPosition,
        handActivity: config.handActivity,
        coordinationStyle: config.coordinationStyle,
        readingFocus: config.readingFocus,
        rightHandMotion: config.rightHandMotion,
        leftHandPattern: config.leftHandPattern,
        allowRests: config.allowRests,
        allowAccidentals: mode === "piano" && config.grade >= 4 ? config.allowAccidentals : false,
      },
      mode === "piano" ? presetMode : false,
    );
    setConfig(next);
    if (mode === "rhythm") {
      setPresetMode(false);
    }
    syncSelections(next, [next.timeSignature], [next.keySignature], EMPTY_PRESET_SHUFFLE);
  }

  function updatePresetMode(nextPresetMode: boolean) {
    const normalized = normalizeConfig(config, nextPresetMode);
    setPresetMode(nextPresetMode);
    setConfig(normalized);
    syncSelections(normalized);
  }

  async function handleGenerate() {
    try {
      setSubmitting(true);
      const seed = nextSeed();
      const normalizedTimes = normalizeTimeSelections(config, selectedTimeSignatures);
      const normalizedKeys = normalizeKeySelections(config, selectedKeySignatures);
      const normalizedShuffle = normalizePresetShuffle(
        config,
        normalizedTimes,
        normalizedKeys,
        presetShuffle,
      );
      const { requestConfig, nextPresetShuffle } = resolvePresetConfigForRun(
        config,
        seed,
        normalizedTimes,
        normalizedKeys,
        normalizedShuffle,
        !presetMode,
      );
      const draft: DesktopCreateDraft = {
        config,
        presetMode,
        selectedTimeSignatures: normalizedTimes,
        selectedKeySignatures: normalizedKeys,
        presetShuffle: nextPresetShuffle,
      };
      await storage.setSettingValue(LAST_CREATE_DRAFT_KEY, draft);
      const generated = await generateExercise({ ...requestConfig, seed });
      await storage.saveGeneratedExercise({
        ...generated,
        generationContext: {
          presetMode,
          selectedTimeSignatures: normalizedTimes,
          selectedKeySignatures: normalizedKeys,
          presetShuffle: nextPresetShuffle,
        },
      });
      setPresetShuffle(nextPresetShuffle);
      navigate(`/exercise/${generated.exerciseId}`);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Generation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function resetToDefaults() {
    const nextSettings = settings ?? DEFAULT_SETTINGS;
    const nextConfig = normalizeConfig({
      ...DEFAULT_CONFIG,
      handPosition: nextSettings.preferredHandPosition,
      grade: nextSettings.defaultGrade,
      readingFocus: nextSettings.defaultReadingFocus,
    });
    setPresetMode(nextConfig.mode === "piano");
    setConfig(nextConfig);
    syncSelections(nextConfig, [nextConfig.timeSignature], [nextConfig.keySignature], EMPTY_PRESET_SHUFFLE);
  }

  if (loading) {
    return (
      <div className="page">
        <div className="card card--centered">
          <p>Loading desktop practice builder...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <p className="eyebrow">Create</p>
          <h1 className="page__title">Desktop exercise builder</h1>
          <p className="page__subtitle">
            Use a guided preset rotation for fast practice reps, or switch into custom mode when you
            want exact control over the musical shape.
          </p>
        </div>
        <div className="page__actions">
          <button type="button" className="button button--ghost" onClick={resetToDefaults}>
            Reset defaults
          </button>
          <button type="button" className="button button--primary" onClick={handleGenerate} disabled={submitting}>
            {submitting ? "Generating..." : "Generate exercise"}
          </button>
        </div>
      </header>

      <div className="content-grid content-grid--wide">
        <div className="stack">
          <section className="card">
            <div className="card__heading">
              <h2>Session type</h2>
            </div>

            <ChoicePills
              label="Mode"
              options={EXERCISE_OPTIONS.modes as ChoiceOption<ExerciseMode>[]}
              value={config.mode}
              onChange={updateMode}
            />

            <ChoicePills
              label="Grade"
              options={EXERCISE_OPTIONS.grades.map((grade) => ({
                value: grade.value,
                label: grade.label,
                hint: grade.subLabel,
              }))}
              value={config.grade}
              onChange={(value) => updateConfig({ grade: Number(value) })}
            />

            {config.mode === "piano" ? (
              <ChoicePills
                label="Builder mode"
                hint="Preset mode rotates meter, key, and texture choices for you."
                options={[
                  { value: "preset", label: "Guided preset" },
                  { value: "custom", label: "Custom setup" },
                ]}
                value={presetMode ? "preset" : "custom"}
                onChange={(value) => updatePresetMode(value === "preset")}
              />
            ) : null}
          </section>

          {presetMode && config.mode === "piano" ? (
            <section className="card">
              <div className="card__heading">
                <h2>Preset rotation</h2>
              </div>

              <MultiChoicePills
                label="Meters in rotation"
                options={EXERCISE_OPTIONS.timeSignatures.map((value) => ({
                  value: value as TimeSignature,
                  label: value,
                }))}
                values={selectedTimeSignatures}
                onToggle={(value) => {
                  const nextValues = toggleItem(selectedTimeSignatures, value);
                  setSelectedTimeSignatures(nextValues);
                  syncSelections(config, nextValues, selectedKeySignatures);
                }}
              />

              <MultiChoicePills
                label="Keys in rotation"
                options={keyOptions}
                values={selectedKeySignatures}
                onToggle={(value) => {
                  const nextValues = toggleItem(selectedKeySignatures, value);
                  setSelectedKeySignatures(nextValues);
                  syncSelections(config, selectedTimeSignatures, nextValues);
                }}
              />

              <ChoicePills
                label="Tempo"
                options={EXERCISE_OPTIONS.tempoPresets.map((tempo) => ({
                  value: tempo.value as TempoPreset,
                  label: tempo.label,
                  hint: `${tempo.bpm} BPM`,
                }))}
                value={config.tempoPreset}
                onChange={(value) => updateConfig({ tempoPreset: value as TempoPreset })}
              />

              <ChoicePills
                label="Hand position"
                options={EXERCISE_OPTIONS.handPositions.map((position) => ({
                  value: position.value as ExerciseConfig["handPosition"],
                  label: position.label,
                }))}
                value={config.handPosition}
                onChange={(value) =>
                  updateConfig({ handPosition: value as ExerciseConfig["handPosition"] })
                }
              />

              <div className="toggle-list">
                <label className="toggle-row">
                  <div>
                    <strong>Allow rests</strong>
                    <p>Let the generator place short breathing spaces where the rhythm permits.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={config.allowRests}
                    onChange={(event) => updateConfig({ allowRests: event.target.checked })}
                  />
                </label>

                <label className="toggle-row">
                  <div>
                    <strong>Allow accidentals</strong>
                    <p>
                      Accidentals are only active for grade 4 and above, matching the backend rules.
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={config.allowAccidentals}
                    disabled={config.grade < 4}
                    onChange={(event) =>
                      updateConfig({ allowAccidentals: event.target.checked })
                    }
                  />
                </label>
              </div>
            </section>
          ) : (
            <section className="card">
              <div className="card__heading">
                <h2>Custom setup</h2>
              </div>

              <ChoicePills
                label="Time signature"
                options={EXERCISE_OPTIONS.timeSignatures.map((value) => ({
                  value,
                  label: value,
                }))}
                value={config.timeSignature}
                onChange={(value) =>
                  updateConfig({ timeSignature: value as ExerciseConfig["timeSignature"] })
                }
              />

              <ChoicePills
                label="Measures"
                options={measureOptions.map((value) => ({
                  value,
                  label: `${value} bars`,
                }))}
                value={config.measureCount}
                onChange={(value) => updateConfig({ measureCount: Number(value) })}
              />

              <ChoicePills
                label="Tempo"
                options={EXERCISE_OPTIONS.tempoPresets.map((tempo) => ({
                  value: tempo.value as TempoPreset,
                  label: tempo.label,
                  hint: `${tempo.bpm} BPM`,
                }))}
                value={config.tempoPreset}
                onChange={(value) => updateConfig({ tempoPreset: value as TempoPreset })}
              />

              {config.mode === "piano" ? (
                <ChoicePills
                  label="Key"
                  options={keyOptions}
                  value={config.keySignature}
                  onChange={(value) =>
                    updateConfig({ keySignature: value as ExerciseConfig["keySignature"] })
                  }
                />
              ) : null}

              <ChoicePills
                label="Hand position"
                options={EXERCISE_OPTIONS.handPositions.map((position) => ({
                  value: position.value as ExerciseConfig["handPosition"],
                  label: position.label,
                }))}
                value={config.handPosition}
                onChange={(value) =>
                  updateConfig({ handPosition: value as ExerciseConfig["handPosition"] })
                }
              />

              <ChoicePills
                label="Hand activity"
                options={EXERCISE_OPTIONS.handActivities.map((option) => ({
                  value: option.value as ExerciseConfig["handActivity"],
                  label: option.label,
                }))}
                value={config.handActivity}
                onChange={(value) =>
                  updateConfig({ handActivity: value as ExerciseConfig["handActivity"] })
                }
              />

              <ChoicePills
                label="Coordination"
                options={EXERCISE_OPTIONS.coordinationStyles.map((option) => ({
                  value: option.value as ExerciseConfig["coordinationStyle"],
                  label: option.label,
                }))}
                value={config.coordinationStyle}
                onChange={(value) =>
                  updateConfig({
                    coordinationStyle: value as ExerciseConfig["coordinationStyle"],
                  })
                }
              />

              {config.mode === "piano" ? (
                <>
                  <ChoicePills
                    label="Reading focus"
                    options={EXERCISE_OPTIONS.readingFocuses.map((option) => ({
                      value: option.value as ReadingFocus,
                      label: option.label,
                    }))}
                    value={config.readingFocus}
                    onChange={(value) =>
                      updateConfig({ readingFocus: value as ExerciseConfig["readingFocus"] })
                    }
                  />

                  <ChoicePills
                    label="Right-hand motion"
                    options={EXERCISE_OPTIONS.rightHandMotions.map((option) => ({
                      value: option.value as ExerciseConfig["rightHandMotion"],
                      label: option.label,
                    }))}
                    value={config.rightHandMotion}
                    onChange={(value) =>
                      updateConfig({
                        rightHandMotion: value as ExerciseConfig["rightHandMotion"],
                      })
                    }
                  />
                </>
              ) : null}

              <ChoicePills
                label="Left-hand pattern"
                options={EXERCISE_OPTIONS.leftHandPatterns.map((option) => ({
                  value: option.value as ExerciseConfig["leftHandPattern"],
                  label: option.label,
                }))}
                value={config.leftHandPattern}
                onChange={(value) =>
                  updateConfig({
                    leftHandPattern: value as ExerciseConfig["leftHandPattern"],
                  })
                }
              />

              <div className="toggle-list">
                <label className="toggle-row">
                  <div>
                    <strong>Allow rests</strong>
                    <p>Add short silences when the rhythm allows them.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={config.allowRests}
                    onChange={(event) => updateConfig({ allowRests: event.target.checked })}
                  />
                </label>

                <label className="toggle-row">
                  <div>
                    <strong>Allow accidentals</strong>
                    <p>
                      The backend will still switch this off automatically for grades below 4.
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={config.allowAccidentals}
                    disabled={config.grade < 4 || config.mode === "rhythm"}
                    onChange={(event) =>
                      updateConfig({ allowAccidentals: event.target.checked })
                    }
                  />
                </label>
              </div>
            </section>
          )}
        </div>

        <aside className="stack stack--sticky">
          <section className="card card--accent">
            <p className="eyebrow eyebrow--light">Ready to generate</p>
            <h2>{summary.lead}</h2>
            <p>{summary.detail}</p>
            <div className="tag-list">
              {summary.chips.map((chip) => (
                <span key={chip} className="tag">
                  {chip}
                </span>
              ))}
            </div>
            <button type="button" className="button button--light" onClick={handleGenerate} disabled={submitting}>
              {submitting ? "Generating..." : "Generate desktop rep"}
            </button>
          </section>

          <section className="card">
            <div className="card__heading">
              <h2>What carries into the next run</h2>
            </div>
            <ul className="detail-list">
              <li>Grade and tempo remain stable across the session.</li>
              <li>Preset mode rotates meter and key choices instead of repeating the exact last rep.</li>
              <li>Every generated exercise is kept in desktop history instead of replacing the last one.</li>
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
