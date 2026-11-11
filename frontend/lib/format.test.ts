import assert from "node:assert/strict";
import { test } from "node:test";
import { formatCategory } from "./format.ts";

test("a category reads as words", () => {
  assert.equal(formatCategory("infra_error"), "Infra error");
  assert.equal(formatCategory("unknown"), "Unknown");
  assert.equal(formatCategory(""), "");
});
