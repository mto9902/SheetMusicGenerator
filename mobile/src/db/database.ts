import * as SQLite from "expo-sqlite";
import { Platform } from "react-native";

import { DEFAULT_SETTINGS } from "@/src/lib/options";
import type {
  AppSettings,
  ExerciseConfig,
  ExerciseGenerationContext,
  GeneratedExercise,
  PracticeSession,
  SavedPreset,
  StoredExercise,
  TimeSignature,
} from "@/src/types/exercise";

const APP_SCHEMA_VERSION = "piano-grade-v1";
const DATABASE_NAME =
  Platform.OS === "web" ? "sheetgenerator-web.db" : "sheetgenerator.db";
const WEB_STORAGE_KEY = "sheetgenerator-web-storage";

type WebDatabaseState = {
  schemaVersion: string;
  presets: SavedPreset[];
  generatedExercises: StoredExercise[];
  practiceSessions: PracticeSession[];
  settings: Record<string, string>;
};

function compactStoredExercise(exercise: StoredExercise): StoredExercise {
  return {
    ...exercise,
    musicXml: "",
    svg: "",
    audioUrl: "",
  };
}

let databasePromise: Promise<SQLite.SQLiteDatabase> | null = null;
let initPromise: Promise<void> | null = null;

function nowIso() {
  return new Date().toISOString();
}

function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function isWeb() {
  return Platform.OS === "web";
}

function createDefaultWebState(): WebDatabaseState {
  return {
    schemaVersion: APP_SCHEMA_VERSION,
    presets: [],
    generatedExercises: [],
    practiceSessions: [],
    settings: {
      schema_version: APP_SCHEMA_VERSION,
      notation_scale: JSON.stringify(DEFAULT_SETTINGS.notationScale),
      metronome_default: JSON.stringify(DEFAULT_SETTINGS.metronomeDefault),
      count_in_default: JSON.stringify(DEFAULT_SETTINGS.countInDefault),
      preferred_hand_position: JSON.stringify(DEFAULT_SETTINGS.preferredHandPosition),
      default_grade: JSON.stringify(DEFAULT_SETTINGS.defaultGrade),
      default_reading_focus: JSON.stringify(DEFAULT_SETTINGS.defaultReadingFocus),
    },
  };
}

function loadWebState(): WebDatabaseState {
  if (!isWeb() || typeof localStorage === "undefined") {
    return createDefaultWebState();
  }

  try {
    const raw = localStorage.getItem(WEB_STORAGE_KEY);
    if (!raw) {
      const state = createDefaultWebState();
      saveWebState(state);
      return state;
    }

    const parsed = JSON.parse(raw) as Partial<WebDatabaseState>;
    const fallback = createDefaultWebState();

    if (parsed.schemaVersion !== APP_SCHEMA_VERSION) {
      saveWebState(fallback);
      return fallback;
    }

    return {
      schemaVersion: APP_SCHEMA_VERSION,
      presets: parsed.presets ?? [],
      generatedExercises: (parsed.generatedExercises ?? []).slice(0, 1),
      practiceSessions: parsed.practiceSessions ?? [],
      settings: {
        ...fallback.settings,
        ...(parsed.settings ?? {}),
        schema_version: APP_SCHEMA_VERSION,
      },
    };
  } catch {
    const fallback = createDefaultWebState();
    try {
      saveWebState(fallback);
    } catch {
      // ignore storage write failures
    }
    return fallback;
  }
}

