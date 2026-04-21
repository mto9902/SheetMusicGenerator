import { openDB, type DBSchema, type IDBPDatabase } from "idb";

import { DEFAULT_SETTINGS } from "@shared/options";
import type {
  AppSettings,
  ExerciseConfig,
  ExerciseListItem,
  GeneratedExercise,
  PracticeSession,
  SavedPreset,
  StoredExercise,
} from "@shared/types";

const DATABASE_NAME = "sheetgenerator-desktop";
const DATABASE_VERSION = 1;

const SETTINGS_KEYS = {
  notationScale: "notation_scale",
  metronomeDefault: "metronome_default",
  countInDefault: "count_in_default",
  preferredHandPosition: "preferred_hand_position",
  defaultGrade: "default_grade",
  defaultReadingFocus: "default_reading_focus",
  lastGeneratorConfig: "last_generator_config",
  lastExerciseId: "last_exercise_id",
} as const;

type SettingValue = unknown;

type HomeSnapshot = {
  lastGeneratorConfig: ExerciseConfig | null;
  lastExerciseId: string | null;
  recentSessions: PracticeSession[];
  recentExercises: ExerciseListItem[];
};

export interface DesktopStorageAdapter {
  initialize(): Promise<void>;
  getSettings(): Promise<AppSettings>;
  updateSettings(settings: AppSettings): Promise<void>;
  getSettingValue<T>(key: string): Promise<T | null>;
  setSettingValue(key: string, value: unknown): Promise<void>;
  saveGeneratedExercise(exercise: GeneratedExercise): Promise<StoredExercise>;
  getExerciseById(exerciseId: string): Promise<StoredExercise | null>;
  getRecentExercises(limit?: number): Promise<ExerciseListItem[]>;
  savePreset(name: string, config: ExerciseConfig): Promise<string>;
  getPresets(): Promise<SavedPreset[]>;
  getPresetById(presetId: string): Promise<SavedPreset | null>;
  savePracticeSession(session: PracticeSession): Promise<void>;
  getRecentSessions(limit?: number): Promise<PracticeSession[]>;
  getLastGeneratorConfig(): Promise<ExerciseConfig | null>;
  getLastExerciseId(): Promise<string | null>;
  getHomeSnapshot(): Promise<HomeSnapshot>;
}

interface SheetGeneratorDesktopDb extends DBSchema {
  settings: {
    key: string;
    value: SettingValue;
  };
  exercises: {
    key: string;
    value: StoredExercise;
  };
  presets: {
    key: string;
    value: SavedPreset;
  };
  sessions: {
    key: string;
    value: PracticeSession;
  };
}

function nowIso() {
  return new Date().toISOString();
}

