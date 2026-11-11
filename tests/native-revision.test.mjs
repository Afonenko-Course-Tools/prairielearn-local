import assert from 'node:assert/strict';
import {test} from 'node:test';
import {acceptRevision, revisionOptions, verifyRevision} from '../scripts/check-native-revision.mjs';

const sha = 'a'.repeat(40);
const options = {courseId: '7', jobId: '19', expectedCommit: sha};
const fixture = () => ({course: {id: '7', path: '/course/java/current', commit_hash: sha, sync_errors: null},
  jobs: [{job_sequence_id: '19', status: 'Success', superseded: false}],
  git: {head: sha, dirty: false, root: '/real/course', coursePath: '/real/course'}});

test('принимает только полный SHA и точные positive numeric IDs до DB init', () => {
  assert.deepEqual(revisionOptions(['--expected-commit', sha, '--job-id', '19', '--course-id', '7']), options);
  for (const args of [[], ['--course-id','7'], ['--course-id','7','--job-id','19','--expected-commit',sha.slice(0,7)],
    ['--course-id','7','--job-id','19','--expected-commit','A'.repeat(40)],
    ['--course-id','7','--job-id','19','--expected-commit',sha+'\n'],
    ['--course-id','7\n','--job-id','19','--expected-commit',sha],
    ['--course-id','0','--job-id','19','--expected-commit',sha],
    ['--course-id','7x','--job-id','19','--expected-commit',sha],
    ['--course-id','7','--job-id','-1','--expected-commit',sha],
    ['--course-id','7','--job-id','19','--expected-commit',sha,'--job-id','19']]) assert.throws(() => revisionOptions(args));
});

test('успешный exact sync job и сохранённый commit подтверждают чистый native Git', () => {
  assert.deepEqual(acceptRevision(options, fixture()), {courseId: '7', jobSequenceId: '19', commit: sha});
});

for (const [name, change] of [
  ['другая сохранённая ревизия при Success', x => x.course.commit_hash = 'b'.repeat(40)],
  ['нет сохранённого commit', x => x.course.commit_hash = null],
  ['course sync_errors при Success', x => x.course.sync_errors = 'invalid JSON'],
  ['другой course ID', x => x.course.id = '8'],
  ['нет course', x => x.course = null],
  ['относительный course path', x => x.course.path = 'course/java'],
  ['нет exact job для курса', x => x.jobs = []],
  ['другой job ID', x => x.jobs[0].job_sequence_id = '20'],
  ['Error job', x => x.jobs[0].status = 'Error'],
  ['Running job', x => x.jobs[0].status = 'Running'],
  ['Stopped job', x => x.jobs[0].status = 'Stopped'],
  ['несколько jobs вместо одного', x => x.jobs.push({...x.jobs[0]})],
  ['более новый native sync', x => x.jobs[0].superseded = true],
  ['HEAD отличается от DB', x => x.git.head = 'b'.repeat(40)],
  ['изменённое или untracked/ignored дерево', x => x.git.dirty = true],
  ['DB path указывает внутрь другого Git root', x => x.git.root = '/other'],
]) {
  test(`отклоняет: ${name}`, () => {const state = fixture(); change(state); assert.throws(() => acceptRevision(options, state));});
}

function nativeFixture({pathChanged = false, lockFails = false} = {}) {
  const state = fixture(), calls = [];
  let locked = false, reads = 0;
  return {calls, native: {
    schemas: {course: {}, job: {}},
    courses: {getLockNameForCoursePath: path => `coursedir:${path}`},
    locks: {async doWithLock(name, settings, use) {
      calls.push('lock'); assert.equal(name, 'coursedir:/course/java/current'); assert.equal(settings.timeout, 10000);
      if (lockFails) throw new Error('lock timeout');
      locked = true; try {return await use();} finally {locked = false; calls.push('unlock');}
    }},
    db: {
      async queryOptionalRow(sql, params) {
        assert.match(sql, /FROM courses WHERE id=\$courseId/); assert.equal(params.courseId, options.courseId);
        calls.push('course'); reads++; if (reads > 1) assert.equal(locked, true);
        return {...state.course, ...(pathChanged && reads > 1 ? {path: '/changed'} : {})};
      },
      async queryRows(sql, params) {
        assert.equal(locked, true); assert.match(sql, /course_id=\$courseId AND job_sequence_id=\$jobId AND type='sync'/);
        assert.match(sql, /later.job_sequence_id > \$jobId/); assert.deepEqual(params, {courseId: '7', jobId: '19'});
        calls.push('job'); return state.jobs;
      },
    },
    async readGit(path) {assert.equal(locked, true); assert.equal(path, state.course.path); calls.push('git'); return state.git;},
  }};
}

test('повторно читает course и проверяет exact job/HEAD под штатным course lock', async () => {
  const {native, calls} = nativeFixture();
  assert.equal((await verifyRevision(options, native)).commit, sha);
  assert.deepEqual(calls, ['course','lock','course','job','git','unlock']);
});
test('смена DB course path во время захвата lock отклоняется до чтения Git', async () => {
  const {native, calls} = nativeFixture({pathChanged: true});
  await assert.rejects(verifyRevision(options, native), /path изменился/);
  assert.deepEqual(calls, ['course','lock','course','unlock']);
});
test('занятый course lock отклоняет проверку без обхода блокировки', async () => {
  const {native, calls} = nativeFixture({lockFails: true});
  await assert.rejects(verifyRevision(options, native), /lock timeout/);
  assert.deepEqual(calls, ['course','lock']);
});