function saveWebState(state: WebDatabaseState) {
  if (!isWeb() || typeof localStorage === "undefined") {
    return true;
  }
  try {
    localStorage.setItem(WEB_STORAGE_KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

function persistWebStateWithPruning(state: WebDatabaseState) {
  if (saveWebState(state)) {
    return;
  }

  if (state.generatedExercises.length > 1) {
    const [latest, ...rest] = state.generatedExercises;
    if (
      saveWebState({
        ...state,
        generatedExercises: [latest, ...rest.map(compactStoredExercise)],
      })
    ) {
      return;
    }

    if (saveWebState({ ...state, generatedExercises: [latest] })) {
      return;
    }
  }

  saveWebState({
    ...state,
    generatedExercises: state.generatedExercises.slice(0, 1).map(compactStoredExercise),
  });
}

function isRetryableDbError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const msg = err.message;
  return (
    msg.includes("Access Handle") ||
    msg.includes("Invalid VFS state") ||
    msg.includes("createSyncAccessHandle")
  );
}

async function deleteOpfsFiles() {
  if (typeof navigator === "undefined" || !navigator.storage?.getDirectory) {
    return;
  }
  try {
    const root = await navigator.storage.getDirectory();
    const toDelete: string[] = [];
    // @ts-expect-error -- AsyncIterableIterator not in all TS libs
    for await (const [name] of root.entries()) {
      if (name.includes("sheetgenerator")) {
        toDelete.push(name);
      }
    }
    for (const name of toDelete) {
      await root.removeEntry(name);
    }
  } catch {
    // OPFS cleanup is best-effort
  }
}

async function resetDatabaseFiles() {
  try {
    await SQLite.deleteDatabaseAsync(DATABASE_NAME);
  } catch {
    // best-effort; the file may not exist yet
  }
  await deleteOpfsFiles();
}

async function openWithRetry(
  retries = 4,
  backoff = 300,
): Promise<SQLite.SQLiteDatabase> {
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      return await SQLite.openDatabaseAsync(DATABASE_NAME);
    } catch (err: unknown) {
      if (!isRetryableDbError(err) || attempt === retries - 1) throw err;

      // On web, stale OPFS/VFS state can survive reloads. Reset the DB files
      // before the final retry rather than reopening the same broken handle.
      if (attempt === retries - 2) {
        await resetDatabaseFiles();
      }

      await delay(backoff * (attempt + 1));
    }
  }
  return SQLite.openDatabaseAsync(DATABASE_NAME);
}

async function getDatabase() {
  if (!databasePromise) {
    databasePromise = openWithRetry().catch((err) => {
      // Reset so future calls can retry
      databasePromise = null;
      throw err;
    });
  }

  return databasePromise;
}

async function clearDisposableContent(db: SQLite.SQLiteDatabase) {
  await db.execAsync(`
    DROP TABLE IF EXISTS presets;
    DROP TABLE IF EXISTS generated_exercises;
    DROP TABLE IF EXISTS practice_sessions;
    DROP TABLE IF EXISTS app_settings;
  `);
}

async function ensureSchemaVersion(db: SQLite.SQLiteDatabase) {
  const row = await db.getFirstAsync<{ value: string }>(
    "SELECT value FROM app_settings WHERE key = ?",
    "schema_version",
  );

  if (!row || row.value !== APP_SCHEMA_VERSION) {
    await clearDisposableContent(db);
    await createTables(db);
    await seedDefaultSettings(db);
  }
}

export function initializeDatabase(): Promise<void> {
  if (isWeb()) {
    if (!initPromise) {
      initPromise = Promise.resolve().then(() => {
        const state = loadWebState();
        persistWebStateWithPruning(state);
      });
    }
    return initPromise;
  }

  if (!initPromise) {
    initPromise = (async () => {
      const db = await getDatabase();
      await createTables(db);
      await ensureSchemaVersion(db);
    })().catch((err) => {
      // Reset both so a future call (e.g. Strict Mode remount) can retry
      initPromise = null;
      databasePromise = null;
      throw err;
    });
  }
  return initPromise;
}

