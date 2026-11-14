import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeSegment, formatCategory } from "./format.ts";

test("a category reads as words", () => {
  assert.equal(formatCategory("infra_error"), "Infra error");
  assert.equal(formatCategory("unknown"), "Unknown");
  assert.equal(formatCategory(""), "");
});

test("a path segment is decoded, and kept as it came when it is not valid encoding", () => {
  assert.equal(decodeSegment("%3Cscript%3E"), "<script>");
  assert.equal(decodeSegment("abc"), "abc");
  assert.equal(decodeSegment("%E0%A4%A"), "%E0%A4%A");
});
