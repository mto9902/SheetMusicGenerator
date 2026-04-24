import {
  configForMode,
  DEFAULT_CONFIG,
  GRADE_PRESETS,
  EXERCISE_OPTIONS,
} from "./options";
import type {
  ExerciseConfig,
  KeySignature,
  PresetShuffleState,
  TimeSignature,
} from "./types";

export const EMPTY_PRESET_SHUFFLE: PresetShuffleState = {
  timeBag: [],
  keyBag: [],
  lastTimeSignature: null,
  lastKeySignature: null,
};

type WeightedChoice<T extends string> = {
  value: T;
  weight: number;
};

export function recommendedPresetMeasureCount(grade: number) {
  const preset = GRADE_PRESETS.find((candidate) => candidate.grade === grade);
  const maxBars = preset?.piano.maxBars ?? DEFAULT_CONFIG.measureCount;
  if (maxBars <= 4) {
    return 4;
  }
  return Math.min(8, maxBars);
}

function availableKeysForGrade(grade: number) {
  return EXERCISE_OPTIONS.keySignatures
    .filter((key) => key.minGrade <= grade)
    .map((key) => key.value as KeySignature);
}

export function normalizeTimeSelections(
  config: ExerciseConfig,
  selections: TimeSignature[],
) {
  const valid = selections.filter((selection) =>
    EXERCISE_OPTIONS.timeSignatures.includes(selection),
  );
  return valid.length ? valid : [config.timeSignature];
}

export function normalizeKeySelections(
  config: ExerciseConfig,
  selections: KeySignature[],
) {
  if (config.mode === "rhythm") {
    return [config.keySignature];
  }

  const allowed = new Set(availableKeysForGrade(config.grade));
  const valid = selections.filter((selection) => allowed.has(selection));
  return valid.length ? valid : [config.keySignature];
}

function pickFromSeed<T extends string>(seed: string, options: T[], fallback: T) {
  if (!options.length) {
    return fallback;
  }

  const total = Array.from(seed).reduce(
    (sum, char, index) => sum + char.charCodeAt(0) * (index + 1),
    0,
  );
  return options[total % options.length] ?? fallback;
}

function seedHash(seed: string) {
  return Array.from(seed).reduce(
    (total, char, index) => (total * 33 + char.charCodeAt(0) + index) >>> 0,
    5381,
  );
}

function shuffleFromSeed<T extends string>(
  seed: string,
  values: T[],
  avoidFirst: T | null,
) {
  const unique = Array.from(new Set(values));
  if (unique.length <= 1) {
    return unique;
  }

  let state = seedHash(seed);
  const next = [...unique];
  for (let index = next.length - 1; index > 0; index -= 1) {
    state = (state * 1664525 + 1013904223) >>> 0;
    const swapIndex = state % (index + 1);
    [next[index], next[swapIndex]] = [next[swapIndex]!, next[index]!];
  }

  if (avoidFirst && next[0] === avoidFirst && next.length > 1) {
    next.push(next.shift()!);
  }

  return next;
}

export function normalizePresetShuffle(
  config: ExerciseConfig,
  selectedTimeSignatures: TimeSignature[],
  selectedKeySignatures: KeySignature[],
  shuffle: PresetShuffleState | null | undefined,
): PresetShuffleState {
  const validTimes = normalizeTimeSelections(config, selectedTimeSignatures);
  const validKeys = normalizeKeySelections(config, selectedKeySignatures);

  const nextTimeBag =
    shuffle?.timeBag.filter((value) => validTimes.includes(value)) ?? [];
  const nextKeyBag =
    shuffle?.keyBag.filter((value) => validKeys.includes(value)) ?? [];

  return {
    timeBag: nextTimeBag,
    keyBag: config.mode === "rhythm" ? [] : nextKeyBag,
    lastTimeSignature:
      shuffle?.lastTimeSignature && validTimes.includes(shuffle.lastTimeSignature)
        ? shuffle.lastTimeSignature
        : null,
    lastKeySignature:
      config.mode !== "rhythm" &&
      shuffle?.lastKeySignature &&
      validKeys.includes(shuffle.lastKeySignature)
        ? shuffle.lastKeySignature
        : null,
  };
}

