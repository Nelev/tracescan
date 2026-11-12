import assert from "node:assert/strict";
import { test } from "node:test";
import { setTokenSource, withSessionToken } from "./session-token.ts";

// One module, one source: the tests run in order and each sets the source it needs.

test("a call made before Clerk has loaded waits for it, then goes signed", async () => {
  let settled = false;
  const pending = withSessionToken({ method: "POST" }).then((init) => {
    settled = true;
    return init;
  });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(settled, false);

  setTokenSource(async () => "tok-1");
  const init = await pending;
  assert.equal(init.method, "POST");
  assert.equal(new Headers(init.headers).get("Authorization"), "Bearer tok-1");
});

test("the token is asked for on every call and keeps the call's own headers", async () => {
  let calls = 0;
  setTokenSource(async () => `tok-${++calls}`);
  await withSessionToken({});
  const init = await withSessionToken({
    headers: { "Content-Type": "application/json" },
  });
  const headers = new Headers(init.headers);
  assert.equal(headers.get("Authorization"), "Bearer tok-2");
  assert.equal(headers.get("Content-Type"), "application/json");
});

test("signed out, or when Clerk fails, the call goes without a token", async () => {
  const init = { method: "GET" };
  setTokenSource(async () => null);
  assert.equal(await withSessionToken(init), init);
  setTokenSource(async () => {
    throw new Error("offline");
  });
  assert.equal(await withSessionToken(init), init);
});
