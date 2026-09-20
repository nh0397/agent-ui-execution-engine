import { readFile, writeFile, mkdir } from "node:fs/promises";
const repo = new URL("../../", import.meta.url);
const read = async (path) =>
  JSON.parse(await readFile(new URL(path, repo), "utf8"));
const manifest = await read("evidence/manifest.json");
const runs = await Promise.all(
  Object.entries(manifest.runs).map(async ([name, summary]) => {
    const text = await readFile(
      new URL(`evidence/${name}/events.jsonl`, repo),
      "utf8",
    );
    return {
      name,
      ...summary,
      result: await read(`evidence/${name}/result.json`),
      events: text.trim().split("\n").map(JSON.parse),
    };
  }),
);
await mkdir(new URL("../src/generated/", import.meta.url), { recursive: true });
await writeFile(
  new URL("../src/generated/evidence.json", import.meta.url),
  JSON.stringify({
    backend: manifest.backend,
    handoff: manifest.human_handoff,
    runs,
    capability: await read("capabilities/update-address.v1.json"),
  }),
);
console.log(
  "Exported reviewed evidence; no local runs or credentials included.",
);
