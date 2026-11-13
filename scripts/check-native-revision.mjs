/** Проверка сохранённой native ревизии после штатного HTTP sync; курс не изменяет. */
import { execFile } from "node:child_process";
import { realpath } from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";
import { promisify } from "node:util";
import { pathToFileURL } from "node:url";

const fullCommit = /^[0-9a-f]{40}(?![\s\S])/;
const numericId = /^[1-9][0-9]*(?![\s\S])/;
const usage =
  "check-native-revision.mjs --course-id ID --job-id ID --expected-commit FULL_SHA";

export function revisionOptions(args) {
  const options = {};
  for (let i = 0; i < args.length; i += 2) {
    if (
      !["--course-id", "--job-id", "--expected-commit"].includes(args[i]) ||
      !args[i + 1] ||
      Object.hasOwn(options, args[i])
    )
      throw new Error(usage);
    options[args[i]] = args[i + 1];
  }
  const result = {
    courseId: options["--course-id"],
    jobId: options["--job-id"],
    expectedCommit: options["--expected-commit"],
  };
  if (
    !numericId.test(result.courseId ?? "") ||
    !numericId.test(result.jobId ?? "") ||
    !fullCommit.test(result.expectedCommit ?? "")
  )
    throw new Error(usage);
  return result;
}

export function acceptRevision(
  { courseId, jobId, expectedCommit },
  { course, jobs, git },
) {
  if (
    !course ||
    course.id !== courseId ||
    !isAbsolute(course.path ?? "") ||
    course.path === "/"
  )
    throw new Error("Native course отсутствует или имеет неверный path");
  if (course.commit_hash !== expectedCommit || course.sync_errors)
    throw new Error(
      "Сохранённая native ревизия не совпадает с готовым выпуском или содержит sync_errors",
    );
  if (
    jobs.length !== 1 ||
    jobs[0].job_sequence_id !== jobId ||
    jobs[0].status !== "Success" ||
    jobs[0].superseded
  )
    throw new Error(
      "Запрошенный sync job не успешен или уже заменён другим sync",
    );
  if (git.head !== expectedCommit || git.dirty || git.root !== git.coursePath)
    throw new Error(
      "Native Git path, HEAD или чистота дерева не совпадают с выпуском",
    );
  return { courseId, jobSequenceId: jobId, commit: expectedCommit };
}

// Отдельные зависимости позволяют проверить отказ до переключения сайта без DB/Docker.
export async function verifyRevision(
  options,
  { db, locks, courses, schemas, readGit },
) {
  const readCourse = () =>
    db.queryOptionalRow(
      "SELECT id::text, path, commit_hash, sync_errors FROM courses WHERE id=$courseId",
      { courseId: options.courseId },
      schemas.course,
    );
  const before = await readCourse();
  if (!before || !isAbsolute(before.path ?? "") || before.path === "/")
    throw new Error("Native course отсутствует или имеет неверный path");
  return locks.doWithLock(
    courses.getLockNameForCoursePath(before.path),
    { timeout: 10000 },
    async () => {
      const course = await readCourse();
      if (!course || course.path !== before.path)
        throw new Error("Native course path изменился во время проверки");
      const jobs = await db.queryRows(
        `SELECT job_sequence_id::text, status,
      EXISTS (SELECT 1 FROM jobs later WHERE later.course_id=$courseId AND later.type='sync'
        AND later.job_sequence_id > $jobId) AS superseded
      FROM jobs WHERE course_id=$courseId AND job_sequence_id=$jobId AND type='sync'`,
        { courseId: options.courseId, jobId: options.jobId },
        schemas.job,
      );
      return acceptRevision(options, {
        course,
        jobs,
        git: await readGit(course.path),
      });
    },
  );
}

async function readGit(coursePath) {
  const git = async (args) =>
    (
      await promisify(execFile)(
        "git",
        ["--no-optional-locks", "-C", coursePath, ...args],
        { timeout: 10000, maxBuffer: 1024 * 1024 },
      )
    ).stdout.trim();
  return {
    head: await git(["rev-parse", "HEAD"]),
    dirty: Boolean(
      await git([
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored",
      ]),
    ),
    root: await realpath(await git(["rev-parse", "--show-toplevel"])),
    coursePath: await realpath(coursePath),
  };
}

async function main() {
  const options = revisionOptions(process.argv.slice(2));
  const root = process.env.PL_ROOT ?? "/PrairieLearn";
  const native = (name) =>
    import(pathToFileURL(`${root}/apps/prairielearn/dist/${name}.js`).href);
  const { config, loadConfig } = await native("lib/config");
  await loadConfig([`${root}/config.json`]);
  const db = await import("@prairielearn/postgres");
  const locks = await import("@prairielearn/named-locks");
  const { z } = await import("zod");
  const pg = {
    user: config.postgresqlUser,
    database: config.postgresqlDatabase,
    host: config.postgresqlHost,
    password: config.postgresqlPassword ?? undefined,
    max: 2,
    statement_timeout: 30000,
  };
  try {
    await db.initAsync(pg, () => {
      process.exitCode = 1;
    });
    // Штатная lock infrastructure может создавать таблицу/строку; course/jobs не записываются.
    await locks.init(pg, () => {
      process.exitCode = 1;
    });
    const result = await verifyRevision(options, {
      db,
      locks,
      courses: await native("models/course"),
      readGit,
      schemas: {
        course: z.object({
          id: z.string(),
          path: z.string().nullable(),
          commit_hash: z.string().nullable(),
          sync_errors: z.string().nullable(),
        }),
        job: z.object({
          job_sequence_id: z.string(),
          status: z.string().nullable(),
          superseded: z.boolean(),
        }),
      },
    });
    console.log(JSON.stringify(result));
  } finally {
    await locks.close();
    await db.closeAsync();
  }
}

// Поддерживает обычный файл и stdin: docker exec ... node --input-type=module - --course-id ...
if (
  process.argv[1] === "-" ||
  (process.argv[1] &&
    import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
) {
  main().catch(() => {
    console.error(
      "Проверка native ревизии отклонена; student-сайт не переключать. Проверьте native sync job и runtime.",
    );
    process.exitCode = 1;
  });
}
