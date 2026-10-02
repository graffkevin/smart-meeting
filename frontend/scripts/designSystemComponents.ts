/**
 * Forbids the Mantine components that the design system replaces (`@ign-junn/design-system`): layout and text
 * (`Box`, `Stack`, `Group`, `Text`, `Title`, `Divider`, `SimpleGrid`…), buttons, tooltips, dialogs, every form field,
 * badges, alerts, loaders, tables and tabs; the deprecated design system components; and the paths of its files: the
 * design system is imported from its single entry (`import { Button } from '@ign-junn/design-system'`), only `/theme`
 * and `/styles.css` keep their own path. Each violation names what to use instead. Multi-line imports are read too.
 * Usage: `bun scripts/designSystemComponents.ts`.
 */
import { Glob } from 'bun';

/** Orval output (bun run api:generate): not written by hand, not checked */
const GENERATED_DIR = 'src/api/generated/';

/** Mantine component → its design system replacement */
const REPLACEMENTS: Record<string, string> = {
  Box: 'Box',
  Stack: 'Stack',
  Group: 'Stack direction="row"',
  Text: 'Typography',
  Title: 'Typography',
  Tooltip: 'Tooltip',
  Button: 'Button',
  Modal: 'Dialog',
  TextInput: 'TextField',
  Textarea: 'TextField multiline',
  PasswordInput: 'TextField type="password"',
  NumberInput: 'TextField type="number"',
  TagsInput: 'TextField type="tags"',
  Select: 'Select',
  MultiSelect: 'MultiSelect',
  Autocomplete: 'Autocomplete',
  Checkbox: 'Checkbox or CheckboxGroup',
  Switch: 'Switch',
  Radio: 'RadioGroup',
  SegmentedControl: 'SegmentedSwitch',
  Slider: 'Slider or StepSlider',
  ColorInput: 'ColorField',
  ColorPicker: 'ColorPicker',
  Chip: 'ChipGroup',
  CopyButton: 'CopyButton',
  Badge: 'Badge',
  Table: 'DataTable or PropertyTable',
  Stepper: 'Steps',
  Alert: 'Alert',
  Loader: 'Spinner (or PageLoader for a page)',
  Progress: 'ProgressBar',
  Divider: 'Divider',
  SimpleGrid: 'Grid',
  Tabs: 'Tabs or TabBar',
  Anchor: 'Link',
};

/** Deprecated design system components → their replacement */
const DEPRECATED: Record<string, string> = {
  IconButton: 'Button with an `icon` and a `label`',
};

/** Paths of the package that keep their own import; everything else comes from the single entry */
const OWN_PATHS = new Set(['theme', 'styles.css']);

const violations: string[] = [];

for (const file of [...new Glob('src/**/*.{ts,tsx}').scanSync('.')].filter((file) => !file.startsWith(GENERATED_DIR))) {
  const source = await Bun.file(file).text();
  for (const match of source.matchAll(/^import (?:type )?\{([^}]*)\} from '@mantine\/core';/gms)) {
    const line = source.slice(0, match.index).split('\n').length;
    for (const specifier of match[1].split(',')) {
      const name = specifier
        .trim()
        .replace(/^type\s+/, '')
        .split(/\s+as\s+/)[0];
      const replacement = REPLACEMENTS[name];
      if (replacement)
        violations.push(`${file}:${line} ${name} from @mantine/core: use ${replacement} of @ign-junn/design-system`);
    }
  }
  for (const match of source.matchAll(/^import [^;]+ from '@ign-junn\/design-system\/([^']+)';/gm)) {
    const line = source.slice(0, match.index).split('\n').length;
    if (!OWN_PATHS.has(match[1]))
      violations.push(`${file}:${line} @ign-junn/design-system/${match[1]}: import it from '@ign-junn/design-system'`);
  }
  for (const match of source.matchAll(/^import (?:type )?\{([^}]*)\} from '@ign-junn\/design-system';/gms)) {
    const line = source.slice(0, match.index).split('\n').length;
    for (const specifier of match[1].split(',')) {
      const name = specifier.trim().split(/\s+as\s+/)[0];
      const replacement = DEPRECATED[name];
      if (replacement) violations.push(`${file}:${line} ${name} is deprecated: use ${replacement}`);
    }
  }
}

if (violations.length > 0) {
  console.error(`Design system components:\n${violations.join('\n')}`);
  process.exit(1);
}
console.log('Design system components: OK');
