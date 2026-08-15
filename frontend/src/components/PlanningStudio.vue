<script setup>
import { computed, reactive, ref, watch } from "vue";

import { ApiError, api } from "../lib/api.js";
import {
  PLANNING_TARGETS,
  editorFromEntity,
  plannerAcceptPayload,
  plannerGeneratePayload,
  planningPayload,
} from "../lib/planning.js";

const props = defineProps({
  novelId: { type: String, required: true },
  workspace: { type: Object, required: true },
});
const emit = defineEmits(["notice", "refresh"]);

const target = ref("story_bible");
const selectedArcId = ref("");
const selectedChapterId = ref("");
const editor = reactive({});
const busy = ref("");
const instruction = ref("");
const generated = ref(null);
const candidateText = ref("");

const config = computed(() => PLANNING_TARGETS[target.value]);
const selectedArc = computed(() =>
  props.workspace.arcs.find((item) => item.arc_id === selectedArcId.value) || null,
);
const selectedChapter = computed(() =>
  props.workspace.chapterPlans.find(
    (item) => item.chapter_plan_id === selectedChapterId.value,
  ) || null,
);
const currentEntity = computed(() => {
  if (target.value === "story_bible") return props.workspace.bible;
  if (target.value === "novel_plan") return props.workspace.plan;
  if (target.value === "story_arc") return selectedArc.value;
  return selectedChapter.value;
});
const isNew = computed(
  () =>
    (target.value === "story_arc" && !selectedArc.value) ||
    (target.value === "chapter_plan" && !selectedChapter.value),
);
const plannerAvailable = computed(
  () => target.value === "novel_plan" || isNew.value,
);
const plannerGate = computed(() => {
  if (target.value === "story_arc") {
    if (!props.workspace.plan) return "必须先建立 Novel Plan";
    if (props.workspace.plan.is_stale) return "Novel Plan 已过期，必须先刷新";
  }
  if (target.value === "chapter_plan") {
    if (!props.workspace.plan) return "必须先建立 Novel Plan";
    if (props.workspace.plan.is_stale) return "Novel Plan 已过期";
    const arc = props.workspace.arcs.find((item) => item.arc_id === editor.arc_id);
    if (!arc) return "请选择 Story Arc";
    if (arc.is_stale) return "所选 Story Arc 已过期";
  }
  if (!plannerAvailable.value) return "现有 Arc/Chapter 请直接编辑；Planner 接受只创建新实体";
  return "";
});

function announce(message, tone = "info") {
  emit("notice", { message, tone });
}

function explain(error) {
  announce(
    error instanceof ApiError ? error.message : error?.message || "操作失败",
    error instanceof ApiError && error.status < 500 ? "warning" : "danger",
  );
}

function replaceEditor(value) {
  Object.keys(editor).forEach((key) => delete editor[key]);
  Object.assign(editor, value);
}

function blankEntity() {
  if (target.value === "story_arc") {
    const maxArc = props.workspace.arcs.reduce(
      (value, item) => Math.max(value, item.arc_number),
      0,
    );
    return { volume_number: 1, arc_number: maxArc + 1 };
  }
  if (target.value === "chapter_plan") {
    const maxChapter = props.workspace.chapterPlans.reduce(
      (value, item) => Math.max(value, item.chapter_number),
      0,
    );
    return {
      arc_id: selectedArcId.value || props.workspace.arcs[0]?.arc_id || "",
      chapter_number: maxChapter + 1,
      target_word_count: 3000,
    };
  }
  return {};
}

function resetEditor() {
  replaceEditor(
    editorFromEntity(target.value, currentEntity.value || blankEntity()),
  );
  generated.value = null;
  candidateText.value = "";
}

function selectTarget(value) {
  target.value = value;
  if (value === "story_arc" && !selectedArcId.value) {
    selectedArcId.value = props.workspace.arcs[0]?.arc_id || "";
  }
  if (value === "chapter_plan" && !selectedChapterId.value) {
    selectedChapterId.value = props.workspace.chapterPlans[0]?.chapter_plan_id || "";
  }
  resetEditor();
}

function newEntity() {
  if (target.value === "story_arc") selectedArcId.value = "";
  if (target.value === "chapter_plan") selectedChapterId.value = "";
  resetEditor();
}

