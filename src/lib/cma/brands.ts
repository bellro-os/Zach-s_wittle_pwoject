import { promises as fs } from "node:fs";
import path from "node:path";
import { BRANDS_DIR } from "@/lib/cma/paths";

/** Minimal brand-profile shape consumed by the CMA UI. */
export interface BrandSummary {
  name: string;
  display_name: string;
  layout_style: string;
  primary: string;
  secondary: string;
  paper: string;
  wordmark: string;
  tagline: string;
  agent_name: string;
}

/**
 * Light-weight YAML reader covering the subset of YAML produced by
 * config/brands/*.yaml — two-space indented blocks, scalar values,
 * optional double-quoted strings. Avoids pulling a yaml dependency
 * into the host for what is a half-dozen flat keys per brand.
 */
function parseSimpleYaml(text: string): Record<string, unknown> {
  const lines = text.split(/\r?\n/);
  const root: Record<string, unknown> = {};
  const stack: Array<{ indent: number; obj: Record<string, unknown> }> = [
    { indent: -1, obj: root },
  ];

  for (const raw of lines) {
    // Strip YAML comments — a ``#`` only counts as a comment when it appears
    // at the start of the line or is preceded by whitespace. This preserves
    // hex color values like ``"#7c22ce"`` that follow a colon.
    const line = raw.replace(/(^|\s)#.*$/, "$1").replace(/\s+$/, "");
    if (!line.trim()) continue;
    const indent = line.match(/^ */)?.[0].length ?? 0;
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].obj;
    const content = line.trim();
    const colonIdx = content.indexOf(":");
    if (colonIdx === -1) continue;
    const key = content.slice(0, colonIdx).trim();
    const valuePart = content.slice(colonIdx + 1).trim();
    if (valuePart === "") {
      const child: Record<string, unknown> = {};
      parent[key] = child;
      stack.push({ indent, obj: child });
    } else {
      // Strip surrounding quotes (single or double)
      let v: string = valuePart;
      if (
        (v.startsWith('"') && v.endsWith('"')) ||
        (v.startsWith("'") && v.endsWith("'"))
      ) {
        v = v.slice(1, -1);
      }
      parent[key] = v;
    }
  }
  return root;
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

export async function listBrands(): Promise<BrandSummary[]> {
  let entries: string[];
  try {
    entries = await fs.readdir(BRANDS_DIR);
  } catch {
    return [];
  }
  const yamlFiles = entries.filter((e) => e.endsWith(".yaml"));
  const out: BrandSummary[] = [];
  for (const file of yamlFiles) {
    const full = path.join(BRANDS_DIR, file);
    try {
      const text = await fs.readFile(full, "utf-8");
      const data = parseSimpleYaml(text);
      const palette = asRecord(data.palette);
      const agent = asRecord(data.agent);
      out.push({
        name: String(data.name ?? file.replace(/\.yaml$/, "")),
        display_name: String(data.display_name ?? data.name ?? file),
        layout_style: String(data.layout_style ?? "dark_band"),
        primary: String(palette.primary ?? "#7c22ce"),
        secondary: String(palette.secondary ?? "#5d1a9c"),
        paper: String(palette.paper ?? "#ffffff"),
        wordmark: String(data.wordmark ?? ""),
        tagline: String(data.tagline ?? ""),
        agent_name: String(agent.name ?? ""),
      });
    } catch {
      continue;
    }
  }
  return out.sort((a, b) => a.display_name.localeCompare(b.display_name));
}
