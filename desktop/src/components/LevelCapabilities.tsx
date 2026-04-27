/**
 * LevelCapabilities
 * -----------------
 * Read-only summary of what the currently-selected grade includes — rhythm
 * vocabulary, largest leap, allowed intervals, and feature flags (accidentals,
 * dynamics, triplets, octaves, position shifts, broken chords).
 *
 * Inspired by Sight Reading Factory's level-info panel: it answers the
 * "what does Grade N actually mean?" question without forcing the user to
 * generate an exercise to find out.
 */
import { useMemo } from 'react';
import { GRADE_PRESETS } from '@shared/options';
import { SectionHeader } from './shared/SectionHeader';

interface LevelCapabilitiesProps {
  grade: number;
  /** When true, the panel is collapsed and only shows a one-line summary. */
  compact?: boolean;
}

interface RhythmGlyph {
  label: string;
  /** Approximate quarter-length values that should "light up" this glyph. */
  qls: number[];
}

const RHYTHM_GLYPHS: RhythmGlyph[] = [
  { label: '𝅝', qls: [4.0] },           // 𝅝 whole
  { label: '𝅗.', qls: [3.0] },          // 𝅗𝅥. dotted half
  { label: '𝅗', qls: [2.0] },           // 𝅗𝅥 half
  { label: '♩.', qls: [1.5] },                // ♩. dotted quarter
  { label: '♩', qls: [1.0] },                 // ♩ quarter
  { label: '♪.', qls: [0.75] },               // ♪. dotted eighth
  { label: '♪', qls: [0.5] },                 // ♪ eighth
  { label: '♬', qls: [0.25] },                // ♬ sixteenth (beamed)
];

function intervalNameForSemitones(semitones: number): string {
  if (semitones <= 0) return 'unison';
  if (semitones <= 2) return '2nd';
  if (semitones <= 4) return '3rd';
  if (semitones <= 5) return '4th';
  if (semitones <= 7) return '5th';
  if (semitones <= 9) return '6th';
  if (semitones <= 11) return '7th';
  if (semitones <= 12) return 'Octave';
  return `${Math.round(semitones / 2)}+ steps`;
}

export function LevelCapabilities({ grade, compact = false }: LevelCapabilitiesProps) {
  const preset = useMemo(
    () => GRADE_PRESETS.find((p) => p.grade === grade) ?? GRADE_PRESETS[0],
    [grade],
  );
  const piano = preset.piano;

  const allowedQls = useMemo(() => {
    const set = new Set<number>(piano.rightQuarterLengths.map((q) => Number(q)));
    for (const q of piano.leftQuarterLengths ?? []) {
      set.add(Number(q));
    }
    return set;
  }, [piano.rightQuarterLengths, piano.leftQuarterLengths]);

  const tripletsAllowed = (piano.tripletChance ?? 0) > 0;
  const accidentalsAllowed = (piano.accidentalChance ?? 0) > 0;
  const dynamicsAllowed = !!piano.dynamicsEnabled;
  const octavesAllowed = !!piano.allowOctaves;
  const albertiAllowed = !!piano.allowAlberti;
  const brokenChordsAllowed = !!piano.allowBrokenChords;
  const positionShiftAllowed = (piano.positionShiftChance ?? 0) > 0;
  const largestLeap = intervalNameForSemitones(piano.maxLeapSemitones ?? 4);
  const intervals = piano.allowIntervals ?? [];
  const maxBars = piano.maxBars ?? 4;

  const features: { label: string; on: boolean }[] = [
    { label: 'Accidentals', on: accidentalsAllowed },
    { label: 'Dynamics', on: dynamicsAllowed },
    { label: 'Triplets', on: tripletsAllowed },
    { label: 'Octaves', on: octavesAllowed },
    { label: 'Position shifts', on: positionShiftAllowed },
    { label: 'Broken chords', on: brokenChordsAllowed || albertiAllowed },
  ];

  if (compact) {
    const enabledCount = features.filter((f) => f.on).length;
    return (
      <div className="text-[11px] text-[#8E8E93]">
        Largest leap <span className="text-[#1C1C1E] font-medium">{largestLeap}</span>
        {' · '}
        {enabledCount}/{features.length} features
      </div>
    );
  }

  return (
    <div className="surface-card p-5">
      <SectionHeader title={`Grade ${grade} includes`} />
      <div className="space-y-4">
        {/* Rhythms */}
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-[#8E8E93] mb-2 font-semibold">
            Rhythms
          </label>
          <div className="flex flex-wrap items-end gap-2 text-[#1C1C1E]">
            {RHYTHM_GLYPHS.map((glyph) => {
              const enabled = glyph.qls.some((q) => allowedQls.has(q));
              return (
                <span
                  key={glyph.label}
                  className={`text-2xl leading-none select-none ${
                    enabled ? 'text-[#1C1C1E]' : 'text-[#E5E5EA]'
                  }`}
                  style={{ fontFamily: '"Noto Music", "Bravura Text", serif' }}
                  title={glyph.qls.map((q) => `${q} quarter`).join(', ')}
                >
                  {glyph.label}
                </span>
              );
            })}
            <span
              className={`ml-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${
                tripletsAllowed
                  ? 'border-[#1C1C1E] text-[#1C1C1E]'
                  : 'border-[#E5E5EA] text-[#C7C7CC]'
              }`}
              title={tripletsAllowed ? 'Triplets allowed' : 'Triplets not used'}
            >
              triplets
            </span>
          </div>
        </div>

        {/* Largest leap */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-[#8E8E93] mb-1 font-semibold">
              Largest leap
            </label>
            <div className="text-lg font-semibold text-[#1C1C1E] leading-tight">{largestLeap}</div>
            <div className="text-[10px] text-[#8E8E93] mt-0.5">
              {piano.maxLeapSemitones ?? 4} semitones
            </div>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-[#8E8E93] mb-1 font-semibold">
              Max bars
            </label>
            <div className="text-lg font-semibold text-[#1C1C1E] leading-tight">{maxBars}</div>
            <div className="text-[10px] text-[#8E8E93] mt-0.5">measures</div>
          </div>
        </div>

        {/* Intervals */}
        {intervals.length > 0 && (
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-[#8E8E93] mb-1.5 font-semibold">
              Allowed intervals
            </label>
            <div className="flex flex-wrap gap-1">
              {intervals.map((name) => (
                <span
                  key={String(name)}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-[#F2F2F7] text-[#3A3A3C] border border-[#E5E5EA]"
                >
                  {String(name)}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Feature flags */}
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-[#8E8E93] mb-1.5 font-semibold">
            Features
          </label>
          <div className="flex flex-wrap gap-1">
            {features.map((feature) => (
              <span
                key={feature.label}
                className={`text-[11px] px-2 py-0.5 rounded-full border ${
                  feature.on
                    ? 'bg-[#1C1C1E] text-white border-[#1C1C1E]'
                    : 'bg-transparent text-[#C7C7CC] border-[#E5E5EA] line-through'
                }`}
              >
                {feature.label}
              </span>
            ))}
          </div>
        </div>

        {/* Goal copy */}
        {preset.goal && (
          <p className="text-[11px] text-[#8E8E93] leading-relaxed italic border-t border-[#F2F2F7] pt-3">
            {preset.goal}
          </p>
        )}
      </div>
    </div>
  );
}
