/** Минимальный проверяемый договор runtime API; реализации загружаются только в PL. */
export interface Actor {
  id: string;
  uid: string;
}
export interface Course {
  id: string;
  path: string | null;
  commit_hash: string | null;
  sync_errors: string | null;
}
export interface Job {
  job_sequence_id: string;
  status: string | null;
  superseded: boolean;
}
export interface GitState {
  head: string;
  dirty: boolean;
  root: string;
  coursePath: string;
}
export interface Options {
  courseId: string;
  jobId: string;
  expectedCommit: string;
}
export interface Schema<T> {
  readonly _output?: T;
}
export interface Schemas {
  course: Schema<Course>;
  job: Schema<Job>;
}
export interface Database {
  runInTransactionAsync<T>(use: () => Promise<T>): Promise<T>;
  queryRows<T>(sql: string, schema: Schema<T>): Promise<T[]>;
  queryRows<T>(
    sql: string,
    params: Record<string, string>,
    schema: Schema<T>,
  ): Promise<T[]>;
  queryOptionalRow<T>(
    sql: string,
    params: Record<string, string>,
    schema: Schema<T>,
  ): Promise<T | null>;
  queryScalar(sql: string, schema: Schema<boolean>): Promise<boolean>;
  queryRow(
    sql: string,
    params: Record<string, string>,
    schema: Schema<unknown>,
  ): Promise<unknown>;
  initAsync(config: PgConfig, onError: () => void): Promise<void>;
  closeAsync(): Promise<void>;
  setRandomSearchSchemaAsync(name: string): Promise<void>;
  loadSqlEquiv(url: string): {
    select_admins: string;
    insert_admin_by_user_uid: string;
  };
}
export interface PgConfig {
  user: string;
  database: string;
  host: string;
  password?: string;
  max: number;
  statement_timeout?: number;
}
export interface Locks {
  init(config: PgConfig, onError: () => void): Promise<void>;
  close(): Promise<void>;
  doWithLock<T>(
    name: string,
    options: { timeout: number },
    use: () => Promise<T>,
  ): Promise<T>;
}
export interface Users {
  selectOptionalUserByUid(uid: string): Promise<Actor | null>;
  selectOrInsertUserByUid(uid: string): Promise<Actor>;
}
export interface AdministratorDependencies {
  db: Pick<
    Database,
    "runInTransactionAsync" | "queryRows" | "queryScalar" | "queryRow"
  >;
  users: Users;
  sql: { select_admins: string; insert_admin_by_user_uid: string };
  UserSchema: Schema<Actor>;
  AdministratorSchema: Schema<unknown>;
  z: { boolean(): Schema<boolean> };
}
export interface RevisionDependencies {
  db: {
    queryOptionalRow(
      sql: string,
      params: Record<string, string>,
      schema: Schema<Course>,
    ): Promise<Course | null>;
    queryRows(
      sql: string,
      params: Record<string, string>,
      schema: Schema<Job>,
    ): Promise<Job[]>;
  };
  locks: Pick<Locks, "doWithLock">;
  courses: { getLockNameForCoursePath(path: string): string };
  schemas: Schemas;
  readGit(path: string): Promise<GitState>;
}
export interface NativeModules {
  "lib/config": {
    config: {
      devMode: boolean;
      postgresqlUser: string;
      postgresqlDatabase: string;
      postgresqlHost: string;
      postgresqlPassword: string | null;
    };
    loadConfig(paths: string[]): Promise<void>;
  };
  "models/user": Users;
  "models/course": RevisionDependencies["courses"];
  "lib/db-types": {
    UserSchema: Schema<Actor>;
    AdministratorSchema: Schema<unknown>;
  };
  "sprocs/index": { init(): Promise<void> };
}
