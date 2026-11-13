/** Пакеты предоставляет установленный PL; локальная проверка использует их узкий API. */
declare module "@prairielearn/postgres" {
  const db: import("./native.js").Database;
  export = db;
}
declare module "@prairielearn/named-locks" {
  const locks: import("./native.js").Locks;
  export = locks;
}
declare module "zod" {
  interface Value<T> {
    readonly _output?: T;
    nullable(): Value<T | null>;
  }
  export const z: {
    boolean(): import("./native.js").Schema<boolean>;
    string(): Value<string>;
    object<T>(shape: {
      [K in keyof T]: import("./native.js").Schema<T[K]>;
    }): import("./native.js").Schema<T>;
  };
}
