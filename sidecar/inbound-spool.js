import { randomUUID } from 'node:crypto';
import { mkdir, open, readdir, readFile, rename, unlink } from 'node:fs/promises';
import { join } from 'node:path';

export function inboundSpool(directory, deliver) {
  let draining = false;
  let sequence = 0;
  const syncDirectory = async () => {
    const fd = await open(directory, 'r');
    try { await fd.sync(); } finally { await fd.close(); }
  };
  return {
    async enqueue(event) {
      await mkdir(directory, { recursive: true, mode: 0o700 });
      const name = `${Date.now()}-${String(sequence++).padStart(12, '0')}-${randomUUID()}`;
      const pending = join(directory, `${name}.pending`);
      const fd = await open(pending, 'wx', 0o600);
      try {
        await fd.writeFile(JSON.stringify(event));
        await fd.sync();
      } finally { await fd.close(); }
      await rename(pending, join(directory, `${name}.json`));
      await syncDirectory();
    },
    async drain() {
      if (draining) return;
      draining = true;
      try {
        await mkdir(directory, { recursive: true, mode: 0o700 });
        const blocked = new Set();
        for (const name of (await readdir(directory)).filter(n => n.endsWith('.json')).sort()) {
          const path = join(directory, name);
          const event = JSON.parse(await readFile(path, 'utf8'));
          const address = event.from.trim().toLowerCase();
          if (blocked.has(address)) continue;
          const result = await deliver(event);
          if (result === 'retry') { blocked.add(address); continue; }
          if (result === 'reject') await rename(path, `${path}.rejected`);
          else await unlink(path);
          await syncDirectory();
        }
      } finally { draining = false; }
    },
  };
}
