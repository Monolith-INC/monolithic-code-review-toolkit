#!/usr/bin/env node
// Compile this repository's portable plugin root into vendor payloads.
//
//   node scripts/build_payloads.mjs build    # regenerate payloads/<vendor>/
//   node scripts/build_payloads.mjs verify   # fail if payloads drift from source
//
// The toolkit's `agent-plugin install` command is hard-coded to its own
// hello-world sample at the pinned revision, so it cannot distribute this
// plugin. What it *does* provide is the adapter compile/verify pipeline, which
// is what this script drives — the same calls each adapter's own
// scripts/payload.mjs makes, pointed at our plugin root and our output tree.
//
// Payloads are build output. Never hand-edit payloads/.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TOOLKIT = join(ROOT, ".toolkit");
const PLUGIN = join(ROOT, "plugins", "monolithic-code-review-toolkit");
const VENDORS = ["claude", "cursor", "codex"];

const operation = process.argv[2];
if (operation !== "build" && operation !== "verify") {
  console.error("Usage: build_payloads.mjs <build|verify>");
  process.exit(2);
}

// The toolkit is cloned and built on demand into .toolkit/ (gitignored).
// with_toolkit.sh owns that lifecycle; `validate` is the cheapest way to
// trigger it and doubles as a conformance gate before we compile anything.
function ensureToolkit() {
  const compiler = join(TOOLKIT, "packages", "compiler", "dist", "index.js");
  if (existsSync(compiler)) return;
  console.error("[payloads] toolkit not built yet; bootstrapping via with_toolkit.sh");
  const result = spawnSync("bash", [join(ROOT, "scripts", "with_toolkit.sh"), "validate", PLUGIN], {
    stdio: ["ignore", "ignore", "inherit"],
  });
  if (result.status !== 0) {
    console.error("[payloads] toolkit bootstrap failed");
    process.exit(1);
  }
}

ensureToolkit();

const { compileVendorPayload, verifyVendorPayload } = await import(
  join(TOOLKIT, "packages", "compiler", "dist", "index.js")
);

const adapters = Object.fromEntries(
  await Promise.all(VENDORS.map(async (vendor) => {
    const module = await import(join(TOOLKIT, "packages", `adapter-${vendor}`, "dist", "index.js"));
    return [vendor, module[`${vendor}Adapter`]];
  })),
);

let failed = false;

for (const vendor of VENDORS) {
  const shipped = join(ROOT, "payloads", vendor);
  const result = operation === "build"
    ? compileVendorPayload({ source: PLUGIN, vendor, output: shipped }, adapters[vendor])
    : verifyVendorPayload({ source: PLUGIN, vendor, shipped }, adapters[vendor]);

  if (result.ok) {
    console.log(`${vendor}: ${operation} ok`);
    continue;
  }

  failed = true;
  console.error(`${vendor}: ${operation} FAILED`);
  for (const diagnostic of result.diagnostics ?? []) {
    console.error(`  [${diagnostic.code}] ${diagnostic.message}${diagnostic.path ? ` (${diagnostic.path})` : ""}`);
  }
}

process.exit(failed ? 1 : 0);
