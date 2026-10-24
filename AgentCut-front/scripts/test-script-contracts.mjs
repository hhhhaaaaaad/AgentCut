import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseScriptContractBundleV1 } from '../src/lib/scriptContractsV1.ts';

const corpus = JSON.parse(readFileSync(new URL('../../docs/contracts/script-contracts-v1.fixtures.json', import.meta.url), 'utf8'));
let accepted = 0, rejected = 0;
for (const sample of corpus.cases) {
  const value = structuredClone(corpus.base);
  for (const patch of sample.patches) {
    let parent = value;
    for (const key of patch.path.slice(0, -1)) parent = parent[key];
    const key = patch.path.at(-1);
    if (patch.op === 'remove') delete parent[key];
    else parent[key] = structuredClone(patch.value);
  }
  if (sample.valid) {
    try { await parseScriptContractBundleV1(value); }
    catch (error) { throw new Error(sample.name + ': ' + error.message); }
    await parseScriptContractBundleV1(JSON.parse(JSON.stringify(value)));
    accepted++;
  } else {
    await assert.rejects(() => parseScriptContractBundleV1(value), undefined, sample.name);
    rejected++;
  }
}
console.log('B1 script/task corpus: ' + accepted + ' accepted, ' + rejected + ' rejected (' + corpus.cases.length + ' shared cases)');

const generated = JSON.parse(readFileSync(new URL('../../docs/contracts/offline-id-director.bundle.json', import.meta.url), 'utf8'));
const compiled = await parseScriptContractBundleV1(generated);
assert.equal(compiled.materialIndex.scenes.length, 5);
assert.equal(compiled.script.estimatedDurationMs, 6000);
assert.equal(compiled.script.reviewStatus, 'NEEDS_REVIEW');
assert.equal(compiled.script.rows[1].sourceParts[0].sourceRange.startMs, 4500);
assert.equal(compiled.script.rows[1].outputRange.startMs, 3000);
assert.equal(compiled.script.captionCues.length, 0);
console.log('Program-built ID director draft: accepted');
