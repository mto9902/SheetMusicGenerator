import gradePresets from "../shared/difficulty-presets.json";
import exerciseOptions from "../shared/exercise-options.json";

import type {
  AppSettings,
  ExerciseConfig,
  ExerciseMode,
  TempoPreset,
} from "./types";

type GradePreset = (typeof gradePresets)[number];

export const EXERCISE_OPTIONS = exerciseOptions;
export const GRADE_PRESETS = gradePresets as GradePreset[];

export const DEFAULT_CONFIG: ExerciseConfig =
  exerciseOptions.defaultConfig as ExerciseConfig;

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

export function configForMode(mode: ExerciseMode): ExerciseConfig {
  const base = { ...DEFAULT_CONFIG };

  if (mode === "rhythm") {
    return {
      ...base,
      mode: "rhythm",
      keySignature: "C",
      allowAccidentals: false,
    };
  }

  return {
    ...base,
    mode: "piano",
  };
}
