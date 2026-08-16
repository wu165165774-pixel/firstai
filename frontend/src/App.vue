<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";

import PlanningStudio from "./components/PlanningStudio.vue";
import { ApiError, api, getAccessToken, setAccessToken } from "./lib/api.js";
import { promptRevisionSummary } from "./lib/prompts.js";
import {
  canImportWorkflow,
  chapterTitle,
  formatDate,
  latestApprovedRevision,
  pipelineStages,
  progressPercent,
  projectionTone,
  statusLabel,
} from "./lib/workspace.js";

const navItems = [
  { key: "overview", label: "创作总览", mark: "总" },
  { key: "planning", label: "规划工作台", mark: "策" },
  { key: "production", label: "章节生产", mark: "写" },
  { key: "manuscript", label: "正文审核", mark: "审" },
];

const userId = ref(localStorage.getItem("novelforge.userId") || "");
const accessToken = ref(getAccessToken());
const activeView = ref("overview");
const projects = ref([]);
const selectedNovelId = ref(localStorage.getItem("novelforge.novelId") || "");
const projectFilter = ref("");
const loadingProjects = ref(false);
const loadingWorkspace = ref(false);
const actionBusy = ref("");
const engineStatus = ref("checking");
const providerCatalog = ref([]);
const notice = reactive({ message: "", tone: "info" });
const createOpen = ref(false);
const createForm = reactive({ title: "", genre: "", premise: "" });
const workflowOpen = ref(false);
const workflowForm = reactive({
  chapter_plan_id: "",
  instruction: "",
  provider: "qwen_local",
  model: "qwen3:8b",
  auto_rewrite: true,
  max_revision_rounds: 2,
  minimum_overall_score: 80,
  priority: 0,
  idempotency_key: "",
});

const workspace = reactive({
  project: null,
  bible: null,
  plan: null,
  arcs: [],
  chapterPlans: [],
  workflows: [],
  manuscripts: [],
  orchestrations: [],
});

const selectedRun = ref(null);
const selectedChapterId = ref("");
const manuscriptDetail = ref(null);
const manuscriptRevisions = ref([]);
const selectedRevisionNumber = ref(null);
const projection = ref(null);

const selectedProject = computed(() =>
  projects.value.find((item) => item.novel_id === selectedNovelId.value),
);
const filteredProjects = computed(() => {
  const term = projectFilter.value.trim().toLocaleLowerCase();
  if (!term) return projects.value;
  return projects.value.filter((item) =>
    [item.title, item.genre, item.premise]
      .join(" ")
      .toLocaleLowerCase()
      .includes(term),
  );
});
const stages = computed(() => pipelineStages(workspace));
const acceptedCount = computed(
  () => workspace.manuscripts.filter((item) => item.accepted_revision).length,
);
const productionProgress = computed(() =>
  progressPercent(acceptedCount.value, workspace.chapterPlans.length),
);
const readyWorkflowCount = computed(
  () => workspace.workflows.filter(canImportWorkflow).length,
);
const staleCount = computed(
  () =>
    Number(Boolean(workspace.plan?.is_stale)) +
    workspace.arcs.filter((item) => item.is_stale).length +
    workspace.chapterPlans.filter((item) => item.is_stale).length,
);
const currentRevision = computed(() =>
  manuscriptRevisions.value.find(
    (item) => item.revision === selectedRevisionNumber.value,
  ),
);
const approvedRevision = computed(() =>
  latestApprovedRevision(manuscriptRevisions.value),
);
const selectedProvider = computed(() =>
  providerCatalog.value.find((item) => item.name === workflowForm.provider),
);
const selectedRunPromptRevisions = computed(() =>
  promptRevisionSummary(
    ...(selectedRun.value?.result?.workflow_steps || []).map(
      (step) => step.metadata,
    ),
  ),
);

function announce(message, tone = "info") {
  notice.message = message;
  notice.tone = tone;
  window.clearTimeout(announce.timer);
  announce.timer = window.setTimeout(() => (notice.message = ""), 5200);
}

function explainError(error) {
  if (error instanceof ApiError) {
    announce(error.message, error.status >= 500 ? "danger" : "warning");
  } else {
    announce(error?.message || "发生未知错误", "danger");
  }
}

async function probeEngine() {
  engineStatus.value = "checking";
  try {
    await api.health();
    engineStatus.value = "online";
  } catch {
    engineStatus.value = "offline";
  }
}

