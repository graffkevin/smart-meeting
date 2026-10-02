/**
 * Repository rules that a text search can check (the `check:rules` greps of junn-apps, as a Bun script so that they
 * also run on Windows). Each violation is printed with its rule; the exit code is 1 when there is any.
 * Usage: `bun scripts/checkRules.ts`.
 */
import { Glob } from 'bun';

/** Orval output (bun run api:generate): not written by hand, not checked */
const GENERATED_DIR = 'src/api/generated/';

const sources = [...new Glob('src/**/*.{ts,tsx}').scanSync('.')]
  .map((file) => file.replaceAll('\\', '/'))
  .filter((file) => !file.startsWith(GENERATED_DIR));

/** A line that only holds a comment */
const isComment = (line: string) => /^\s*(\/?\*|\/\/)/.test(line);

/** Rules on the lines of the files a filter selects */
const LINE_RULES: { name: string; pattern: RegExp; applies: (file: string) => boolean }[] = [
  {
    name: 'arrow functions only, no let, no for / while loop',
    pattern: /^\s*(export )?(default )?(async )?function[ *]|\blet\s|\b(for|while) \(/,
    applies: () => true,
  },
  {
    name: 'no HTML tag in JSX: a component with the `component` prop',
    pattern: /(^|[^\w])<[a-z][a-z0-9]*(\s|\/?>|$)/,
    applies: (file) => file.endsWith('.tsx'),
  },
  {
    name: 'no hardcoded UI text: it belongs to src/locales/',
    pattern: /['"`][^'"`]*[éèêàùçôîâ]/,
    applies: (file) => !file.startsWith('src/locales/') && !file.startsWith('src/tests/'),
  },
  {
    name: 'no `!x?.y`: check with a type guard, then handle the positive case',
    pattern: /!\w+(\.\w+)*\?\./,
    applies: () => true,
  },
  {
    name: "no `typeof x === '…'`: the type guards of the design system",
    pattern: /typeof [^=;]+[!=]== '/,
    applies: (file) => !file.startsWith('src/tests/'),
  },
  {
    name: 'components/ are bricks: no import of features, services or stores',
    pattern: /from '@\/(features|services|stores)\//,
    applies: (file) => file.startsWith('src/components/'),
  },
  {
    name: 'services/ and utils/ import no feature, component or hook',
    pattern: /from '@\/(features|components|hooks)\//,
    applies: (file) => file.startsWith('src/services/') || file.startsWith('src/utils/'),
  },
];

/** Rules on the place of the files */
const FILE_RULES: { name: string; violates: (file: string) => boolean }[] = [
  {
    name: 'services/, utils/ and constants/ hold no JSX',
    violates: (file) => /^src\/(services|utils|constants)\//.test(file) && file.endsWith('.tsx'),
  },
  {
    name: 'services/ and utils/ are flat',
    violates: (file) => /^src\/(services|utils)\/[^/]+\//.test(file),
  },
  {
    name: 'features/ hold components and their use*.ts hooks only',
    violates: (file) => /^src\/features\/.*\/(?!use)[^/]+\.ts$/.test(file),
  },
];

const violations = await Promise.all(
  sources.map(async (file) => {
    const lines = (await Bun.file(file).text()).split('\n');
    const lineViolations = LINE_RULES.filter((rule) => rule.applies(file)).flatMap((rule) =>
      lines.flatMap((line, index) =>
        !isComment(line) && rule.pattern.test(line) ? [`${file}:${index + 1}: ${rule.name}\n    ${line.trim()}`] : [],
      ),
    );
    const fileViolations = FILE_RULES.filter((rule) => rule.violates(file)).map((rule) => `${file}: ${rule.name}`);

    return [...lineViolations, ...fileViolations];
  }),
);

const all = violations.flat();
if (all.length > 0) {
  console.error(`Repository rules:\n${all.join('\n')}`);
  process.exit(1);
}
console.log('Repository rules: OK');
