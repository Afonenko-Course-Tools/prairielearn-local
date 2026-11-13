import assert from "node:assert/strict";
import { test } from "node:test";
import {
  adminSettings,
  initialAdministrator,
} from "../scripts/bootstrap-admin.mjs";

const env = { BOOTSTRAP_ADMIN_UID: "bootstrap@local.invalid" };
test("настройки actor не требуют курса, registry или Gateway", () => {
  assert.deepEqual(adminSettings(env), {
    actorUid: env.BOOTSTRAP_ADMIN_UID,
    plRoot: "/PrairieLearn",
  });
  for (const uid of ["", "a b", " leading", "trailing ", "a\nb"]) {
    assert.throws(() => adminSettings({ BOOTSTRAP_ADMIN_UID: uid }));
  }
});

/** @param {{users?: import("../types/native.js").Actor[], admins?: import("../types/native.js").Actor[], courses?: number}} [settings] */
function nativeFixture({ users = [], admins = [], courses = 0 } = {}) {
  const state = {
    users: [...users],
    admins: [...admins],
    courses,
    created: 0,
    grants: 0,
    transaction: false,
  };
  /** @type {import("../types/native.js").AdministratorDependencies} */
  const native = {
    UserSchema: {},
    AdministratorSchema: {},
    z: { boolean: () => ({}) },
    sql: {
      select_admins: "native select_admins",
      insert_admin_by_user_uid: "native insert_admin_by_user_uid",
    },
    db: {
      async runInTransactionAsync(use) {
        state.transaction = true;
        try {
          return await use();
        } finally {
          state.transaction = false;
        }
      },
      async queryRows(sql) {
        assert.equal(sql, "native select_admins");
        return state.admins;
      },
      async queryScalar() {
        return state.users.length > 0 || state.courses > 0;
      },
      async queryRow(sql, args) {
        assert.equal(sql, "native insert_admin_by_user_uid");
        assert.equal(state.transaction, true);
        const actor = state.users.find((row) => row.uid === args.uid);
        assert.ok(actor);
        assert.equal(args.authn_user_id, actor.id);
        state.grants++;
        state.admins.push(actor);
        return { id: "1", user_id: actor.id };
      },
    },
    users: {
      async selectOptionalUserByUid(uid) {
        return state.users.find((row) => row.uid === uid) ?? null;
      },
      async selectOrInsertUserByUid(uid) {
        assert.equal(state.transaction, true);
        state.created++;
        const row = { id: "7", uid };
        state.users.push(row);
        return row;
      },
    },
  };
  return { native, state };
}

test("пустая БД: один native actor и native grant; повтор только проверяет", async () => {
  const { native, state } = nativeFixture();
  const actor = await initialAdministrator(native, env.BOOTSTRAP_ADMIN_UID);
  assert.equal(actor.id, "7");
  assert.equal(state.created, 1);
  assert.equal(state.grants, 1);
  await initialAdministrator(native, env.BOOTSTRAP_ADMIN_UID);
  assert.equal(state.created, 1);
  assert.equal(state.grants, 1);
});

for (const fixture of [
  { users: [{ id: "2", uid: "learner@local.invalid" }] },
  { courses: 1 },
  {
    users: [{ id: "2", uid: "other@local.invalid" }],
    admins: [{ id: "2", uid: "other@local.invalid" }],
  },
  { users: [{ id: "2", uid: env.BOOTSTRAP_ADMIN_UID }] },
]) {
  test(
    "непустая БД без administrator с заданным UID не меняет пользователей и права " +
      JSON.stringify(fixture),
    async () => {
      const { native, state } = nativeFixture(fixture);
      await assert.rejects(
        initialAdministrator(native, env.BOOTSTRAP_ADMIN_UID),
      );
      assert.equal(state.created, 0);
      assert.equal(state.grants, 0);
    },
  );
}

test("существующий native administrator: read-success без создания и grant", async () => {
  const actor = { id: "7", uid: env.BOOTSTRAP_ADMIN_UID };
  const { native, state } = nativeFixture({
    users: [actor],
    admins: [actor],
    courses: 1,
  });
  assert.deepEqual(
    await initialAdministrator(native, env.BOOTSTRAP_ADMIN_UID),
    actor,
  );
  assert.equal(state.created, 0);
  assert.equal(state.grants, 0);
});

test("смена configured UID и отозванная роль не дают новый grant", async () => {
  const actor = { id: "7", uid: env.BOOTSTRAP_ADMIN_UID };
  for (const scenario of [
    {
      fixture: { users: [actor], admins: [actor] },
      uid: "other@local.invalid",
    },
    { fixture: { users: [actor], admins: [] }, uid: actor.uid },
  ]) {
    const { native, state } = nativeFixture(scenario.fixture);
    await assert.rejects(initialAdministrator(native, scenario.uid));
    assert.equal(state.created, 0);
    assert.equal(state.grants, 0);
  }
});
