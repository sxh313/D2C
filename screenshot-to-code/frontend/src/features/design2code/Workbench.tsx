import { useCallback, useEffect, useRef, useState } from "react";
import { LuArrowUpRight, LuClipboardPaste, LuFileCode, LuImagePlus, LuLayers, LuPlus, LuRefreshCw, LuX } from "react-icons/lu";
import { buildSelectedElementInstruction } from "../../components/select-and-edit/utils";
import "./workbench.css";

type ImageInput = { name: string; data: string };
type Capabilities = { provider_configured: boolean; figma_mode: "mcp" | "rest"; figma_configured: boolean; generation_available: boolean; configuration_issues: string[] };
type SourceSet = { source_set_id: string; source_set_revision: number; source_set_hash: string };
type Run = { run_id: string; status: string; error: string | null; model_requests: number; repairs: number; result: { candidate_name?: string; files: { path: string; content: string }[]; checks?: { id: string; status: string; message: string }[]; build_details?: string } | null };
type Dimension = "layout" | "style" | "content" | "behavior";
type SelectedElement = { html: string; context: string; label: string };


type Draft = { images: ImageInput[]; spec: string; figma: string; bundle: ImageInput | null; instruction: string; authority: Record<Dimension, string> };

function openDraftDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("design2code-workbench", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("drafts");
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

async function readDraft(): Promise<Draft | undefined> {
  const db = await openDraftDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("drafts", "readonly");
      const request = tx.objectStore("drafts").get("current");
      request.onsuccess = () => resolve(request.result as Draft | undefined);
      request.onerror = () => reject(request.error);
    });
  } finally { db.close(); }
}

async function writeDraft(draft: Draft): Promise<void> {
  const db = await openDraftDatabase();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("drafts", "readwrite");
      tx.objectStore("drafts").put(draft, "current");
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error);
      tx.onerror = () => reject(tx.error);
    });
  } finally { db.close(); }
}

