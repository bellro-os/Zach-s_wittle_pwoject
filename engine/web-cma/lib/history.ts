import { promises as fs } from "node:fs";
import path from "node:path";
import { OUTPUTS_DIR } from "./paths";

export interface CmaHistoryEntry {
  pdfName: string;
  htmlName: string;
  brand: string;
  slug: string;
  size: number;
  mtime: number;
}

/**
 * Scan outputs/ for PDFs produced by scripts/build_cma.py
 * (filename pattern: ``CMA_<brand>_<slug>.pdf``).
 */
export async function listHistory(limit = 30): Promise<CmaHistoryEntry[]> {
  let entries: string[];
  try {
    entries = await fs.readdir(OUTPUTS_DIR);
  } catch {
    return [];
  }
  const candidates: CmaHistoryEntry[] = [];
  for (const name of entries) {
    if (!name.startsWith("CMA_") || !name.endsWith(".pdf")) continue;
    const stem = name.slice(4, -4); // strip "CMA_" and ".pdf"
    const firstUs = stem.indexOf("_");
    if (firstUs === -1) continue;
    const brand = stem.slice(0, firstUs);
    const slug = stem.slice(firstUs + 1);
    try {
      const stat = await fs.stat(path.join(OUTPUTS_DIR, name));
      candidates.push({
        pdfName: name,
        htmlName: `cma_${brand}_${slug}.html`,
        brand,
        slug,
        size: stat.size,
        mtime: stat.mtimeMs,
      });
    } catch {
      continue;
    }
  }
  candidates.sort((a, b) => b.mtime - a.mtime);
  return candidates.slice(0, limit);
}

export function humanizeSlug(slug: string): string {
  return slug
    .split("_")
    .map((w) => (w.length > 0 ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ")
    .replace(/\bN\b/g, "N")
    .trim();
}