async function createTables(db: SQLite.SQLiteDatabase) {
  if (Platform.OS !== "web") {
    await db.execAsync("PRAGMA journal_mode = WAL;");
  }

  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS presets (
      id TEXT PRIMARY KEY NOT NULL,
      name TEXT NOT NULL,
      config_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS generated_exercises (
      exercise_id TEXT PRIMARY KEY NOT NULL,
      seed TEXT NOT NULL,
      title TEXT NOT NULL,
      config_json TEXT NOT NULL,
      music_xml TEXT NOT NULL,
      svg TEXT NOT NULL,
      audio_url TEXT NOT NULL,
      measure_count INTEGER NOT NULL,
      time_signature TEXT NOT NULL,
      grade INTEGER NOT NULL,
      summary_json TEXT NOT NULL,
      debug_json TEXT,
      generation_context_json TEXT,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS practice_sessions (
      id TEXT PRIMARY KEY NOT NULL,
      exercise_id TEXT NOT NULL,
      preset_id TEXT,
      title TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT NOT NULL,
      self_rating INTEGER NOT NULL,
      duration_seconds INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_settings (
      key TEXT PRIMARY KEY NOT NULL,
      value TEXT NOT NULL
    );
  `);

  try {
    await db.execAsync("ALTER TABLE generated_exercises ADD COLUMN debug_json TEXT;");
  } catch {
    // Column already exists on existing installs.
  }
  try {
    await db.execAsync(
      "ALTER TABLE generated_exercises ADD COLUMN generation_context_json TEXT;",
    );
  } catch {
    // Column already exists on existing installs.
  }
}

async function seedDefaultSettings(db: SQLite.SQLiteDatabase) {
  const defaults: Record<string, string> = {
    schema_version: APP_SCHEMA_VERSION,
    notation_scale: JSON.stringify(DEFAULT_SETTINGS.notationScale),
    metronome_default: JSON.stringify(DEFAULT_SETTINGS.metronomeDefault),
    count_in_default: JSON.stringify(DEFAULT_SETTINGS.countInDefault),
    preferred_hand_position: JSON.stringify(DEFAULT_SETTINGS.preferredHandPosition),
    default_grade: JSON.stringify(DEFAULT_SETTINGS.defaultGrade),
    default_reading_focus: JSON.stringify(DEFAULT_SETTINGS.defaultReadingFocus),
  };

  for (const [key, value] of Object.entries(defaults)) {
    await db.runAsync(
      "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
      key,
      value,
    );
  }
}

function parseJson<T>(raw: string) {
  return JSON.parse(raw) as T;
}

export async function getSettings(): Promise<AppSettings> {
  if (isWeb()) {
    const state = loadWebState();
    const values = new Map(Object.entries(state.settings));

    return {
      notationScale: parseJson<number>(
        values.get("notation_scale") ?? JSON.stringify(DEFAULT_SETTINGS.notationScale),
      ),
      metronomeDefault: parseJson<boolean>(
        values.get("metronome_default") ??
          JSON.stringify(DEFAULT_SETTINGS.metronomeDefault),
      ),
      countInDefault: parseJson<boolean>(
        values.get("count_in_default") ?? JSON.stringify(DEFAULT_SETTINGS.countInDefault),
      ),
      preferredHandPosition: parseJson<AppSettings["preferredHandPosition"]>(
        values.get("preferred_hand_position") ??
          JSON.stringify(DEFAULT_SETTINGS.preferredHandPosition),
      ),
      defaultGrade: parseJson<number>(
        values.get("default_grade") ?? JSON.stringify(DEFAULT_SETTINGS.defaultGrade),
      ),
      defaultReadingFocus: parseJson<AppSettings["defaultReadingFocus"]>(
        values.get("default_reading_focus") ??
          JSON.stringify(DEFAULT_SETTINGS.defaultReadingFocus),
      ),
    };
  }

  const db = await getDatabase();
  const rows = await db.getAllAsync<{ key: string; value: string }>(
    "SELECT key, value FROM app_settings",
  );

  const values = new Map(rows.map((row) => [row.key, row.value]));

  return {
    notationScale: parseJson<number>(
      values.get("notation_scale") ?? JSON.stringify(DEFAULT_SETTINGS.notationScale),
    ),
    metronomeDefault: parseJson<boolean>(
      values.get("metronome_default") ??
        JSON.stringify(DEFAULT_SETTINGS.metronomeDefault),
    ),
    countInDefault: parseJson<boolean>(
      values.get("count_in_default") ?? JSON.stringify(DEFAULT_SETTINGS.countInDefault),
    ),
    preferredHandPosition: parseJson<AppSettings["preferredHandPosition"]>(
      values.get("preferred_hand_position") ??
        JSON.stringify(DEFAULT_SETTINGS.preferredHandPosition),
    ),
    defaultGrade: parseJson<number>(
      values.get("default_grade") ??
        values.get("default_stage") ??
        JSON.stringify(DEFAULT_SETTINGS.defaultGrade),
    ),
    defaultReadingFocus: parseJson<AppSettings["defaultReadingFocus"]>(
      values.get("default_reading_focus") ??
        JSON.stringify(DEFAULT_SETTINGS.defaultReadingFocus),
    ),
  };
}

export async function updateSettings(settings: AppSettings) {
  if (isWeb()) {
    const state = loadWebState();
    state.settings = {
      ...state.settings,
      notation_scale: JSON.stringify(settings.notationScale),
      metronome_default: JSON.stringify(settings.metronomeDefault),
      count_in_default: JSON.stringify(settings.countInDefault),
      preferred_hand_position: JSON.stringify(settings.preferredHandPosition),
      default_grade: JSON.stringify(settings.defaultGrade),
      default_reading_focus: JSON.stringify(settings.defaultReadingFocus),
      schema_version: APP_SCHEMA_VERSION,
    };
    persistWebStateWithPruning(state);
    return;
  }

  const db = await getDatabase();
  const entries: [string, unknown][] = [
    ["notation_scale", settings.notationScale],
    ["metronome_default", settings.metronomeDefault],
    ["count_in_default", settings.countInDefault],
    ["preferred_hand_position", settings.preferredHandPosition],
    ["default_grade", settings.defaultGrade],
    ["default_reading_focus", settings.defaultReadingFocus],
  ];

  for (const [key, value] of entries) {
    await db.runAsync(
      `
      INSERT INTO app_settings (key, value)
      VALUES (?, ?)
      ON CONFLICT(key) DO UPDATE SET value = excluded.value
      `,
      key,
      JSON.stringify(value),
    );
  }
}

export async function getSettingValue<T>(key: string) {
  if (isWeb()) {
    const state = loadWebState();
    const value = state.settings[key];
    return value ? parseJson<T>(value) : null;
  }

  const db = await getDatabase();
  const row = await db.getFirstAsync<{ value: string }>(
    "SELECT value FROM app_settings WHERE key = ?",
    key,
  );

  return row ? parseJson<T>(row.value) : null;
}

export async function setSettingValue(key: string, value: unknown) {
  if (isWeb()) {
    const state = loadWebState();
    state.settings[key] = JSON.stringify(value);
    state.settings.schema_version = APP_SCHEMA_VERSION;
    persistWebStateWithPruning(state);
    return;
  }

  const db = await getDatabase();
  await db.runAsync(
    `
    INSERT INTO app_settings (key, value)
    VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    `,
    key,
    JSON.stringify(value),
  );
}

export async function saveGeneratedExercise(exercise: GeneratedExercise) {
  if (isWeb()) {
    const state = loadWebState();
    const createdAt = nowIso();
    const stored: StoredExercise = {
      ...exercise,
      createdAt,
    };
    // Keep generated sheet state fresh-only so stale exercise URLs cannot
    // silently masquerade as the current backend output on web.
    state.generatedExercises = [stored];
    state.settings.last_generator_config = JSON.stringify(exercise.config);
    state.settings.last_exercise_id = JSON.stringify(exercise.exerciseId);
    persistWebStateWithPruning(state);
    return;
  }

  const db = await getDatabase();
  const createdAt = nowIso();

  // Fresh generation should replace prior saved sheet content so the active
  // exercise always reflects the newest backend result.
  await db.runAsync("DELETE FROM generated_exercises");

  await db.runAsync(
    `
    INSERT OR REPLACE INTO generated_exercises (
      exercise_id,
      seed,
      title,
      config_json,
      music_xml,
      svg,
      audio_url,
      measure_count,
      time_signature,
      grade,
      summary_json,
      debug_json,
      generation_context_json,
      created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    exercise.exerciseId,
    exercise.seed,
    exercise.title,
    JSON.stringify(exercise.config),
    exercise.musicXml,
    exercise.svg,
    exercise.audioUrl,
    exercise.measureCount,
    exercise.timeSignature,
    exercise.grade,
    JSON.stringify(exercise.summary),
    exercise.debug ? JSON.stringify(exercise.debug) : null,
    exercise.generationContext ? JSON.stringify(exercise.generationContext) : null,
    createdAt,
  );

  await setSettingValue("last_generator_config", exercise.config);
  await setSettingValue("last_exercise_id", exercise.exerciseId);
}

export async function getExerciseById(
  exerciseId: string,
): Promise<StoredExercise | null> {
  if (isWeb()) {
    const state = loadWebState();
    return (
      state.generatedExercises.find((exercise) => exercise.exerciseId === exerciseId) ?? null
    );
  }

  const db = await getDatabase();
  const row = await db.getFirstAsync<{
    exercise_id: string;
    seed: string;
    title: string;
    config_json: string;
    music_xml: string;
    svg: string;
    audio_url: string;
    measure_count: number;
    time_signature: string;
    grade: number;
    summary_json: string;
    debug_json: string | null;
    generation_context_json: string | null;
    created_at: string;
  }>(
    "SELECT * FROM generated_exercises WHERE exercise_id = ?",
    exerciseId,
  );

  if (!row) {
    return null;
  }

  return {
    exerciseId: row.exercise_id,
    seed: row.seed,
    title: row.title,
    config: parseJson<ExerciseConfig>(row.config_json),
    musicXml: row.music_xml,
    svg: row.svg,
    audioUrl: row.audio_url,
    measureCount: row.measure_count,
    timeSignature: row.time_signature as TimeSignature,
    grade: row.grade,
    summary: parseJson<GeneratedExercise["summary"]>(row.summary_json),
    debug: row.debug_json
      ? parseJson<GeneratedExercise["debug"]>(row.debug_json)
      : null,
    generationContext: row.generation_context_json
      ? parseJson<ExerciseGenerationContext>(row.generation_context_json)
      : null,
    createdAt: row.created_at,
  } satisfies StoredExercise;
}

export async function getRecentExercises(limit = 8) {
  if (isWeb()) {
    const state = loadWebState();
    return state.generatedExercises
      .slice()
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
      .slice(0, limit)
      .map((exercise) => ({
        exerciseId: exercise.exerciseId,
        title: exercise.title,
        config: exercise.config,
        createdAt: exercise.createdAt,
        grade: exercise.grade,
      }));
  }

  const db = await getDatabase();
  const rows = await db.getAllAsync<{
    exercise_id: string;
    title: string;
    config_json: string;
    created_at: string;
    grade: number;
  }>(
    `
    SELECT exercise_id, title, config_json, created_at, grade
    FROM generated_exercises
    ORDER BY datetime(created_at) DESC
    LIMIT ?
    `,
    limit,
  );

  return rows.map((row) => ({
    exerciseId: row.exercise_id,
    title: row.title,
    config: parseJson<ExerciseConfig>(row.config_json),
    createdAt: row.created_at,
    grade: row.grade,
  }));
}

export async function savePreset(name: string, config: ExerciseConfig) {
  if (isWeb()) {
    const state = loadWebState();
    const timestamp = nowIso();
    const id = `preset-${Date.now().toString(36)}-${Math.random()
      .toString(36)
      .slice(2, 7)}`;

    state.presets = [
      {
        id,
        name,
        config,
        createdAt: timestamp,
        updatedAt: timestamp,
      },
      ...state.presets,
    ];
    state.settings.last_generator_config = JSON.stringify(config);
    persistWebStateWithPruning(state);
    return id;
  }

  const db = await getDatabase();
  const timestamp = nowIso();
  const id = `preset-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 7)}`;

  await db.runAsync(
    `
    INSERT INTO presets (id, name, config_json, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
    `,
    id,
    name,
    JSON.stringify(config),
    timestamp,
    timestamp,
  );

  await setSettingValue("last_generator_config", config);

  return id;
}

export async function getPresets() {
  if (isWeb()) {
    const state = loadWebState();
    return state.presets
      .slice()
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  }

  const db = await getDatabase();
  const rows = await db.getAllAsync<{
    id: string;
    name: string;
    config_json: string;
    created_at: string;
    updated_at: string;
  }>(
    `
    SELECT id, name, config_json, created_at, updated_at
    FROM presets
    ORDER BY datetime(updated_at) DESC
    `,
  );

  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    config: parseJson<ExerciseConfig>(row.config_json),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  })) satisfies SavedPreset[];
}

