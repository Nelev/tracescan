import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { checkUi, UI_COMPONENTS } from "./ui-catalog.ts";
import { describeCatalog } from "./ui-catalog-prompt.ts";

const spec = (elements: Record<string, unknown>) => ({
  root: "page",
  elements: {
    page: { type: "Stack", props: {}, children: Object.keys(elements) },
    ...elements,
  },
});

test("a spec of the allowed components fits the catalog", () => {
  const ok = spec({
    title: {
      type: "Heading",
      props: { text: "Retrieval misses", level: "h2" },
      children: [],
    },
    ids: {
      type: "Table",
      props: { columns: ["Trace", "Span"], rows: [["tr_1", "s1"]] },
      children: [],
    },
    note: {
      type: "Alert",
      props: { title: "Unverified", type: "warning" },
      children: [],
    },
  });
  assert.deepEqual(checkUi(ok), { ok: true });
});

test("a component outside the catalog is refused", () => {
  const result = checkUi(
    spec({ m: { type: "Marquee", props: { text: "hi" }, children: [] } }),
  );
  assert.equal(result.ok, false);
});

test("the whole catalog is allowed, not a subset", () => {
  // Pins the decision to allow all of the package's components, not a hand-picked few.
  assert.equal(UI_COMPONENTS.length, 36);
  const ok = spec({
    tabs: {
      type: "Tabs",
      props: { tabs: [{ label: "One", value: "one" }] },
      children: [],
    },
    accordion: {
      type: "Accordion",
      props: { items: [{ title: "A", content: "b" }] },
      children: [],
    },
    progress: { type: "Progress", props: { value: 40 }, children: [] },
    button: { type: "Button", props: { label: "Go" }, children: [] },
  });
  assert.deepEqual(checkUi(ok), { ok: true });
});

test("a prop of the wrong shape is refused, and the value is not in the issues", () => {
  const secret = "patient John Doe";
  const result = checkUi(
    spec({
      t: { type: "Text", props: { text: [secret] }, children: [] },
    }),
  );
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.ok(result.issues.some((i) => i.includes("elements.t.props.text")));
    assert.ok(!result.issues.join("\n").includes(secret));
  }
});

test("a required prop that is missing is refused, an optional one may be left out", () => {
  const missing = checkUi(
    spec({ t: { type: "Text", props: {}, children: [] } }),
  );
  assert.equal(missing.ok, false);
  const optional = checkUi(
    spec({ t: { type: "Text", props: { text: "hi" }, children: [] } }),
  );
  assert.deepEqual(optional, { ok: true });
});

test("anything that is not a spec is refused, never a throw", () => {
  for (const value of [null, "page", 3, [], {}, { root: "x" }]) {
    assert.equal(checkUi(value).ok, false);
  }
});

test("the description for the server's model has a row per component and says what is required", () => {
  const text = describeCatalog();
  for (const name of UI_COMPONENTS)
    assert.ok(text.includes(`| \`${name}\` |`), name);
  assert.ok(text.includes('`level`: "h1", "h2", "h3" or "h4"')); // an enum, with its values
  assert.ok(text.includes("`text`: string, required")); // a required prop is marked
  assert.ok(text.includes("`rows`: array of array of string, required")); // a nested type
});

test("the backend's copy of the description is up to date", () => {
  const file = new URL("../../backend/api/ui_catalog.md", import.meta.url);
  assert.equal(
    readFileSync(file, "utf8"),
    describeCatalog(),
    "run `npm run export:ui-prompt`",
  );
});
