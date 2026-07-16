/* Build-time loader for pipeline-published JSON (synced into public/data/).
   Static export renders these at build; the raw JSON also ships at /data/*.json
   so every figure has a one-click "Get the data" link. Server components only. */

import { promises as fs } from "fs";
import path from "path";
import type { Published } from "./published";

export async function loadPublished<T>(name: string): Promise<Published<T>> {
  const file = path.join(process.cwd(), "public", "data", `${name}.json`);
  return JSON.parse(await fs.readFile(file, "utf-8")) as Published<T>;
}