function drawFromShuffleBag<T extends string>(
  seed: string,
  label: string,
  values: T[],
  bag: T[],
  previous: T | null,
  fallback: T,
) {
  const normalizedValues = Array.from(new Set(values));
  if (!normalizedValues.length) {
    return {
      value: fallback,
      bag: [] as T[],
    };
  }

  const normalizedBag = bag.filter((item) => normalizedValues.includes(item));
  const workingBag =
    normalizedBag.length > 0
      ? normalizedBag
      : shuffleFromSeed(`${seed}-${label}`, normalizedValues, previous);

  const value = workingBag[0] ?? fallback;
  return {
    value,
    bag: workingBag.slice(1),
  };
}

function pickWeightedFromSeed<T extends string>(
  seed: string,
  options: WeightedChoice<T>[],
  fallback: T,
) {
  const expanded = options.flatMap((option) =>
    Array.from({ length: Math.max(0, Math.round(option.weight)) }, () => option.value),
  );
  return pickFromSeed(seed, expanded, fallback);
}

function presetCoordinationWeights(
  grade: number,
): WeightedChoice<ExerciseConfig["coordinationStyle"]>[] {
  if (grade <= 1) {
    return [
      { value: "support", weight: 5 },
      { value: "together", weight: 3 },
      { value: "alternating", weight: 2 },
    ];
  }
  if (grade === 2) {
    return [
      { value: "support", weight: 5 },
      { value: "together", weight: 3 },
      { value: "alternating", weight: 2 },
    ];
  }
  if (grade === 3) {
    return [
      { value: "support", weight: 4 },
      { value: "together", weight: 3 },
      { value: "alternating", weight: 3 },
    ];
  }
  if (grade === 4) {
    return [
      { value: "support", weight: 2 },
      { value: "together", weight: 4 },
      { value: "alternating", weight: 4 },
    ];
  }
  return [
    { value: "support", weight: 2 },
    { value: "together", weight: 4 },
    { value: "alternating", weight: 5 },
  ];
}

function presetReadingFocusWeights(
  grade: number,
): WeightedChoice<ExerciseConfig["readingFocus"]>[] {
  if (grade <= 1) {
    return [
      { value: "balanced", weight: 6 },
      { value: "melodic", weight: 3 },
      { value: "harmonic", weight: 1 },
    ];
  }
  if (grade === 2) {
    return [
      { value: "balanced", weight: 5 },
      { value: "melodic", weight: 3 },
      { value: "harmonic", weight: 2 },
    ];
  }
  if (grade === 3) {
    return [
      { value: "balanced", weight: 4 },
      { value: "melodic", weight: 3 },
      { value: "harmonic", weight: 3 },
    ];
  }
  if (grade === 4) {
    return [
      { value: "balanced", weight: 4 },
      { value: "melodic", weight: 4 },
      { value: "harmonic", weight: 2 },
    ];
  }
  return [
    { value: "balanced", weight: 4 },
    { value: "melodic", weight: 4 },
    { value: "harmonic", weight: 2 },
  ];
}

function presetRightHandMotionWeights(
  grade: number,
): WeightedChoice<ExerciseConfig["rightHandMotion"]>[] {
  if (grade <= 1) {
    return [
      { value: "stepwise", weight: 5 },
      { value: "small-leaps", weight: 2 },
      { value: "mixed", weight: 4 },
    ];
  }
  if (grade === 2) {
    return [
      { value: "stepwise", weight: 6 },
      { value: "small-leaps", weight: 3 },
      { value: "mixed", weight: 2 },
    ];
  }
  if (grade === 3) {
    return [
      { value: "stepwise", weight: 4 },
      { value: "small-leaps", weight: 4 },
      { value: "mixed", weight: 3 },
    ];
  }
  if (grade === 4) {
    return [
      { value: "stepwise", weight: 2 },
      { value: "small-leaps", weight: 4 },
      { value: "mixed", weight: 5 },
    ];
  }
  return [
    { value: "stepwise", weight: 2 },
    { value: "small-leaps", weight: 4 },
    { value: "mixed", weight: 6 },
  ];
}

function familyToLeftPattern(family: string): ExerciseConfig["leftHandPattern"] {
  if (["repeated", "support-bass", "waltz-bass", "octave-support"].includes(family)) {
    return "repeated";
  }
  if (["simple-broken", "arpeggio-support", "alberti"].includes(family)) {
    return "simple-broken";
  }
  return "held";
}

