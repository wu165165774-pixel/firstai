import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, api, request, setAccessToken } from "../src/lib/api.js";

test("request unwraps the standard backend envelope", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => (globalThis.fetch = originalFetch));
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/novels?user_id=writer&limit=200");
    assert.equal(options.method, undefined);
    return new Response(
      JSON.stringify({ code: 0, message: "success", data: [{ novel_id: "n1" }] }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  assert.deepEqual(await api.listProjects("writer"), [{ novel_id: "n1" }]);
});

test("provider catalog requests a bounded availability probe", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => (globalThis.fetch = originalFetch));
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/v1/providers?probe=true&timeout_ms=2500");
    return new Response(
      JSON.stringify({ data: { providers: ["qwen_local"], catalog: [], probed: true } }),
      { status: 200 },
    );
  };

  const result = await api.listProviders({ probe: true, timeoutMs: 2500 });
  assert.equal(result.probed, true);
});

test("request serializes mutation bodies as JSON", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => (globalThis.fetch = originalFetch));
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/novels/n1/manuscript/chapters/import-workflow");
    assert.equal(options.method, "POST");
    assert.match(options.headers.get("Content-Type"), /application\/json/);
    assert.deepEqual(JSON.parse(options.body), {
      workflow_run_id: "run1",
      expected_manuscript_revision: null,
    });
    return new Response(JSON.stringify({ data: { deduplicated: false } }), {
      status: 201,
    });
  };

  assert.deepEqual(await api.importWorkflow("n1", "run1"), {
    deduplicated: false,
  });
});

test("workflow re-import carries manuscript optimistic revision", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => (globalThis.fetch = originalFetch));
  globalThis.fetch = async (_url, options) => {
    assert.equal(JSON.parse(options.body).expected_manuscript_revision, 4);
    return new Response(JSON.stringify({ data: { deduplicated: true } }), {
      status: 200,
    });
  };

  assert.deepEqual(await api.importWorkflow("n1", "run1", 4), {
    deduplicated: true,
  });
});

test("async workflow submission carries queue headers and grounded payload", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => (globalThis.fetch = originalFetch));
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/workflows/chapter/runs/async");
    assert.equal(options.headers.get("Idempotency-Key"), "ui-key");
    assert.equal(options.headers.get("X-Workflow-Priority"), "7");
    assert.equal(JSON.parse(options.body).chapter_plan_revision, 3);
    return new Response(
      JSON.stringify({ data: { run: { run_id: "run-ui" }, job: {} } }),
      { status: 202 },
    );
  };

  const result = await api.enqueueWorkflow(
    { chapter_plan_id: "cp-1", chapter_plan_revision: 3 },
    { idempotencyKey: "ui-key", priority: 7 },
  );
  assert.equal(result.run.run_id, "run-ui");
});

test("request exposes backend validation messages", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => (globalThis.fetch = originalFetch));
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "revision conflict" }), {
      status: 409,
    });

  await assert.rejects(
    () => request("/conflict"),
    (error) =>
      error instanceof ApiError &&
      error.status === 409 &&
      error.message === "revision conflict",
  );
});

test("configured access token is sent as a bearer header", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
    setAccessToken("", { persist: false });
  });
  setAccessToken("session-secret", { persist: false });
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.headers.get("Authorization"), "Bearer session-secret");
    return new Response(
      JSON.stringify({ data: { authenticated: true, user_id: "writer" } }),
      { status: 200 },
    );
  };

  const identity = await api.identity();
  assert.equal(identity.user_id, "writer");
});
