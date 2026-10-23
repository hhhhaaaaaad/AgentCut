import test from 'node:test';
import assert from 'node:assert/strict';
import { isRenderedPlanCurrent, isTaskDone, mergeTask, omitNullFields, outputDuration, savedPlanVersion, validatePlan } from '../src/lib/plan.ts';
import { formatTime, parseTime } from '../src/lib/format.ts';
import { apiErrorMessage } from '../src/lib/apiError.ts';

const plan = () => ({
  schemaVersion: '1.0', planVersion: 1, projectId: '1',
  source: { assetId: '1', url: 'http://localhost/video.mp4', duration: 60, width: 1920, height: 1080, fps: 30 },
  global: { output: { width: 1080, height: 1920, fps: 30 } },
  timeline: [{ id: 'seg_1', keep: true, sourceRange: { start: 10, end: 20 }, operations: [{ type: 'speed', rate: 2 }] }],
});

test('NEEDS_REVIEW stops polling like other terminal states', () => {
  for (const status of ['NEEDS_REVIEW', 'SUCCESS', 'FAILED']) assert.equal(isTaskDone({ status }), true);
  assert.equal(isTaskDone({ status: 'RETRYING' }), false);
});
test('late responses cannot decrease progress or revive a terminal task', () => {
  const current = { taskId: '1', progress: 70, status: 'RUNNING' };
  assert.equal(mergeTask(current, { ...current, progress: 20 }).progress, 70);
  const terminal = { ...current, status: 'NEEDS_REVIEW', progress: 100 };
  assert.deepEqual(mergeTask(terminal, current), terminal);
  assert.equal(mergeTask(terminal, { taskId: '2', progress: 0, status: 'PENDING' }).progress, 0);
});
test('JSON must match Plan structure before entering editor state', () => {
  assert.equal(validatePlan(plan()), null);
  assert.match(validatePlan({ timeline: null }), /方案格式有误/);
  const invalid = plan(); invalid.timeline[0].operations = [{ type: 'speed', rate: 0 }];
  assert.ok(validatePlan(invalid));
});
test('duplicate IDs and invalid global source ranges are rejected', () => {
  const duplicate = plan(); duplicate.timeline.push(structuredClone(duplicate.timeline[0]));
  assert.match(validatePlan(duplicate), /ID 重复/);
  const reversed = plan(); reversed.timeline[0].sourceRange.end = 5;
  assert.match(validatePlan(reversed), /结束时间/);
  const outside = plan(); outside.timeline[0].sourceRange.end = 61;
  assert.match(validatePlan(outside), /超出/);
});
test('duration honors keep decisions and speed operations', () => {
  const data = plan();
  data.timeline.push({ id: 'seg_2', keep: false, sourceRange: { start: 20, end: 60 } });
  assert.equal(outputDuration(data.timeline), 5);
});
test('timecode formatting preserves tenths and carries across minutes', () => {
  assert.equal(formatTime(28.4, true), '00:28.4');
  assert.equal(formatTime(59.96, true), '01:00.0');
  assert.equal(parseTime('01:02.5'), 62.5);
  assert.equal(parseTime('12.5'), 12.5);
});

test('Java null optional fields are normalized while required fields remain required', () => {
  const data = plan(); data.title = null; data.global.bgm = null; data.global.output.codec = null;
  assert.equal(validatePlan(omitNullFields(data)), null);
  data.source = null;
  assert.ok(validatePlan(omitNullFields(data)));
});
test('subtitles use segment output time after speed adjustment', () => {
  const data = plan();
  data.timeline[0].operations.unshift({ type: 'subtitle', text: '测试', start: 0, end: 5 });
  assert.equal(validatePlan(data), null);
  data.timeline[0].operations[0].end = 10;
  assert.match(validatePlan(data), /输出时长/);
});
test('removed segments cannot retain operations and crop cannot exceed source dimensions', () => {
  const removed = plan(); removed.timeline[0].keep = false;
  assert.match(validatePlan(removed), /删除的片段/);
  const cropped = plan(); cropped.timeline[0].operations = [{ type: 'crop', x: 0, y: 0, width: 1080, height: 1920 }];
  assert.match(validatePlan(cropped), /裁切范围/);
});

test('archive versions take precedence over the independent document planVersion', () => {
  assert.equal(savedPlanVersion(plan(), ['2', '10', '1']), 10);
  assert.equal(savedPlanVersion(plan(), []), 1);
  assert.equal(savedPlanVersion(null, []), null);
});

test('a saved edit invalidates an old render even when document planVersion is unchanged', () => {
  const original = plan();
  const edited = structuredClone(original);
  edited.timeline[0].sourceRange.end = 18;
  assert.equal(isRenderedPlanCurrent(original, structuredClone(original), false), true);
  assert.equal(isRenderedPlanCurrent(edited, original, false), false);
  assert.equal(isRenderedPlanCurrent(original, original, true), false);
  assert.equal(isRenderedPlanCurrent(original, null, false), false);
});

test('network and timeout failures provide actionable messages', () => {
  assert.match(apiErrorMessage({ code: 'ERR_NETWORK', message: 'Network Error' }), /无法连接后端/);
  assert.match(apiErrorMessage({ code: 'ECONNABORTED', message: 'timeout of 15000ms exceeded' }), /请求超时/);
});

test('backend errors preserve business messages and handle empty or structured bodies', () => {
  assert.equal(apiErrorMessage({ response: { status: 400, data: { message: '片段超出源视频时长' } } }), '片段超出源视频时长');
  assert.match(apiErrorMessage({ response: { status: 500, data: { error: 'Internal Server Error' } } }), /HTTP 500/);
  assert.match(apiErrorMessage({ response: { status: 404, data: { detail: [{ type: 'missing' }] } } }), /数据不存在/);
});
