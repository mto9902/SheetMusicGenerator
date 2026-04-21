import { useEffect, useState } from "react";

import { ChoicePills } from "@/components/ChoicePills";
import { storage } from "@/storage";
import { EXERCISE_OPTIONS } from "@shared/options";
import type { AppSettings } from "@shared/types";

const SCALE_OPTIONS = [
  { value: 0.9, label: "Compact" },
  { value: 1, label: "Normal" },
  { value: 1.15, label: "Large" },
  { value: 1.3, label: "XL" },
];

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      await storage.initialize();
      const next = await storage.getSettings();
      if (!cancelled) {
        setSettings(next);
      }
    }

    void loadSettings();

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    if (!settings) {
      return;
    }

    await storage.updateSettings(settings);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1600);
  }

  if (!settings) {
    return (
      <div className="page">
        <div className="card card--centered">
          <p>Loading settings...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page__title">Desktop practice defaults</h1>
          <p className="page__subtitle">
            Keep notation scale, defaults, and session behavior aligned with how you actually
            practice at a desk.
          </p>
        </div>
        <div className="page__actions">
          <button type="button" className="button button--primary" onClick={handleSave}>
            Save settings
          </button>
        </div>
      </header>

      {saved ? <div className="notice">Desktop defaults saved.</div> : null}

      <section className="card">
        <ChoicePills
          label="Notation scale"
          options={SCALE_OPTIONS}
          value={settings.notationScale}
          onChange={(value) => setSettings((current) => current && { ...current, notationScale: Number(value) })}
        />

        <ChoicePills
          label="Default hand position"
          options={EXERCISE_OPTIONS.handPositions.map((position) => ({
            value: position.value as AppSettings["preferredHandPosition"],
            label: position.label,
          }))}
          value={settings.preferredHandPosition}
          onChange={(value) =>
            setSettings(
              (current) =>
                current && {
                  ...current,
                  preferredHandPosition: value as AppSettings["preferredHandPosition"],
                },
            )
          }
        />

        <ChoicePills
          label="Default grade"
          options={EXERCISE_OPTIONS.grades.map((grade) => ({
            value: grade.value,
            label: grade.label,
            hint: grade.subLabel,
          }))}
          value={settings.defaultGrade}
          onChange={(value) =>
            setSettings((current) => current && { ...current, defaultGrade: Number(value) })
          }
        />

        <ChoicePills
          label="Default reading focus"
          options={EXERCISE_OPTIONS.readingFocuses.map((focus) => ({
            value: focus.value as AppSettings["defaultReadingFocus"],
            label: focus.label,
          }))}
          value={settings.defaultReadingFocus}
          onChange={(value) =>
            setSettings(
              (current) =>
                current && {
                  ...current,
                  defaultReadingFocus: value as AppSettings["defaultReadingFocus"],
                },
            )
          }
        />

        <div className="toggle-list">
          <label className="toggle-row">
            <div>
              <strong>Enable metronome pulse by default</strong>
              <p>Show the beat pulse automatically once practice starts.</p>
            </div>
            <input
              type="checkbox"
              checked={settings.metronomeDefault}
              onChange={(event) =>
                setSettings((current) => current && { ...current, metronomeDefault: event.target.checked })
              }
            />
          </label>

          <label className="toggle-row">
            <div>
              <strong>Enable count-in by default</strong>
              <p>Start each practice run with a visual count-in.</p>
            </div>
            <input
              type="checkbox"
              checked={settings.countInDefault}
              onChange={(event) =>
                setSettings((current) => current && { ...current, countInDefault: event.target.checked })
              }
            />
          </label>
        </div>
      </section>
    </div>
  );
}
