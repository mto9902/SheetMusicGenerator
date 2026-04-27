import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ControlTower } from "@/components/ControlTower";
import { PaperDesk } from "@/components/PaperDesk";
import { InstrumentCard } from "@/components/InstrumentCard";
import { HistoryDrawer } from "@/components/HistoryDrawer";
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
  normalizeGradeStage,
} from "@shared/options";
import { EMPTY_PRESET_SHUFFLE } from "@shared/presetGeneration";
import type {
  AppSettings,
  ExerciseConfig,
  ExerciseListItem,
  KeySignature,
  StoredExercise,
} from "@shared/types";

interface CreatePageProps {
  onAudioChange?: (url: string | null, noteEvents: import("@shared/types").NoteEvent[] | null, bpm: number) => void;
}

export function CreatePage({ onAudioChange }: CreatePageProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [config, setConfig] = useState<ExerciseConfig>(DEFAULT_CONFIG);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [activeExercise, setActiveExercise] = useState<StoredExercise | null>(null);
  const [recentExercises, setRecentExercises] = useState<ExerciseListItem[]>([]);

  useEffect(() => {
    onAudioChange?.(
      activeExercise?.audioUrl ?? null,
      activeExercise?.noteEvents ?? null,
      activeExercise?.summary.bpm ?? 92,
    );
  }, [activeExercise, onAudioChange]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

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

  function normalizeConfig(next: ExerciseConfig): ExerciseConfig {
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

    const availableKeys = EXERCISE_OPTIONS.keySignatures
      .filter((k) => k.minGrade <= normalized.grade)
      .map((k) => k.value);
    if (!availableKeys.some((candidate) => candidate === normalized.keySignature)) {
      normalized.keySignature = (availableKeys[0] ?? "C") as KeySignature;
    }

    return normalized;
  }

  function updateConfig(patch: Partial<ExerciseConfig>) {
    setConfig((current) => normalizeConfig({ ...current, ...patch }));
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
    if (!activeExercise) return;
    const presetName = window.prompt("Preset name", `${activeExercise.title} preset`);
    if (!presetName) return;
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

  const rightActions = (
    <div className="flex gap-2">
      <button
        type="button"
        className="tactile-btn flex-1 h-9 text-xs font-medium text-gray-600 disabled:opacity-45 disabled:cursor-not-allowed"
        onClick={() => activeExercise && navigate(`/exercise/${activeExercise.exerciseId}`)}
        disabled={!activeExercise}
      >
        Focus view
      </button>
      <button
        type="button"
        className="tactile-btn flex-1 h-9 text-xs font-medium text-gray-600 disabled:opacity-45 disabled:cursor-not-allowed"
        onClick={saveActivePreset}
        disabled={!activeExercise}
      >
        Save preset
      </button>
      <button
        type="button"
        className="tactile-btn h-9 px-3 text-xs font-medium text-gray-500"
        onClick={resetToDefaults}
      >
        Reset
      </button>
    </div>
  );

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-sm text-[#8E8E93]">Loading composition desk...</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col relative">
      <div className="flex-1 min-h-0 flex relative overflow-hidden">
        {/* Left - Parameters */}
        <div className="p-4 pb-16 shrink-0 overflow-y-auto scrollbar-hide">
          <ControlTower config={config} onChange={updateConfig} />
        </div>

        {/* Center - Notation */}
        <div className="flex-1 h-full min-h-0 p-4 pb-16 min-w-0 overflow-hidden flex flex-col">
          <PaperDesk
            exercise={activeExercise}
            scale={settings?.notationScale ?? 1}
            onCompose={handleGenerate}
            submitting={submitting}
          />
        </div>

        {/* Right - Playback */}
        <div className="p-4 pb-16 shrink-0 overflow-y-auto scrollbar-hide">
          <InstrumentCard config={config} onChange={updateConfig} actions={rightActions} />
        </div>

        {/* Bottom - History */}
        <HistoryDrawer
          exercises={recentExercises}
          activeId={activeExercise?.exerciseId}
          open={historyOpen}
          onToggle={() => setHistoryOpen((v) => !v)}
          onSelect={openExerciseInWorkbench}
        />
      </div>

    </div>
  );
}
