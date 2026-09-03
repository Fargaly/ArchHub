import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";

const canonical = (value) => {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
};
const digest = (value) => createHash("sha256").update(value).digest("hex");
const source = JSON.parse(await readFile("site-export.json", "utf8"));
const sealed = { ...source };
delete sealed.export_sha256;
const actualExportHash = digest(JSON.stringify(canonical(sealed)));
if (actualExportHash !== source.export_sha256) throw new Error("site export seal is invalid");
if (source.format !== "archhub-universal-cell-site-v2") throw new Error("unsupported site export format");
if (source.publication_tier !== "T0 PUBLIC") throw new Error("site export is not T0 PUBLIC");
if (Object.keys(source.routes).length !== 7) throw new Error("site export must contain seven routes");

await rm("dist", { recursive: true, force: true });
await mkdir("dist/client", { recursive: true });
for (const [assetPath, contents] of Object.entries(source.assets)) {
  const target = join("dist/client", assetPath);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, contents, "utf8");
}
for (const [route, record] of Object.entries(source.routes)) {
  if (digest(record.html) !== record.html_sha256) throw new Error(`route seal is invalid: ${route}`);
  if (record.output_path.includes("..") || record.output_path.startsWith("/")) {
    throw new Error(`unsafe route output path: ${record.output_path}`);
  }
  const target = join("dist/client", record.output_path);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, record.html, "utf8");
}
const redirect = "<!doctype html><meta charset=\"utf-8\"><meta http-equiv=\"refresh\" content=\"0;url=/website\"><title>ArchHub</title><a href=\"/website\">ArchHub</a>";
const missing = "<!doctype html><meta charset=\"utf-8\"><title>Not found</title><h1>Not found</h1><p><a href=\"/website\">Return to ArchHub</a></p>";
await writeFile("dist/client/index.html", redirect, "utf8");
await writeFile("dist/client/404.html", missing, "utf8");
await mkdir("dist/server", { recursive: true });
await writeFile("dist/server/index.js", `export default {\n  async fetch(request, env) {\n    if (!env.ASSETS) return new Response("Static assets unavailable", { status: 503 });\n    return env.ASSETS.fetch(request);\n  }\n};\n`, "utf8");
await mkdir("dist/.openai", { recursive: true });
await writeFile("dist/.openai/hosting.json", await readFile(".openai/hosting.json", "utf8"), "utf8");
await writeFile("dist/build-manifest.json", JSON.stringify({
  format: source.format,
  export_sha256: source.export_sha256,
  publication_tier: source.publication_tier,
  routes: Object.keys(source.routes).sort()
}, null, 2) + "\n", "utf8");