function makeId(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function sortByDateDesc<T>(items: T[], getDate: (item: T) => string) {
  return items.slice().sort((left, right) => Date.parse(getDate(right)) - Date.parse(getDate(left)));
}

class IndexedDbStorageAdapter implements DesktopStorageAdapter {
  private databasePromise: Promise<IDBPDatabase<SheetGeneratorDesktopDb>> | null = null;

  private getDatabase() {
    if (!this.databasePromise) {
      this.databasePromise = openDB<SheetGeneratorDesktopDb>(DATABASE_NAME, DATABASE_VERSION, {
        upgrade(database) {
          if (!database.objectStoreNames.contains("settings")) {
            database.createObjectStore("settings");
          }
          if (!database.objectStoreNames.contains("exercises")) {
            database.createObjectStore("exercises");
          }
          if (!database.objectStoreNames.contains("presets")) {
            database.createObjectStore("presets");
          }
          if (!database.objectStoreNames.contains("sessions")) {
            database.createObjectStore("sessions");
          }
        },
      });
    }

    return this.databasePromise;
  }

  private async ensureDefaults() {
    const database = await this.getDatabase();
    const defaults: Record<string, unknown> = {
      [SETTINGS_KEYS.notationScale]: DEFAULT_SETTINGS.notationScale,
      [SETTINGS_KEYS.metronomeDefault]: DEFAULT_SETTINGS.metronomeDefault,
      [SETTINGS_KEYS.countInDefault]: DEFAULT_SETTINGS.countInDefault,
      [SETTINGS_KEYS.preferredHandPosition]: DEFAULT_SETTINGS.preferredHandPosition,
      [SETTINGS_KEYS.defaultGrade]: DEFAULT_SETTINGS.defaultGrade,
      [SETTINGS_KEYS.defaultReadingFocus]: DEFAULT_SETTINGS.defaultReadingFocus,
    };

    const transaction = database.transaction("settings", "readwrite");
    for (const [key, value] of Object.entries(defaults)) {
      const existing = await transaction.store.get(key);
      if (existing === undefined) {
        await transaction.store.put(value, key);
      }
    }
    await transaction.done;
  }

  async initialize() {
    await this.getDatabase();
    await this.ensureDefaults();
  }

  async getSettings(): Promise<AppSettings> {
    await this.ensureDefaults();
    const database = await this.getDatabase();

    return {
      notationScale:
        ((await database.get("settings", SETTINGS_KEYS.notationScale)) as number | undefined) ??
        DEFAULT_SETTINGS.notationScale,
      metronomeDefault:
        ((await database.get("settings", SETTINGS_KEYS.metronomeDefault)) as boolean | undefined) ??
        DEFAULT_SETTINGS.metronomeDefault,
      countInDefault:
        ((await database.get("settings", SETTINGS_KEYS.countInDefault)) as boolean | undefined) ??
        DEFAULT_SETTINGS.countInDefault,
      preferredHandPosition:
        ((await database.get(
          "settings",
          SETTINGS_KEYS.preferredHandPosition,
        )) as AppSettings["preferredHandPosition"] | undefined) ??
        DEFAULT_SETTINGS.preferredHandPosition,
      defaultGrade:
        ((await database.get("settings", SETTINGS_KEYS.defaultGrade)) as number | undefined) ??
        DEFAULT_SETTINGS.defaultGrade,
      defaultReadingFocus:
        ((await database.get(
          "settings",
          SETTINGS_KEYS.defaultReadingFocus,
        )) as AppSettings["defaultReadingFocus"] | undefined) ??
        DEFAULT_SETTINGS.defaultReadingFocus,
    };
  }

  async updateSettings(settings: AppSettings) {
    const database = await this.getDatabase();
    const transaction = database.transaction("settings", "readwrite");
    await transaction.store.put(settings.notationScale, SETTINGS_KEYS.notationScale);
    await transaction.store.put(settings.metronomeDefault, SETTINGS_KEYS.metronomeDefault);
    await transaction.store.put(settings.countInDefault, SETTINGS_KEYS.countInDefault);
    await transaction.store.put(settings.preferredHandPosition, SETTINGS_KEYS.preferredHandPosition);
    await transaction.store.put(settings.defaultGrade, SETTINGS_KEYS.defaultGrade);
    await transaction.store.put(settings.defaultReadingFocus, SETTINGS_KEYS.defaultReadingFocus);
    await transaction.done;
  }

  async getSettingValue<T>(key: string) {
    const database = await this.getDatabase();
    const value = await database.get("settings", key);
    return (value as T | undefined) ?? null;
  }

  async setSettingValue(key: string, value: unknown) {
    const database = await this.getDatabase();
    await database.put("settings", value, key);
  }

  async saveGeneratedExercise(exercise: GeneratedExercise) {
    const database = await this.getDatabase();
    const stored: StoredExercise = {
      ...exercise,
      createdAt: nowIso(),
    };

    await database.put("exercises", stored, stored.exerciseId);
    await database.put("settings", stored.config, SETTINGS_KEYS.lastGeneratorConfig);
    await database.put("settings", stored.exerciseId, SETTINGS_KEYS.lastExerciseId);

    return stored;
  }

  async getExerciseById(exerciseId: string) {
    const database = await this.getDatabase();
    return (await database.get("exercises", exerciseId)) ?? null;
  }

  async getRecentExercises(limit = 8) {
    const database = await this.getDatabase();
    const exercises = await database.getAll("exercises");

    return sortByDateDesc(exercises, (exercise) => exercise.createdAt)
      .slice(0, limit)
      .map((exercise) => ({
        exerciseId: exercise.exerciseId,
        title: exercise.title,
        config: exercise.config,
        createdAt: exercise.createdAt,
        grade: exercise.grade,
      }));
  }

  async savePreset(name: string, config: ExerciseConfig) {
    const database = await this.getDatabase();
    const timestamp = nowIso();
    const preset: SavedPreset = {
      id: makeId("preset"),
      name,
      config,
      createdAt: timestamp,
      updatedAt: timestamp,
    };

    await database.put("presets", preset, preset.id);
    await database.put("settings", config, SETTINGS_KEYS.lastGeneratorConfig);

    return preset.id;
  }

  async getPresets() {
    const database = await this.getDatabase();
    const presets = await database.getAll("presets");
    return sortByDateDesc(presets, (preset) => preset.updatedAt);
  }

  async getPresetById(presetId: string) {
    const database = await this.getDatabase();
    return (await database.get("presets", presetId)) ?? null;
  }

  async savePracticeSession(session: PracticeSession) {
    const database = await this.getDatabase();
    await database.put("sessions", session, session.id);
  }

  async getRecentSessions(limit = 8) {
    const database = await this.getDatabase();
    const sessions = await database.getAll("sessions");
    return sortByDateDesc(sessions, (session) => session.finishedAt).slice(0, limit);
  }

  async getLastGeneratorConfig() {
    return this.getSettingValue<ExerciseConfig>(SETTINGS_KEYS.lastGeneratorConfig);
  }

  async getLastExerciseId() {
    return this.getSettingValue<string>(SETTINGS_KEYS.lastExerciseId);
  }

  async getHomeSnapshot() {
    const [lastGeneratorConfig, lastExerciseId, recentSessions, recentExercises] =
      await Promise.all([
        this.getLastGeneratorConfig(),
        this.getLastExerciseId(),
        this.getRecentSessions(4),
        this.getRecentExercises(4),
      ]);

    return {
      lastGeneratorConfig,
      lastExerciseId,
      recentSessions,
      recentExercises,
    };
  }
}

export const storage: DesktopStorageAdapter = new IndexedDbStorageAdapter();
export type { HomeSnapshot };
