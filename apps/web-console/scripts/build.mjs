import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outArg = process.argv.indexOf("--out-dir");
const output = resolve(root, outArg >= 0 ? process.argv[outArg + 1] : "dist");
const source = resolve(root, "src/index.html");
await mkdir(output, { recursive: true });
await cp(source, resolve(output, "index.html"));
const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
await writeFile(resolve(output, "manifest.json"), JSON.stringify({
  entry: "web-console",
  version: packageJson.version,
  source: "apps/web-console/src/index.html",
  business_runtime: false,
}, null, 2) + "\n", "utf8");
console.log(`built web-console to ${output}`);
