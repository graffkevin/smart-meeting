/**
 * Enforces the declaration order inside function bodies:
 *   1. library hooks (`useState`, `useQuery`, `useTranslation`…)
 *   2. application hooks (imported from `@/…` or defined in the file)
 *   3. other values (`const x = …`, `useMemo`)
 *   4. functions (`const f = (…) => …`, `useCallback`)
 *   5. the `return`
 * Usage: `bun scripts/declarationOrder.ts`.
 */
import { Glob } from 'bun';

/** Orval output (bun run api:generate): not written by hand, not checked */
const GENERATED_DIR = 'src/api/generated/';

const RANK_NAMES = ['', 'library hook', 'application hook', 'value', 'function'];

const FUNCTION = /^const \w+ = (async )?(<[^>]*>)?\(([^)]*)\)( *: *[^=]+)? =>|^const \w+ = useCallback\(/;
const HOOK_CALL = /^const .+? = (?:(\w+)\.)?(use\w+)(<[^>]*>)?\(/;

/** Maps every imported name of a file to its module */
const importsOf = (source: string): Map<string, string> => {
  const imports = new Map<string, string>();
  for (const [, clause, module] of source.matchAll(/^import (?:type )?(.+?) from '([^']+)';/gms)) {
    for (const name of clause.replace(/[{}]/g, ',').split(',')) {
      const local = name
        .trim()
        .split(/\s+as\s+/)
        .pop();
      if (local) imports.set(local, module);
    }
  }

  return imports;
};

const rankOf = (code: string, imports: Map<string, string>): number => {
  if (FUNCTION.test(code)) return 4;
  const match = code.match(HOOK_CALL);
  if (match === null || match[2] === 'useMemo') return 3;
  // `Context.useStoreContext()`: the hook belongs to where the object comes from
  const hook = match[1] ?? match[2];

  // Only hooks imported from a package are library hooks; local and `@/…` hooks belong to the app
  const module = imports.get(hook);

  return module && !module.startsWith('@/') ? 1 : 2;
};

const violations: string[] = [];

for (const file of [...new Glob('src/**/*.{ts,tsx}').scanSync('.')].filter((file) => !file.startsWith(GENERATED_DIR))) {
  const source = await Bun.file(file).text();
  const imports = importsOf(source);
  // Highest rank already met at each indentation (= each function body)
  const highest = new Map<number, number>();
  const lines = source.split('\n');
  lines.forEach((line, i) => {
    // Blank lines separate statements, they do not close a function body
    if (line.trim() === '') return;
    const indent = line.length - line.trimStart().length;
    // A multi-line destructuring (`const {\n  a,\n} = useForm(…)`) is read up to its `=`
    const end = line.includes(' = ') ? i : lines.findIndex((l, j) => j > i && /^\s*[}\]] = /.test(l));
    const code = lines
      .slice(i, Math.max(end, i) + 1)
      .map((l) => l.trim())
      .join(' ');
    for (const depth of highest.keys()) if (depth > indent) highest.delete(depth);
    if (indent === 0 || !code.startsWith('const ')) return;
    const rank = rankOf(code, imports);
    const previous = highest.get(indent) ?? 0;
    if (rank < previous)
      violations.push(`${file}:${i + 1} ${RANK_NAMES[rank]} declared after a ${RANK_NAMES[previous]}`);
    highest.set(indent, Math.max(previous, rank));
  });
}

if (violations.length > 0) {
  console.error(`Declaration order (library hooks, app hooks, values, functions, return):\n${violations.join('\n')}`);
  process.exit(1);
}
console.log('Declaration order: OK');
