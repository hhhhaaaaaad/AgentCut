import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import Ajv2020 from 'ajv/dist/2020.js';

const contractDir = resolve(fileURLToPath(new URL('.', import.meta.url)), '../../docs/contracts');
const load = (name) => JSON.parse(readFileSync(resolve(contractDir, name), 'utf8'));
const validate = new Ajv2020({ allErrors: true }).compile(load('analysis-evidence-v1.schema.json'));

for (const name of [
  'analysis-evidence-v1.valid.json',
  'analysis-evidence-v1.needs-review.json',
  'analysis-evidence-v1.no-speech.json',
  'analysis-evidence-v1.mixed.json',
]) {
  assert.equal(validate(load(name)), true, `${name}: ${JSON.stringify(validate.errors)}`);
}

for (const name of ['analysis-evidence-v1.invalid-extra-time.json']) {
  assert.equal(validate(load(name)), false, `${name} should fail strict schema validation`);
}

const fractionalTime = load('analysis-evidence-v1.valid.json');
fractionalTime.windows[0].startMs = 0.5;
assert.equal(validate(fractionalTime), false, 'timestamps must be integer milliseconds');

console.log('AnalysisEvidence 1.0 frontend schema fixtures passed');
