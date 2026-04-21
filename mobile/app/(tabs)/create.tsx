import { useMutation } from "@tanstack/react-query";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { ChipGroup } from "@/src/components/ChipGroup";
import { DevApiBadge } from "@/src/components/DevApiBadge";
import { SurfaceCard } from "@/src/components/SurfaceCard";
import { TopBar } from "@/src/components/TopBar";
import {
  getLastGeneratorConfig,
  getPresetById,
  getSettingValue,
  getSettings,
  saveGeneratedExercise,
  setSettingValue,
} from "@/src/db/database";
import { generateExercise } from "@/src/lib/api";
import {
  configForMode,
  DEFAULT_CONFIG,
  GRADE_PRESETS,
  EXERCISE_OPTIONS,
  nextSeed,
} from "@/src/lib/options";
import {
  EMPTY_PRESET_SHUFFLE as SHARED_EMPTY_PRESET_SHUFFLE,
  normalizeKeySelections,
  normalizeTimeSelections,
  normalizePresetShuffle as normalizeSharedPresetShuffle,
  recommendedPresetMeasureCount as recommendedSharedPresetMeasureCount,
  resolvePresetConfigForRun as resolveSharedPresetConfigForRun,
} from "@/src/lib/presetGeneration";
import { Colors } from "@/src/theme/colors";
import type {
  ExerciseConfig,
  KeySignature,
  ExerciseMode,
  PresetShuffleState,
  ReadingFocus,
  TempoPreset,
  TimeSignature,
} from "@/src/types/exercise";

type CreateUiState = {
  config: ExerciseConfig;
  selectedTimeSignatures: TimeSignature[];
  selectedKeySignatures: KeySignature[];
  showCustomize: boolean;
  presetShuffle: PresetShuffleState;
};

const LAST_CREATE_UI_STATE_KEY = "last_create_ui_state";
const EMPTY_PRESET_SHUFFLE: PresetShuffleState = SHARED_EMPTY_PRESET_SHUFFLE;

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

function motionPhrase(config: ExerciseConfig) {
  if (config.rightHandMotion === "stepwise") {
    return "stepwise";
  }

  if (config.rightHandMotion === "small-leaps") {
    return "small-leap";
  }

  return "mixed-motion";
}

function leftPatternPhrase(config: ExerciseConfig) {
  if (config.leftHandPattern === "held") {
    return "held left-hand support";
  }

  if (config.leftHandPattern === "repeated") {
    return "repeated left-hand anchors";
  }

  return "broken left-hand support";
}

function readingFocusPhrase(focus: ReadingFocus) {
  if (focus === "melodic") {
    return "melodic pattern reading";
  }

  if (focus === "harmonic") {
    return "harmonic reading";
  }

  return "balanced phrase reading";
}

function summarizeSelection(values: string[], kind: string) {
  if (!values.length) {
    return `No ${kind}s selected`;
  }
  if (values.length === 1) {
    return values[0];
  }
  return `${values.length} ${kind}s selected`;
}

