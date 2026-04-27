import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { SectionHeader } from './shared/SectionHeader';
import { RotaryKnob } from './shared/RotaryKnob';
import { Minus, Plus } from 'lucide-react';
import { Dropdown } from './shared/Dropdown';
import type { ExerciseConfig, ExerciseMode, HandActivity, TempoPreset } from '@shared/types';
import { EXERCISE_OPTIONS, tempoPresetToBpm } from '@shared/options';

interface InstrumentCardProps {
  config: ExerciseConfig;
  onChange: (patch: Partial<ExerciseConfig>) => void;
  actions?: ReactNode;
}

const WHITE_KEYS = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
const BLACK_KEYS = [null, 'C#', 'D#', null, 'F#', 'G#', 'A#'];
export function InstrumentCard({ config, onChange, actions }: InstrumentCardProps) {
  const bpm = tempoPresetToBpm(config.tempoPreset);
  const tempoValues = useMemo(() => EXERCISE_OPTIONS.tempoPresets.map((t) => t.value as TempoPreset), []);

  function adjustTempo(direction: -1 | 1) {
    const idx = tempoValues.indexOf(config.tempoPreset);
    const nextIdx = Math.max(0, Math.min(tempoValues.length - 1, idx + direction));
    onChange({ tempoPreset: tempoValues[nextIdx] ?? config.tempoPreset });
  }

  return (
    <div className="w-[220px] flex flex-col gap-3 overflow-y-auto scrollbar-hide pb-4">
      {actions}

      {/* Instrument Card */}
      <div className="panel-card p-4">
        <SectionHeader title="Instrument" />
        <Dropdown
          value={config.mode === 'piano' ? 'Piano' : 'Piano rhythm'}
          options={['Piano', 'Piano rhythm']}
          onChange={(v) => onChange({ mode: (v === 'Piano' ? 'piano' : 'rhythm') as ExerciseMode })}
        />
      </div>

      {/* Mix Card */}
      <div className="panel-card p-4">
        <SectionHeader title="Mix" />
        <div className="flex items-center justify-center py-2">
          <RotaryKnob
            value={config.handActivity === 'both' ? 70 : 50}
            min={0}
            max={100}
            size={44}
            label={config.handActivity === 'both' ? 'Both hands' : config.handActivity === 'right-only' ? 'Right hand' : 'Left hand'}
            onChange={() => {}}
          />
        </div>
        <div className="flex gap-1 mt-2">
          {(['right-only', 'left-only', 'both'] as HandActivity[]).map((ha) => (
            <button
              key={ha}
              type="button"
              className={`flex-1 h-8 text-xs font-medium rounded-md border transition-colors ${
                config.handActivity === ha
                  ? 'bg-[#3A3A3A] text-white border-[#3A3A3A] shadow-inner'
                  : 'tactile-btn text-gray-600'
              }`}
              onClick={() => onChange({ handActivity: ha })}
            >
              {ha === 'right-only' ? 'RH' : ha === 'left-only' ? 'LH' : 'Both'}
            </button>
          ))}
        </div>
      </div>

      {/* Tempo Card */}
      <div className="panel-card p-4">
        <SectionHeader title="Tempo" />
        <div className="flex items-center gap-2 justify-center">
          <button
            type="button"
            className="tactile-circle-sm w-10 h-10 flex items-center justify-center"
            onClick={() => adjustTempo(-1)}
            disabled={config.tempoPreset === tempoValues[0]}
          >
            <Minus size={14} />
          </button>
          <div 
            className="w-12 text-center text-2xl font-bold tabular-nums text-gray-800"
          >
            {bpm}
          </div>
          <button
            type="button"
            className="tactile-circle-sm w-10 h-10 flex items-center justify-center"
            onClick={() => adjustTempo(1)}
            disabled={config.tempoPreset === tempoValues[tempoValues.length - 1]}
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      {/* Output Card */}
      <div className="panel-card p-4">
        <SectionHeader title="Output" />
        <div className="rounded-xl overflow-hidden bg-[#F5F5F5] p-3">
          <img
            src="/waveform.png"
            alt="Audio output waveform"
            className="w-full h-12 object-contain opacity-60"
            draggable={false}
          />
        </div>
      </div>

      {/* Keyboard Card */}
      <div className="panel-card p-4">
        <SectionHeader title="Keyboard" />
        <div className="flex justify-center">
          <div className="relative flex">
            {WHITE_KEYS.map((note) => (
              <div
                key={note}
                className={`piano-white relative w-7 h-14 flex items-end justify-center pb-1 ${
                  note === config.handPosition ? 'active' : ''
                }`}
              >
                <span className="text-[7px] text-[#C7C7CC]">{note}</span>
              </div>
            ))}
            <div className="absolute top-0 left-0 flex">
              {BLACK_KEYS.map((note, i) => {
                if (!note) return <div key={`gap-${i}`} className="w-7" />;
                return (
                  <div
                    key={note}
                    className="piano-black absolute w-[14px] h-9"
                    style={{ left: i * 28 + 18 }}
                  />
                );
              })}
            </div>
          </div>
        </div>
        <div className="mt-3">
          <Dropdown
            value={EXERCISE_OPTIONS.handPositions.find((p) => p.value === config.handPosition)?.label ?? config.handPosition}
            options={EXERCISE_OPTIONS.handPositions.map((p) => p.label)}
            onChange={(v) => {
              const pos = EXERCISE_OPTIONS.handPositions.find((p) => p.label === v)?.value;
              if (pos) onChange({ handPosition: pos as ExerciseConfig['handPosition'] });
            }}
          />
        </div>
      </div>
    </div>
  );
}
