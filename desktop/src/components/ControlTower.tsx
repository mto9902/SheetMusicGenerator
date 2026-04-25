import { useMemo } from 'react';
import { SectionHeader } from './shared/SectionHeader';
import { RotaryKnob } from './shared/RotaryKnob';
import { ToggleSwitch } from './shared/ToggleSwitch';
import { Dropdown } from './shared/Dropdown';
import type { ExerciseConfig, GradeStage, KeySignature, ReadingFocus, TimeSignature } from '@shared/types';
import { EXERCISE_OPTIONS, GRADE_PRESETS, visibleGradeStages } from '@shared/options';

interface ControlTowerProps {
  config: ExerciseConfig;
  onChange: (patch: Partial<ExerciseConfig>) => void;
}

const STYLE_OPTIONS = ['Classical', 'Melody-first', 'Harmony focus'] as const;
const STYLE_VALUES: ReadingFocus[] = ['balanced', 'melodic', 'harmonic'];

export function ControlTower({ config, onChange }: ControlTowerProps) {
  const keyOptions = useMemo(() => {
    return EXERCISE_OPTIONS.keySignatures
      .filter((k) => k.minGrade <= config.grade)
      .map((k) => k.value as KeySignature);
  }, [config.grade]);

  const measureOptions = useMemo(() => {
    const gradeMeta = GRADE_PRESETS.find((p) => p.grade === config.grade);
    const maxBars = gradeMeta?.piano.maxBars ?? EXERCISE_OPTIONS.measureCounts[EXERCISE_OPTIONS.measureCounts.length - 1];
    return EXERCISE_OPTIONS.measureCounts.filter((c) => c <= maxBars);
  }, [config.grade]);

  const stageOptions = useMemo(() => visibleGradeStages(config.mode, config.grade), [config.mode, config.grade]);

  const scaleMode = config.keySignature.endsWith('m') ? 'minor' : 'major';
  const densityValue =
    config.rightHandMotion === 'stepwise' ? 0 : config.rightHandMotion === 'small-leaps' ? 1 : 2;
  const styleIndex = STYLE_VALUES.indexOf(config.readingFocus);

  return (
    <div className="w-[300px] flex flex-col gap-3 overflow-y-auto scrollbar-hide pb-4">
      {/* Composition Card */}
      <div className="surface-card p-5">
        <SectionHeader title="Composition" />
        <div className="space-y-4">
          {/* Time Signature */}
          <div>
            <label className="block text-xs text-[#8E8E93] mb-2 font-medium">Time Signature</label>
            <div className="flex flex-wrap gap-1">
              {EXERCISE_OPTIONS.timeSignatures.map((ts) => (
                <button
                  key={ts}
                  type="button"
                  className={`key-pill ${config.timeSignature === ts ? 'active' : ''}`}
                  onClick={() => onChange({ timeSignature: ts as TimeSignature })}
                >
                  {ts}
                </button>
              ))}
            </div>
          </div>

          {/* Key Selector */}
          <div>
            <label className="block text-xs text-[#8E8E93] mb-2 font-medium">Key</label>
            <div className="flex flex-wrap gap-1">
              {keyOptions.map((k) => (
                <button
                  key={k}
                  type="button"
                  className={`key-pill ${config.keySignature === k ? 'active' : ''}`}
                  onClick={() => onChange({ keySignature: k })}
                >
                  {k.replace('m', '')}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Character Card */}
      <div className="surface-card p-5">
        <SectionHeader title="Character" />
        <div className="space-y-3">
          <Dropdown
            label="Scale Mode"
            value={scaleMode === 'minor' ? 'Minor' : 'Major'}
            options={['Major', 'Minor']}
            onChange={(v) => {
              const target = v.toLowerCase() as 'major' | 'minor';
              if (target === scaleMode) return;
              const nextKey = EXERCISE_OPTIONS.keySignatures
                .filter((k) => k.minGrade <= config.grade)
                .find((k) => (k.type as string) === target)?.value as KeySignature;
              if (nextKey) onChange({ keySignature: nextKey });
            }}
          />
          <Dropdown
            label="Style"
            value={STYLE_OPTIONS[styleIndex] ?? STYLE_OPTIONS[0]}
            options={[...STYLE_OPTIONS]}
            onChange={(v) => {
              const idx = STYLE_OPTIONS.indexOf(v as typeof STYLE_OPTIONS[number]);
              onChange({ readingFocus: STYLE_VALUES[idx] ?? 'balanced' });
            }}
          />
          {config.mode === 'piano' && config.grade === 1 && stageOptions.length > 0 && (
            <div>
              <label className="block text-xs text-[#8E8E93] mb-2 font-medium">Grade 1 Stage</label>
              <div className="flex flex-wrap gap-1">
                {stageOptions.map((stage) => (
                  <button
                    key={stage.value}
                    type="button"
                    className={`key-pill ${config.gradeStage === stage.value ? 'active' : ''}`}
                    onClick={() => onChange({ gradeStage: stage.value as GradeStage })}
                    title={stage.hint}
                  >
                    {stage.label.replace('1', '')}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Structure Card */}
      <div className="surface-card p-5">
        <SectionHeader title="Structure" />
        <div className="space-y-5">
          <div className="flex items-center justify-center py-1">
            <RotaryKnob
              value={config.measureCount}
              min={measureOptions[0] ?? 4}
              max={measureOptions[measureOptions.length - 1] ?? 64}
              size={56}
              label={`${config.measureCount} measures`}
              onChange={(v) => {
                const closest = measureOptions.reduce((prev, curr) =>
                  Math.abs(curr - v) < Math.abs(prev - v) ? curr : prev
                );
                onChange({ measureCount: closest });
              }}
            />
          </div>

          {/* Difficulty Slider */}
          <div>
            <label className="block text-xs text-[#8E8E93] mb-2 font-medium">Difficulty</label>
            <div className="slider-track">
              <button
                type="button"
                className="slider-thumb"
                style={{ left: `${((config.grade - 1) / 4) * 100}%` }}
                onPointerDown={(e) => {
                  const track = e.currentTarget.parentElement!;
                  const move = (ev: PointerEvent) => {
                    const rect = track.getBoundingClientRect();
                    const x = ev.clientX - rect.left;
                    const pct = Math.max(0, Math.min(1, x / rect.width));
                    const grade = Math.max(1, Math.min(5, Math.round(1 + pct * 4)));
                    onChange({ grade });
                  };
                  const up = () => {
                    window.removeEventListener('pointermove', move);
                    window.removeEventListener('pointerup', up);
                  };
                  window.addEventListener('pointermove', move);
                  window.addEventListener('pointerup', up);
                }}
              />
            </div>
            <div className="flex justify-between mt-1">
              <span className="text-[10px] text-[#C7C7CC]">Beginner</span>
              <span className="text-[10px] text-[#2C2C2E] font-semibold">Grade {config.grade}</span>
              <span className="text-[10px] text-[#C7C7CC]">Virtuoso</span>
            </div>
          </div>

          {/* Note Density Slider */}
          <div>
            <label className="block text-xs text-[#8E8E93] mb-2 font-medium">Note Density</label>
            <div className="slider-track">
              <button
                type="button"
                className="slider-thumb"
                style={{ left: `${(densityValue / 2) * 100}%` }}
                disabled={config.grade === 1 && config.gradeStage === 'g1-pocket'}
                onPointerDown={(e) => {
                  if (config.grade === 1 && config.gradeStage === 'g1-pocket') return;
                  const track = e.currentTarget.parentElement!;
                  const move = (ev: PointerEvent) => {
                    const rect = track.getBoundingClientRect();
                    const x = ev.clientX - rect.left;
                    const pct = Math.max(0, Math.min(1, x / rect.width));
                    const val = Math.round(pct * 2);
                    onChange({
                      rightHandMotion: val <= 0 ? 'stepwise' : val === 1 ? 'small-leaps' : 'mixed',
                      leftHandPattern: val >= 2 && config.grade >= 2 ? 'simple-broken' : config.leftHandPattern,
                    });
                  };
                  const up = () => {
                    window.removeEventListener('pointermove', move);
                    window.removeEventListener('pointerup', up);
                  };
                  window.addEventListener('pointermove', move);
                  window.addEventListener('pointerup', up);
                }}
              />
            </div>
            <div className="flex justify-between mt-1">
              <span className="text-[10px] text-[#C7C7CC]">Open</span>
              <span className="text-[10px] text-[#2C2C2E] font-semibold">
                {config.rightHandMotion === 'stepwise' ? 'Stepwise' : config.rightHandMotion === 'small-leaps' ? 'Small leaps' : 'Mixed'}
              </span>
              <span className="text-[10px] text-[#C7C7CC]">Busy</span>
            </div>
          </div>
        </div>
      </div>

      {/* Options Card */}
      <div className="surface-card p-5">
        <SectionHeader title="Options" />
        <div className="space-y-3">
          <ToggleSwitch
            value={config.allowRests}
            onChange={(v) => onChange({ allowRests: v })}
            label="Allow rests"
          />
          <ToggleSwitch
            value={config.allowAccidentals}
            onChange={(v) => onChange({ allowAccidentals: v })}
            label="Accidentals"
          />
        </div>
      </div>
    </div>
  );
}
