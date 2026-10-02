// Dashboard boundary tests — verify no Supabase dependency and root-based routing.
// Run: node test/boundary.mjs

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');

let failures = 0;

function assert(condition, message) {
  if (!condition) {
    console.error(`FAIL: ${message}`);
    failures++;
  } else {
    console.log(`PASS: ${message}`);
  }
}

// 1. package.json must not depend on @supabase/supabase-js
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf-8'));
assert(
  !pkg.dependencies?.['@supabase/supabase-js'],
  'package.json has no @supabase/supabase-js dependency'
);
assert(
  !pkg.devDependencies?.['@supabase/supabase-js'],
  'package.json has no @supabase/supabase-js devDependency'
);

// 2. No source file imports from @supabase
function listFiles(dir, exts) {
  const results = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name === 'test') continue;
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...listFiles(fullPath, exts));
    } else if (exts.includes(extname(entry.name))) {
      results.push(fullPath);
    }
  }
  return results;
}

const srcFiles = listFiles(join(root, 'src'), ['.ts', '.tsx']);
for (const file of srcFiles) {
  const content = readFileSync(file, 'utf-8').toLowerCase();
  assert(
    !content.includes('supabase'),
    `${file} contains no supabase reference`
  );
}

// 3. vite.config.ts must not have base: '/SWE-Jobs/'
const viteConfig = readFileSync(join(root, 'vite.config.ts'), 'utf-8');
assert(
  !viteConfig.includes("/SWE-Jobs/"),
  'vite.config.ts has no /SWE-Jobs/ base'
);

// 4. App.tsx must not have basename="/SWE-Jobs"
const appContent = readFileSync(join(root, 'src', 'App.tsx'), 'utf-8');
assert(
  !appContent.includes('basename="/SWE-Jobs"'),
  'App.tsx has no basename="/SWE-Jobs"'
);

// 5. No VITE_SUPABASE env vars in .env.example
const envExamplePath = join(root, '.env.example');
if (existsSync(envExamplePath)) {
  const envExample = readFileSync(envExamplePath, 'utf-8');
  assert(
    !envExample.includes('SUPABASE'),
    '.env.example has no VITE_SUPABASE variables'
  );
}

// 6. Dockerfile must not reference SUPABASE build args
const dockerfilePath = join(root, 'Dockerfile');
if (existsSync(dockerfilePath)) {
  const dockerfile = readFileSync(dockerfilePath, 'utf-8');
  assert(
    !dockerfile.toUpperCase().includes('SUPABASE'),
    'Dockerfile has no SUPABASE build args'
  );
}

// 7. If dist/ exists, it must not contain supabase references
const distPath = join(root, 'dist');
if (existsSync(distPath)) {
  const distFiles = listFiles(distPath, ['.js', '.html', '.css']);
  let foundSupabase = false;
  for (const file of distFiles) {
    const content = readFileSync(file, 'utf-8').toLowerCase();
    if (content.includes('supabase')) {
      foundSupabase = true;
      console.error(`FAIL: ${file} contains supabase reference`);
      failures++;
    }
  }
  if (!foundSupabase) {
    console.log('PASS: dist/ contains no supabase references');
  }
} else {
  console.log('SKIP: dist/ does not exist (run npm run build first)');
}

// 8. api.ts must use VITE_API_BASE (not VITE_SUPABASE_URL)
const apiContent = readFileSync(join(root, 'src', 'api.ts'), 'utf-8');
assert(
  apiContent.includes('VITE_API_BASE'),
  'api.ts uses VITE_API_BASE'
);
assert(
  !apiContent.includes('SUPABASE'),
  'api.ts has no SUPABASE references'
);

// Summary
if (failures > 0) {
  console.error(`\n${failures} test(s) failed.`);
  process.exit(1);
} else {
  console.log('\nAll boundary tests passed.');
}