async function saveEntity() {
  busy.value = "save";
  try {
    const entity = currentEntity.value;
    const payload = planningPayload(target.value, editor, {
      revision: entity?.revision ?? null,
    });
    let saved;
    if (target.value === "story_bible") {
      saved = await api.updateBible(props.novelId, payload);
    } else if (target.value === "novel_plan") {
      saved = await api.updatePlan(props.novelId, payload);
    } else if (target.value === "story_arc") {
      saved = entity
        ? await api.updateArc(props.novelId, entity.arc_id, payload)
        : await api.createArc(props.novelId, payload);
      selectedArcId.value = saved.arc_id;
    } else {
      saved = entity
        ? await api.updateChapterPlan(props.novelId, entity.chapter_plan_id, payload)
        : await api.createChapterPlan(props.novelId, payload);
      selectedChapterId.value = saved.chapter_plan_id;
    }
    emit("refresh");
    replaceEditor(editorFromEntity(target.value, saved));
    announce(`${config.value.label}已保存为 r${saved.revision}`, "success");
  } catch (error) {
    explain(error);
  } finally {
    busy.value = "";
  }
}

async function generateCandidate() {
  if (plannerGate.value) {
    announce(plannerGate.value, "warning");
    return;
  }
  busy.value = "generate";
  try {
    const result = await api.generatePlanCandidate(
      props.novelId,
      plannerGeneratePayload(target.value, editor, instruction.value),
    );
    generated.value = result;
    candidateText.value = JSON.stringify(result.candidate, null, 2);
    announce("候选已生成，尚未持久化", "success");
  } catch (error) {
    explain(error);
  } finally {
    busy.value = "";
  }
}

async function acceptCandidate() {
  if (!generated.value) return;
  busy.value = "accept";
  try {
    let candidate;
    try {
      candidate = JSON.parse(candidateText.value);
    } catch (error) {
      throw new Error(`候选 JSON 无效：${error.message}`);
    }
    const result = await api.acceptPlanCandidate(
      props.novelId,
      plannerAcceptPayload(generated.value, candidate),
    );
    const saved = result[result.target];
    if (result.target === "story_arc") selectedArcId.value = saved.arc_id;
    if (result.target === "chapter_plan") {
      selectedChapterId.value = saved.chapter_plan_id;
    }
    generated.value = null;
    candidateText.value = "";
    emit("refresh");
    replaceEditor(editorFromEntity(target.value, saved));
    announce(`候选已显式接受并持久化为 r${saved.revision}`, "success");
  } catch (error) {
    explain(error);
  } finally {
    busy.value = "";
  }
}

watch(selectedArcId, () => {
  if (target.value === "story_arc") resetEditor();
});
watch(selectedChapterId, () => {
  if (target.value === "chapter_plan") resetEditor();
});
watch(
  () => props.workspace.project?.novel_id,
  () => {
    selectedArcId.value = props.workspace.arcs[0]?.arc_id || "";
    selectedChapterId.value =
      props.workspace.chapterPlans[0]?.chapter_plan_id || "";
    resetEditor();
  },
  { immediate: true },
);
</script>

