export const PLANNING_TARGETS = Object.freeze({
  story_bible: {
    label: "故事圣经",
    scalars: [],
    lists: [{ key: "themes", label: "主题（每行一项）" }],
    json: [
      { key: "world", label: "世界设定", shape: "object" },
      { key: "characters", label: "角色", shape: "array" },
      { key: "factions", label: "组织", shape: "array" },
      { key: "locations", label: "地点", shape: "array" },
      { key: "rules", label: "规则", shape: "array" },
      { key: "timeline", label: "时间线", shape: "array" },
      { key: "metadata", label: "Metadata", shape: "object" },
    ],
  },
  novel_plan: {
    label: "小说规划",
    scalars: [
      { key: "story_premise", label: "故事前提", rows: 3 },
      { key: "core_conflict", label: "核心冲突", rows: 3 },
      { key: "central_question", label: "中心问题", rows: 2 },
      { key: "ending_direction", label: "结局方向", rows: 3 },
    ],
    lists: [{ key: "themes", label: "主题（每行一项）" }],
    json: [
      { key: "main_plot", label: "主线节拍", shape: "array" },
      { key: "character_arcs", label: "人物弧", shape: "array" },
      { key: "volume_plans", label: "分卷规划", shape: "array" },
      { key: "metadata", label: "Metadata", shape: "object" },
    ],
  },
  story_arc: {
    label: "故事弧",
    scalars: [
      { key: "volume_number", label: "卷号", type: "number", required: true, min: 1 },
      { key: "arc_number", label: "弧号", type: "number", required: true, min: 1 },
      { key: "title", label: "标题", required: true },
      { key: "objective", label: "目标", rows: 2 },
      { key: "summary", label: "摘要", rows: 3 },
      { key: "opening_state", label: "开场状态", rows: 2 },
      { key: "closing_state", label: "结束状态", rows: 2 },
      { key: "core_conflict", label: "核心冲突", rows: 3 },
      { key: "stakes", label: "代价与风险", rows: 2 },
      { key: "target_chapter_start", label: "起始章节", type: "number", nullable: true, min: 1 },
      { key: "target_chapter_end", label: "结束章节", type: "number", nullable: true, min: 1 },
    ],
    lists: [
      { key: "plot_threads", label: "剧情线（每行一项）" },
      { key: "dependencies", label: "依赖（每行一项）" },
    ],
    json: [
      { key: "turning_points", label: "转折点", shape: "array" },
      { key: "character_progression", label: "人物推进", shape: "array" },
      { key: "metadata", label: "Metadata", shape: "object" },
    ],
  },
  chapter_plan: {
    label: "章节规划",
    scalars: [
      { key: "chapter_number", label: "章节号", type: "number", required: true, min: 1 },
      { key: "title", label: "标题", required: true },
      { key: "objective", label: "章节目标", rows: 2 },
      { key: "summary", label: "章节摘要", rows: 3 },
      { key: "pov_character_id", label: "POV 角色 ID", nullable: true },
      { key: "pov_character_name", label: "POV 角色名" },
      { key: "opening_state", label: "开场状态", rows: 2 },
      { key: "closing_state", label: "结束状态", rows: 2 },
      { key: "conflict", label: "冲突", rows: 3 },
      { key: "reveal", label: "揭示", rows: 2 },
      { key: "hook", label: "章末钩子", rows: 2 },
      { key: "target_word_count", label: "目标字数", type: "number" },
    ],
    lists: [{ key: "continuity_dependencies", label: "连续性依赖（每行一项）" }],
    json: [
      { key: "scene_beats", label: "场景节拍", shape: "array" },
      { key: "metadata", label: "Metadata", shape: "object" },
    ],
  },
});

const pretty = (value, fallback) =>
  JSON.stringify(value ?? fallback, null, 2);

