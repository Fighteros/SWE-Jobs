import assert from 'node:assert/strict';
import { mkdtemp, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { inboundSpool } from './inbound-spool.js';

test('retry survives restart and preserves order for the same sender', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'inbound-'));
  try {
    const attempts = [];
    const first = inboundSpool(dir, async e => {
      attempts.push(e.id);
      return e.id === 1 ? 'retry' : 'ack';
    });
    for (const [id, from] of [[1, 'a'], [2, 'a'], [3, 'b']]) await first.enqueue({id, from});
    await first.drain();
    assert.deepEqual(attempts, [1, 3]);
    const restarted = inboundSpool(dir, async e => {
      attempts.push(e.id);
      return e.id === 2 ? 'reject' : 'ack';
    });
    await restarted.drain();
    assert.deepEqual(attempts, [1, 3, 1, 2]);
    assert.match((await readdir(dir)).join(), /^[^,]+\.rejected$/);
  } finally { await rm(dir, {recursive: true, force: true}); }
});
