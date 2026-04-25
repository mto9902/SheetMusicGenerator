export type ExerciseMode = "piano" | "rhythm";
export type TempoPreset = "slow" | "medium" | "fast";
export type TimeSignature = "2/4" | "3/4" | "4/4" | "6/8";
export type KeySignature =
  | "C" | "G" | "F" | "D" | "Bb" | "A" | "E" | "Eb" | "Ab"
  | "Am" | "Dm" | "Em" | "Gm" | "Cm" | "Bm" | "Fm" | "F#m" | "C#m";
export type HandPosition = "C" | "G" | "D" | "F" | "Bb";
export type HandActivity = "right-only" | "left-only" | "both";
export type CoordinationStyle = "support" | "alternating" | "together";
export type ReadingFocus = "balanced" | "melodic" | "harmonic";
export type RightHandMotion = "stepwise" | "small-leaps" | "mixed";
export type LeftHandPattern = "held" | "repeated" | "simple-broken";
export type GradeStage = "g1-pocket" | "g1-extend" | "g1-staff";

export type ExerciseConfig = {
  mode: ExerciseMode;
  grade: number;
  gradeStage?: GradeStage;
  timeSignature: TimeSignature;
  measureCount: number;
  tempoPreset: TempoPreset;
  keySignature: KeySignature;
  handPosition: HandPosition;
  handActivity: HandActivity;
  coordinationStyle: CoordinationStyle;
  readingFocus: ReadingFocus;
  rightHandMotion: RightHandMotion;
  leftHandPattern: LeftHandPattern;
  allowRests: boolean;
  allowAccidentals: boolean;
};

export type ExerciseSummary = {
  bpm: number;
  stageLabel?: string;
  handPositionLabel: string;
  coordinationLabel: string;
  phraseShapeLabel: string;
  cadenceLabel: string;
  harmonyFocus: string[];
  techniqueFocus: string[];
  rhythmFocus: string[];
  seedLabel: string;
};

export type ExerciseDebug = {
  scoreBreakdown?: Record<string, number> | null;
  planSummary?: Record<string, unknown> | null;
  qualityGate?: Record<string, unknown> | null;
};

export type PresetShuffleState = {
  timeBag: TimeSignature[];
  keyBag: KeySignature[];
  lastTimeSignature: TimeSignature | null;
  lastKeySignature: KeySignature | null;
};

export type ExerciseGenerationContext = {
  presetMode: boolean;
  selectedTimeSignatures: TimeSignature[];
  selectedKeySignatures: KeySignature[];
  presetShuffle: PresetShuffleState;
};

export type NoteEvent = {
  pitches: number[];
  quarterLength: number;
  offset: number;
  hand: string;
  measure: number;
  isRest?: boolean;
  dynamic?: string | null;
  articulation?: string | null;
  eventId?: string | null;
  tieType?: string | null;
  slurId?: string | null;
  slurRole?: string | null;
  hairpinStart?: Record<string, string> | null;
  hairpinStopIds?: string[] | null;
  tuplet?: Record<string, number> | null;
  dynamicScalar?: number | null;
  durationScale?: number | null;
  reattack?: number | null;
  touch?: number | null;
  technique?: string | null;
  fermata?: boolean;
};

export type GeneratedExercise = {
  exerciseId: string;
  seed: string;
  config: ExerciseConfig;
  title: string;
  musicXml: string;
  svg: string;
  audioUrl: string;
  measureCount: number;
  timeSignature: TimeSignature;
  grade: number;
  summary: ExerciseSummary;
  noteEvents: NoteEvent[];
  debug?: ExerciseDebug | null;
  generationContext?: ExerciseGenerationContext | null;
};

export type SavedPreset = {
  id: string;
  name: string;
  config: ExerciseConfig;
  createdAt: string;
  updatedAt: string;
};

export type StoredExercise = GeneratedExercise & {
  createdAt: string;
};

export type ExerciseListItem = {
  exerciseId: string;
  title: string;
  config: ExerciseConfig;
  createdAt: string;
  grade: number;
};

export type PracticeSession = {
  id: string;
  exerciseId: string;
  presetId: string | null;
  title: string;
  startedAt: string;
  finishedAt: string;
  selfRating: number;
  durationSeconds: number;
};

export type AppSettings = {
  notationScale: number;
  metronomeDefault: boolean;
  countInDefault: boolean;
  preferredHandPosition: HandPosition;
  defaultGrade: number;
  defaultReadingFocus: ReadingFocus;
};
