import assert from "node:assert/strict";
import { test } from "node:test";
import {
  clampPage,
  pageCount,
  pageForRow,
  pageItems,
  pageOffset,
  pageRange,
  pageSizeFor,
  totalFrom,
} from "./pages.ts";

test("a list has at least one page, and a page is held to them", () => {
  assert.equal(pageCount(0), 1);
  assert.equal(pageCount(25), 1);
  assert.equal(pageCount(26), 2);
  assert.equal(pageCount(312), 13);
  assert.equal(clampPage(0, 13), 1);
  assert.equal(clampPage(14, 13), 13);
  assert.equal(clampPage(5, 13), 5);
});

test("a page skips the rows before it and shows its own range", () => {
  assert.equal(pageOffset(1), 0);
  assert.equal(pageOffset(3), 50);
  assert.deepEqual(pageRange(2, 312), { from: 26, to: 50 });
  assert.deepEqual(pageRange(13, 312), { from: 301, to: 312 });
  assert.deepEqual(pageRange(1, 0), { from: 0, to: 0 });
});

test("the pager shows the ends and the current page's neighbours, with gaps", () => {
  assert.deepEqual(pageItems(1, 1), [1]);
  assert.deepEqual(pageItems(1, 3), [1, 2, 3]);
  assert.deepEqual(pageItems(5, 13), [1, "gap", 4, 5, 6, "gap", 13]);
  assert.deepEqual(pageItems(1, 13), [1, 2, "gap", 13]);
  assert.deepEqual(pageItems(13, 13), [1, "gap", 12, 13]);
  // A single left-out page is shown as itself, never as a gap.
  assert.deepEqual(pageItems(4, 13), [1, 2, 3, 4, 5, "gap", 13]);
});

test("the total comes from the header, or the rows when the server sends none", () => {
  assert.equal(totalFrom("312", 25), 312);
  assert.equal(totalFrom("0", 0), 0);
  assert.equal(totalFrom(null, 50), 50);
  assert.equal(totalFrom("many", 50), 50);
  assert.equal(totalFrom("-1", 50), 50);
});

test("a taller window holds more rows a page, in steps", () => {
  assert.equal(pageSizeFor(700), 10);
  assert.equal(pageSizeFor(800), 15);
  assert.equal(pageSizeFor(1099), 15);
  assert.equal(pageSizeFor(1100), 20);
  assert.equal(pageSizeFor(1400), 25);
  assert.equal(pageSizeFor(2160), 25);
});

test("a new page size keeps the first row on screen", () => {
  // Rows 21–30 at 10 a page (page 3) are on page 2 at 20 a page (rows 21–40).
  assert.equal(pageForRow(20, 20), 2);
  // Rows 41–60 at 20 a page (page 3) start on page 5 at 10 a page.
  assert.equal(pageForRow(40, 10), 5);
  assert.equal(pageForRow(0, 25), 1);
});
