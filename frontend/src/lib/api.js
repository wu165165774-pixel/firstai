const API_ROOT = import.meta.env?.VITE_API_ROOT || "/api/v1";

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
  listProjects: (userId) =>
    request(`/novels${query({ user_id: userId, limit: 200 })}`),
  createProject: (payload) =>
    request("/novels", { method: "POST", body: payload }),
  getProject: (novelId) => request(`/novels/${novelId}`),
  getBible: (novelId) => request(`/novels/${novelId}/story-bible`),
  getPlan: (novelId) => request(`/novels/${novelId}/plan`),
  listArcs: (novelId) => request(`/novels/${novelId}/arcs?limit=500`),
  listChapterPlans: (novelId) =>
    request(`/novels/${novelId}/chapter-plans?limit=500`),
  listWorkflows: (novelId) =>
    request(`/workflows/runs${query({ novel_id: novelId, limit: 100 })}`),
  getWorkflow: (runId) => request(`/workflows/runs/${runId}`),
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
