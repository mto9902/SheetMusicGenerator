import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EXERCISE_OPTIONS } from "@shared/options";
import {
  formatDuration,
  formatHandPositionLabel,
  formatTimeAgo,
} from "@shared/format";

import { storage, type HomeSnapshot } from "@/storage";

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="summary-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function HomePage() {
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<HomeSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadSnapshot() {
      await storage.initialize();
      const next = await storage.getHomeSnapshot();
      if (!cancelled) {
        setSnapshot(next);
      }
    }

    void loadSnapshot();

    return () => {
      cancelled = true;
    };
  }, []);

  const lastConfig = snapshot?.lastGeneratorConfig ?? null;
  const recentSessions = snapshot?.recentSessions ?? [];
  const recentExercises = snapshot?.recentExercises ?? [];
  const lastExerciseId = snapshot?.lastExerciseId ?? null;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <p className="eyebrow">Desktop Release Surface</p>
          <h1 className="page__title">Build the next reading rep from a bigger desk</h1>
          <p className="page__subtitle">
            Desktop-first practice flow for generating, replaying, and tracking sight-reading
            work without mobile navigation constraints.
          </p>
        </div>
      </header>

      <section className="quick-actions">
        <button
          type="button"
          className="quick-action quick-action--primary"
          onClick={() => navigate("/create?mode=piano&fresh=1")}
        >
          <span className="quick-action__eyebrow">Quick start</span>
          <strong>Piano reading</strong>
          <p>Generate a guided grand-staff rep with phrase-led reading and harmonic anchors.</p>
        </button>
        <button
          type="button"
          className="quick-action"
          onClick={() => navigate("/create?mode=rhythm&fresh=1")}
        >
          <span className="quick-action__eyebrow">Quick start</span>
          <strong>Piano rhythm</strong>
          <p>Keep pitch fixed and focus the whole session on pulse, counting, and coordination.</p>
        </button>
      </section>

      <div className="content-grid">
        <section className="card">
          <div className="card__heading">
            <h2>Resume your last setup</h2>
            <div className="inline-actions">
              <button type="button" className="button button--ghost" onClick={() => navigate("/create?resume=1")}>
                Resume setup
              </button>
              {lastExerciseId ? (
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => navigate(`/exercise/${lastExerciseId}`)}
                >
                  Open last sheet
                </button>
              ) : null}
            </div>
          </div>

          {lastConfig ? (
            <div className="summary-list">
              <SummaryRow label="Mode" value={lastConfig.mode === "piano" ? "Piano reading" : "Piano rhythm"} />
              <SummaryRow label="Meter" value={lastConfig.timeSignature} />
              <SummaryRow
                label="Hand position"
                value={formatHandPositionLabel(lastConfig.handPosition)}
              />
              <SummaryRow
                label="Grade"
                value={
                  EXERCISE_OPTIONS.grades.find((grade) => grade.value === lastConfig.grade)?.label ??
                  `Grade ${lastConfig.grade}`
                }
              />
            </div>
          ) : (
            <p className="empty-copy">
              Your latest generator setup will appear here after the first desktop session.
            </p>
          )}
        </section>

        <section className="card">
          <div className="card__heading">
            <h2>Recent sheets</h2>
            <button type="button" className="button button--ghost" onClick={() => navigate("/library")}>
              Open library
            </button>
          </div>
          {recentExercises.length ? (
            <div className="stack-list">
              {recentExercises.map((exercise) => (
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
                    </span>
                  </div>
                  <span className="list-item__meta">{formatTimeAgo(exercise.createdAt)}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="empty-copy">Generated exercises will appear here once you start using the desktop app.</p>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card__heading">
          <h2>Recent practice</h2>
        </div>
        {recentSessions.length ? (
          <div className="stack-list">
            {recentSessions.map((session) => (
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
            Finish a practice run and the desktop dashboard will start building your recent history.
          </p>
        )}
      </section>
    </div>
  );
}
