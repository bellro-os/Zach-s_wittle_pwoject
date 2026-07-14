import path from "node:path";

/**
 * Absolute path to the MLS Bot project root (one level up from web-cma/).
 * All Python invocations and brand/output file paths derive from here.
 */
export const PROJECT_ROOT = path.resolve(process.cwd(), "..");
export const PYTHON_SRC = path.join(PROJECT_ROOT, "src");
export const BRANDS_DIR = path.join(PROJECT_ROOT, "config", "brands");
export const OUTPUTS_DIR = path.join(PROJECT_ROOT, "outputs");