function buildRepPreview(
  config: ExerciseConfig,
  selectedTimeSignatures: TimeSignature[],
  selectedKeySignatures: KeySignature[],
  showCustomize: boolean,
) {
  const tempoLabel = optionLabel(
    EXERCISE_OPTIONS.tempoPresets.map((tempo) => ({
      value: tempo.value as TempoPreset,
      label: tempo.label,
    })),
    config.tempoPreset,
  ).toLowerCase();

  const timeSummary = summarizeSelection(
    normalizeTimeSelections(config, selectedTimeSignatures),
    "meter",
  );

  if (config.mode === "rhythm") {
    return {
      lead: showCustomize
        ? `You'll practice fixed-anchor rhythm reading in ${config.timeSignature} with ${config.measureCount} bars at a ${tempoLabel} tempo.`
        : `You'll practice fixed-anchor rhythm reading across ${timeSummary} at a ${tempoLabel} tempo.`,
      detail: showCustomize
        ? "This rep keeps pitch decisions out of the way so you can lock in pulse, subdivision, and hand timing first."
        : "This preset keeps the goal simple: pick the level, choose the meters you want in rotation, and start reading.",
    };
  }

  const keySummaryValues = normalizeKeySelections(config, selectedKeySignatures).map(describeKey);
  const keySummary = summarizeSelection(keySummaryValues, "key");

  if (!showCustomize) {
    const presetBars = recommendedSharedPresetMeasureCount(config.grade);
    return {
      lead: `You'll practice guided piano reading across ${timeSummary} in ${keySummary}.`,
      detail:
        `This preset uses Grade ${config.grade} as the main difficulty guardrail, then rotates through your selected meter and key options inside an ${presetBars}-bar rep.`,
    };
  }

  const keyLabel = describeKey(config.keySignature);
  const motionLabel = motionPhrase(config);
  const focusLabel = readingFocusPhrase(config.readingFocus);
  const positionLabel = `${config.handPosition} position`;
  const accidentalPhrase = config.allowAccidentals
    ? " with controlled chromatic color"
    : "";

  let lead = `You'll practice ${motionLabel} piano reading in ${keyLabel}.`;
  if (config.handActivity === "right-only") {
    lead = `You'll practice ${motionLabel} right-hand reading in ${keyLabel}.`;
  } else if (config.handActivity === "left-only") {
    lead = `You'll practice left-hand support reading in ${keyLabel}.`;
  } else if (config.coordinationStyle === "support") {
    lead = `You'll practice ${motionLabel} right-hand reading with steady left-hand support in ${keyLabel}.`;
  } else if (config.coordinationStyle === "alternating") {
    lead = `You'll practice hand-to-hand exchanges in ${keyLabel} with ${motionLabel} shapes.`;
  } else if (config.coordinationStyle === "together") {
    lead = `You'll practice aligned two-hand reading in ${keyLabel} with ${motionLabel} shapes.`;
  }

  let detail = `This ${config.measureCount}-bar ${tempoLabel} rep leans toward ${focusLabel} around ${positionLabel}${accidentalPhrase}.`;
  if (showCustomize && config.handActivity !== "right-only") {
    detail = `This ${config.measureCount}-bar ${tempoLabel} rep leans toward ${focusLabel}, uses ${leftPatternPhrase(config)}, and stays around ${positionLabel}${accidentalPhrase}.`;
  }

  return { lead, detail };
}

function buildRepWhy(config: ExerciseConfig, showCustomize: boolean) {
  if (!showCustomize) {
    return `Why this preset works: the grade sets the musical ceiling for you, so you only choose the meter and keys you want to read today while the app stretches that into a ${recommendedSharedPresetMeasureCount(config.grade)}-bar guided rep.`;
  }

  if (config.mode === "rhythm") {
    return "Why this rep: it strips away pitch decisions so your eyes and pulse can lock onto subdivision and timing first.";
  }

  if (config.coordinationStyle === "together") {
    return "Why this rep: it keeps both hands visually aligned so you can chunk vertical shapes instead of decoding each note alone.";
  }

  if (config.readingFocus === "harmonic") {
    return "Why this rep: it teaches you to feel harmony under the fingers, so the next bar becomes more predictable before you play it.";
  }

  if (config.rightHandMotion === "small-leaps") {
    return "Why this rep: it trains interval recognition and shape-reading without burying the line under extra accompaniment noise.";
  }

  return "Why this rep: it gives you one clear reading target with enough support to feel musical, not just mechanically correct.";
}

function buildSetupSummary(
  config: ExerciseConfig,
  selectedTimeSignatures: TimeSignature[],
  selectedKeySignatures: KeySignature[],
  showCustomize: boolean,
) {
  const timeSummary = summarizeSelection(
    normalizeTimeSelections(config, selectedTimeSignatures),
    "meter",
  );

  if (!showCustomize && config.mode === "piano") {
    return [
      `Grade ${config.grade}`,
      `${recommendedSharedPresetMeasureCount(config.grade)} bars`,
      timeSummary,
      summarizeSelection(
        normalizeKeySelections(config, selectedKeySignatures).map(describeKey),
        "key",
      ),
    ];
  }

  if (!showCustomize && config.mode === "rhythm") {
    return [`Grade ${config.grade}`, timeSummary, "Preset mode"];
  }

  if (config.mode === "rhythm") {
    return [
      `Grade ${config.grade}`,
      config.timeSignature,
      optionLabel(
        EXERCISE_OPTIONS.tempoPresets.map((tempo) => ({
          value: tempo.value as TempoPreset,
          label: tempo.label,
        })),
        config.tempoPreset,
      ),
      `${config.measureCount} bars`,
    ];
  }

  return [
    `Grade ${config.grade}`,
    readingFocusPhrase(config.readingFocus),
    optionLabel(
      EXERCISE_OPTIONS.coordinationStyles.map((option) => ({
        value: option.value as ExerciseConfig["coordinationStyle"],
        label: option.label,
      })),
      config.coordinationStyle,
    ),
    leftPatternPhrase(config),
    motionPhrase(config),
    describeKey(config.keySignature),
  ];
}

