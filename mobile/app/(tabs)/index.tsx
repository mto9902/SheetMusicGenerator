import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { SurfaceCard } from "@/src/components/SurfaceCard";
import { TopBar } from "@/src/components/TopBar";
import { getHomeSnapshot } from "@/src/db/database";
import { EXERCISE_OPTIONS } from "@/src/lib/options";
import {
  formatDuration,
  formatHandActivityLabel,
  formatHandPositionLabel,
  formatModeLabel,
  formatTimeAgo,
} from "@/src/lib/format";
import { Colors } from "@/src/theme/colors";
import type { ExerciseConfig, ExerciseMode, PracticeSession } from "@/src/types/exercise";

type HomeSnapshot = Awaited<ReturnType<typeof getHomeSnapshot>>;

function SummaryLine({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.summaryLine}>
      <Text style={styles.summaryLabel}>{label}</Text>
      <Text style={styles.summaryValue}>{value}</Text>
    </View>
  );
}

export default function HomeScreen() {
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<HomeSnapshot | null>(null);

  const loadSnapshot = useCallback(async () => {
    const next = await getHomeSnapshot();
    setSnapshot(next);
  }, []);

  useFocusEffect(
    useCallback(() => {
      void loadSnapshot();
    }, [loadSnapshot]),
  );

  const lastConfig = snapshot?.lastGeneratorConfig ?? null;
  const recentSessions = snapshot?.recentSessions ?? [];
  const recentExercises = snapshot?.recentExercises ?? [];

  function openCreateFromConfig(config: ExerciseConfig | null, mode?: ExerciseMode) {
    if (config) {
      router.push({
        pathname: "/(tabs)/create",
        params: { resume: "last" },
      });
      return;
    }

    router.push({
      pathname: "/(tabs)/create",
      params: { mode: mode || "piano" },
    });
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <TopBar
        eyebrow="SheetGenerator"
        title="Build your next piano reading session"
        subtitle="Generate phrase-led grand-staff reading, keep your last setup nearby, and move straight into the next musical rep."
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

      <View style={styles.quickRow}>
        <TouchableOpacity
          style={[styles.quickCard, styles.quickCardAccent]}
          onPress={() => openCreateFromConfig(null, "piano")}
          activeOpacity={0.82}
        >
          <Text style={[styles.quickEyebrow, styles.quickEyebrowAccent]}>Quick start</Text>
          <Text style={[styles.quickTitle, styles.quickTitleAccent]}>Piano Reading</Text>
          <Text style={[styles.quickBody, styles.quickBodyAccent]}>
            Grand-staff phrase reading with right-hand lead, harmonic anchors, and clearer cadences.
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.quickCard}
          onPress={() => openCreateFromConfig(null, "rhythm")}
          activeOpacity={0.82}
        >
          <Text style={styles.quickEyebrow}>Quick start</Text>
          <Text style={styles.quickTitle}>Piano Rhythm</Text>
          <Text style={styles.quickBody}>
            Fixed-anchor rhythm practice for both hands while keeping the pulse readable.
          </Text>
        </TouchableOpacity>
      </View>

      <SurfaceCard>
        <Text style={styles.sectionTitle}>Resume your last setup</Text>
        {lastConfig ? (
          <>
            <SummaryLine label="Mode" value={formatModeLabel(lastConfig.mode)} />
            <SummaryLine label="Meter" value={lastConfig.timeSignature} />
            <SummaryLine
              label="Hands"
              value={`${formatHandPositionLabel(lastConfig.handPosition)} - ${formatHandActivityLabel(lastConfig.handActivity)}`}
            />
            <SummaryLine
              label="Focus"
              value={`${lastConfig.measureCount} bars - ${EXERCISE_OPTIONS.grades.find((g) => g.value === lastConfig.grade)?.label ?? `Grade ${lastConfig.grade}`} - ${lastConfig.readingFocus} reading`}
            />
            <TouchableOpacity
              style={styles.primaryButton}
              onPress={() => openCreateFromConfig(lastConfig)}
              activeOpacity={0.82}
            >
              <Text style={styles.primaryButtonText}>Resume setup</Text>
            </TouchableOpacity>
          </>
        ) : (
          <Text style={styles.emptyCopy}>
            Generate your first guided reading sheet and the latest setup will live here for easy reuse.
          </Text>
        )}
      </SurfaceCard>

      <SurfaceCard>
        <Text style={styles.sectionTitle}>Recent practice</Text>
        {recentSessions.length === 0 ? (
          <Text style={styles.emptyCopy}>
            Finish a session and it will appear here with timing, self-rating, and your latest reading work.
          </Text>
        ) : (
          recentSessions.map((session: PracticeSession) => (
            <View key={session.id} style={styles.row}>
              <View style={styles.rowCopy}>
                <Text style={styles.rowTitle}>{session.title}</Text>
                <Text style={styles.rowMeta}>
                  {formatDuration(session.durationSeconds)} - rating {session.selfRating}/5 -{" "}
                  {formatTimeAgo(session.finishedAt)}
                </Text>
              </View>
            </View>
          ))
        )}
      </SurfaceCard>

      <SurfaceCard>
        <Text style={styles.sectionTitle}>Recent sheets</Text>
        {recentExercises.length === 0 ? (
          <Text style={styles.emptyCopy}>Your latest generated exercises will appear here.</Text>
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
    paddingBottom: 36,
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
  quickRow: {
    flexDirection: "row",
    gap: 12,
  },
  quickCard: {
    flex: 1,
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
    padding: 16,
    gap: 8,
  },
  quickCardAccent: {
    backgroundColor: Colors.accent,
    borderColor: Colors.accent,
  },
  quickEyebrow: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    color: Colors.muted,
  },
  quickEyebrowAccent: {
    color: "#d7e0f0",
  },
  quickTitle: {
    fontSize: 24,
    fontWeight: "800",
    color: Colors.ink,
  },
  quickTitleAccent: {
    color: "#fff",
  },
  quickBody: {
    fontSize: 13,
    lineHeight: 20,
    color: Colors.muted,
  },
  quickBodyAccent: {
    color: "#d7e0f0",
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: Colors.ink,
  },
  summaryLine: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: Colors.faint,
    paddingTop: 10,
  },
  summaryLabel: {
    fontSize: 13,
    fontWeight: "700",
    color: Colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  summaryValue: {
    fontSize: 14,
    color: Colors.ink,
  },
  primaryButton: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: Colors.accent,
    borderWidth: 1,
    borderColor: Colors.accent,
    paddingVertical: 14,
    marginTop: 4,
  },
  primaryButtonText: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "800",
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