<template>
  <section class="planning-studio">
    <aside class="planning-nav panel">
      <div class="panel-heading">
        <div><p class="eyebrow">PLANNING STUDIO</p><h2>规划领域</h2></div>
      </div>
      <button
        v-for="(item, key) in PLANNING_TARGETS"
        :key="key"
        type="button"
        :class="['planning-target', { active: target === key }]"
        @click="selectTarget(key)"
      >
        <span>{{ key === 'story_bible' ? '圣' : key === 'novel_plan' ? '纲' : key === 'story_arc' ? '弧' : '章' }}</span>
        <div><strong>{{ item.label }}</strong><small>{{ key === 'story_bible' ? `r${workspace.bible?.revision || 0}` : key === 'novel_plan' ? `r${workspace.plan?.revision || 0}` : key === 'story_arc' ? `${workspace.arcs.length} 个` : `${workspace.chapterPlans.length} 章` }}</small></div>
      </button>

      <template v-if="target === 'story_arc'">
        <div class="entity-picker-head"><span>故事弧</span><button type="button" @click="newEntity">＋ 新建</button></div>
        <button v-for="item in workspace.arcs" :key="item.arc_id" type="button" :class="['entity-picker', { active: selectedArcId === item.arc_id }]" @click="selectedArcId = item.arc_id">
          <strong>V{{ item.volume_number }} · A{{ item.arc_number }}</strong><span>{{ item.title }}</span><i :class="item.is_stale ? 'warning' : 'ready'"></i>
        </button>
      </template>
      <template v-if="target === 'chapter_plan'">
        <div class="entity-picker-head"><span>章节</span><button type="button" @click="newEntity">＋ 新建</button></div>
        <button v-for="item in workspace.chapterPlans" :key="item.chapter_plan_id" type="button" :class="['entity-picker', { active: selectedChapterId === item.chapter_plan_id }]" @click="selectedChapterId = item.chapter_plan_id">
          <strong>CH {{ item.chapter_number }}</strong><span>{{ item.title }}</span><i :class="item.is_stale ? 'warning' : 'ready'"></i>
        </button>
      </template>
    </aside>

    <form class="planning-editor panel" @submit.prevent="saveEntity">
      <div class="editor-title">
        <div><p class="eyebrow">DOMAIN EDITOR</p><h2>{{ isNew ? `新建${config.label}` : config.label }}</h2><p>保存通过正式领域 API，并携带当前 optimistic revision。</p></div>
        <div><span v-if="currentEntity">r{{ currentEntity.revision }}</span><b v-if="currentEntity?.is_stale" class="status-chip warning">已过期</b></div>
      </div>

      <label v-if="target === 'chapter_plan'" class="editor-field">所属 Story Arc
        <select v-model="editor.arc_id" required>
          <option value="" disabled>选择 Story Arc</option>
          <option v-for="arc in workspace.arcs" :key="arc.arc_id" :value="arc.arc_id">V{{ arc.volume_number }} · A{{ arc.arc_number }} · {{ arc.title }}{{ arc.is_stale ? '（过期）' : '' }}</option>
        </select>
      </label>

      <div class="editor-fields">
        <label v-for="field in config.scalars" :key="field.key" :class="['editor-field', { wide: field.rows }]">
          {{ field.label }}
          <textarea v-if="field.rows" v-model="editor[field.key]" :rows="field.rows"></textarea>
          <input v-else v-model="editor[field.key]" :type="field.type || 'text'" :required="field.required" :min="field.type === 'number' ? field.min ?? 0 : undefined" />
        </label>
        <label v-for="field in config.lists" :key="field.key" class="editor-field wide">
          {{ field.label }}
          <textarea v-model="editor[field.key]" rows="3"></textarea>
        </label>
      </div>

      <details v-for="field in config.json" :key="field.key" class="json-editor">
        <summary>{{ field.label }} <small>{{ field.shape === 'array' ? 'JSON Array' : 'JSON Object' }}</small></summary>
        <textarea v-model="editor[field.key]" rows="10" spellcheck="false"></textarea>
      </details>

      <div class="editor-actions">
        <button type="button" class="quiet-button" @click="resetEditor">放弃修改</button>
        <button type="submit" class="primary-button" :disabled="busy">{{ busy === 'save' ? '保存中…' : isNew ? '创建' : '保存新修订' }}</button>
      </div>
    </form>

    <aside class="planner-panel panel">
      <p class="eyebrow">LOCAL QWEN PLANNER</p>
      <h2>候选生成与审核</h2>
      <template v-if="target === 'story_bible'">
        <p class="planner-help">Story Bible 当前由人工结构化编辑维护；Planner 的三个受控目标是 Novel Plan、Story Arc 与 Chapter Plan。</p>
      </template>
      <template v-else>
        <p class="planner-help">生成只返回经过校验的 candidate，接受前不会写入数据库。</p>
        <label class="editor-field">Planner 指令
          <textarea v-model="instruction" rows="6" :placeholder="`描述希望生成的${config.label}、叙事目标与约束`"></textarea>
        </label>
        <div v-if="plannerGate" class="planner-gate">{{ plannerGate }}</div>
        <button type="button" class="wide-button" :disabled="busy || Boolean(plannerGate)" @click="generateCandidate">
          {{ busy === 'generate' ? 'Qwen 生成中…' : '生成候选' }}
        </button>
        <template v-if="generated">
          <div class="candidate-meta">
            <b>persisted = {{ generated.persisted }}</b>
            <span>{{ generated.model }} · {{ Math.round(generated.latency_ms || 0) }} ms</span>
            <small>{{ generated.usage?.total_tokens || 0 }} tokens · context {{ generated.metadata?.planner_context_chars || '—' }} chars</small>
          </div>
          <label class="editor-field candidate-json">候选 JSON（可在接受前修改）
            <textarea v-model="candidateText" rows="18" spellcheck="false"></textarea>
          </label>
          <button type="button" class="primary-button candidate-accept" :disabled="busy" @click="acceptCandidate">
            {{ busy === 'accept' ? '接受中…' : '显式接受并持久化' }}
          </button>
        </template>
      </template>
    </aside>
  </section>
</template>