function toggleItem<T extends string>(items: T[], value: T) {
  if (items.includes(value)) {
    const next = items.filter((item) => item !== value);
    return next;
  }
  return [...items, value];
}

export default function CreateScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    mode?: ExerciseMode;
    resume?: string;
    presetId?: string;
  }>();
  const [config, setConfig] = useState<ExerciseConfig>(
    params.mode === "rhythm" ? configForMode("rhythm") : DEFAULT_CONFIG,
  );
  const [showCustomize, setShowCustomize] = useState(false);
  const [selectedTimeSignatures, setSelectedTimeSignatures] = useState<TimeSignature[]>([
    params.mode === "rhythm" ? "4/4" : DEFAULT_CONFIG.timeSignature,
  ]);
  const [selectedKeySignatures, setSelectedKeySignatures] = useState<KeySignature[]>([
    DEFAULT_CONFIG.keySignature,
  ]);
  const [presetShuffle, setPresetShuffle] =
    useState<PresetShuffleState>(EMPTY_PRESET_SHUFFLE);

  const gradeMeta = useMemo(
    () => GRADE_PRESETS.find((preset) => preset.grade === config.grade),
    [config.grade],
  );
  const measureOptions = useMemo(() => {
    const maxBars = gradeMeta?.piano.maxBars ?? 12;
    return EXERCISE_OPTIONS.measureCounts.filter((value) => value <= maxBars);
  }, [gradeMeta]);
  const keyOptions = useMemo(
    () =>
      EXERCISE_OPTIONS.keySignatures.filter(
        (k: { value: string; label: string; minGrade: number }) =>
          k.minGrade <= config.grade,
      ),
    [config.grade],
  );
  const preview = useMemo(
    () =>
      buildRepPreview(
        config,
        selectedTimeSignatures,
        selectedKeySignatures,
        showCustomize,
      ),
    [config, selectedKeySignatures, selectedTimeSignatures, showCustomize],
  );
  const whyRep = useMemo(() => buildRepWhy(config, showCustomize), [config, showCustomize]);
  const setupSummary = useMemo(
    () =>
      buildSetupSummary(
        config,
        selectedTimeSignatures,
        selectedKeySignatures,
        showCustomize,
      ),
    [config, selectedKeySignatures, selectedTimeSignatures, showCustomize],
  );
  const previewMeta = useMemo(() => {
    if (!showCustomize) {
      return setupSummary;
    }

    return [
      `${config.measureCount} bars`,
      config.timeSignature,
      optionLabel(
        EXERCISE_OPTIONS.tempoPresets.map((tempo) => ({
          value: tempo.value as TempoPreset,
          label: tempo.label,
        })),
        config.tempoPreset,
      ),
      config.mode === "piano" ? `${config.handPosition} position` : "Rhythm focus",
    ];
  }, [config, setupSummary, showCustomize]);
  const customizeExpanded = showCustomize;

  const generateMutation = useMutation({
    mutationFn: async ({
      seed,
      requestConfig,
      uiState,
    }: {
      seed: string;
      requestConfig: ExerciseConfig;
      uiState: CreateUiState;
    }) => {
      await setSettingValue(LAST_CREATE_UI_STATE_KEY, uiState);
      const result = await generateExercise({ ...requestConfig, seed });
      await saveGeneratedExercise({
        ...result,
        generationContext: {
          presetMode: !uiState.showCustomize,
          selectedTimeSignatures: uiState.selectedTimeSignatures,
          selectedKeySignatures: uiState.selectedKeySignatures,
          presetShuffle: uiState.presetShuffle,
        },
      });
      return result;
    },
    onSuccess: (result) => {
      router.push(`/exercise/${result.exerciseId}`);
    },
    onError: (error) => {
      Alert.alert(
        "Generation failed",
        error instanceof Error ? error.message : "Please try again.",
      );
    },
  });

  const normalizeConfig = useCallback((next: ExerciseConfig) => {
    const normalized = { ...next };
    const nextGradeMeta =
      GRADE_PRESETS.find((preset) => preset.grade === normalized.grade) ?? GRADE_PRESETS[0];

    if (normalized.measureCount > nextGradeMeta.piano.maxBars) {
      normalized.measureCount = nextGradeMeta.piano.maxBars;
    }

    if (normalized.mode === "rhythm" || normalized.grade < 4) {
      normalized.allowAccidentals = false;
    }

    const availableKeys = EXERCISE_OPTIONS.keySignatures.filter(
      (k: { value: string; minGrade: number }) => k.minGrade <= normalized.grade,
    );
    if (!availableKeys.some((k: { value: string }) => k.value === normalized.keySignature)) {
      normalized.keySignature = "C";
    }

    return normalized;
  }, []);

  function updateConfig(patch: Partial<ExerciseConfig>) {
    setConfig((current) => {
      const next = normalizeConfig({ ...current, ...patch });
      if (!showCustomize && next.mode === "piano") {
        next.measureCount = recommendedSharedPresetMeasureCount(next.grade);
      }
      setSelectedTimeSignatures((items) => {
        const normalizedTimes = normalizeTimeSelections(next, items);
        setSelectedKeySignatures((keyItems) => {
          const normalizedKeys = normalizeKeySelections(next, keyItems);
          setPresetShuffle((currentShuffle) =>
            normalizeSharedPresetShuffle(next, normalizedTimes, normalizedKeys, currentShuffle),
          );
          return normalizedKeys;
        });
        return normalizedTimes;
      });
      return next;
    });
  }

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      void (async () => {
        const appSettings = await getSettings();
        const lastConfig = await getLastGeneratorConfig();
        const lastUiState = await getSettingValue<CreateUiState>(LAST_CREATE_UI_STATE_KEY);
        let nextConfig: ExerciseConfig = {
          ...DEFAULT_CONFIG,
          handPosition: appSettings.preferredHandPosition,
          grade: appSettings.defaultGrade,
          readingFocus: appSettings.defaultReadingFocus,
        };
        let nextTimeSelections: TimeSignature[] = [nextConfig.timeSignature];
        let nextKeySelections: KeySignature[] = [nextConfig.keySignature];
        let nextShowCustomize = false;
        let nextPresetShuffle: PresetShuffleState = EMPTY_PRESET_SHUFFLE;

        if (params.mode === "rhythm") {
          nextConfig = {
            ...configForMode("rhythm"),
            handPosition: appSettings.preferredHandPosition,
            grade: appSettings.defaultGrade,
            readingFocus: appSettings.defaultReadingFocus,
          };
          nextTimeSelections = [nextConfig.timeSignature];
          nextKeySelections = [nextConfig.keySignature];
          nextShowCustomize = true;
        } else if (params.resume === "last") {
          if (lastUiState) {
            nextConfig = lastUiState.config;
            nextTimeSelections = lastUiState.selectedTimeSignatures;
            nextKeySelections = lastUiState.selectedKeySignatures;
            nextShowCustomize = Boolean(lastUiState.showCustomize);
            nextPresetShuffle = lastUiState.presetShuffle ?? EMPTY_PRESET_SHUFFLE;
          } else if (lastConfig) {
            nextConfig = lastConfig;
          }
        } else if (params.presetId) {
          const preset = await getPresetById(params.presetId);
          if (preset) {
            nextConfig = preset.config;
            nextShowCustomize = true;
          }
        } else if (lastUiState) {
          nextConfig = lastUiState.config;
          nextTimeSelections = lastUiState.selectedTimeSignatures;
          nextKeySelections = lastUiState.selectedKeySignatures;
          nextShowCustomize = Boolean(lastUiState.showCustomize);
          nextPresetShuffle = lastUiState.presetShuffle ?? EMPTY_PRESET_SHUFFLE;
        } else if (lastConfig) {
          nextConfig = lastConfig;
        } else if (params.mode === "piano") {
          nextConfig = {
            ...nextConfig,
            mode: "piano",
            handPosition: appSettings.preferredHandPosition,
            readingFocus: appSettings.defaultReadingFocus,
          };
        }

        if (!cancelled) {
          const normalized = normalizeConfig(nextConfig);
          const normalizedShowCustomize =
            nextShowCustomize || normalized.mode !== "piano";
          if (!normalizedShowCustomize && normalized.mode === "piano") {
            normalized.measureCount = recommendedSharedPresetMeasureCount(normalized.grade);
          }
          const normalizedTimeSelections = normalizeTimeSelections(
            normalized,
            nextTimeSelections,
          );
          const normalizedKeySelections = normalizeKeySelections(
            normalized,
            nextKeySelections,
          );
          const normalizedPresetShuffle = normalizeSharedPresetShuffle(
            normalized,
            normalizedTimeSelections,
            normalizedKeySelections,
            nextPresetShuffle,
          );
          setConfig(normalized);
          setSelectedTimeSignatures(normalizedTimeSelections);
          setSelectedKeySignatures(normalizedKeySelections);
          setPresetShuffle(normalizedPresetShuffle);
          setShowCustomize(normalizedShowCustomize);
        }
      })();

      return () => {
        cancelled = true;
      };
    }, [normalizeConfig, params.mode, params.presetId, params.resume]),
  );

  function updateMode(mode: ExerciseMode) {
    setConfig((current) => {
      const next = configForMode(mode);
      const normalized = normalizeConfig({
        ...next,
        grade: current.grade,
        timeSignature: current.timeSignature,
        measureCount: current.measureCount,
        tempoPreset: current.tempoPreset,
        keySignature: mode === "piano" ? current.keySignature : next.keySignature,
        handPosition: current.handPosition,
        handActivity: current.handActivity,
        coordinationStyle: current.coordinationStyle,
        readingFocus: current.readingFocus,
        rightHandMotion: current.rightHandMotion,
        leftHandPattern: current.leftHandPattern,
        allowRests: current.allowRests,
        allowAccidentals:
          mode === "piano" && current.grade >= 4 ? current.allowAccidentals : false,
      });
      setSelectedTimeSignatures((items) => {
        const normalizedTimes = normalizeTimeSelections(normalized, items);
        setSelectedKeySignatures((keyItems) => {
          const normalizedKeys = normalizeKeySelections(normalized, keyItems);
          setPresetShuffle((currentShuffle) =>
            normalizeSharedPresetShuffle(
              normalized,
              normalizedTimes,
              normalizedKeys,
              currentShuffle,
            ),
          );
          return normalizedKeys;
        });
        return normalizedTimes;
      });
      return normalized;
    });
  }

  function toggleCustomize() {
    if (customizeExpanded) {
      if (config.mode !== "piano") {
        updateMode("piano");
      } else {
        setConfig((current) =>
          normalizeConfig({
            ...current,
            mode: "piano",
            measureCount: recommendedSharedPresetMeasureCount(current.grade),
          }),
        );
      }
      setShowCustomize(false);
      return;
    }

    setShowCustomize(true);
  }

  function handleGenerate() {
    const seed = nextSeed();
    const normalizedTimeSelections = normalizeTimeSelections(config, selectedTimeSignatures);
    const normalizedKeySelections = normalizeKeySelections(config, selectedKeySignatures);
    const normalizedPresetShuffle = normalizeSharedPresetShuffle(
      config,
      normalizedTimeSelections,
      normalizedKeySelections,
      presetShuffle,
    );
    const { requestConfig, nextPresetShuffle } = resolveSharedPresetConfigForRun(
      config,
      seed,
      normalizedTimeSelections,
      normalizedKeySelections,
      normalizedPresetShuffle,
      showCustomize,
    );
    setPresetShuffle(nextPresetShuffle);
    generateMutation.mutate({
      seed,
      requestConfig,
      uiState: {
        config,
        selectedTimeSignatures: normalizedTimeSelections,
        selectedKeySignatures: normalizedKeySelections,
        showCustomize,
        presetShuffle: nextPresetShuffle,
      },
    });
  }

  const advancedFields = (
    <>
      <ChipGroup
        label="Mode"
        value={config.mode}
        options={EXERCISE_OPTIONS.modes}
        onChange={(value) => updateMode(value as ExerciseMode)}
      />

      <ChipGroup
        label="Time signature"
        value={config.timeSignature}
        options={EXERCISE_OPTIONS.timeSignatures.map((value) => ({
          value,
          label: value,
        }))}
        onChange={(value) =>
          updateConfig({ timeSignature: value as ExerciseConfig["timeSignature"] })
        }
      />

      <ChipGroup
        label="Measures"
        value={config.measureCount}
        options={measureOptions.map((value) => ({
          value,
          label: String(value),
        }))}
        onChange={(value) => updateConfig({ measureCount: Number(value) })}
      />

      <ChipGroup
        label="Tempo"
        value={config.tempoPreset}
        options={EXERCISE_OPTIONS.tempoPresets.map((tempo) => ({
          value: tempo.value as TempoPreset,
          label: tempo.label,
        }))}
        onChange={(value) => updateConfig({ tempoPreset: value as TempoPreset })}
      />

      {config.mode === "piano" ? (
        <ChipGroup
          label="Key"
          value={config.keySignature}
          options={keyOptions.map((k: { value: string; label: string }) => ({
            value: k.value as ExerciseConfig["keySignature"],
            label: k.label,
          }))}
          onChange={(value) =>
            updateConfig({ keySignature: value as ExerciseConfig["keySignature"] })
          }
        />
      ) : null}

      <ChipGroup
        label="Hand position"
        value={config.handPosition}
        options={EXERCISE_OPTIONS.handPositions.map((option) => ({
          value: option.value as ExerciseConfig["handPosition"],
          label: option.label,
        }))}
        onChange={(value) =>
          updateConfig({ handPosition: value as ExerciseConfig["handPosition"] })
        }
      />

      <ChipGroup
        label="Hand activity"
        value={config.handActivity}
        options={EXERCISE_OPTIONS.handActivities.map((option) => ({
          value: option.value as ExerciseConfig["handActivity"],
          label: option.label,
        }))}
        onChange={(value) =>
          updateConfig({ handActivity: value as ExerciseConfig["handActivity"] })
        }
      />

      <ChipGroup
        label="Coordination"
        value={config.coordinationStyle}
        options={EXERCISE_OPTIONS.coordinationStyles.map((option) => ({
          value: option.value as ExerciseConfig["coordinationStyle"],
          label: option.label,
        }))}
        onChange={(value) =>
          updateConfig({
            coordinationStyle: value as ExerciseConfig["coordinationStyle"],
          })
        }
      />

      {config.mode === "piano" ? (
        <ChipGroup
          label="Reading focus"
          value={config.readingFocus}
          options={EXERCISE_OPTIONS.readingFocuses.map((option) => ({
            value: option.value as ReadingFocus,
            label: option.label,
          }))}
          onChange={(value) =>
            updateConfig({
              readingFocus: value as ExerciseConfig["readingFocus"],
            })
          }
        />
      ) : null}

      {config.mode === "piano" ? (
        <ChipGroup
          label="Right-hand motion"
          value={config.rightHandMotion}
          options={EXERCISE_OPTIONS.rightHandMotions.map((option) => ({
            value: option.value as ExerciseConfig["rightHandMotion"],
            label: option.label,
          }))}
          onChange={(value) =>
            updateConfig({
              rightHandMotion: value as ExerciseConfig["rightHandMotion"],
            })
          }
        />
      ) : null}

      <ChipGroup
        label="Left-hand pattern"
        value={config.leftHandPattern}
        options={EXERCISE_OPTIONS.leftHandPatterns.map((option) => ({
          value: option.value as ExerciseConfig["leftHandPattern"],
          label: option.label,
        }))}
        onChange={(value) =>
          updateConfig({
            leftHandPattern: value as ExerciseConfig["leftHandPattern"],
          })
        }
      />

      <View style={styles.toggleRow}>
        <View style={styles.toggleCopy}>
          <Text style={styles.toggleTitle}>Allow rests</Text>
          <Text style={styles.toggleBody}>
            Add short rests when the rhythm permits it.
          </Text>
        </View>
        <Switch
          value={config.allowRests}
          onValueChange={(value) => updateConfig({ allowRests: value })}
        />
      </View>

      {config.mode === "piano" ? (
        <View style={styles.toggleRow}>
          <View style={styles.toggleCopy}>
            <Text style={styles.toggleTitle}>Allow accidentals</Text>
            <Text style={styles.toggleBody}>
              Available from Grade 4 onward for controlled chromatic tension and resolution.
            </Text>
          </View>
          <Switch
            value={config.allowAccidentals}
            onValueChange={(value) => updateConfig({ allowAccidentals: value })}
            disabled={config.grade < 4}
          />
        </View>
      ) : null}
    </>
  );

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <TopBar
        eyebrow="Generator"
        title="Plan your next piano reading rep"
        subtitle="Pick what you want to train, preview how the rep will feel, then generate a guided grand-staff exercise."
        rightSlot={
          <TouchableOpacity
            style={styles.settingsButton}
            onPress={() => router.push("/settings")}
            activeOpacity={0.82}
          >
            <Text style={styles.settingsButtonText}>Settings</Text>
          </TouchableOpacity>
        }
      />

      <DevApiBadge note="New generation should come from this backend." />

      <SurfaceCard>
        <ChipGroup
          label="Grade"
          value={config.grade}
          options={EXERCISE_OPTIONS.grades.map((grade) => ({
            value: grade.value,
            label: grade.label,
          }))}
          onChange={(value) => updateConfig({ grade: Number(value) })}
        />

        {gradeMeta ? (
          <View style={styles.inlineNote}>
            <Text style={styles.inlineNoteTitle}>
              {gradeMeta.label} - {gradeMeta.abrsmLevel}
            </Text>
            <Text style={styles.inlineNoteBody}>{gradeMeta.goal}</Text>
            <Text style={styles.inlineNoteBody}>{gradeMeta.description}</Text>
          </View>
        ) : null}

        <View style={styles.presetSection}>
          <View style={styles.sectionCopy}>
            <Text style={styles.sectionEyebrow}>Preset</Text>
            <Text style={styles.sectionTitle}>Pick your level, meter, and key set</Text>
            <Text style={styles.sectionBody}>
              Presets stay simple on purpose. Choose the grade, select the meters and keys you want in rotation, then start reading.
            </Text>
          </View>

          <View style={styles.multiSelectWrap}>
            <Text style={styles.multiSelectLabel}>Time signatures</Text>
            <View style={styles.multiSelectRow}>
              {EXERCISE_OPTIONS.timeSignatures.map((value) => {
                const typedValue = value as TimeSignature;
                const active = selectedTimeSignatures.includes(typedValue);
                return (
                  <TouchableOpacity
                    key={value}
                    style={[styles.multiChip, active && styles.multiChipActive]}
                    onPress={() =>
                      setSelectedTimeSignatures((current) => {
                        const next = toggleItem(current, typedValue);
                        const normalizedTimes = next.length ? next : [typedValue];
                        setPresetShuffle((currentShuffle) =>
                          normalizeSharedPresetShuffle(
                            config,
                            normalizedTimes,
                            selectedKeySignatures,
                            {
                              ...currentShuffle,
                              timeBag: [],
                            },
                          ),
                        );
                        return normalizedTimes;
                      })
                    }
                    activeOpacity={0.82}
                  >
                    <Text style={[styles.multiChipText, active && styles.multiChipTextActive]}>
                      {value}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>

          {config.mode === "piano" ? (
            <View style={styles.multiSelectWrap}>
              <Text style={styles.multiSelectLabel}>Key signatures</Text>
              <View style={styles.multiSelectRow}>
                {keyOptions.map((keyOption: { value: string; label: string }) => {
                  const typedValue = keyOption.value as KeySignature;
                  const active = selectedKeySignatures.includes(typedValue);
                  return (
                    <TouchableOpacity
                      key={keyOption.value}
                      style={[styles.multiChip, active && styles.multiChipActive]}
                      onPress={() =>
                        setSelectedKeySignatures((current) => {
                          const next = toggleItem(current, typedValue);
                          const normalizedKeys = next.length ? next : [typedValue];
                          setPresetShuffle((currentShuffle) =>
                            normalizeSharedPresetShuffle(
                              config,
                              selectedTimeSignatures,
                              normalizedKeys,
                              {
                                ...currentShuffle,
                                keyBag: [],
                              },
                            ),
                          );
                          return normalizedKeys;
                        })
                      }
                      activeOpacity={0.82}
                    >
                      <Text
                        style={[styles.multiChipText, active && styles.multiChipTextActive]}
                      >
                        {keyOption.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </View>
          ) : null}
        </View>

        <View style={styles.previewCard}>
          <View style={styles.previewHeader}>
            <Text style={styles.previewLabel}>This rep will feel like</Text>
            <Text style={styles.previewModeTag}>
              {showCustomize
                ? "Custom rep"
                : config.mode === "piano"
                  ? "Preset rep"
                  : "Rhythm preset"}
            </Text>
          </View>
          <Text style={styles.previewLead}>{preview.lead}</Text>
          <Text style={styles.previewBody}>{preview.detail}</Text>
          <View style={styles.previewMetaRow}>
            {previewMeta.map((item, index) => (
              <Text key={`${item}-${index}`} style={styles.previewMetaChip}>
                {item}
              </Text>
            ))}
          </View>
        </View>

        <View style={styles.setupSummaryCard}>
          <Text style={styles.setupSummaryLabel}>Current setup</Text>
          <View style={styles.setupSummaryRow}>
            {setupSummary.map((item) => (
              <Text key={item} style={styles.setupSummaryChip}>
                {item}
              </Text>
            ))}
          </View>
        </View>
      </SurfaceCard>

      {config.mode === "piano" ? (
        <SurfaceCard>
          <TouchableOpacity
            style={styles.customizeToggle}
            onPress={toggleCustomize}
            activeOpacity={0.82}
          >
            <View style={styles.customizeCopy}>
              <Text style={styles.customizeTitle}>
                {customizeExpanded ? "Custom setup is open" : "Need more control?"}
              </Text>
              <Text style={styles.customizeBody}>
                {customizeExpanded
                  ? "You can now adjust all available reading features, not just the preset selectors."
                  : "Open the full control panel only when you want to move beyond grade, meter, and key selection."}
              </Text>
            </View>
            <Text style={styles.customizeAction}>
              {customizeExpanded ? "Close custom" : "Custom"}
            </Text>
          </TouchableOpacity>

          {customizeExpanded ? advancedFields : null}
        </SurfaceCard>
      ) : (
        <SurfaceCard>{advancedFields}</SurfaceCard>
      )}

      <TouchableOpacity
        style={[styles.primaryButton, generateMutation.isPending && styles.buttonDisabled]}
        onPress={handleGenerate}
        activeOpacity={0.82}
        disabled={generateMutation.isPending}
      >
        {generateMutation.isPending ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.primaryButtonText}>Start</Text>
        )}
      </TouchableOpacity>

      <SurfaceCard style={styles.coachNote}>
        <Text style={styles.coachNoteLabel}>Why this rep</Text>
        <Text style={styles.coachNoteBody}>{whyRep}</Text>
      </SurfaceCard>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Colors.bg,
  },
  content: {
    padding: 20,
    gap: 16,
    paddingBottom: 40,
  },
  settingsButton: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  settingsButtonText: {
    fontSize: 13,
    fontWeight: "700",
    color: Colors.ink,
  },
  inlineNote: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paperAlt,
    padding: 14,
    gap: 4,
  },
  inlineNoteTitle: {
    fontSize: 15,
    fontWeight: "700",
    color: Colors.ink,
  },
  inlineNoteBody: {
    fontSize: 13,
    lineHeight: 20,
    color: Colors.muted,
  },
  presetSection: {
    gap: 12,
    paddingTop: 4,
  },
  sectionCopy: {
    gap: 4,
  },
  sectionEyebrow: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    color: Colors.muted,
  },
  sectionTitle: {
    fontSize: 19,
    lineHeight: 24,
    fontWeight: "800",
    color: Colors.ink,
  },
  sectionBody: {
    fontSize: 14,
    lineHeight: 21,
    color: Colors.muted,
  },
  multiSelectWrap: {
    gap: 8,
  },
  multiSelectLabel: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.8,
    color: Colors.muted,
  },
  multiSelectRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  multiChip: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  multiChipActive: {
    borderColor: Colors.accent,
    backgroundColor: Colors.accentSoft,
  },
  multiChipText: {
    fontSize: 13,
    fontWeight: "700",
    color: Colors.ink,
  },
  multiChipTextActive: {
    color: Colors.accent,
  },
  previewCard: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paperAlt,
    padding: 14,
    gap: 8,
  },
  previewHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  previewLabel: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    color: Colors.muted,
  },
  previewModeTag: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
    paddingHorizontal: 8,
    paddingVertical: 4,
    fontSize: 11,
    fontWeight: "700",
    color: Colors.ink,
  },
  previewLead: {
    fontSize: 18,
    lineHeight: 25,
    fontWeight: "800",
    color: Colors.ink,
  },
  previewBody: {
    fontSize: 14,
    lineHeight: 21,
    color: Colors.muted,
  },
  previewMetaRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    paddingTop: 2,
  },
  previewMetaChip: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 12,
    fontWeight: "700",
    color: Colors.muted,
  },
  setupSummaryCard: {
    gap: 8,
    paddingTop: 6,
  },
  setupSummaryLabel: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    color: Colors.muted,
  },
  setupSummaryRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  setupSummaryChip: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 12,
    fontWeight: "700",
    color: Colors.ink,
  },
  customizeToggle: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.faint,
    paddingBottom: 12,
  },
  customizeCopy: {
    flex: 1,
    gap: 4,
  },
  customizeTitle: {
    fontSize: 16,
    fontWeight: "800",
    color: Colors.ink,
  },
  customizeBody: {
    fontSize: 13,
    lineHeight: 20,
    color: Colors.muted,
  },
  customizeAction: {
    fontSize: 13,
    fontWeight: "800",
    color: Colors.accent,
  },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: Colors.faint,
    paddingTop: 12,
  },
  toggleCopy: {
    flex: 1,
    gap: 4,
  },
  toggleTitle: {
    fontSize: 14,
    fontWeight: "700",
    color: Colors.ink,
  },
  toggleBody: {
    fontSize: 13,
    lineHeight: 20,
    color: Colors.muted,
  },
  primaryButton: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: Colors.accent,
    borderWidth: 1,
    borderColor: Colors.accent,
    paddingVertical: 16,
  },
  primaryButtonText: {
    color: "#fff",
    fontSize: 15,
    fontWeight: "800",
  },
  buttonDisabled: {
    opacity: 0.65,
  },
  coachNote: {
    gap: 6,
  },
  coachNoteLabel: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    color: Colors.muted,
  },
  coachNoteBody: {
    fontSize: 14,
    lineHeight: 21,
    color: Colors.ink,
  },
});
