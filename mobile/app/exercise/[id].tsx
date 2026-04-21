import { useMutation } from "@tanstack/react-query";
import { Ionicons } from "@expo/vector-icons";
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";

import { NotationPreview } from "@/src/components/NotationPreview";
import { DevApiBadge } from "@/src/components/DevApiBadge";
import { SurfaceCard } from "@/src/components/SurfaceCard";
import { TopBar } from "@/src/components/TopBar";
import {
  getExerciseById,
  getSettingValue,
  getSettings,
  saveGeneratedExercise,
  savePracticeSession,
  savePreset,
} from "@/src/db/database";
import { generateExercise } from "@/src/lib/api";
import {
  formatDuration,
  formatHandPositionLabel,
  formatModeLabel,
} from "@/src/lib/format";
import { nextSeed } from "@/src/lib/options";
import {
  normalizePresetShuffle,
  resolvePresetConfigForRun,
} from "@/src/lib/presetGeneration";
import { Colors } from "@/src/theme/colors";
import type {
  AppSettings,
  ExerciseGenerationContext,
  PresetShuffleState,
  TimeSignature,
  KeySignature,
  StoredExercise,
} from "@/src/types/exercise";

type LastCreateUiState = {
  selectedTimeSignatures: TimeSignature[];
  selectedKeySignatures: KeySignature[];
  showCustomize: boolean;
  presetShuffle?: PresetShuffleState;
};

const LAST_CREATE_UI_STATE_KEY = "last_create_ui_state";

function beatMs(bpm: number) {
  return Math.max(280, Math.round((60 / bpm) * 1000));
}

function countBeats(timeSignature: string) {
  return Number(timeSignature.split("/")[0]) || 4;
}

