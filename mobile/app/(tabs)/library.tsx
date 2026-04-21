import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { SurfaceCard } from "@/src/components/SurfaceCard";
import { TopBar } from "@/src/components/TopBar";
import { getPresets, getRecentExercises, getRecentSessions } from "@/src/db/database";
import {
  formatDuration,
  formatHandActivityLabel,
  formatHandPositionLabel,
  formatModeLabel,
  formatTimeAgo,
} from "@/src/lib/format";
import { Colors } from "@/src/theme/colors";
import type { PracticeSession, SavedPreset } from "@/src/types/exercise";

type RecentExercise = Awaited<ReturnType<typeof getRecentExercises>>[number];

export default function LibraryScreen() {
  const router = useRouter();
  const [presets, setPresets] = useState<SavedPreset[]>([]);
  const [recentExercises, setRecentExercises] = useState<RecentExercise[]>([]);
  const [sessions, setSessions] = useState<PracticeSession[]>([]);

  const loadData = useCallback(async () => {
    const [savedPresets, generated, recentSessions] = await Promise.all([
      getPresets(),
      getRecentExercises(),
      getRecentSessions(),
    ]);
    setPresets(savedPresets);
    setRecentExercises(generated);
    setSessions(recentSessions);
  }, []);

  useFocusEffect(
    useCallback(() => {
      void loadData();
    }, [loadData]),
  );

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <TopBar
        eyebrow="Library"
        title="Presets and piano practice history"
        subtitle="Keep your favorite hand setups close and review how your recent reading sessions felt."
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

      <SurfaceCard>
        <Text style={styles.sectionTitle}>Saved presets</Text>
        {presets.length === 0 ? (
          <Text style={styles.emptyCopy}>
            Save a preset from the exercise screen and it will appear here.
          </Text>
        ) : (
          presets.map((preset) => (
            <TouchableOpacity
              key={preset.id}
              style={styles.row}
              onPress={() =>
                router.push({
                  pathname: "/(tabs)/create",
                  params: { presetId: preset.id },
                })
              }
              activeOpacity={0.82}
            >
              <View style={styles.rowCopy}>
                <Text style={styles.rowTitle}>{preset.name}</Text>
                <Text style={styles.rowMeta}>
                  {formatModeLabel(preset.config.mode)} -{" "}
                  {formatHandPositionLabel(preset.config.handPosition)} - Grade{" "}
                  {preset.config.grade}
                </Text>
              </View>
              <Text style={styles.rowAction}>Reuse</Text>
            </TouchableOpacity>
          ))
        )}
      </SurfaceCard>

      <SurfaceCard>
        <Text style={styles.sectionTitle}>Recent sheets</Text>
        {recentExercises.length === 0 ? (
          <Text style={styles.emptyCopy}>
            Generated exercises will show up here after your first session.
          </Text>
        ) : (
          recentExercises.map((exercise) => (
            <TouchableOpacity
              key={exercise.exerciseId}
              style={styles.row}
              onPress={() => router.push(`/exercise/${exercise.exerciseId}`)}
              activeOpacity={0.82}
            >
              <View style={styles.rowCopy}>
                <Text style={styles.rowTitle}>{exercise.title}</Text>
                <Text style={styles.rowMeta}>
                  {formatHandPositionLabel(exercise.config.handPosition)} -{" "}
                  {exercise.config.timeSignature} - {exercise.config.measureCount} bars -{" "}
                  {formatTimeAgo(exercise.createdAt)}
                </Text>
              </View>
              <Text style={styles.rowAction}>Open</Text>
            </TouchableOpacity>
          ))
        )}
      </SurfaceCard>

      <SurfaceCard>
        <Text style={styles.sectionTitle}>Recent sessions</Text>
        {sessions.length === 0 ? (
          <Text style={styles.emptyCopy}>
            Complete a practice run and your session history will build here.
          </Text>
        ) : (
          sessions.map((session) => (
            <View key={session.id} style={styles.row}>
              <View style={styles.rowCopy}>
                <Text style={styles.rowTitle}>{session.title}</Text>
                <Text style={styles.rowMeta}>
                  Rating {session.selfRating}/5 - {formatDuration(session.durationSeconds)} -{" "}
                  {formatTimeAgo(session.finishedAt)}
                </Text>
              </View>
            </View>
          ))
        )}
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
  sectionTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: Colors.ink,
  },
  emptyCopy: {
    fontSize: 14,
    lineHeight: 22,
    color: Colors.muted,
  },
  row: {
    borderTopWidth: 1,
    borderTopColor: Colors.faint,
    paddingTop: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  rowCopy: {
    flex: 1,
    gap: 4,
  },
  rowTitle: {
    fontSize: 15,
    fontWeight: "700",
    color: Colors.ink,
  },
  rowMeta: {
    fontSize: 13,
    lineHeight: 20,
    color: Colors.muted,
  },
  rowAction: {
    fontSize: 13,
    fontWeight: "700",
    color: Colors.accent,
  },
});
