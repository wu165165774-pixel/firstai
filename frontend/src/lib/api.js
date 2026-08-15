const API_ROOT = import.meta.env?.VITE_API_ROOT || "/api/v1";
const TOKEN_STORAGE_KEY = "novelforge.accessToken";
let accessToken = "";

try {
  accessToken = globalThis.sessionStorage?.getItem(TOKEN_STORAGE_KEY) || "";
} catch {
  accessToken = "";
}

export function setAccessToken(value, { persist = true } = {}) {
  accessToken = String(value || "").trim();
  if (!persist) return;
  try {
    if (accessToken) globalThis.sessionStorage?.setItem(TOKEN_STORAGE_KEY, accessToken);
    else globalThis.sessionStorage?.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // In-memory authentication still works when browser storage is unavailable.
  }
}

export function getAccessToken() {
  return accessToken;
}

export class ApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function errorMessage(payload, status) {
  const detail = payload?.detail ?? payload?.message;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("；");
  }
  return `请求失败（HTTP ${status}）`;
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  }
  if (accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers,
    body:
      options.body === undefined || typeof options.body === "string"
        ? options.body
        : JSON.stringify(options.body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(errorMessage(payload, response.status), {
      status: response.status,
      detail: payload?.detail,
    });
  }
  return payload?.data ?? payload;
}

const query = (values) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      params.set(key, String(value));
    }
  });
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
};

export const api = {
  health: () => request("/health"),
  identity: () => request("/auth/me"),
  listProjects: (userId) =>
    request(`/novels${query({ user_id: userId, limit: 200 })}`),
  createProject: (payload) =>
    request("/novels", { method: "POST", body: payload }),
  getProject: (novelId) => request(`/novels/${novelId}`),
  getBible: (novelId) => request(`/novels/${novelId}/story-bible`),
  updateBible: (novelId, payload) =>
    request(`/novels/${novelId}/story-bible`, { method: "PUT", body: payload }),
  getPlan: (novelId) => request(`/novels/${novelId}/plan`),
  updatePlan: (novelId, payload) =>
    request(`/novels/${novelId}/plan`, { method: "PUT", body: payload }),
  listArcs: (novelId) => request(`/novels/${novelId}/arcs?limit=500`),
  createArc: (novelId, payload) =>
    request(`/novels/${novelId}/arcs`, { method: "POST", body: payload }),
  updateArc: (novelId, arcId, payload) =>
    request(`/novels/${novelId}/arcs/${arcId}`, { method: "PUT", body: payload }),
  listChapterPlans: (novelId) =>
    request(`/novels/${novelId}/chapter-plans?limit=500`),
  createChapterPlan: (novelId, payload) =>
    request(`/novels/${novelId}/chapter-plans`, { method: "POST", body: payload }),
  updateChapterPlan: (novelId, chapterPlanId, payload) =>
    request(`/novels/${novelId}/chapter-plans/${chapterPlanId}`, {
      method: "PUT",
      body: payload,
    }),
  generatePlanCandidate: (novelId, payload) =>
    request(`/novels/${novelId}/planner/generate`, {
      method: "POST",
      body: payload,
    }),
  acceptPlanCandidate: (novelId, payload) =>
    request(`/novels/${novelId}/planner/accept`, {
      method: "POST",
      body: payload,
    }),
  listWorkflows: (novelId) =>
    request(`/workflows/runs${query({ novel_id: novelId, limit: 100 })}`),
  getWorkflow: (runId) => request(`/workflows/runs/${runId}`),
  enqueueWorkflow: (payload, { idempotencyKey, priority = 0 } = {}) =>
    request("/workflows/chapter/runs/async", {
      method: "POST",
      headers: {
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
        "X-Workflow-Priority": String(priority),
      },
      body: payload,
    }),
  listManuscripts: (novelId) =>
    request(`/novels/${novelId}/manuscript/chapters?limit=500`),
  getManuscript: (novelId, chapterId) =>
    request(`/novels/${novelId}/manuscript/chapters/${chapterId}`),
  listRevisions: (novelId, chapterId) =>
    request(
      `/novels/${novelId}/manuscript/chapters/${chapterId}/revisions?limit=200`,
    ),
  importWorkflow: (novelId, runId, expectedRevision = null) =>
    request(`/novels/${novelId}/manuscript/chapters/import-workflow`, {
      method: "POST",
      body: {
        workflow_run_id: runId,
        expected_manuscript_revision: expectedRevision,
      },
    }),
  acceptRevision: (novelId, chapterId, revision, expectedRevision) =>
    request(
      `/novels/${novelId}/manuscript/chapters/${chapterId}/revisions/${revision}/accept`,
      { method: "POST", body: { expected_manuscript_revision: expectedRevision } },
    ),
  getProjection: (novelId, chapterId, revision) =>
    request(
      `/novels/${novelId}/manuscript/chapters/${chapterId}/revisions/${revision}/fact-projection`,
    ),
  retryProjection: (novelId, chapterId, revision) =>
    request(
      `/novels/${novelId}/manuscript/chapters/${chapterId}/revisions/${revision}/fact-projection/retry`,
      { method: "POST" },
    ),
  listOrchestrations: (novelId) =>
    request(`/novels/${novelId}/orchestrations?limit=100`),
  createOrchestration: (novelId, payload, idempotencyKey) =>
    request(`/novels/${novelId}/orchestrations`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload,
    }),
  controlOrchestration: (novelId, orchestrationId, action, revision) =>
    request(`/novels/${novelId}/orchestrations/${orchestrationId}/${action}`, {
      method: "POST",
      body: { expected_revision: revision },
    }),
};
