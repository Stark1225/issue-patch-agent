export type TaskStatus =
  | "queued"
  | "analyzing"
  | "retrieving"
  | "planning"
  | "patching"
  | "testing"
  | "reporting"
  | "completed"
  | "failed";

export interface Task {
  id: string;
  repository_path: string;
  issue: string;
  test_command: string;
  status: TaskStatus;
}

export interface WorkflowResult {
  task: Task;
  plan: { steps: string[] };
  tool_calls: { tool_name: string; arguments: Record<string, string>; result?: string }[];
  patch_result: { diff: string; tests_passed: boolean | null; applied_to_worktree: boolean };
  error?: string;
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new Error((await response.json().catch(() => null))?.detail ?? "请求失败，请确认后端服务已启动。");
  }
  return response.json() as Promise<T>;
}

export function createTask(input: Omit<Task, "id" | "status">): Promise<Task> {
  return request("/tasks", { method: "POST", body: JSON.stringify(input) });
}

export function runTask(taskId: string, generatePatch: boolean): Promise<WorkflowResult> {
  return request(`/tasks/${taskId}/run?generate_patch=${generatePatch}`, { method: "POST" });
}
