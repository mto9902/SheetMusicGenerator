import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { formatGradeStageLabel as formatConfigStageLabel } from "@shared/options";
import {
  formatDuration,
  formatHandPositionLabel,
  formatModeLabel,
  formatTimeAgo,
} from "@shared/format";
import type { ExerciseListItem, PracticeSession, SavedPreset } from "@shared/types";

import { storage } from "@/storage";

export function LibraryPage() {
  const navigate = useNavigate();
  const [presets, setPresets] = useState<SavedPreset[]>([]);
  const [recentExercises, setRecentExercises] = useState<ExerciseListItem[]>([]);
  const [sessions, setSessions] = useState<PracticeSession[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function loadLibrary() {
      await storage.initialize();
      const [nextPresets, nextExercises, nextSessions] = await Promise.all([
        storage.getPresets(),
        storage.getRecentExercises(),
        storage.getRecentSessions(),
      ]);

      if (!cancelled) {
        setPresets(nextPresets);
        setRecentExercises(nextExercises);
        setSessions(nextSessions);
      }
    }

    void loadLibrary();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <p className="eyebrow">Library</p>
          <h1 className="page__title">Presets and desktop history</h1>
          <p className="page__subtitle">
            Keep favorite setups close, reopen recent sheets, and review what practice felt like.
          </p>
        </div>
      </header>

      <div className="content-grid">
        <section className="card">
          <div className="card__heading">
            <h2>Saved presets</h2>
          </div>
          {presets.length ? (
            <div className="stack-list">
              {presets.map((preset) => {
                const stageLabel = formatConfigStageLabel(preset.config.gradeStage);
                return (
                <button
                  key={preset.id}
                  type="button"
                  className="list-item"
                  onClick={() => navigate(`/create?presetId=${preset.id}`)}
                >
                  <div className="list-item__main">
                    <strong>{preset.name}</strong>
                    <span>
                      {formatModeLabel(preset.config.mode)} | {formatHandPositionLabel(preset.config.handPosition)} |
                      {" "}Grade {preset.config.grade}
                      {stageLabel ? ` | ${stageLabel}` : ""}
                    </span>
                  </div>
                  <span className="list-item__meta">Reuse</span>
                </button>
                );
              })}
            </div>
          ) : (
            <p className="empty-copy">
              Save a preset from the exercise page and it will appear here.
            </p>
          )}
        </section>

        <section className="card">
          <div className="card__heading">
            <h2>Recent sheets</h2>
          </div>
          {recentExercises.length ? (
            <div className="stack-list">
              {recentExercises.map((exercise) => {
                const stageLabel = formatConfigStageLabel(exercise.config.gradeStage);
                return (
                <button
                  key={exercise.exerciseId}
                  type="button"
                  className="list-item"
                  onClick={() => navigate(`/exercise/${exercise.exerciseId}`)}
                >
                  <div className="list-item__main">
                    <strong>{exercise.title}</strong>
                    <span>
                      {formatHandPositionLabel(exercise.config.handPosition)} | {exercise.config.timeSignature} |{" "}
                      {exercise.config.measureCount} bars
                      {stageLabel ? ` | ${stageLabel}` : ""}
                    </span>
                  </div>
                  <span className="list-item__meta">{formatTimeAgo(exercise.createdAt)}</span>
                </button>
                );
              })}
            </div>
          ) : (
            <p className="empty-copy">Generated exercises will appear here after the first desktop run.</p>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card__heading">
          <h2>Recent sessions</h2>
        </div>
        {sessions.length ? (
          <div className="stack-list">
            {sessions.map((session) => (
              <div key={session.id} className="list-item list-item--static">
                <div className="list-item__main">
                  <strong>{session.title}</strong>
                  <span>
                    Rating {session.selfRating}/5 | {formatDuration(session.durationSeconds)}
                  </span>
                </div>
                <span className="list-item__meta">{formatTimeAgo(session.finishedAt)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="empty-copy">
            Practice sessions will collect here once you start finishing desktop reps.
          </p>
        )}
      </section>
    </div>
  );
}