function presetLeftPatternWeights(
  grade: number,
): WeightedChoice<ExerciseConfig["leftHandPattern"]>[] {
  const preset = GRADE_PRESETS.find((candidate) => candidate.grade === grade);
  const familyCounts = new Map<ExerciseConfig["leftHandPattern"], number>();
  const families = preset?.piano.leftPatternFamilies ?? ["held"];

  for (const family of families) {
    const pattern = familyToLeftPattern(family);
    familyCounts.set(pattern, (familyCounts.get(pattern) ?? 0) + 1);
  }

  return Array.from(familyCounts.entries())
    .map(([value, weight]) => {
      let adjustedWeight = weight;
      if (grade <= 1) {
        if (value === "repeated") {
          adjustedWeight += 2;
        } else if (value === "held") {
          adjustedWeight = Math.max(1, adjustedWeight - 0.5);
        }
      } else if (grade === 2) {
        if (value === "repeated") {
          adjustedWeight += 1;
        } else if (value === "simple-broken") {
          adjustedWeight += 1;
        }
      }
      return {
        value,
        weight: adjustedWeight,
      };
    })
    .filter((option) => option.weight > 0);
}

export function resolvePresetConfigForRun(
  config: ExerciseConfig,
  seed: string,
  selectedTimeSignatures: TimeSignature[],
  selectedKeySignatures: KeySignature[],
  presetShuffle: PresetShuffleState,
  showCustomize: boolean,
) {
  if (showCustomize) {
    return {
      requestConfig: config,
      nextPresetShuffle: presetShuffle,
    };
  }

  const timeDraw = drawFromShuffleBag(
    seed,
    "time",
    normalizeTimeSelections(config, selectedTimeSignatures),
    presetShuffle.timeBag,
    presetShuffle.lastTimeSignature,
    config.timeSignature,
  );
  const keyDraw =
    config.mode === "rhythm"
      ? {
          value: "C" as KeySignature,
          bag: [] as KeySignature[],
        }
      : drawFromShuffleBag(
          seed,
          "key",
          normalizeKeySelections(config, selectedKeySignatures),
          presetShuffle.keyBag,
          presetShuffle.lastKeySignature,
          config.keySignature,
        );
  const nextCoordinationStyle = pickWeightedFromSeed(
    `${seed}-coordination`,
    presetCoordinationWeights(config.grade),
    DEFAULT_CONFIG.coordinationStyle,
  );
  const nextReadingFocus = pickWeightedFromSeed(
    `${seed}-focus`,
    presetReadingFocusWeights(config.grade),
    DEFAULT_CONFIG.readingFocus,
  );
  const nextRightHandMotion = pickWeightedFromSeed(
    `${seed}-motion`,
    presetRightHandMotionWeights(config.grade),
    DEFAULT_CONFIG.rightHandMotion,
  );
  const nextLeftHandPattern = pickWeightedFromSeed(
    `${seed}-left-pattern`,
    presetLeftPatternWeights(config.grade),
    DEFAULT_CONFIG.leftHandPattern,
  );
  const nextMeasureCount = recommendedPresetMeasureCount(config.grade);

  return {
    requestConfig: {
      ...configForMode("piano"),
      grade: config.grade,
      gradeStage: config.gradeStage,
      measureCount: nextMeasureCount,
      tempoPreset: config.tempoPreset,
      timeSignature: timeDraw.value,
      keySignature: keyDraw.value,
      handPosition: config.handPosition,
      handActivity: "both" as ExerciseConfig["handActivity"],
      coordinationStyle: nextCoordinationStyle,
      readingFocus: nextReadingFocus,
      rightHandMotion:
        config.grade === 1 && config.gradeStage === "g1-pocket"
          ? "stepwise"
          : nextRightHandMotion,
      leftHandPattern: nextLeftHandPattern,
      allowRests: config.allowRests,
      allowAccidentals: config.allowAccidentals,
    },
    nextPresetShuffle: {
      timeBag: timeDraw.bag,
      keyBag: keyDraw.bag,
      lastTimeSignature: timeDraw.value,
      lastKeySignature: config.mode === "rhythm" ? null : keyDraw.value,
    },
  };
}
