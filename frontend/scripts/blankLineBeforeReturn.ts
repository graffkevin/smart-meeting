/**
 * Enforces a blank line before every `return` statement (no Biome rule covers it).
 * A `return` needs none when it opens its block (previous line ends with `{`), follows a
 * `case`/`default` label or a brace-less `if`/`else`, or follows a comment. Usage: `bun scripts/blankLineBeforeReturn.ts [--fix]`.
 */
import { Glob } from 'bun';

/** Orval output (bun run api:generate): not written by hand, not checked */
const GENERATED_DIR = 'src/api/generated/';

const fix = process.argv.includes('--fix');

const needsBlankLine = (previous: string): boolean => {
  const line = previous.trim();
  if (line === '' || line.endsWith('{') || line.endsWith('=> (') || line.endsWith(':')) return false;
  if (/^(\}\s*)?(if|else)\b/.test(line) && !line.endsWith(';')) return false;

  return !(line.startsWith('//') || line.startsWith('*') || line.startsWith('/*'));
};

const violations: string[] = [];
const files = [...new Glob('src/**/*.{ts,tsx}').scanSync('.')].filter((file) => !file.startsWith(GENERATED_DIR));

for (const file of files) {
  const lines = (await Bun.file(file).text()).split('\n');
  const output = lines.flatMap((line, i) => {
    const isReturn = /^\s*return\b/.test(line);
    if (!isReturn || i === 0 || !needsBlankLine(lines[i - 1])) return [line];
    violations.push(`${file}:${i + 1}`);

    return ['', line];
  });
  if (fix && output.length !== lines.length) await Bun.write(file, output.join('\n'));
}

if (violations.length > 0 && !fix) {
  console.error(`Missing blank line before return:\n${violations.join('\n')}`);
  process.exit(1);
}
console.log(fix ? `Fixed ${violations.length} return statement(s)` : 'Blank lines before return: OK');
