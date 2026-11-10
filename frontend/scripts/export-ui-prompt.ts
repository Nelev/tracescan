import { writeFileSync } from "node:fs";
import { describeCatalog } from "../lib/ui-catalog-prompt.ts";

// Writes the catalog in words for the server's model (backend/api/ui_spec.py puts it in its prompt).
const target = new URL("../../backend/api/ui_catalog.md", import.meta.url);
writeFileSync(target, describeCatalog());
console.log(`wrote ${target.pathname}`);
