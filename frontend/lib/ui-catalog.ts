import { defineCatalog } from "@json-render/core";
import { schema } from "@json-render/react/schema";
import { shadcnComponentDefinitions } from "@json-render/shadcn/catalog";

/**
 * What a UI spec from the server may contain: the shadcn catalog of @json-render/shadcn less the
 * components that take a URL (`REMOVED`). The
 * server's small model writes the specs and the backend passes them on unchecked
 * (backend/api/ui_spec.py), so this catalog is the only check before anything is drawn: it says
 * which components exist and what props each takes. Ten of them are drawn by our own components
 * (app/_components/ui-parts.tsx); the rest by the package's (registered in ui-view.tsx).
 *
 * This module has no React in it, so it runs under plain Node in the tests.
 */

/**
 * The components that take a URL (`Image.src`, `Avatar.src`, `Link.href`). The package draws it
 * unchecked, and the model copies text from proposals, which come from trace content: a prompt
 * injection could make an image load `https://elsewhere/?d=<clinical text>` with no click, or a
 * link lead anywhere. No other component takes a URL, so without these the model cannot write one.
 */
export const REMOVED = ["Image", "Avatar", "Link"] as const;

type Removed = (typeof REMOVED)[number];

/** `components` without the `REMOVED` ones; also used for the package's drawing components. */
export function withoutRemoved<T extends Record<string, unknown>>(
  components: T,
): Omit<T, Removed> {
  const kept = { ...components };
  for (const name of REMOVED) delete kept[name];
  return kept;
}

export const COMPONENT_DEFINITIONS = withoutRemoved(shadcnComponentDefinitions);

export const UI_COMPONENTS = Object.keys(
  COMPONENT_DEFINITIONS,
) as (keyof typeof COMPONENT_DEFINITIONS)[];

export const catalog = defineCatalog(schema, {
  components: COMPONENT_DEFINITIONS,
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
      COMPONENT_DEFINITIONS[element.type as keyof typeof COMPONENT_DEFINITIONS];
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
