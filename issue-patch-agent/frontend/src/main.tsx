import { FormEvent, useState } from "react";
import { createRoot } from "react-dom/client";

import { createTask, runTask, type WorkflowResult } from "./api";
import "./styles.css";

const initialForm = {
  repository_url: "",
  issue: "",
  test_command: "pytest -q",
};

function App() {
  const [form, setForm] = useState(initialForm);
  const [generatePatch, setGeneratePatch] = useState(false);
  const [result, setResult] = useState<WorkflowResult | null>(null);
  const [message, setMessage] = useState("等待创建任务");
  const [isRunning, setIsRunning] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsRunning(true);
    setResult(null);
    setMessage("正在创建隔离任务…");
    try {
      const task = await createTask(form);
      setMessage("正在执行分析、检索和测试…");
      const workflow = await runTask(task.id, generatePatch);
      setResult(workflow);
      setMessage(workflow.error ?? "任务已完成");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "发生未知错误");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">SAFE CODE MAINTENANCE AGENT</p>
        <h1>IssuePatch <span>Agent</span></h1>
        <p className="intro">在隔离 worktree 中检索、规划、生成可审查补丁并运行测试。原始仓库保持不变。</p>
      </header>

      <section className="shell">
        <form onSubmit={handleSubmit}>
          <label>公开 GitHub 仓库 URL
            <input required type="url" placeholder="https://github.com/owner/repository" value={form.repository_url} onChange={(event) => setForm({ ...form, repository_url: event.target.value })} />
          </label>
          <label>Issue / 修复目标
            <textarea required placeholder="例如：登录失败后页面显示空白，应该显示错误提示。" value={form.issue} onChange={(event) => setForm({ ...form, issue: event.target.value })} />
          </label>
          <label>允许执行的测试命令
            <input required value={form.test_command} onChange={(event) => setForm({ ...form, test_command: event.target.value })} />
          </label>
          <label className="toggle">
            <input type="checkbox" checked={generatePatch} onChange={(event) => setGeneratePatch(event.target.checked)} />
            <span>调用 DeepSeek 生成补丁（会消耗 API 额度）</span>
          </label>
          <button disabled={isRunning}>{isRunning ? "任务运行中…" : "创建并运行任务"}</button>
          <p className="status">{message}</p>
        </form>

        <aside>
          <h2>执行边界</h2>
          <ul>
            <li>仅使用临时 Git worktree</li>
            <li>仅允许 pytest 测试命令</li>
            <li>补丁必须是受限 unified diff</li>
            <li>补丁只应用到临时副本</li>
          </ul>
        </aside>
      </section>

      {result && <ResultPanel result={result} />}
    </main>
  );
}

function ResultPanel({ result }: { result: WorkflowResult }) {
  return (
    <section className="results">
      <div className="result-header">
        <div><p className="eyebrow">TASK {result.task.id.slice(0, 8)}</p><h2>状态：<span className={`badge ${result.task.status}`}>{result.task.status}</span></h2></div>
        <p>{result.patch_result.tests_passed === true ? "测试通过" : result.patch_result.tests_passed === false ? "测试失败" : "未执行测试"}</p>
      </div>
      {result.error && <p className="error">{result.error}</p>}
      <div className="grid">
        <article><h3>修改计划</h3><ol>{result.plan.steps.map((step) => <li key={step}>{step}</li>)}</ol></article>
        <article><h3>工具轨迹</h3>{result.tool_calls.map((call, index) => <details key={`${call.tool_name}-${index}`}><summary>{call.tool_name}</summary><pre>{call.result || "无输出"}</pre></details>)}</article>
      </div>
      <article className="diff"><h3>可审查 Diff {result.patch_result.applied_to_worktree && "（仅临时 worktree）"}</h3><pre>{result.patch_result.diff || "本次未生成补丁。"}</pre></article>
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