const api = "/api/d2c/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${api}${path}`, options);
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(typeof problem.detail === "string" ? problem.detail : `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function jsonPost(body: unknown, headers: Record<string, string> = {}): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) };
}

function readFile(file: File): Promise<ImageInput> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => typeof reader.result === "string" ? resolve({ name: file.name || "粘贴的截图.png", data: reader.result }) : reject(new Error("图片读取失败"));
    reader.onerror = () => reject(new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}

const statusText: Record<string, string> = {
  CREATED: "正在准备", GENERATING: "正在生成代码", GENERATED: "代码已生成，等待构建",
  BUILDING: "正在构建", REPAIRING: "正在修改", READY_FOR_REVIEW: "等待查看", COMPLETE_LOCAL: "已完成",
  FAILED: "任务失败", UNKNOWN_EXTERNAL: "模型结果未知", CANCELLED: "已停止",
};
const checkStatusText: Record<string, string> = { PASS: "通过", FAIL: "失败", NOT_RUN: "未执行", MANUAL_REVIEW: "待人工检查" };

function VisualReview({ runId, candidate }: { runId: string; candidate?: string }) {
  const [references, setReferences] = useState<{ id: string; type: string; name: string; data_url: string }[]>([]);
  const [selected, setSelected] = useState(0);
  const [viewport, setViewport] = useState<"desktop" | "mobile">("desktop");
  const [error, setError] = useState("");
  const [imageError, setImageError] = useState(false);
  useEffect(() => {
    let active = true;
    setReferences([]); setSelected(0); setError("");
    request<{ references: typeof references }>(`/runs/${runId}/visual-references`)
      .then((data) => { if (active) setReferences(data.references); })
      .catch(() => { if (active) setError("无法读取本次任务的参考图。"); });
    return () => { active = false; };
  }, [runId]);
  useEffect(() => { setImageError(false); }, [runId, candidate, viewport]);
  return <details className="d2c-visual-review"><summary>人工视觉对照</summary>
    <p className="d2c-help">参考图与构建时截图并排展示。尺寸和资料用途可能不同，请结合来源规则人工判断；这里不计算相似度，也不会自动判定通过。</p>
    {error && <p role="alert">{error}</p>}
    <div className="d2c-visual-controls">
      <label>参考图 <select value={selected} onChange={(event) => setSelected(Number(event.target.value))} disabled={!references.length}>
        {references.length ? references.map((item, index) => <option key={item.id} value={index}>{item.type === "figma" ? "Figma" : "截图"}：{item.name}</option>) : <option>没有图片参考</option>}
      </select></label>
      <label>生成页面 <select value={viewport} onChange={(event) => setViewport(event.target.value as "desktop" | "mobile")}><option value="desktop">桌面 1440 × 900</option><option value="mobile">手机 390 × 844</option></select></label>
    </div>
    <div className="d2c-visual-grid"><div><strong>任务参考图</strong>{references[selected] ? <img src={references[selected].data_url} alt="任务参考图" /> : <p>本任务没有截图或 Figma 参考图。</p>}</div>
      <div><strong>构建时页面截图</strong>{imageError ? <p>该视口截图未生成，请检查构建和视口检查结果。</p> : <img src={`${api}/runs/${runId}/inspection-image/${viewport}?candidate=${encodeURIComponent(candidate || "candidate")}`} alt="生成页面检查截图" onError={() => setImageError(true)} />}</div></div>
  </details>;
}

export default function D2CWorkbench() {
  const [images, setImages] = useState<ImageInput[]>([]);
  const [spec, setSpec] = useState("");
  const [figma, setFigma] = useState("");
  const [bundle, setBundle] = useState<ImageInput | null>(null);
  const [instruction, setInstruction] = useState("");
  const [authority, setAuthority] = useState<Record<Dimension, string>>({ layout: "", style: "", content: "", behavior: "" });
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [restoreId, setRestoreId] = useState("");
  const [selectedFile, setSelectedFile] = useState(0);
  const [preview, setPreview] = useState("");
  const [previewReady, setPreviewReady] = useState(false);
  const [view, setView] = useState<"preview" | "code">("preview");
  const [repairInstruction, setRepairInstruction] = useState("");
  const [selectedElement, setSelectedElement] = useState<SelectedElement | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draftReady, setDraftReady] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [draftStorageAvailable, setDraftStorageAvailable] = useState(true);
  const draftWrites = useRef<Promise<void>>(Promise.resolve());
  const fileRef = useRef<HTMLInputElement>(null);
  const previewRef = useRef<HTMLIFrameElement>(null);
  const selectionToken = useRef("");

  useEffect(() => {
    let active = true;
    readDraft().then((draft) => {
      if (!active || !draft) return;
      setImages(draft.images || []);
      setSpec(draft.spec || "");
      setFigma(draft.figma || "");
      setBundle(draft.bundle || null);
      setInstruction(draft.instruction || "");
      if (draft.authority) setAuthority(draft.authority);
    }).catch(() => { if (active) { setDraftStorageAvailable(false); setDraftError("无法读取或保存本机草稿；请检查浏览器存储设置。"); } })
      .finally(() => { if (active) setDraftReady(true); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!draftReady || !draftStorageAvailable) return;
    const draft: Draft = { images, spec, figma, bundle, instruction, authority };
    const timer = window.setTimeout(() => {
      draftWrites.current = draftWrites.current.catch(() => {}).then(() => writeDraft(draft));
      void draftWrites.current.then(() => setDraftError("")).catch(() => setDraftError("草稿保存失败，请检查浏览器存储空间。"));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draftReady, draftStorageAvailable, images, spec, figma, bundle, instruction, authority]);

  const addImages = useCallback(async (files: File[]) => {
    setError("");
    const valid = files.filter((file) => ["image/png", "image/jpeg"].includes(file.type) && file.size <= 10 * 1024 * 1024);
    if (valid.length !== files.length) setError("请选择不超过 10 MiB 的 PNG 或 JPEG 图片。");
    try {
      const incoming = await Promise.all(valid.map(readFile));
      setImages((previous) => [...previous, ...incoming].slice(0, 3));
      if (images.length + incoming.length > 3) setError("一个页面最多添加 3 张截图。");
    } catch { setError("无法读取图片，请重新选择。"); }
  }, [images.length]);

  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      const files = Array.from(event.clipboardData?.items || []).filter((item) => item.type.startsWith("image/"))
        .map((item) => item.getAsFile()).filter((file): file is File => file !== null);
      if (files.length) { event.preventDefault(); void addImages(files); }
    };
    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [addImages]);

  useEffect(() => {
    request<Capabilities>("/capabilities").then(setCapabilities).catch(() => setError("无法连接后端，请检查本地服务是否启动。"));
    const lastRun = window.localStorage.getItem("d2c_last_run");
    if (lastRun) request<Run>(`/runs/${lastRun}`).then(setRun).catch(() => setError("暂时无法恢复上次任务，请确认后端运行后刷新。"));
  }, []);

  useEffect(() => {
    if (!run || !["CREATED", "GENERATING", "BUILDING", "REPAIRING"].includes(run.status)) return;
    const timer = window.setInterval(() => {
      request<Run>(`/runs/${run.run_id}`).then(setRun).catch(() => setError("无法更新任务状态。"));
    }, 1800);
    return () => window.clearInterval(timer);
  }, [run]);

  const currentRunId = run?.run_id;
  const currentStatus = run?.status;
  const currentCandidate = run?.result?.candidate_name;
  useEffect(() => { setSelectedElement(null); setSelecting(false); selectionToken.current = ""; }, [currentRunId, currentCandidate]);
  useEffect(() => { setPreviewReady(false); setSelecting(false); selectionToken.current = ""; }, [preview, view]);

  useEffect(() => {
    const onMessage = (event: MessageEvent<unknown>) => {
      if (!previewRef.current?.contentWindow || event.source !== previewRef.current.contentWindow || !event.data || typeof event.data !== "object") return;
      const data = event.data as Record<string, unknown>;
      if (data.type === "d2c-selection-cancelled" && selectionToken.current && data.token === selectionToken.current) {
        selectionToken.current = "";
        setSelecting(false);
        return;
      }
      if (data.type !== "d2c-element-selected" || !selectionToken.current || data.token !== selectionToken.current || typeof data.html !== "string" || typeof data.context !== "string" || typeof data.label !== "string") return;
      setSelectedElement({ html: data.html.slice(0, 2000), context: data.context.slice(0, 800), label: data.label.slice(0, 80) });
      selectionToken.current = "";
      setSelecting(false);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  function toggleSelection() {
    const enabled = !selecting;
    selectionToken.current = enabled ? crypto.randomUUID() : "";
    previewRef.current?.contentWindow?.postMessage({ type: "d2c-select-mode", enabled, token: selectionToken.current }, "*");
    setSelecting(enabled);
  }
  useEffect(() => {
    if (!currentRunId || !currentStatus || !["READY_FOR_REVIEW", "COMPLETE_LOCAL"].includes(currentStatus)) return;
    request<{ url: string }>(`/runs/${currentRunId}/preview`).then((value) => setPreview(value.url))
      .catch(() => setError("预览服务启动失败，请检查本机预览端口。"));
  }, [currentRunId, currentStatus, currentCandidate]);

  async function handleGenerate() {
    if (!images.length && !spec.trim() && !figma.trim() && !bundle) { setError("请至少添加一份设计资料。"); return; }
    setBusy(true); setError(""); setSelectedFile(0); setPreview(""); setView("preview");
    try {
      const sources: { input_id: string; role: string; scope: object; required: boolean }[] = [];
      const sourceIds: Record<string, string> = {};
      for (const image of images) {
        const item = await request<{ input_id: string }>("/design-inputs", jsonPost({ input_type: "screenshot", content: image.data, name: image.name }));
        sources.push({ input_id: item.input_id, role: "visual_reference", scope: { page: "page" }, required: true });
        sourceIds.screenshot ||= item.input_id;
      }
      if (spec.trim()) {
        const item = await request<{ input_id: string }>("/design-inputs", jsonPost({ input_type: "spec", content: spec }));
        sources.push({ input_id: item.input_id, role: "behavior_and_content", scope: { page: "page" }, required: true });
        sourceIds.spec = item.input_id;
      }
      if (figma.trim()) {
        const item = await request<{ input_id: string }>("/design-inputs", jsonPost({ input_type: "figma", content: figma.trim() }));
        sources.push({ input_id: item.input_id, role: "structure_reference", scope: { page: "page" }, required: true });
        sourceIds.figma = item.input_id;
      }
      if (bundle) {
        const item = await request<{ input_id: string }>("/design-inputs", jsonPost({ input_type: "figma_bundle", content: bundle.data, name: bundle.name }));
        sources.push({ input_id: item.input_id, role: "reference_project", scope: { page: "page" }, required: true });
        sourceIds.figma_bundle = item.input_id;
      }
      const authorityByDimension: Record<string, string> = {};
      for (const [dimension, choice] of Object.entries(authority)) {
        if (choice === "instructions") authorityByDimension[dimension] = choice;
        else if (choice && sourceIds[choice]) authorityByDimension[dimension] = sourceIds[choice];
        else if (choice) throw new Error("来源规则引用的资料已移除，请重新选择。");
      }
      const sourceSet = await request<SourceSet>("/source-sets", jsonPost({ sources, instructions: instruction, authority_by_dimension: authorityByDimension }));
      await request(`/source-sets/${sourceSet.source_set_id}/confirm`, jsonPost(sourceSet));
      const created = await request<{ run_id: string }>("/runs", jsonPost(sourceSet, { "Idempotency-Key": crypto.randomUUID() }));
      window.localStorage.setItem("d2c_last_run", created.run_id);
      setRun(await request<Run>(`/runs/${created.run_id}`));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }

  async function handleRepair() {
    if (!run || !repairInstruction.trim()) return;
    setBusy(true); setError("");
    try {
      const fullInstruction = selectedElement ? buildSelectedElementInstruction(repairInstruction, selectedElement.html, selectedElement.context) : repairInstruction;
      if (fullInstruction.length > 5000) throw new Error("修改要求和选中元素内容过长，请缩短要求或选择更小的元素。");
      await request(`/runs/${run.run_id}/repair`, jsonPost({ instruction: fullInstruction }, { "Idempotency-Key": crypto.randomUUID() }));
      setPreview("");
      setRun(await request<Run>(`/runs/${run.run_id}`));
      setRepairInstruction("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "修复请求失败。"); }
    finally { setBusy(false); }
  }

  async function handleStop() {
    if (!run) return;
    setBusy(true); setError("");
    try {
      await request(`/runs/${run.run_id}/cancel`, { method: "POST" });
      setRun(await request<Run>(`/runs/${run.run_id}`));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "停止失败。"); }
    finally { setBusy(false); }
  }

  async function handleRestore() {
    const id = restoreId.trim();
    if (!/^run_[a-f0-9]{32}$/.test(id)) { setError("请输入完整的任务 ID，例如 run_ 后跟 32 位字符。"); return; }
    setBusy(true); setError("");
    try {
      const restored = await request<Run>(`/runs/${id}`);
      setPreview(""); setSelectedFile(0); setView("preview"); setRun(restored);
      window.localStorage.setItem("d2c_last_run", restored.run_id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "无法恢复任务。"); }
    finally { setBusy(false); }
  }

  const isRunning = busy || !!run && ["CREATED", "GENERATING", "BUILDING", "REPAIRING"].includes(run.status);
  const files = run?.result?.files || [];
  if (!draftReady) return <main className="d2c-shell">正在恢复本机草稿…</main>;
  return <div className="d2c-shell">
    <header className="d2c-header"><div className="d2c-brand"><span className="d2c-brand-mark"><LuLayers /></span><div><strong>Design2Code</strong><small>本地设计工作台</small></div></div><div className="d2c-header-right"><span className={`d2c-dot ${capabilities?.provider_configured ? "ready" : ""}`} />{capabilities?.provider_configured ? "模型已配置" : "检查模型配置"}<span className="d2c-local">本机运行</span></div></header>
    <main className="d2c-main"><div className="d2c-intro"><div><div className="d2c-eyebrow">DESIGN MATERIALS → WORKING PAGE</div><h1>把设计，变成可以运行的页面。</h1><p>组合截图、需求和 Figma，告诉我们各自该参考什么。</p></div><div className="d2c-intro-note"><span>输出</span><strong>React + TypeScript</strong></div></div>
      <div className="d2c-grid"><section className="d2c-card d2c-inputs">{draftError && <div className="d2c-error" role="alert">{draftError}</div>}<div className="d2c-section-heading"><div><span className="d2c-step">INPUT</span><h2>设计资料</h2></div><span className="d2c-count">{images.length + Number(!!spec.trim()) + Number(!!figma.trim()) + Number(!!bundle)} 份资料</span></div>
        <label className="d2c-label">截图 <span>可添加 3 张</span></label>
        <div className="d2c-drop" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void addImages(Array.from(event.dataTransfer.files)); }}>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg" multiple hidden onChange={(event) => { void addImages(Array.from(event.target.files || [])); event.target.value = ""; }} />
          <div className="d2c-drop-icon"><LuImagePlus /></div><strong>拖入截图，或 <button type="button" onClick={() => fileRef.current?.click()}>选择图片</button></strong><span><LuClipboardPaste /> 也可以直接 Ctrl + V 粘贴</span>
        </div>
        {images.length > 0 && <div className="d2c-thumbnails">{images.map((image, index) => <div className="d2c-thumb" key={`${image.name}-${index}`}><img src={image.data} alt={image.name} /><button type="button" aria-label={`移除 ${image.name}`} onClick={() => setImages((old) => old.filter((_, i) => i !== index))}><LuX /></button></div>)}</div>}
        <label className="d2c-label" htmlFor="d2c-spec">需求 Spec <span>文字或 Markdown</span></label><textarea id="d2c-spec" value={spec} onChange={(event) => setSpec(event.target.value)} placeholder={'例如：任务列表支持搜索、状态筛选和新建弹窗。'} rows={4} />
        <label className="d2c-label" htmlFor="d2c-figma">Figma 节点链接 <span>{!capabilities ? "正在检查配置" : capabilities.figma_mode === "mcp" ? (capabilities.figma_configured ? "MCP 模式；请在 Figma 中运行插件" : "请先安装 MCP Bridge") : (capabilities.figma_configured ? "REST 令牌已配置" : "需要配置访问令牌")}</span></label><input id="d2c-figma" value={figma} onChange={(event) => setFigma(event.target.value)} placeholder="https://www.figma.com/design/…?node-id=…" />
        <label className="d2c-label" htmlFor="d2c-bundle">FigmaToCode 项目包 <span>可选 ZIP，最多 10 MiB</span></label>
        <input id="d2c-bundle" type="file" accept=".zip,application/zip" onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          if (!file.name.toLowerCase().endsWith(".zip") || file.size > 10 * 1024 * 1024) { setError("请选择不超过 10 MiB 的 ZIP 项目包。"); return; }
          void readFile(file).then((value) => { setBundle(value); setError(""); }).catch(() => setError("项目包读取失败。"));
        }} />
        {bundle && <p className="d2c-help">已选择 {bundle.name} <button type="button" onClick={() => setBundle(null)}>移除</button>。源码和图片仅作为参考，包内脚本不会执行。</p>}
        <label className="d2c-label" htmlFor="d2c-instruction">生成指令 <span>说明各份资料的用途</span></label><textarea id="d2c-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：布局按 Figma，颜色参考截图，交互按 Spec。" rows={3} />
        <details><summary>选择各维度的参考来源（可选）</summary>
          {([ ["layout", "布局"], ["style", "视觉样式"], ["content", "内容"], ["behavior", "交互"] ] as const).map(([dimension, label]) =>
            <label className="d2c-label" key={dimension}>{label}<select value={authority[dimension]} onChange={(event) => setAuthority((previous) => ({ ...previous, [dimension]: event.target.value }))}>
              <option value="">按资料角色参考</option>{images.length > 0 && <option value="screenshot">第一张截图</option>}{spec.trim() && <option value="spec">Spec</option>}{figma.trim() && <option value="figma">Figma</option>}{bundle && <option value="figma_bundle">FigmaToCode 项目包</option>}{instruction.trim() && <option value="instructions">生成指令</option>}
            </select></label>)}
        </details>
        <div className="d2c-help" aria-label="本次资料摘要">
          <strong>本次资料摘要</strong>
          <p>{images.length ? `${images.length} 张截图作为视觉参考` : "未添加截图"}；{spec.trim() ? "Spec 作为内容与交互参考" : "未添加 Spec"}；{figma.trim() ? "Figma 作为结构参考" : "未添加 Figma"}；{bundle ? "项目包作为源码和图片参考" : "未添加项目包"}。</p>
          <p>资料存在冲突时，请在生成指令中写明以哪一份为准。系统不会自动判断所有冲突。</p>
        </div>
        {error && <div className="d2c-error" role="alert">{error}</div>}
        <button className="d2c-generate" disabled={isRunning || !capabilities?.generation_available} onClick={() => void handleGenerate()}>{isRunning ? <><LuRefreshCw className="d2c-spin" /> 正在处理</> : <>确认资料并生成 <LuArrowUpRight /></>}</button>
        {run && ["CREATED", "GENERATING", "BUILDING", "REPAIRING"].includes(run.status) && <button type="button" disabled={busy} onClick={() => void handleStop()}>停止当前任务</button>}
        {!capabilities?.generation_available && <p className="d2c-help">生成暂不可用，请检查后端服务、根目录 .env 配置及 pnpm 安装。</p>}
      </section><section className="d2c-card d2c-result"><div className="d2c-section-heading"><div><span className="d2c-step">OUTPUT</span><h2>生成结果</h2></div><span className="d2c-status"><span className="d2c-dot ready" />{run ? statusText[run.status] || run.status : "等待开始"}</span></div>
        <details><summary>按任务 ID 恢复</summary><label className="d2c-label" htmlFor="d2c-restore">完整任务 ID</label><input id="d2c-restore" value={restoreId} onChange={(event) => setRestoreId(event.target.value)} placeholder="run_…" /><button type="button" disabled={isRunning || !restoreId.trim()} onClick={() => void handleRestore()}>恢复任务</button></details>
        {!run && <div className="d2c-empty"><div className="d2c-paper"><LuFileCode /><span>YOUR PAGE</span><i /><i /><i /></div><strong>你的页面会显示在这里</strong><p>先添加资料，再填写本次生成要求。</p><div><LuPlus /> 截图 <LuPlus /> Spec <LuPlus /> Figma</div></div>}
        {run && <div className="d2c-result-content">{run.error && <div className="d2c-error">{run.error}</div>}<div className="d2c-run-meta">任务 {run.run_id} <span>模型请求 {run.model_requests} 次</span></div>{files.length > 0 ? <><div className="d2c-result-actions"><button type="button" className={view === "preview" ? "active" : ""} onClick={() => setView("preview")}>页面预览</button><button type="button" className={view === "code" ? "active" : ""} onClick={() => setView("code")}>查看源码</button>{["READY_FOR_REVIEW", "COMPLETE_LOCAL", "FAILED"].includes(run.status) && <a href={`${api}/runs/${run.run_id}/export`}>下载工程</a>}</div>{view === "preview" ? preview ? <><iframe ref={previewRef} title="生成页面预览" className="d2c-preview" sandbox="allow-scripts allow-forms" src={preview} onLoad={() => { setPreviewReady(true); setSelecting(false); setSelectedElement(null); selectionToken.current = ""; }} />{run.status === "READY_FOR_REVIEW" && run.repairs < 1 && run.model_requests < 2 && <div><button type="button" disabled={!previewReady} onClick={toggleSelection}>{selecting ? "取消选取" : "在预览中选取元素"}</button>{selecting && <span> 请点击预览中的元素</span>}{selectedElement && <p>已选：{selectedElement.label || "页面元素"} <button type="button" onClick={() => setSelectedElement(null)}>清除</button></p>}</div>}</> : <div className="d2c-preview-placeholder">{run.status === "FAILED" ? "构建失败，暂时无法预览。" : "等待构建并启动预览。"}</div> : <><div className="d2c-file-tabs">{files.map((file, index) => <button type="button" key={file.path} className={selectedFile === index ? "active" : ""} onClick={() => setSelectedFile(index)}>{file.path}</button>)}</div><pre className="d2c-code"><code>{files[selectedFile]?.content}</code></pre></>}{["READY_FOR_REVIEW", "COMPLETE_LOCAL"].includes(run.status) && <VisualReview runId={run.run_id} candidate={run.result?.candidate_name} />}{run.result?.checks?.map((check) => <div className="d2c-check" key={check.id}><strong>{checkStatusText[check.status] || check.status}</strong> {check.message}</div>)}{run.result?.build_details && <details><summary>构建详情</summary><pre className="d2c-code">{run.result.build_details}</pre></details>}{["READY_FOR_REVIEW", "FAILED"].includes(run.status) && run.repairs < 1 && run.model_requests < 2 && <div className="d2c-repair"><label htmlFor="d2c-repair">需要修改什么？</label><textarea id="d2c-repair" rows={2} value={repairInstruction} onChange={(event) => setRepairInstruction(event.target.value)} placeholder="例如：将主按钮改为蓝色，保持其他布局。" /><button disabled={busy || !repairInstruction.trim()} onClick={() => void handleRepair()}>修改页面（剩余 1 次）</button></div>}</> : <p className="d2c-help">{statusText[run.status] || "正在处理"}</p>}</div>}
      </section></div><footer className="d2c-footer">DESIGN2CODE <span>设计资料保存在本机 · 模型生成通过已配置的服务执行</span></footer></main>
  </div>;
}