async function loadProviderCatalog({ probe = true } = {}) {
  try {
    const result = await api.listProviders({ probe, timeoutMs: 3000 });
    providerCatalog.value = result.catalog || [];
    const current = providerCatalog.value.find(
      (item) => item.name === workflowForm.provider && item.configured,
    );
    const fallback =
      current || providerCatalog.value.find((item) => item.configured);
    if (fallback) {
      workflowForm.provider = fallback.name;
      if (!fallback.supported_models.includes(workflowForm.model)) {
        workflowForm.model = fallback.default_model || fallback.supported_models[0] || "";
      }
    }
  } catch {
    providerCatalog.value = [];
  }
}

async function loadProjects({ keepSelection = true } = {}) {
  const identity = userId.value.trim();
  if (!identity) {
    projects.value = [];
    selectedNovelId.value = "";
    return;
  }
  loadingProjects.value = true;
  try {
    projects.value = await api.listProjects(identity);
    if (
      !keepSelection ||
      !projects.value.some((item) => item.novel_id === selectedNovelId.value)
    ) {
      selectedNovelId.value = projects.value[0]?.novel_id || "";
    }
  } catch (error) {
    explainError(error);
  } finally {
    loadingProjects.value = false;
  }
}

async function reloadLibrary() {
  await loadProjects({ keepSelection: false });
  if (selectedNovelId.value) {
    localStorage.setItem("novelforge.novelId", selectedNovelId.value);
    await loadWorkspace();
    return;
  }
  localStorage.removeItem("novelforge.novelId");
  Object.assign(workspace, {
    project: null,
    bible: null,
    plan: null,
    arcs: [],
    chapterPlans: [],
    workflows: [],
    manuscripts: [],
    orchestrations: [],
  });
}

async function connectIdentity() {
  setAccessToken(accessToken.value);
  try {
    const identity = await api.identity();
    if (identity.authenticated && identity.user_id) {
      userId.value = identity.user_id;
    }
    await loadProviderCatalog();
    await reloadLibrary();
    announce(
      identity.authenticated ? `已认证为 ${identity.user_id}` : "开发模式：未启用后端鉴权",
      "success",
    );
  } catch (error) {
    explainError(error);
  }
}

async function loadWorkspace() {
  if (!selectedNovelId.value) return;
  void probeEngine();
  loadingWorkspace.value = true;
  selectedRun.value = null;
  try {
    const novelId = selectedNovelId.value;
    const [project, bible, plan, arcs, chapterPlans, workflows, manuscripts, orchestrations] =
      await Promise.all([
        api.getProject(novelId),
        api.getBible(novelId),
        api.getPlan(novelId),
        api.listArcs(novelId),
        api.listChapterPlans(novelId),
        api.listWorkflows(novelId),
        api.listManuscripts(novelId),
        api.listOrchestrations(novelId),
      ]);
    Object.assign(workspace, {
      project,
      bible,
      plan,
      arcs,
      chapterPlans,
      workflows,
      manuscripts,
      orchestrations,
    });
    if (
      selectedChapterId.value &&
      !manuscripts.some(
        (item) => item.manuscript_chapter_id === selectedChapterId.value,
      )
    ) {
      selectedChapterId.value = "";
      manuscriptDetail.value = null;
      manuscriptRevisions.value = [];
      projection.value = null;
    }
  } catch (error) {
    explainError(error);
  } finally {
    loadingWorkspace.value = false;
  }
}

