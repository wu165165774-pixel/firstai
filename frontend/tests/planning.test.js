import assert from "node:assert/strict";
import test from "node:test";

import {
  editorFromEntity,
  plannerAcceptPayload,
  plannerGeneratePayload,
  planningPayload,
} from "../src/lib/planning.js";

test("planning editor round-trips chapter fields and optimistic revision", () => {
  const editor = editorFromEntity("chapter_plan", {
    arc_id: "arc-1",
    chapter_number: 3,
    title: "潮汐门",
    scene_beats: [{ beat_id: "b1", order: 1, title: "启程" }],
    continuity_dependencies: ["第二章已接受"],
  });
  const payload = planningPayload("chapter_plan", editor, { revision: 4 });
  assert.equal(payload.arc_id, "arc-1");
  assert.equal(payload.chapter_number, 3);
  assert.equal(payload.expected_revision, 4);
  assert.equal(payload.scene_beats[0].beat_id, "b1");
  assert.deepEqual(payload.continuity_dependencies, ["第二章已接受"]);
});

test("planning payload rejects malformed structured fields", () => {
  const editor = editorFromEntity("story_bible", {});
  editor.characters = "{}";
  assert.throws(() => planningPayload("story_bible", editor), /必须是 JSON 数组/);
});

test("planning payload rejects zero fixed coordinates before the API call", () => {
  const editor = editorFromEntity("story_arc", {
    volume_number: 0,
    arc_number: 1,
    title: "无效坐标",
  });
  assert.throws(() => planningPayload("story_arc", editor), /卷号必须是大于等于 1 的整数/);
  assert.throws(
    () => plannerGeneratePayload("chapter_plan", { arc_id: "arc-1", chapter_number: 0 }, "生成"),
    /章节号必须是大于等于 1 的整数/,
  );
});

test("planner generation preserves fixed coordinates", () => {
  const arc = plannerGeneratePayload(
    "story_arc",
    { volume_number: 2, arc_number: 5 },
    "生成归航故事弧",
  );
  assert.equal(arc.volume_number, 2);
  assert.equal(arc.arc_number, 5);
  assert.equal(arc.reasoning_effort, "medium");

  const chapter = plannerGeneratePayload(
    "chapter_plan",
    { arc_id: "arc-2", chapter_number: 9 },
    "生成第九章",
  );
  assert.equal(chapter.arc_id, "arc-2");
  assert.equal(chapter.chapter_number, 9);
});

test("planner acceptance reuses candidate coordinates and source revisions", () => {
  const generated = {
    target: "chapter_plan",
    candidate: { arc_id: "arc-original", chapter_number: 12, title: "原始" },
    source_revisions: {
      project_revision: 1,
      story_bible_revision: 2,
      novel_plan_revision: 3,
      story_arc_revision: 4,
    },
  };
  const candidate = { arc_id: "arc-modified", chapter_number: 99, title: "回声" };
  const payload = plannerAcceptPayload(generated, candidate);
  assert.equal(payload.arc_id, "arc-original");
  assert.equal(payload.chapter_number, 12);
  assert.equal(payload.candidate.arc_id, "arc-modified");
  assert.equal(payload.source_revisions.story_arc_revision, 4);
});
