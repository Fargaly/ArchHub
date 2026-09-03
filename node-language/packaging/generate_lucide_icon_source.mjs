import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ICON_NAMES = Object.freeze([
  'arrow-left',
  'group',
  'house',
  'maximize',
  'minus',
  'play',
  'plus',
  'redo-2',
  'search',
  'settings',
  'share-2',
  'ungroup',
  'undo-2',
  'zoom-in',
  'zoom-out',
]);

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const packageRoot = resolve(root, 'node_modules', 'lucide-static');
const packageDocument = JSON.parse(await readFile(
  resolve(packageRoot, 'package.json'), 'utf8'));
if (packageDocument.version !== '1.25.0' || packageDocument.license !== 'ISC') {
  throw new Error('lucide-static provenance does not match the admitted release');
}

const sourceBytes = await readFile(resolve(packageRoot, 'icon-nodes.json'));
const source = JSON.parse(sourceBytes.toString('utf8'));
const icons = Object.fromEntries(ICON_NAMES.map(name => {
  const primitives = source[name];
  if (!Array.isArray(primitives) || primitives.length === 0) {
    throw new Error(`Lucide icon ${name} is missing or empty`);
  }
  return [name, primitives];
}));
const canonicalIcons = JSON.stringify(icons);
const digest = value => createHash('sha256').update(value).digest('hex');
const document = {
  schema: 'archhub-lucide-source-v1',
  package: {
    name: packageDocument.name,
    version: packageDocument.version,
    license: packageDocument.license,
    homepage: packageDocument.homepage,
    repository: packageDocument.repository.url,
    source: 'icon-nodes.json',
    source_sha256: digest(sourceBytes),
    selected_geometry_sha256: digest(canonicalIcons),
  },
  icons,
};

const target = resolve(root, 'nodelang', 'assets');
await mkdir(target, { recursive: true });
await writeFile(
  resolve(target, 'lucide-icons-1.25.0.json'),
  `${JSON.stringify(document, null, 2)}\n`,
  'utf8',
);
await writeFile(
  resolve(target, 'LUCIDE-1.25.0-LICENSE.txt'),
  await readFile(resolve(packageRoot, 'LICENSE')),
);
