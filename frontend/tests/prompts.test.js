import assert from "node:assert/strict";
import test from "node:test";

import { promptRevisionSummary } from "../src/lib/prompts.js";


test("prompt revision summary is sorted and deduplicated", () => {
  const summary = promptRevisionSummary(
    {
      prompt_provenance: [
        { prompt_id: "agent.review.request", revision: 2 },
        { prompt_id: "agent.review.system", revision: 1 },
      ],
    },
    {
      prompt_provenance: [
        { prompt_id: "agent.review.request", revision: 2 },
      ],
    },
  );
  assert.equal(
    summary,
    "agent.review.request@r2 · agent.review.system@r1",
  );
});


test("prompt revision summary ignores malformed client metadata", () => {
  assert.equal(
    promptRevisionSummary(
      { prompt_provenance: [{ prompt_id: "forged", revision: 0 }] },
      null,
    ),
    "",
  );
});
