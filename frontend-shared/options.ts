import gradePresets from "../shared/difficulty-presets.json";
import exerciseOptions from "../shared/exercise-options.json";

import type {
  AppSettings,
  ExerciseConfig,
  GradeStage,
  ExerciseMode,
  TempoPreset,
} from "./types";

type GradePreset = (typeof gradePresets)[number];

export const EXERCISE_OPTIONS = exerciseOptions;
export const GRADE_PRESETS = gradePresets as GradePreset[];

export const DEFAULT_CONFIG: ExerciseConfig =
  exerciseOptions.defaultConfig as ExerciseConfig;

export const GRADE_STAGE_OPTIONS =
  (exerciseOptions.gradeStages ?? []) as Array<{
    value: GradeStage;
    label: string;
    grade: number;
    hint?: string;
  }>;

export const DEFAULT_SETTINGS: AppSettings = {
  notationScale: 1,
  metronomeDefault: true,
  countInDefault: true,
  preferredHandPosition: "C",
  defaultGrade: DEFAULT_CONFIG.grade,
  defaultReadingFocus: DEFAULT_CONFIG.readingFocus,
};

const TEMPO_BY_PRESET = new Map<TempoPreset, number>(
  exerciseOptions.tempoPresets.map((tempo) => [tempo.value as TempoPreset, tempo.bpm]),
);

export function tempoPresetToBpm(tempoPreset: TempoPreset) {
  return TEMPO_BY_PRESET.get(tempoPreset) ?? 92;
}

export function nextSeed() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function normalizeGradeStage(
  mode: ExerciseMode,
  grade: number,
  gradeStage?: GradeStage | null,
): GradeStage | undefined {
  if (mode !== "piano" || grade !== 1) {
    return undefined;
  }

  if (gradeStage === "g1-pocket" || gradeStage === "g1-extend" || gradeStage === "g1-staff") {
    return gradeStage;
  }

  return "g1-extend";
}

export function formatGradeStageLabel(gradeStage?: GradeStage | null) {
  if (!gradeStage) {
    return "";
  }

  return GRADE_STAGE_OPTIONS.find((stage) => stage.value === gradeStage)?.label ?? "";
}

export function visibleGradeStages(mode: ExerciseMode, grade: number) {
  if (mode !== "piano" || grade !== 1) {
    return [];
  }

  return GRADE_STAGE_OPTIONS.filter((stage) => stage.grade === 1);
}

export function configForMode(mode: ExerciseMode): ExerciseConfig {
  const base = { ...DEFAULT_CONFIG };

  if (mode === "rhythm") {
    return {
      ...base,
      mode: "rhythm",
      gradeStage: undefined,
      keySignature: "C",
      allowAccidentals: false,
    };
  }

  return {
    ...base,
    mode: "piano",
    gradeStage: normalizeGradeStage("piano", base.grade, base.gradeStage),
  };
}