export async function getPresetById(presetId: string) {
  if (isWeb()) {
    const state = loadWebState();
    return state.presets.find((preset) => preset.id === presetId) ?? null;
  }

  const db = await getDatabase();
  const row = await db.getFirstAsync<{
    id: string;
    name: string;
    config_json: string;
    created_at: string;
    updated_at: string;
  }>(
    `
    SELECT id, name, config_json, created_at, updated_at
    FROM presets
    WHERE id = ?
    `,
    presetId,
  );

  if (!row) {
    return null;
  }

  return {
    id: row.id,
    name: row.name,
    config: parseJson<ExerciseConfig>(row.config_json),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  } satisfies SavedPreset;
}

export async function savePracticeSession(session: PracticeSession) {
  if (isWeb()) {
    const state = loadWebState();
    state.practiceSessions = [
      session,
      ...state.practiceSessions.filter((item) => item.id !== session.id),
    ].slice(0, 20);
    persistWebStateWithPruning(state);
    return;
  }

  const db = await getDatabase();
  await db.runAsync(
    `
    INSERT INTO practice_sessions (
      id,
      exercise_id,
      preset_id,
      title,
      started_at,
      finished_at,
      self_rating,
      duration_seconds
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    session.id,
    session.exerciseId,
    session.presetId,
    session.title,
    session.startedAt,
    session.finishedAt,
    session.selfRating,
    session.durationSeconds,
  );
}

export async function getRecentSessions(limit = 8) {
  if (isWeb()) {
    const state = loadWebState();
    return state.practiceSessions
      .slice()
      .sort((a, b) => Date.parse(b.finishedAt) - Date.parse(a.finishedAt))
      .slice(0, limit);
  }

  const db = await getDatabase();
  return db.getAllAsync<PracticeSession>(
    `
    SELECT
      id,
      exercise_id as exerciseId,
      preset_id as presetId,
      title,
      started_at as startedAt,
      finished_at as finishedAt,
      self_rating as selfRating,
      duration_seconds as durationSeconds
    FROM practice_sessions
    ORDER BY datetime(finished_at) DESC
    LIMIT ?
    `,
    limit,
  );
}

export async function getLastGeneratorConfig() {
  return getSettingValue<ExerciseConfig>("last_generator_config");
}

export async function getLastExerciseId() {
  return getSettingValue<string>("last_exercise_id");
}

export async function getHomeSnapshot() {
  const [lastGeneratorConfig, lastExerciseId, recentSessions, recentExercises] =
    await Promise.all([
      getLastGeneratorConfig(),
      getLastExerciseId(),
      getRecentSessions(4),
      getRecentExercises(4),
    ]);

  return {
    lastGeneratorConfig,
    lastExerciseId,
    recentSessions,
    recentExercises,
  };
}
