import type {
  ExerciseConfig,
  KeySignature,
  PresetShuffleState,
  TimeSignature,
} from "@shared/types";

export const LAST_CREATE_DRAFT_KEY = "desktop_last_create_draft";

export type DesktopCreateDraft = {
  config: ExerciseConfig;
  selectedTimeSignatures: TimeSignature[];
  selectedKeySignatures: KeySignature[];
  presetMode: boolean;
  presetShuffle: PresetShuffleState;
};