async function exportNovel() {
  if (!selectedNovelId.value) return;
  actionBusy.value = "export";
  try {
    const result = await api.exportNovel(selectedNovelId.value);
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = result.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    announce(
      `已导出 ${result.acceptedChapterCount} 章接受正文与当前规划`,
      "success",
    );
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

async function selectProject(novelId) {
  selectedNovelId.value = novelId;
  localStorage.setItem("novelforge.novelId", novelId);
  await loadWorkspace();
}

async function createProject() {
  if (!userId.value.trim() || !createForm.title.trim()) {
    announce("请填写创作者 ID 与项目名称", "warning");
    return;
  }
  actionBusy.value = "create-project";
  try {
    const created = await api.createProject({
      user_id: userId.value.trim(),
      title: createForm.title.trim(),
      genre: createForm.genre.trim(),
      premise: createForm.premise.trim(),
    });
    createOpen.value = false;
    Object.assign(createForm, { title: "", genre: "", premise: "" });
    await loadProjects({ keepSelection: false });
    await selectProject(created.novel_id);
    announce("新项目已建立，可以开始完善故事圣经", "success");
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

async function inspectRun(run) {
  actionBusy.value = `run:${run.run_id}`;
  try {
    selectedRun.value = await api.getWorkflow(run.run_id);
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

async function importRun(run) {
  actionBusy.value = `import:${run.run_id}`;
  try {
    const detail =
      selectedRun.value?.run_id === run.run_id
        ? selectedRun.value
        : await api.getWorkflow(run.run_id);
    const existingChapter = workspace.manuscripts.find(
      (item) => item.chapter_plan_id === detail.request.chapter_plan_id,
    );
    const result = await api.importWorkflow(
      selectedNovelId.value,
      run.run_id,
      existingChapter?.revision ?? null,
    );
    await loadWorkspace();
    activeView.value = "manuscript";
    await openManuscript(result.chapter.manuscript_chapter_id);
    announce(result.deduplicated ? "该运行已导入，已打开正文" : "候选正文已导入", "success");
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

async function openManuscript(chapterId) {
  selectedChapterId.value = chapterId;
  actionBusy.value = `chapter:${chapterId}`;
  projection.value = null;
  try {
    const [detail, revisions] = await Promise.all([
      api.getManuscript(selectedNovelId.value, chapterId),
      api.listRevisions(selectedNovelId.value, chapterId),
    ]);
    manuscriptDetail.value = detail;
    manuscriptRevisions.value = revisions;
    selectedRevisionNumber.value =
      latestApprovedRevision(revisions)?.revision ||
      detail.chapter.accepted_revision ||
      revisions[0]?.revision ||
      null;
    if (selectedRevisionNumber.value) await loadProjection();
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

async function loadProjection() {
  if (!selectedChapterId.value || !selectedRevisionNumber.value) return;
  try {
    projection.value = await api.getProjection(
      selectedNovelId.value,
      selectedChapterId.value,
      selectedRevisionNumber.value,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      projection.value = null;
      return;
    }
    explainError(error);
  }
}

async function acceptCurrentRevision() {
  if (!currentRevision.value || !manuscriptDetail.value) return;
  actionBusy.value = "accept";
  try {
    const result = await api.acceptRevision(
      selectedNovelId.value,
      selectedChapterId.value,
      currentRevision.value.revision,
      manuscriptDetail.value.chapter.revision,
    );
    projection.value = result.fact_projection;
    await loadWorkspace();
    await openManuscript(selectedChapterId.value);
    announce(result.changed ? "正文已接受，事实投影已启动" : "该修订已是接受版本", "success");
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

async function retryProjection() {
  actionBusy.value = "retry-projection";
  try {
    projection.value = await api.retryProjection(
      selectedNovelId.value,
      selectedChapterId.value,
      selectedRevisionNumber.value,
    );
    announce(
      projection.value.status === "completed" ? "事实投影已完成" : "已提交重试",
      projection.value.status === "completed" ? "success" : "info",
    );
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

async function createOrchestration() {
  if (!workspace.chapterPlans.length || workspace.plan?.is_stale) {
    announce("需要 fresh Novel Plan 和 Chapter Plan 才能启动生产", "warning");
    return;
  }
  actionBusy.value = "create-orchestration";
  try {
    await api.createOrchestration(
      selectedNovelId.value,
      { user_id: workspace.project.user_id },
      `workbench:${selectedNovelId.value}:${Date.now()}`,
    );
    await loadWorkspace();
    announce("全小说生产任务已建立", "success");
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

function openWorkflowComposer() {
  const plan = workspace.chapterPlans.find((item) => !item.is_stale);
  workflowForm.chapter_plan_id = plan?.chapter_plan_id || "";
  workflowForm.instruction = plan
    ? `按已接受的第 ${plan.chapter_number} 章规划《${plan.title}》写出完整正文，并承接此前已接受正文。`
    : "";
  workflowForm.idempotency_key = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  workflowOpen.value = true;
}

async function enqueueChapterWorkflow() {
  const plan = workspace.chapterPlans.find(
    (item) => item.chapter_plan_id === workflowForm.chapter_plan_id,
  );
  if (!plan || plan.is_stale) {
    announce("请选择 fresh Chapter Plan", "warning");
    return;
  }
  actionBusy.value = "enqueue-workflow";
  try {
    const submission = await api.enqueueWorkflow(
      {
        user_id: workspace.project.user_id,
        novel_id: selectedNovelId.value,
        instruction: workflowForm.instruction.trim(),
        chapter_plan_id: plan.chapter_plan_id,
        chapter_plan_revision: plan.revision,
        provider: workflowForm.provider,
        model: workflowForm.model,
        use_memory: true,
        auto_rewrite: workflowForm.auto_rewrite,
        max_revision_rounds: Number(workflowForm.max_revision_rounds),
        minimum_overall_score: Number(workflowForm.minimum_overall_score),
      },
      {
        idempotencyKey: `workbench:${selectedNovelId.value}:${plan.chapter_plan_id}:${workflowForm.idempotency_key}`,
        priority: Number(workflowForm.priority),
      },
    );
    workflowOpen.value = false;
    await loadWorkspace();
    selectedRun.value = submission.run;
    announce(
      submission.deduplicated ? "相同 Workflow 已在队列中" : "章节 Workflow 已进入队列",
      "success",
    );
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

function relayNotice(payload) {
  announce(payload.message, payload.tone);
}

async function controlOrchestration(item, action) {
  actionBusy.value = `${action}:${item.orchestration_id}`;
  try {
    await api.controlOrchestration(
      selectedNovelId.value,
      item.orchestration_id,
      action,
      item.revision,
    );
    await loadWorkspace();
    const actionLabels = { pause: "暂停", resume: "恢复", retry: "重试", advance: "推进" };
    announce(`生产任务已${actionLabels[action] || action}`, "success");
  } catch (error) {
    explainError(error);
  } finally {
    actionBusy.value = "";
  }
}

watch(userId, (value) => localStorage.setItem("novelforge.userId", value.trim()));
watch(selectedRevisionNumber, () => loadProjection());
watch(
  () => workflowForm.provider,
  (name) => {
    const provider = providerCatalog.value.find((item) => item.name === name);
    if (
      provider &&
      !provider.supported_models.includes(workflowForm.model)
    ) {
      workflowForm.model =
        provider.default_model || provider.supported_models[0] || "";
    }
  },
);

onMounted(async () => {
  await Promise.all([probeEngine(), loadProviderCatalog()]);
  await loadProjects();
  if (selectedNovelId.value) await loadWorkspace();
});
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand-row">
        <div class="brand-seal">NF</div>
        <div>
          <strong>NovelForge</strong>
          <span>长篇创作系统</span>
        </div>
      </div>

      <nav class="primary-nav" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.key"
          type="button"
          :class="{ active: activeView === item.key }"
          @click="activeView = item.key"
        >
          <span class="nav-mark">{{ item.mark }}</span>
          {{ item.label }}
        </button>
      </nav>

      <div class="library-head">
        <span>项目库</span>
        <button type="button" class="icon-button" title="新建项目" @click="createOpen = true">＋</button>
      </div>
      <label class="search-box">
        <span>⌕</span>
        <input v-model="projectFilter" placeholder="搜索项目" />
      </label>
      <div class="project-list" :class="{ muted: loadingProjects }">
        <button
          v-for="item in filteredProjects"
          :key="item.novel_id"
          type="button"
          class="project-item"
          :class="{ active: item.novel_id === selectedNovelId }"
          @click="selectProject(item.novel_id)"
        >
          <span class="project-glyph">{{ item.title.slice(0, 1) }}</span>
          <span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.genre || "未设类型" }} · r{{ item.revision }}</small>
          </span>
        </button>
        <p v-if="!filteredProjects.length" class="empty-copy">
          {{ userId ? "还没有项目" : "填写创作者 ID 后加载项目" }}
        </p>
      </div>

      <div class="identity-card">
        <label for="user-id">创作者 ID</label>
        <div class="identity-input">
          <input id="user-id" v-model="userId" placeholder="user_id" @keyup.enter="connectIdentity" />
        </div>
        <label for="access-token">访问令牌（仅当前浏览器会话）</label>
        <div class="identity-input">
          <input id="access-token" v-model="accessToken" type="password" autocomplete="current-password" placeholder="Bearer token；开发模式可留空" @keyup.enter="connectIdentity" />
          <button type="button" @click="connectIdentity">连接</button>
        </div>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ activeView === "overview" ? "STORY OPERATIONS" : activeView === "planning" ? "PLANNING STUDIO" : activeView === "production" ? "CHAPTER PRODUCTION" : "MANUSCRIPT REVIEW" }}</p>
          <h1>{{ workspace.project?.title || "选择或建立一个创作项目" }}</h1>
        </div>
        <div class="topbar-actions">
          <span :class="['connection-pill', engineStatus]"><i></i> {{ engineStatus === "online" ? "本地引擎在线" : engineStatus === "offline" ? "本地引擎离线" : "检测本地引擎" }}</span>
          <button type="button" class="quiet-button" :disabled="actionBusy === 'export' || !selectedNovelId" @click="exportNovel">
            {{ actionBusy === "export" ? "导出中…" : "导出小说" }}
          </button>
          <button type="button" class="quiet-button" :disabled="loadingWorkspace" @click="loadWorkspace">
            {{ loadingWorkspace ? "同步中…" : "同步数据" }}
          </button>
        </div>
      </header>

      <section v-if="!selectedNovelId" class="welcome-panel">
        <div class="welcome-copy">
          <p class="eyebrow">LOCAL-FIRST NOVEL STUDIO</p>
          <h2>把宏大故事，拆成每一步都可验证的生产链。</h2>
          <p>从故事圣经到正式正文，每次生成都保留来源、修订与人工接受边界。</p>
          <button type="button" class="primary-button" @click="createOpen = true">建立第一个项目</button>
        </div>
        <div class="welcome-orbit" aria-hidden="true">
          <span>构思</span><span>规划</span><span>写作</span><span>审核</span>
          <strong>NF</strong>
        </div>
      </section>

      <PlanningStudio
        v-else-if="activeView === 'planning'"
        :novel-id="selectedNovelId"
        :workspace="workspace"
        @notice="relayNotice"
        @refresh="loadWorkspace"
      />

      <template v-else-if="activeView === 'overview'">
        <section class="hero-grid">
          <article class="story-hero">
            <p class="eyebrow">当前创作意图</p>
            <h2>{{ workspace.project?.premise || "还没有填写故事前提" }}</h2>
            <div class="hero-meta">
              <span>{{ workspace.project?.genre || "类型待定" }}</span>
              <span>{{ workspace.project?.language || "zh-CN" }}</span>
              <span>{{ workspace.project?.target_word_count?.toLocaleString() || 0 }} 字目标</span>
            </div>
          </article>
          <article class="progress-card">
            <div class="ring" :style="{ '--progress': `${productionProgress * 3.6}deg` }">
              <span><strong>{{ productionProgress }}</strong>%</span>
            </div>
            <div>
              <p class="eyebrow">正文推进</p>
              <h3>{{ acceptedCount }} / {{ workspace.chapterPlans.length }} 章已接受</h3>
              <p>{{ readyWorkflowCount }} 个 Workflow 可导入，{{ staleCount }} 个规划对象需要刷新。</p>
            </div>
          </article>
        </section>

        <section class="section-block">
          <div class="section-heading">
            <div><p class="eyebrow">AUTHORITATIVE CHAIN</p><h2>故事生产链</h2></div>
            <span>每一步均绑定精确 revision</span>
          </div>
          <div class="pipeline">
            <article v-for="stage in stages" :key="stage.key" :class="['pipeline-stage', stage.state]">
              <span class="stage-index">{{ stage.index }}</span>
              <i></i>
              <h3>{{ stage.title }}</h3>
              <p>{{ stage.detail }}</p>
            </article>
          </div>
        </section>

        <section class="overview-columns">
          <article class="panel arc-panel">
            <div class="panel-heading"><div><p class="eyebrow">STORY ARCS</p><h2>故事弧</h2></div><span>{{ workspace.arcs.length }}</span></div>
            <div v-if="workspace.arcs.length" class="arc-list">
              <div v-for="arc in workspace.arcs.slice(0, 6)" :key="arc.arc_id" class="arc-row">
                <span class="arc-coordinate">V{{ arc.volume_number }} · A{{ arc.arc_number }}</span>
                <div><strong>{{ arc.title }}</strong><p>{{ arc.objective || arc.summary || "尚未填写目标" }}</p></div>
                <span :class="['status-dot', arc.is_stale ? 'warning' : 'success']">{{ arc.is_stale ? "过期" : `r${arc.revision}` }}</span>
              </div>
            </div>
            <p v-else class="panel-empty">尚未创建故事弧。</p>
          </article>

          <article class="panel pulse-panel">
            <div class="panel-heading"><div><p class="eyebrow">LIVE PULSE</p><h2>生产脉搏</h2></div><span>{{ workspace.workflows.length }}</span></div>
            <div class="metric-grid">
              <div><strong>{{ workspace.chapterPlans.length }}</strong><span>章节规划</span></div>
              <div><strong>{{ workspace.workflows.length }}</strong><span>生成运行</span></div>
              <div><strong>{{ workspace.manuscripts.length }}</strong><span>正文聚合</span></div>
              <div><strong>{{ workspace.orchestrations.length }}</strong><span>全书任务</span></div>
            </div>
            <div class="recent-run" v-for="run in workspace.workflows.slice(0, 3)" :key="run.run_id">
              <span :class="['run-signal', run.execution_status]"></span>
              <div><strong>{{ statusLabel(run.execution_status) }}</strong><small>{{ formatDate(run.updated_at) }} · {{ run.latest_content_length }} 字</small></div>
            </div>
          </article>
        </section>
      </template>

      <template v-else-if="activeView === 'production'">
        <section class="production-head">
          <div><p class="eyebrow">ORCHESTRATION</p><h2>章节生产控制台</h2><p>按冻结的章节规划顺序生成，每一章都等待人工接受。</p></div>
          <div class="production-actions">
            <button type="button" class="quiet-button" :disabled="actionBusy || !workspace.chapterPlans.length" @click="openWorkflowComposer">创建单章 Workflow</button>
            <button type="button" class="primary-button" :disabled="actionBusy || !workspace.chapterPlans.length" @click="createOrchestration">启动全书生产</button>
          </div>
        </section>

        <section class="production-layout">
          <div class="production-main">
            <article class="panel">
              <div class="panel-heading"><div><p class="eyebrow">CHAPTER MAP</p><h2>章节地图</h2></div><span>{{ workspace.chapterPlans.length }}</span></div>
              <div class="chapter-map">
                <div v-for="chapter in workspace.chapterPlans" :key="chapter.chapter_plan_id" :class="['chapter-card', { stale: chapter.is_stale }]">
                  <span class="chapter-number">{{ String(chapter.chapter_number).padStart(2, "0") }}</span>
                  <div><strong>{{ chapter.title }}</strong><p>{{ chapter.objective || chapter.summary || "目标待补充" }}</p><small>r{{ chapter.revision }} · {{ chapter.target_word_count || 0 }} 字</small></div>
                  <span class="chapter-state">{{ chapter.is_stale ? "需刷新" : "可生产" }}</span>
                </div>
                <p v-if="!workspace.chapterPlans.length" class="panel-empty">先完成 Novel Plan、Story Arc 与 Chapter Plan。</p>
              </div>
            </article>

            <article class="panel">
              <div class="panel-heading"><div><p class="eyebrow">WORKFLOW RUNS</p><h2>生成运行</h2></div><span>{{ readyWorkflowCount }} 可导入</span></div>
              <div class="run-table">
                <div class="run-row header"><span>状态</span><span>运行</span><span>质量</span><span>更新时间</span><span></span></div>
                <div v-for="run in workspace.workflows" :key="run.run_id" class="run-row">
                  <span><b :class="['status-chip', run.execution_status]">{{ statusLabel(run.execution_status) }}</b></span>
                  <span><button type="button" class="link-button" @click="inspectRun(run)">{{ run.run_id.slice(0, 8) }}</button><small>{{ run.latest_content_length }} 字</small></span>
                  <span>{{ run.quality_gate_passed ? "通过" : "未通过" }}<small>{{ run.revision_rounds }} 轮修订</small></span>
                  <span>{{ formatDate(run.updated_at) }}</span>
                  <span><button v-if="canImportWorkflow(run)" type="button" class="small-button" :disabled="actionBusy" @click="importRun(run)">导入正文</button></span>
                </div>
                <p v-if="!workspace.workflows.length" class="panel-empty">还没有章节 Workflow。</p>
              </div>
            </article>
          </div>

          <aside class="production-side">
            <article class="panel orchestrator-card">
              <div class="panel-heading"><div><p class="eyebrow">BOOK RUNS</p><h2>全书任务</h2></div></div>
              <div v-for="item in workspace.orchestrations" :key="item.orchestration_id" class="orchestration-item">
                <div><b :class="['status-chip', item.status]">{{ statusLabel(item.status) }}</b><small>r{{ item.revision }}</small></div>
                <strong>{{ item.accepted_chapters }} / {{ item.total_chapters }} 章</strong>
                <div class="mini-progress"><i :style="{ width: `${progressPercent(item.accepted_chapters, item.total_chapters)}%` }"></i></div>
                <div class="button-row">
                  <button v-if="item.status === 'paused'" type="button" :disabled="actionBusy" @click="controlOrchestration(item, 'resume')">恢复</button>
                  <button v-else-if="!['completed', 'failed'].includes(item.status)" type="button" :disabled="actionBusy" @click="controlOrchestration(item, 'pause')">暂停</button>
                  <button v-if="item.status === 'failed'" type="button" :disabled="actionBusy" @click="controlOrchestration(item, 'retry')">重试</button>
                  <button v-if="['ready', 'waiting_for_acceptance'].includes(item.status)" type="button" :disabled="actionBusy" @click="controlOrchestration(item, 'advance')">推进</button>
                </div>
              </div>
              <p v-if="!workspace.orchestrations.length" class="panel-empty">尚未启动全书生产任务。</p>
            </article>

            <article v-if="selectedRun" class="panel run-inspector">
              <p class="eyebrow">RUN INSPECTOR</p>
              <h2>{{ selectedRun.run_id.slice(0, 12) }}</h2>
              <p>{{ selectedRun.result?.review_report?.summary || selectedRun.error || "运行详情" }}</p>
              <dl><div><dt>状态</dt><dd>{{ statusLabel(selectedRun.execution_status) }}</dd></div><div><dt>质量分</dt><dd>{{ selectedRun.result?.quality_scores?.overall ?? "—" }}</dd></div><div><dt>事实候选</dt><dd>{{ selectedRun.result?.review_report?.candidate_facts?.length || 0 }}</dd></div><div><dt>总 tokens</dt><dd>{{ selectedRun.result?.usage?.total_tokens || 0 }}</dd></div></dl>
              <small v-if="selectedRunPromptRevisions">Prompt {{ selectedRunPromptRevisions }}</small>
            </article>
          </aside>
        </section>
      </template>

      <template v-else>
        <section class="manuscript-layout">
          <aside class="manuscript-index panel">
            <div class="panel-heading"><div><p class="eyebrow">MANUSCRIPT</p><h2>正文目录</h2></div><span>{{ acceptedCount }}/{{ workspace.manuscripts.length }}</span></div>
            <button
              v-for="chapter in workspace.manuscripts"
              :key="chapter.manuscript_chapter_id"
              type="button"
              :class="['manuscript-link', { active: selectedChapterId === chapter.manuscript_chapter_id }]"
              @click="openManuscript(chapter.manuscript_chapter_id)"
            >
              <span>{{ String(chapter.chapter_number).padStart(2, "0") }}</span>
              <div><strong>{{ chapterTitle(chapter, workspace.chapterPlans) }}</strong><small>{{ chapter.accepted_revision ? `已接受 r${chapter.accepted_revision}` : "等待接受" }}</small></div>
              <i :class="chapter.accepted_revision ? 'accepted' : ''"></i>
            </button>
            <p v-if="!workspace.manuscripts.length" class="panel-empty">从“章节生产”导入通过质量门的 Workflow。</p>
          </aside>

          <section class="manuscript-reader panel">
            <template v-if="currentRevision">
              <div class="reader-head">
                <div><p class="eyebrow">REVISION {{ currentRevision.revision }}</p><h2>{{ chapterTitle(manuscriptDetail.chapter, workspace.chapterPlans) }}</h2><p>{{ currentRevision.review_summary || "已审核候选正文" }}</p></div>
                <div class="revision-actions">
                  <select v-model.number="selectedRevisionNumber" aria-label="选择正文修订">
                    <option v-for="item in manuscriptRevisions" :key="item.revision" :value="item.revision">r{{ item.revision }} · {{ item.review_status === "approved" ? "已批准" : "已取代" }}</option>
                  </select>
                  <button type="button" class="primary-button" :disabled="actionBusy || currentRevision.is_accepted || currentRevision.review_status !== 'approved'" @click="acceptCurrentRevision">
                    {{ currentRevision.is_accepted ? "已接受" : "接受此修订" }}
                  </button>
                </div>
              </div>
              <div class="quality-strip">
                <span v-for="(value, key) in currentRevision.quality_scores" :key="key"><small>{{ key.replaceAll("_", " ") }}</small><strong>{{ value }}</strong></span>
              </div>
              <article class="chapter-content">{{ currentRevision.content }}</article>
            </template>
            <div v-else class="reader-empty"><span>稿</span><h2>选择一章开始审核</h2><p>正文内容、质量评分、候选事实与接受动作会在这里显示。</p></div>
          </section>

          <aside class="fact-panel panel">
            <template v-if="currentRevision">
              <div class="panel-heading"><div><p class="eyebrow">FACT PROJECTION</p><h2>事实回写</h2></div><b :class="['status-chip', projectionTone(projection?.status)]">{{ projection ? statusLabel(projection.status) : "未触发" }}</b></div>
              <div class="fact-summary"><div><strong>{{ currentRevision.candidate_facts.length }}</strong><span>冻结事实</span></div><div><strong>{{ projection?.completed_count || 0 }}</strong><span>已完成</span></div><div><strong>{{ projection?.failed_count || 0 }}</strong><span>失败</span></div></div>
              <article v-for="fact in currentRevision.candidate_facts" :key="fact.fact_id" class="fact-card">
                <span>{{ fact.fact_type }}</span><strong>{{ fact.evidence }}</strong><p>{{ fact.subject_name || fact.subject_entity_id }} {{ fact.predicate || fact.value }} {{ fact.object_name || fact.object_entity_id || "" }}</p><small>{{ fact.knowledge_scope }} · chapter {{ fact.chapter_number }}</small>
              </article>
              <div v-for="item in projection?.items || []" :key="item.projection_id" class="sink-card">
                <div><strong>{{ item.fact_id }}</strong><small>attempt {{ item.attempts }}</small></div>
                <ul><li :class="{ done: item.memory_projected }">Memory</li><li :class="{ done: item.vector_projected }">Vector</li><li :class="{ done: item.graph_projected }">Graph</li></ul>
                <p v-if="item.last_error">{{ item.last_error }}</p>
              </div>
              <button v-if="projection && projection.status !== 'completed'" type="button" class="wide-button" :disabled="actionBusy" @click="retryProjection">重试未完成投影</button>
            </template>
            <p v-else class="panel-empty">选择正文修订后查看候选事实与三存储 checkpoint。</p>
          </aside>
        </section>
      </template>
    </main>

    <transition name="toast">
      <div v-if="notice.message" :class="['toast', notice.tone]">{{ notice.message }}</div>
    </transition>

    <div v-if="createOpen" class="modal-backdrop" @click.self="createOpen = false">
      <form class="modal-card" @submit.prevent="createProject">
        <p class="eyebrow">NEW STORY</p><h2>建立创作项目</h2><p>项目创建后会自动获得 Story Bible 与 Novel Plan 初始 revision。</p>
        <label>项目名称<input v-model="createForm.title" required maxlength="256" placeholder="例如：潮汐档案" /></label>
        <label>作品类型<input v-model="createForm.genre" maxlength="128" placeholder="悬疑 / 奇幻 / 科幻" /></label>
        <label>故事前提<textarea v-model="createForm.premise" rows="5" maxlength="8000" placeholder="一句话描述主角、冲突与代价。"></textarea></label>
        <div class="modal-actions"><button type="button" class="quiet-button" @click="createOpen = false">取消</button><button type="submit" class="primary-button" :disabled="actionBusy">建立项目</button></div>
      </form>
    </div>

    <div v-if="workflowOpen" class="modal-backdrop" @click.self="workflowOpen = false">
      <form class="modal-card workflow-modal" @submit.prevent="enqueueChapterWorkflow">
        <p class="eyebrow">CHAPTER WORKFLOW</p><h2>创建单章写作任务</h2><p>任务绑定当前 fresh Chapter Plan revision，并进入持久化异步队列。</p>
        <label>章节规划
          <select v-model="workflowForm.chapter_plan_id" required>
            <option value="" disabled>选择 fresh Chapter Plan</option>
            <option v-for="plan in workspace.chapterPlans" :key="plan.chapter_plan_id" :value="plan.chapter_plan_id" :disabled="plan.is_stale">CH {{ plan.chapter_number }} · {{ plan.title }} · r{{ plan.revision }}{{ plan.is_stale ? '（过期）' : '' }}</option>
          </select>
        </label>
        <label>写作指令<textarea v-model="workflowForm.instruction" rows="5" required maxlength="8000"></textarea></label>
        <div class="modal-grid">
          <label>Provider
            <select v-if="providerCatalog.length" v-model="workflowForm.provider" required>
              <option v-for="provider in providerCatalog" :key="provider.name" :value="provider.name" :disabled="!provider.configured">
                {{ provider.name }} · {{ !provider.configured ? '未配置' : provider.available === true ? '可用' : provider.available === false ? '暂不可用' : '未探测' }}
              </option>
            </select>
            <input v-else v-model="workflowForm.provider" required />
          </label>
          <label>Model
            <select v-if="selectedProvider?.supported_models?.length" v-model="workflowForm.model" required>
              <option v-for="model in selectedProvider.supported_models" :key="model" :value="model">{{ model }}</option>
            </select>
            <input v-else v-model="workflowForm.model" required />
          </label>
          <label>最低总分<input v-model.number="workflowForm.minimum_overall_score" type="number" min="0" max="100" /></label>
          <label>最大修订轮数<input v-model.number="workflowForm.max_revision_rounds" type="number" min="0" max="5" /></label>
          <label>队列优先级<input v-model.number="workflowForm.priority" type="number" min="-100" max="100" /></label>
          <label class="check-field"><input v-model="workflowForm.auto_rewrite" type="checkbox" /> 自动 Rewrite</label>
        </div>
        <div class="modal-actions"><button type="button" class="quiet-button" @click="workflowOpen = false">取消</button><button type="submit" class="primary-button" :disabled="actionBusy">{{ actionBusy === 'enqueue-workflow' ? '提交中…' : '进入异步队列' }}</button></div>
      </form>
    </div>
  </div>
</template>
