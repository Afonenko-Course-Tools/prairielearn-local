/** Только начальный local administrator; курсы и конфигурации входа не публикует. */
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

export function adminSettings(env) {
  const actorUid = env.BOOTSTRAP_ADMIN_UID;
  if (
    !actorUid ||
    actorUid.trim() !== actorUid ||
    /[\x00-\x20\x7f]/.test(actorUid)
  )
    throw Error("Задайте постоянный BOOTSTRAP_ADMIN_UID");
  return { actorUid, plRoot: env.PL_ROOT ?? "/PrairieLearn" };
}

/** Только первый actor в пустой БД; существующая роль никогда не выдаётся заново. */
export async function initialAdministrator(
  { db, users, sql, UserSchema, AdministratorSchema, z },
  uid,
) {
  return db.runInTransactionAsync(async () => {
    const admins = await db.queryRows(sql.select_admins, UserSchema);
    const actor = await users.selectOptionalUserByUid(uid);
    if (actor && admins.some((row) => row.id === actor.id)) {
      return actor;
    }
    const occupied = await db.queryScalar(
      "SELECT EXISTS(SELECT 1 FROM users) OR EXISTS(SELECT 1 FROM courses)",
      z.boolean(),
    );
    if (actor || admins.length || occupied)
      throw Error(
        "Начальный администратор создаётся только в пустой локальной БД; существующие права не изменены",
      );
    const created = await users.selectOrInsertUserByUid(uid);
    await db.queryRow(
      sql.insert_admin_by_user_uid,
      { uid, authn_user_id: created.id },
      AdministratorSchema,
    );
    return created;
  });
}

export async function bootstrapActor(settings) {
  const native = (path) =>
    import(
      pathToFileURL(
        join(settings.plRoot, "apps/prairielearn/dist", path + ".js"),
      ).href
    );
  const [{ config, loadConfig }, db, locks, { z }, users, schemas] =
    await Promise.all([
      native("lib/config"),
      import("@prairielearn/postgres"),
      import("@prairielearn/named-locks"),
      import("zod"),
      native("models/user"),
      native("lib/db-types"),
    ]);
  await loadConfig([join(settings.plRoot, "config.json")]);
  if (process.env.NODE_ENV !== "production" || config.devMode !== false)
    throw Error("Начальная инициализация требует production и devMode=false");
  const pg = {
    user: config.postgresqlUser,
    database: config.postgresqlDatabase,
    host: config.postgresqlHost,
    password: config.postgresqlPassword ?? undefined,
    max: 2,
  };
  await db.initAsync(pg, () => {
    process.exitCode = 1;
  });
  try {
    await locks.init(pg, () => {
      process.exitCode = 1;
    });
    await db.setRandomSearchSchemaAsync("local-stack-bootstrap");
    await (await native("sprocs/index")).init();
    const sql = db.loadSqlEquiv(
      pathToFileURL(
        join(
          settings.plRoot,
          "apps/prairielearn/dist/pages/administratorAdmins/administratorAdmins.js",
        ),
      ).href,
    );
    await locks.doWithLock(
      "local-stack-initial-administrator",
      { timeout: 30000 },
      () =>
        initialAdministrator(
          { db, users, sql, z, ...schemas },
          settings.actorUid,
        ),
    );
  } finally {
    await locks.close();
    await db.closeAsync();
  }
}

export async function main(env = process.env) {
  await bootstrapActor(adminSettings(env));
  console.log(
    "Начальный локальный actor проверен; курсы и регистрации не изменялись.",
  );
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
