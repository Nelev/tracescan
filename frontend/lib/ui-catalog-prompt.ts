import { shadcnComponentDefinitions } from "@json-render/shadcn/catalog";
import { z } from "zod";

/**
 * The catalog in words, for the server's model. It is used only by `npm run export:ui-prompt`
 * (scripts/export-ui-prompt.ts) and its test, so it lives apart from lib/ui-catalog.ts, which the
 * browser loads. This module has no React in it, so it runs under plain Node.
 */
type JsonSchema = {
  type?: string | string[];
  enum?: unknown[];
  anyOf?: JsonSchema[];
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  required?: string[];
};

const alternatives = (s: JsonSchema): JsonSchema[] => s.anyOf ?? [s];
const typesOf = (s: JsonSchema): string[] =>
  Array.isArray(s.type) ? s.type : s.type ? [s.type] : [];
const acceptsNull = (s: JsonSchema) =>
  alternatives(s).some((alt) => typesOf(alt).includes("null"));

/** What a prop holds, in words: `string`, `"sm", "md" or "lg"`, `array of {label: string}`. */
function kindOf(schema: JsonSchema, depth = 0): string {
  const parts: string[] = [];
  for (const alt of alternatives(schema)) {
    if (alt.enum) {
      parts.push(...alt.enum.map((value) => JSON.stringify(value)));
      continue;
    }
    const all = typesOf(alt);
    const types = all.filter((type) => type !== "null");
    if (all.length === 0) parts.push("value"); // a type the schema could not describe
    for (const type of types) {
      if (type === "array") {
        parts.push(
          `array of ${alt.items ? kindOf(alt.items, depth + 1) : "value"}`,
        );
      } else if (type === "object") {
        parts.push(objectKind(alt, depth));
      } else {
        parts.push(type);
      }
    }
  }
  return parts.length < 2
    ? (parts[0] ?? "value")
    : `${parts.slice(0, -1).join(", ")} or ${parts.at(-1)}`;
}

function objectKind(schema: JsonSchema, depth: number): string {
  const keys = Object.keys(schema.properties ?? {});
  if (keys.length === 0 || depth > 2) return "object";
  const fields = keys.map((key) => {
    const field = (schema.properties as Record<string, JsonSchema>)[key];
    const optional = schema.required?.includes(key) ? "" : "?";
    return `${key}${optional}: ${kindOf(field, depth + 1)}`;
  });
  return `{${fields.join(", ")}}`;
}

const cellOf = (text: string) =>
  text.replaceAll("|", "\\|").replaceAll("\n", " ");

/**
 * One row per component: what it is for, each prop with the values it accepts (the ones that must
 * be given are marked), and whether it takes children. It is written to backend/api/ui_catalog.md,
 * and the backend puts it in the model's prompt as plain text; a test fails when the file is out
 * of date.
 */
export function describeCatalog(): string {
  const rows = ["| Type | Use | Props | Children |", "|---|---|---|---|"];
  for (const [name, definition] of Object.entries(shadcnComponentDefinitions)) {
    const { description, slots, props } = definition as {
      description?: string;
      slots?: string[];
      props: z.ZodType;
    };
    const schema = z.toJSONSchema(props, {
      io: "input",
      unrepresentable: "any",
    }) as JsonSchema;
    const cells = Object.entries(schema.properties ?? {}).map(
      ([prop, propSchema]) =>
        `\`${prop}\`: ${kindOf(propSchema)}${acceptsNull(propSchema) ? "" : ", required"}`,
    );
    const children = (slots?.length ?? 0) > 0 ? "yes" : "no";
    rows.push(
      `| \`${name}\` | ${cellOf(description ?? "")} | ${cellOf(cells.join("; "))} | ${children} |`,
    );
  }
  return `${rows.join("\n")}\n`;
}
