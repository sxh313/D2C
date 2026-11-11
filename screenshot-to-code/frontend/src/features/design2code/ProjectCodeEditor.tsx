import { useEffect, useRef, useState } from "react";
import CodeMirror from "../../components/preview/CodeMirror";
import { EditorTheme } from "../../types";

type SourceFile = { path: string; content: string };
type Snapshot = { base_candidate_hash: string; files: SourceFile[]; editable: boolean };
type CodeDraft = { base_candidate_hash: string; files: SourceFile[]; key?: string };

async function draftStore<T>(runId: string, value?: CodeDraft | null): Promise<T | undefined> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const opened = indexedDB.open("design2code-code-drafts", 1);
    opened.onupgradeneeded = () => opened.result.createObjectStore("drafts");
    opened.onsuccess = () => resolve(opened.result);
    opened.onerror = () => reject(new Error("无法打开源码草稿存储。"));
  });
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const tx = db.transaction("drafts", value === undefined ? "readonly" : "readwrite");
      const store = tx.objectStore("drafts");
      const operation = value === undefined ? store.get(runId) : value === null ? store.delete(runId) : store.put(value, runId);
      let result: T | undefined;
      operation.onsuccess = () => { result = operation.result as T | undefined; };
      tx.oncomplete = () => resolve(result);
      tx.onabort = tx.onerror = () => reject(new Error("源码草稿保存失败，请检查浏览器存储。"));
    });
  } finally { db.close(); }
}

async function snapshot(runId: string): Promise<Snapshot> {
  const response = await fetch(`/api/d2c/v1/runs/${runId}/code-edit`);
  if (!response.ok) throw new Error("无法读取候选源码，请重试。");
  return response.json() as Promise<Snapshot>;
}

export function ProjectCodeEditor({ runId, enabled, onSubmitted }: {
  runId: string; enabled: boolean; onSubmitted: () => Promise<void>;
}) {
  const [base, setBase] = useState<Snapshot | null>(null);
  const [draft, setDraft] = useState<CodeDraft | null>(null);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(true);
  const writes = useRef<Promise<unknown>>(Promise.resolve());
  const generation = useRef(0);
  const stale = !!base && !!draft && base.base_candidate_hash !== draft.base_candidate_hash && !draft.key;
  const dirty = !!base && !!draft && JSON.stringify(base.files) !== JSON.stringify(draft.files);
  useEffect(() => {
    let active = true;
    void Promise.all([snapshot(runId), draftStore<CodeDraft>(runId)]).then(([current, stored]) => {
      if (!active) return;
      setBase(current);
      setDraft(stored || { base_candidate_hash: current.base_candidate_hash, files: current.files });
      setEditing(!!stored);
    }).catch((caught: unknown) => { if (active) setError(caught instanceof Error ? caught.message : "无法读取源码草稿。"); });
    return () => { active = false; generation.current += 1; };
  }, [runId]);

  function persist(next: CodeDraft) {
    const version = ++generation.current;
    setDraft(next); setSaved(false); setError("");
    writes.current = writes.current.catch(() => {}).then(() => draftStore(runId, next));
    void writes.current.then(() => { if (version === generation.current) setSaved(true); })
      .catch(() => { if (version === generation.current) setError("源码草稿保存失败，尚不能提交构建。"); });
  }
  async function discard() {
    setBusy(true); setError("");
    try {
      await writes.current.catch(() => {});
      const current = await snapshot(runId);
      await draftStore(runId, null);
      setBase(current); setDraft({ base_candidate_hash: current.base_candidate_hash, files: current.files });
      setSaved(true); setEditing(false);
    } catch { setError("无法清除草稿，请检查本机服务和浏览器存储。"); }
    finally { setBusy(false); }
  }
  async function submit() {
    if (!draft || !base || busy) return;
    setBusy(true); setError("");
    const pending = { ...draft, key: draft.key || crypto.randomUUID() };
    try {
      await writes.current;
      await draftStore(runId, pending);
      setDraft(pending);
      let response: Response;
      try { response = await fetch(`/api/d2c/v1/runs/${runId}/code-edit`, {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": pending.key },
        body: JSON.stringify({ base_candidate_hash: pending.base_candidate_hash, files: pending.files }),
      }); } catch { throw new Error("提交结果未知。草稿与原请求标识已保存，请点击恢复提交，不会另建任务。"); }
      if (!response.ok) {
        const problem = await response.json().catch(() => ({}));
        if (response.status >= 400 && response.status < 500) {
          const editable = { ...pending, key: undefined };
          await draftStore(runId, editable); setDraft(editable);
        }
        throw new Error(typeof problem.detail === "string" ? problem.detail : "源码提交失败，请恢复提交以确认原请求。");
      }
      await draftStore(runId, null);
      await onSubmitted();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "源码修改未提交。"); }
    finally { setBusy(false); }
  }
  const file = draft?.files[selected] || draft?.files[0];
  const readOnly = !editing || busy || !enabled || !base?.editable || stale || !!draft?.key;
  return <div className="d2c-source-editor">
    <p className="d2c-help">手写修改无需模型请求，占用本任务唯一一次修改额度。提交后重新构建与检查，保留修改前版本。草稿不会改变当前预览和导出。</p>
    {error && <p role="alert">{error}</p>}
    {stale && <p role="status">已保留旧候选的源码草稿；当前候选已变更，请先下载草稿或放弃草稿再编辑。</p>}
    <div className="d2c-result-actions">
      {!editing && base?.editable && enabled && <button type="button" onClick={() => setEditing(true)}>编辑源码</button>}
      {editing && <><button type="button" disabled={busy || !saved || (!draft?.key && (!enabled || !base?.editable || stale || !dirty))} onClick={() => void submit()}>{busy ? "正在提交…" : draft?.key ? "恢复源码提交" : "构建手写修改（剩余 1 次）"}</button>
        <button type="button" disabled={busy || !!draft?.key} onClick={() => void discard()}>放弃源码草稿</button>
        <button type="button" disabled={!draft} onClick={() => {
          const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }));
          const link = document.createElement("a"); link.href = url; link.download = `${runId}-source-draft.json`; link.click();
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        }}>下载源码草稿</button><span role="status">{saved ? dirty ? "源码草稿已保存，尚未构建" : "与当前候选一致" : "正在保存源码草稿…"}</span></>}
    </div>
    <div className="d2c-file-tabs" role="group" aria-label="工程文件">{draft?.files.map((item, index) => <button type="button" key={item.path} aria-pressed={selected === index} className={selected === index ? "active" : ""} onClick={() => setSelected(index)}>{item.path}</button>)}</div>
    {file && <CodeMirror key={file.path} code={file.content} editorTheme={EditorTheme.COBALT} readOnly={readOnly} language={/\.html?$/.test(file.path) ? "html" : "text"}
      label={`源码 ${file.path}`} className="d2c-native-code" onCodeChange={(content) => {
        if (!draft || readOnly) return;
        persist({ ...draft, files: draft.files.map((item) => item.path === file.path ? { ...item, content } : item) });
      }} />}
  </div>;
}
