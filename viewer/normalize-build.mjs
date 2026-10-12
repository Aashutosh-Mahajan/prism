// Keep bundled text deterministic on Windows and preserve repository LF conventions.
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

async function normalize(directory) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, item.name);
    if (item.isDirectory()) await normalize(path);
    else if (/\.(html|css|js)$/.test(item.name)) {
      const text = await readFile(path, "utf8");
      await writeFile(path, text.replace(/\r\n/g, "\n").replace(/[\t ]+$/gm, ""), "utf8");
    }
  }
}
await normalize(fileURLToPath(new URL("../prism/viewer_dist", import.meta.url)));