export function editorFromEntity(target, entity = {}) {
  const config = PLANNING_TARGETS[target];
  if (!config) throw new Error(`Unknown planning target: ${target}`);
  const result = {};
  config.scalars.forEach(({ key }) => {
    result[key] = entity[key] ?? "";
  });
  config.lists.forEach(({ key }) => {
    result[key] = (entity[key] || []).join("\n");
  });
  config.json.forEach(({ key, shape }) => {
    result[key] = pretty(entity[key], shape === "array" ? [] : {});
  });
  if (target === "chapter_plan") result.arc_id = entity.arc_id || "";
  return result;
}

function parseJson(value, label, shape) {
  let parsed;
  try {
    parsed = JSON.parse(value || (shape === "array" ? "[]" : "{}"));
  } catch (error) {
    throw new Error(`${label}不是有效 JSON：${error.message}`);
  }
  if (shape === "array" && !Array.isArray(parsed)) {
    throw new Error(`${label}必须是 JSON 数组`);
  }
  if (shape === "object" && (Array.isArray(parsed) || !parsed || typeof parsed !== "object")) {
    throw new Error(`${label}必须是 JSON 对象`);
  }
  return parsed;
}

export function planningPayload(target, editor, { revision = null } = {}) {
  const config = PLANNING_TARGETS[target];
  if (!config) throw new Error(`Unknown planning target: ${target}`);
  const payload = {};
  config.scalars.forEach(({ key, label, type, required, nullable, min = 0 }) => {
    const raw = editor[key];
    if (required && (raw === "" || raw === null || raw === undefined)) {
      throw new Error(`请填写${label}`);
    }
    if (type === "number") {
      if (raw === "" || raw === null || raw === undefined) {
        payload[key] = nullable ? null : 0;
      } else {
        const number = Number(raw);
        if (!Number.isInteger(number) || number < min) {
          throw new Error(`${label}必须是大于等于 ${min} 的整数`);
        }
        payload[key] = number;
      }
    } else {
      payload[key] = nullable && !String(raw || "").trim() ? null : String(raw || "").trim();
    }
  });
  config.lists.forEach(({ key }) => {
    payload[key] = String(editor[key] || "")
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
  });
  config.json.forEach(({ key, label, shape }) => {
    payload[key] = parseJson(editor[key], label, shape);
  });
  if (target === "chapter_plan") {
    if (!editor.arc_id) throw new Error("请选择 Story Arc");
    payload.arc_id = editor.arc_id;
  }
  if (revision !== null) payload.expected_revision = revision;
  return payload;
}

export function plannerGeneratePayload(target, editor, instruction) {
  const payload = {
    target,
    instruction: String(instruction || "").trim(),
    provider: "qwen_local",
    model: "qwen3:8b",
    use_memory: true,
    reasoning_effort: "medium",
    temperature: 0.2,
    max_tokens: 2600,
  };
  if (!payload.instruction) throw new Error("请填写 Planner 指令");
  if (target === "story_arc") {
    payload.volume_number = Number(editor.volume_number);
    payload.arc_number = Number(editor.arc_number);
    if (!Number.isInteger(payload.volume_number) || payload.volume_number < 1) {
      throw new Error("卷号必须是大于等于 1 的整数");
    }
    if (!Number.isInteger(payload.arc_number) || payload.arc_number < 1) {
      throw new Error("弧号必须是大于等于 1 的整数");
    }
  }
  if (target === "chapter_plan") {
    if (!editor.arc_id) throw new Error("请选择 Story Arc");
    payload.arc_id = editor.arc_id;
    payload.chapter_number = Number(editor.chapter_number);
    if (!Number.isInteger(payload.chapter_number) || payload.chapter_number < 1) {
      throw new Error("章节号必须是大于等于 1 的整数");
    }
  }
  return payload;
}

export function plannerAcceptPayload(generated, candidate) {
  const payload = {
    target: generated.target,
    candidate,
    source_revisions: generated.source_revisions,
  };
  if (generated.target === "story_arc") {
    payload.volume_number = generated.candidate.volume_number;
    payload.arc_number = generated.candidate.arc_number;
  }
  if (generated.target === "chapter_plan") {
    payload.arc_id = generated.candidate.arc_id;
    payload.chapter_number = generated.candidate.chapter_number;
  }
  return payload;
}
