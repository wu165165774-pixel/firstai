export const STATUS_LABELS = Object.freeze({
  planning: "规划中",
  writing: "写作中",
  archived: "已归档",
  drafting: "写作中",
  paused: "已暂停",
  completed: "已完成",
  ready: "就绪",
  waiting_for_workflow: "生成中",
  waiting_for_acceptance: "待接受",
  failed: "失败",
  queued: "排队中",
  running: "运行中",
  retrying: "重试中",
  succeeded: "已通过",
  resumable: "可恢复",
  dead_letter: "死信",
  cancelled: "已取消",
  pending: "待处理",
  processing: "处理中",
});

export function statusLabel(value) {
  return STATUS_LABELS[value] || value || "未知";
}

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function progressPercent(accepted, total) {
  if (!total) return 0;
  return Math.min(100, Math.round((accepted / total) * 100));
}

export function pipelineStages(workspace) {
  const project = workspace.project;
  const bible = workspace.bible;
  const plan = workspace.plan;
  const arcs = workspace.arcs || [];
  const chapters = workspace.chapterPlans || [];
  const manuscripts = workspace.manuscripts || [];
  const freshArcs = arcs.filter((item) => !item.is_stale).length;
  const freshChapters = chapters.filter((item) => !item.is_stale).length;
  const accepted = manuscripts.filter((item) => item.accepted_revision).length;
  return [
    {
      key: "project",
      index: "01",
      title: "创作项目",
      detail: project ? `r${project.revision} · ${project.genre || "未设类型"}` : "尚未建立",
      state: project ? "ready" : "empty",
    },
    {
      key: "bible",
      index: "02",
      title: "故事圣经",
      detail: bible ? `r${bible.revision} · ${bible.characters?.length || 0} 位角色` : "尚未建立",
      state: bible ? "ready" : "empty",
    },
    {
      key: "plan",
      index: "03",
      title: "小说规划",
      detail: plan ? `r${plan.revision}${plan.is_stale ? " · 已过期" : " · 新鲜"}` : "尚未建立",
      state: !plan ? "empty" : plan.is_stale ? "warning" : "ready",
    },
    {
      key: "arcs",
      index: "04",
      title: "故事弧",
      detail: `${freshArcs}/${arcs.length} 个可用`,
      state: freshArcs ? "ready" : arcs.length ? "warning" : "empty",
    },
    {
      key: "chapters",
      index: "05",
      title: "章节规划",
      detail: `${freshChapters}/${chapters.length} 章可生产`,
      state: freshChapters ? "ready" : chapters.length ? "warning" : "empty",
    },
    {
      key: "manuscript",
      index: "06",
      title: "正式正文",
      detail: `${accepted}/${manuscripts.length} 章已接受`,
      state: accepted ? "ready" : manuscripts.length ? "warning" : "empty",
    },
  ];
}

export function latestApprovedRevision(revisions) {
  return [...(revisions || [])]
    .filter((item) => item.review_status === "approved")
    .sort((left, right) => right.revision - left.revision)[0] || null;
}

export function canImportWorkflow(run) {
  return Boolean(
    run &&
      run.execution_status === "succeeded" &&
      run.workflow_status === "completed" &&
      run.quality_gate_passed,
  );
}

export function projectionTone(status) {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "processing") return "active";
  return "warning";
}

export function chapterTitle(chapter, chapterPlans) {
  const plan = (chapterPlans || []).find(
    (item) => item.chapter_plan_id === chapter?.chapter_plan_id,
  );
  return plan?.title || `第 ${chapter?.chapter_number || "—"} 章`;
}
