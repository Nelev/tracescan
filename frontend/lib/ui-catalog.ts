import { defineCatalog } from "@json-render/core";
import { schema } from "@json-render/react/schema";
import { shadcnComponentDefinitions } from "@json-render/shadcn/catalog";

/**
 * What a UI spec from the server may contain: the whole shadcn catalog of @json-render/shadcn. The
 * server's small model writes the specs and the backend passes them on unchecked
 * (backend/api/ui_spec.py), so this catalog is the only check before anything is drawn: it says
 * which components exist and what props each takes. Ten of them are drawn by our own components
 * (app/_components/ui-parts.tsx); the rest by the package's (registered in ui-view.tsx).
 *
 * This module has no React in it, so it runs under plain Node in the tests.
 */
export const UI_COMPONENTS = Object.keys(
  shadcnComponentDefinitions,
) as (keyof typeof shadcnComponentDefinitions)[];

export const catalog = defineCatalog(schema, {
  components: shadcnComponentDefinitions,
  actions: {},
});

export type UiCheck = { ok: true } | { ok: false; issues: string[] };

const issueText = (path: PropertyKey[], code: string) =>
  `${path.join(".") || "(spec)"}: ${code}`;

/**
 * Whether a spec fits the catalog. `catalog.validate` tests the structure and the component types
 * only, not the props, so each element's props are tested here against the component's own schema.
 * The issues are where and why only (a path and a code), never the values: they go to the console,
 * and a value could be text from a proposal.
 */
export function checkUi(spec: unknown): UiCheck {
  const checked = catalog.validate(spec);
  if (!checked.success) {
    const issues = checked.error?.issues ?? [];
    return {
      ok: false,
      issues: issues.map((issue) => issueText(issue.path, issue.code)),
    };
  }
  const issues: string[] = [];
  const { elements } = checked.data as {
    elements: Record<string, { type: string; props: unknown }>;
  };
  for (const [key, element] of Object.entries(elements)) {
    const definition =
      shadcnComponentDefinitions[
        element.type as keyof typeof shadcnComponentDefinitions
      ];
    // The schemas make an optional prop nullable, not optional, and the model leaves out what it
    // does not need: a prop that is missing counts as null.
    const props: Record<string, unknown> = { ...(element.props as object) };
    for (const name of Object.keys(definition.props.shape)) {
      if (!(name in props)) props[name] = null;
    }
    const result = definition.props.safeParse(props);
    if (result.success) continue;
    for (const issue of result.error.issues) {
      issues.push(
        issueText(["elements", key, "props", ...issue.path], issue.code),
      );
    }
  }
  return issues.length === 0 ? { ok: true } : { ok: false, issues };
}
