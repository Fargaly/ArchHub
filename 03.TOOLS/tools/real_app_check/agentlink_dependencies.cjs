// Restore only verified npm cache bytes; never execute package install scripts.
const path = require('node:path');
const fs = require('node:fs/promises');

async function restore(npmRoot, cache, destination, version) {
  const cacache = require(path.join(npmRoot, 'node_modules/cacache'));
  const semver = require(path.join(npmRoot, 'node_modules/semver'));
  const ssri = require(path.join(npmRoot, 'node_modules/ssri'));
  const packages = new Map();
  let packedBytes = 0;
  async function collect(name, range, parent) {
    if (!/^(?:@[a-z0-9._-]+\/)?[a-z0-9._-]+$/.test(name) || !semver.validRange(range)) {
      throw new Error('Unsupported cached dependency');
    }
    const url = 'https://registry.npmjs.org/' + name.replace('/', '%2f');
    const key = 'make-fetch-happen:request-cache:' + url;
    const info = await cacache.get.info(cache, key);
    if (!info) throw Object.assign(new Error('Cached metadata absent'), {code: 'ENOTCACHED'});
    // Largest account packument: 28,290,217 bytes; 1.25x rounded to four MiB.
    if (info.size > 36 * 1024 * 1024) throw new Error('Cached metadata exceeds qualification budget');
    const metadata = await cacache.get(cache, key);
    const versions = JSON.parse(metadata.data).versions;
    const selected = semver.maxSatisfying(Object.keys(versions), range);
    const manifest = versions[selected];
    if (!manifest || manifest.name !== name || manifest.version !== selected) {
      throw Object.assign(new Error('Exact cached dependency unavailable'), {code: 'ENOTCACHED'});
    }
    if (!parent && selected !== version) {
      throw Object.assign(new Error('Complete exact cached dependency unavailable'), {code: 'ENOTCACHED'});
    }
    const relative = path.join(parent, 'node_modules', name);
    if (packages.has(relative)) return;
    const integrity = manifest.dist?.integrity;
    if (typeof integrity !== 'string' || !/^sha512-[A-Za-z0-9+/]{86}==$/.test(integrity)) {
      throw new Error('Cached dependency has no SHA512 integrity');
    }
    const content = await cacache.get.hasContent(cache, integrity);
    if (!content) throw Object.assign(new Error('Cached archive absent'), {code: 'ENOTCACHED'});
    packedBytes += content.size;
    if (packages.size >= 128 || packedBytes > 64 * 1024 * 1024) throw new Error('Cached closure exceeds qualification budget');
    const data = await cacache.get.byDigest(cache, integrity);
    if (!ssri.checkData(data, integrity)) throw new Error('Cached dependency integrity mismatch');
    packages.set(relative, {manifest, data});
    for (const [dependency, constraint] of Object.entries(manifest.dependencies || {})) {
      // Optional native optimizations are omitted from the disposable qualification.
      if (Object.hasOwn(manifest.optionalDependencies || {}, dependency)) continue;
      // Keep Node's normal nested resolution; incompatible ranges never overwrite a parent.
      const ancestor = [...packages.entries()].find(([key, p]) =>
        relative.startsWith(path.dirname(key) + path.sep) && p.manifest.name === dependency &&
        semver.satisfies(p.manifest.version, constraint));
      if (!ancestor) await collect(dependency, constraint, relative);
    }
    for (const [peer] of Object.entries(manifest.peerDependencies || {})) {
      if (!manifest.peerDependenciesMeta?.[peer]?.optional) throw new Error('Required cached peer unsupported');
    }
  }
  try {
    await collect('@opencode-ai/plugin', version, '');
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTCACHED') return false;
    throw error;
  }
  // Hand only verified bytes to Python's bounded standard-library extractor.
  await fs.mkdir(destination, {recursive: true});
  async function writeFresh(name, data) {
    const file = await fs.open(path.join(destination, name), 'wx');
    try { await file.writeFile(data); }
    finally { await file.close(); }
  }
  const plan = [];
  for (const [relative, {manifest, data}] of packages) {
    const archive = String(plan.length) + '.tgz';
    await writeFresh(archive, data);
    plan.push({relative, manifest, archive});
  }
  await writeFresh('manifest.json', JSON.stringify(plan));
  return true;
}

if (require.main === module) {
  restore(...process.argv.slice(2)).then(used => console.log(used ? 'LOCAL_DEPENDENCIES_VERIFIED' : 'LOCAL_DEPENDENCIES_ABSENT'))
    .catch(error => { console.error(error.code || error.name, error.message); process.exitCode = 1; });
}
