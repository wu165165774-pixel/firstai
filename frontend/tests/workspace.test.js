import assert from "node:assert/strict";
import test from "node:test";

import {
  canImportWorkflow,
  chapterTitle,
  latestApprovedRevision,
  pipelineStages,
  progressPercent,
  projectionTone,
  statusLabel,
} from "../src/lib/workspace.js";

test("pipeline stages expose stale and accepted state", () => {
  const stages = pipelineStages({
    project: { revision: 2, genre: "悬疑" },
    bible: { revision: 4, characters: [{}, {}] },
    plan: { revision: 3, is_stale: true },
    arcs: [{ is_stale: false }, { is_stale: true }],
    chapterPlans: [{ is_stale: false }],
    manuscripts: [{ accepted_revision: 2 }, { accepted_revision: null }],
  });
  assert.equal(stages.length, 6);
  assert.equal(stages[2].state, "warning");
  assert.equal(stages[3].detail, "1/2 个可用");
  assert.equal(stages[5].detail, "1/2 章已接受");
});

test("latest approved revision ignores superseded candidates", () => {
  const result = latestApprovedRevision([
    { revision: 3, review_status: "superseded" },
    { revision: 1, review_status: "approved" },
    { revision: 2, review_status: "approved" },
  ]);
  assert.equal(result.revision, 2);
});

test("workflow import requires the complete quality gate", () => {
  assert.equal(
    canImportWorkflow({
      execution_status: "succeeded",
      workflow_status: "completed",
      quality_gate_passed: true,
    }),
    true,
  );
  assert.equal(
    canImportWorkflow({
      execution_status: "succeeded",
      workflow_status: "completed",
      quality_gate_passed: false,
    }),
    false,
  );
});

test("presentation helpers remain deterministic", () => {
  assert.equal(progressPercent(2, 3), 67);
  assert.equal(progressPercent(1, 0), 0);
  assert.equal(projectionTone("failed"), "danger");
  assert.equal(statusLabel("waiting_for_acceptance"), "待接受");
  assert.equal(
    chapterTitle(
      { chapter_number: 5, chapter_plan_id: "cp-1" },
      [{ chapter_plan_id: "cp-1", title: "潮汐回声" }],
    ),
    "潮汐回声",
  );
});