export default function ExerciseScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [exercise, setExercise] = useState<StoredExercise | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [presetModalVisible, setPresetModalVisible] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [ratingVisible, setRatingVisible] = useState(false);
  const [countingIn, setCountingIn] = useState(false);
  const [countBeat, setCountBeat] = useState(0);
  const [practiceStart, setPracticeStart] = useState<string | null>(null);
  const [practiceSeconds, setPracticeSeconds] = useState(0);
  const [pulseIndex, setPulseIndex] = useState(0);
  const countIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const practiceIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pulseIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const player = useAudioPlayer(exercise?.audioUrl ?? undefined, {
    updateInterval: 250,
  });
  const playerStatus = useAudioPlayerStatus(player);

  const regenerateMutation = useMutation({
    mutationFn: async () => {
      if (!exercise) {
        throw new Error("Exercise missing");
      }

      const seed = nextSeed();
      let requestConfig = exercise.config;
      let nextGenerationContext: ExerciseGenerationContext | null =
        exercise.generationContext ?? null;

      if (!nextGenerationContext) {
        const [lastExerciseId, lastCreateUiState] = await Promise.all([
          getSettingValue<string>("last_exercise_id"),
          getSettingValue<LastCreateUiState>(LAST_CREATE_UI_STATE_KEY),
        ]);
        if (
          lastExerciseId === exercise.exerciseId &&
          lastCreateUiState &&
          !lastCreateUiState.showCustomize
        ) {
          nextGenerationContext = {
            presetMode: true,
            selectedTimeSignatures: lastCreateUiState.selectedTimeSignatures,
            selectedKeySignatures: lastCreateUiState.selectedKeySignatures,
            presetShuffle: lastCreateUiState.presetShuffle ?? {
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

      const next = await generateExercise({
        ...requestConfig,
        seed,
      });
      await saveGeneratedExercise({
        ...next,
        generationContext: nextGenerationContext,
      });
      return next.exerciseId;
    },
    onSuccess: (exerciseId) => {
      router.replace(`/exercise/${exerciseId}`);
    },
    onError: (error) => {
      Alert.alert(
        "Could not regenerate",
        error instanceof Error ? error.message : "Try again.",
      );
    },
  });

  const bpm = exercise?.summary.bpm ?? 92;
  const totalCountBeats = exercise ? countBeats(exercise.timeSignature) : 4;
  const pulseDots = useMemo(() => Array.from({ length: totalCountBeats }), [totalCountBeats]);

  const clearTimers = useCallback(() => {
    if (countIntervalRef.current) {
      clearInterval(countIntervalRef.current);
      countIntervalRef.current = null;
    }
    if (practiceIntervalRef.current) {
      clearInterval(practiceIntervalRef.current);
      practiceIntervalRef.current = null;
    }
    if (pulseIntervalRef.current) {
      clearInterval(pulseIntervalRef.current);
      pulseIntervalRef.current = null;
    }
  }, []);

  const loadExercise = useCallback(async () => {
    if (!id) {
      return;
    }

    setLoading(true);

    try {
      const [nextExercise, nextSettings] = await Promise.all([
        getExerciseById(id),
        getSettings(),
      ]);
      setExercise(nextExercise);
      setSettings(nextSettings);
      setPresetName(nextExercise ? `${nextExercise.title} preset` : "My preset");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(
    useCallback(() => {
      void loadExercise();
      return clearTimers;
    }, [clearTimers, loadExercise]),
  );

  useEffect(() => {
    if (!practiceStart) {
      return;
    }

    practiceIntervalRef.current = setInterval(() => {
      setPracticeSeconds(
        Math.floor((Date.now() - new Date(practiceStart).getTime()) / 1000),
      );
    }, 1000);

    return () => {
      if (practiceIntervalRef.current) {
        clearInterval(practiceIntervalRef.current);
        practiceIntervalRef.current = null;
      }
    };
  }, [practiceStart]);

  useEffect(() => {
    if (!practiceStart || !settings?.metronomeDefault) {
      if (pulseIntervalRef.current) {
        clearInterval(pulseIntervalRef.current);
        pulseIntervalRef.current = null;
      }
      return;
    }

    setPulseIndex(0);
    pulseIntervalRef.current = setInterval(() => {
      setPulseIndex((current) => (current + 1) % totalCountBeats);
    }, beatMs(bpm));

    return () => {
      if (pulseIntervalRef.current) {
        clearInterval(pulseIntervalRef.current);
        pulseIntervalRef.current = null;
      }
    };
  }, [bpm, practiceStart, settings?.metronomeDefault, totalCountBeats]);

  function beginPracticeNow() {
    setPulseIndex(0);
    setPracticeStart(new Date().toISOString());
    setPracticeSeconds(0);
  }

  function startPractice() {
    if (!exercise) {
      return;
    }

    if (!settings?.countInDefault) {
      beginPracticeNow();
      return;
    }

    setCountingIn(true);
    setCountBeat(totalCountBeats);

    countIntervalRef.current = setInterval(() => {
      setCountBeat((current) => {
        if (current <= 1) {
          if (countIntervalRef.current) {
            clearInterval(countIntervalRef.current);
            countIntervalRef.current = null;
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
    await savePracticeSession({
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
    setRatingVisible(false);
    Alert.alert("Session saved", "Your practice session is now in the library.");
  }

  async function handleSavePreset() {
    if (!exercise) {
      return;
    }

    await savePreset(presetName.trim() || `${exercise.title} preset`, exercise.config);
    setPresetModalVisible(false);
    Alert.alert("Preset saved", "You can reuse it any time from the Library tab.");
  }

  if (loading || !settings) {
    return (
      <View style={styles.loadingWrap}>
        <ActivityIndicator color={Colors.accent} />
      </View>
    );
  }

  if (!exercise) {
    return (
      <View style={styles.loadingWrap}>
        <Text style={styles.emptyText}>Exercise not found.</Text>
      </View>
    );
  }

  return (
    <>
      <ScrollView
        style={styles.screen}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
      <TopBar
        eyebrow="Exercise"
        title={exercise.title}
        subtitle={`Grand staff - ${exercise.timeSignature} - ${exercise.measureCount} bars - Grade ${exercise.grade} guided reading`}
          onBack={() => router.back()}
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

        <DevApiBadge note="If this looks wrong, regenerate against this API." />

        <SurfaceCard>
          <NotationPreview svg={exercise.svg} scale={settings.notationScale} />

          <View style={styles.summaryGrid}>
            <SurfaceCard style={styles.summaryTile}>
              <Text style={styles.summaryLabel}>Phrase shape</Text>
              <Text style={styles.summaryValue}>{exercise.summary.phraseShapeLabel}</Text>
            </SurfaceCard>

            <SurfaceCard style={styles.summaryTile}>
              <Text style={styles.summaryLabel}>Cadence</Text>
              <Text style={styles.summaryValue}>{exercise.summary.cadenceLabel}</Text>
            </SurfaceCard>

            <SurfaceCard style={styles.summaryTile}>
              <Text style={styles.summaryLabel}>Harmony focus</Text>
              <Text style={styles.summaryValue}>
                {exercise.summary.harmonyFocus[0] || exercise.summary.handPositionLabel}
              </Text>
            </SurfaceCard>

            <SurfaceCard style={styles.summaryTile}>
              <Text style={styles.summaryLabel}>Technique focus</Text>
              <Text style={styles.summaryValue}>
                {exercise.summary.techniqueFocus[0] ||
                  exercise.summary.rhythmFocus[0] ||
                  exercise.summary.coordinationLabel}
              </Text>
            </SurfaceCard>
          </View>

          <SurfaceCard style={styles.summaryBand}>
            <Text style={styles.summaryBandTitle}>Reading profile</Text>
            <Text style={styles.summaryBandBody}>
              {exercise.summary.handPositionLabel} - {exercise.summary.coordinationLabel} -
              {" "}
              {exercise.summary.rhythmFocus.join(", ")}
            </Text>
          </SurfaceCard>

          <View style={styles.rowButtons}>
            <TouchableOpacity
              style={styles.primaryButton}
              onPress={() => {
                if (playerStatus.playing) {
                  player.pause();
                } else {
                  player.play();
                }
              }}
              activeOpacity={0.82}
            >
              <Ionicons
                name={playerStatus.playing ? "pause" : "play"}
                size={16}
                color="#fff"
              />
              <Text style={styles.primaryButtonText}>
                {playerStatus.playing ? "Pause preview" : "Play preview"}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={() => regenerateMutation.mutate()}
              activeOpacity={0.82}
            >
              <Text style={styles.secondaryButtonText}>
                {regenerateMutation.isPending ? "Regenerating..." : "Regenerate"}
              </Text>
            </TouchableOpacity>
          </View>

          <View style={styles.rowButtons}>
            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={() => setPresetModalVisible(true)}
              activeOpacity={0.82}
            >
              <Text style={styles.secondaryButtonText}>Save preset</Text>
            </TouchableOpacity>

            {!practiceStart ? (
              <TouchableOpacity
                style={styles.primaryButton}
                onPress={startPractice}
                activeOpacity={0.82}
              >
                <Text style={styles.primaryButtonText}>Start practice</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={styles.primaryButton}
                onPress={() => setRatingVisible(true)}
                activeOpacity={0.82}
              >
                <Text style={styles.primaryButtonText}>Finish session</Text>
              </TouchableOpacity>
            )}
          </View>
        </SurfaceCard>

        <SurfaceCard>
          <Text style={styles.sectionTitle}>Practice status</Text>
          {countingIn ? (
            <Text style={styles.statusLead}>Count in: {countBeat}</Text>
          ) : practiceStart ? (
            <>
              <Text style={styles.statusLead}>Practice running</Text>
              <Text style={styles.statusBody}>{formatDuration(practiceSeconds)}</Text>
              {settings.metronomeDefault ? (
                <View style={styles.pulseRow}>
                  {pulseDots.map((_, index) => (
                    <View
                      key={index}
                      style={[
                        styles.pulseDot,
                        index === pulseIndex && styles.pulseDotActive,
                      ]}
                    />
                  ))}
                </View>
              ) : null}
            </>
          ) : (
            <Text style={styles.statusBody}>
              Start practice to trigger the count-in and begin logging this piano session.
            </Text>
          )}
        </SurfaceCard>
      </ScrollView>

      <Modal visible={presetModalVisible} transparent animationType="fade">
        <Pressable style={styles.backdrop} onPress={() => setPresetModalVisible(false)}>
          <Pressable style={styles.modalCard} onPress={() => {}}>
            <Text style={styles.modalTitle}>Save preset</Text>
            <Text style={styles.modalBody}>
              Give this guided reading setup a name so you can reopen it from the Library tab.
            </Text>
            <TextInput
              value={presetName}
              onChangeText={setPresetName}
              style={styles.input}
              placeholder="Warm-up in 4/4"
              placeholderTextColor={Colors.muted}
            />
            <TouchableOpacity
              style={styles.primaryButton}
              onPress={handleSavePreset}
              activeOpacity={0.82}
            >
              <Text style={styles.primaryButtonText}>Save preset</Text>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>

      <Modal visible={ratingVisible} transparent animationType="fade">
        <Pressable style={styles.backdrop} onPress={() => setRatingVisible(false)}>
          <Pressable style={styles.modalCard} onPress={() => {}}>
            <Text style={styles.modalTitle}>How did that feel?</Text>
            <Text style={styles.modalBody}>
              Save the session with a quick self-rating so your recent reading history stays meaningful.
            </Text>
            <View style={styles.ratingRow}>
              {[1, 2, 3, 4, 5].map((value) => (
                <TouchableOpacity
                  key={value}
                  style={styles.ratingPill}
                  onPress={() => void finishPractice(value)}
                  activeOpacity={0.82}
                >
                  <Text style={styles.ratingPillText}>{value}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </>
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
    paddingBottom: 36,
  },
  loadingWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: Colors.bg,
  },
  emptyText: {
    color: Colors.muted,
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
  summaryGrid: {
    flexDirection: "row",
    gap: 10,
    flexWrap: "wrap",
  },
  summaryTile: {
    flex: 1,
    minWidth: 92,
    gap: 4,
    padding: 12,
  },
  summaryBand: {
    gap: 6,
    padding: 12,
  },
  summaryLabel: {
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 1,
    fontWeight: "700",
    color: Colors.muted,
  },
  summaryValue: {
    fontSize: 15,
    fontWeight: "700",
    color: Colors.ink,
  },
  summaryBandTitle: {
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 1,
    fontWeight: "700",
    color: Colors.muted,
  },
  summaryBandBody: {
    fontSize: 14,
    lineHeight: 22,
    color: Colors.ink,
  },
  rowButtons: {
    flexDirection: "row",
    gap: 10,
  },
  primaryButton: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: Colors.accent,
    borderWidth: 1,
    borderColor: Colors.accent,
    paddingVertical: 14,
    paddingHorizontal: 16,
  },
  primaryButtonText: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "800",
  },
  secondaryButton: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
    paddingVertical: 14,
    paddingHorizontal: 16,
  },
  secondaryButtonText: {
    color: Colors.ink,
    fontSize: 14,
    fontWeight: "700",
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: Colors.ink,
  },
  statusLead: {
    fontSize: 26,
    lineHeight: 32,
    fontWeight: "800",
    color: Colors.ink,
  },
  statusBody: {
    fontSize: 14,
    lineHeight: 22,
    color: Colors.muted,
  },
  pulseRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 6,
  },
  pulseDot: {
    width: 14,
    height: 14,
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paperAlt,
  },
  pulseDotActive: {
    backgroundColor: Colors.accent,
    borderColor: Colors.accent,
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(20, 24, 29, 0.42)",
    justifyContent: "center",
    padding: 24,
  },
  modalCard: {
    backgroundColor: Colors.paper,
    borderWidth: 1,
    borderColor: Colors.faint,
    padding: 18,
    gap: 12,
  },
  modalTitle: {
    fontSize: 24,
    fontWeight: "800",
    color: Colors.ink,
  },
  modalBody: {
    fontSize: 14,
    lineHeight: 22,
    color: Colors.muted,
  },
  input: {
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: "#fff",
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: Colors.ink,
  },
  ratingRow: {
    flexDirection: "row",
    gap: 10,
  },
  ratingPill: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paperAlt,
    paddingVertical: 14,
  },
  ratingPillText: {
    fontSize: 16,
    fontWeight: "800",
    color: Colors.ink,
  },
});
