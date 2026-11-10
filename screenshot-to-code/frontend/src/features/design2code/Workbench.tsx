import { useCallback, useEffect, useRef, useState } from "react";
import { LuArrowUpRight, LuClipboardPaste, LuFileCode, LuImagePlus, LuLayers, LuPlus, LuRefreshCw, LuX } from "react-icons/lu";
import { buildSelectedElementInstruction } from "../../components/select-and-edit/utils";
import "./workbench.css";

type ImageInput = { name: string; data: string };
type Capabilities = { provider_configured: boolean; figma_mode: "mcp" | "rest"; figma_configured: boolean; generation_available: boolean; configuration_issues: string[]; token_limit_configured: boolean; cost_limit_configured: boolean };
type SourceSet = { source_set_id: string; source_set_revision: number; source_set_hash: string };
type PendingRun = { sourceSet: SourceSet; key: string };
type PendingRepair = { runId: string; instruction: string; key: string };
type Run = { run_id: string; status: string; error: string | null; model_requests: number; repairs: number; result: { candidate_name?: string; files: { path: string; content: string }[]; checks?: { id: string; status: string; message: string }[]; build_details?: string } | null };
type RecentRun = { run_id: string; status: string; model_requests: number; repairs: number; created_at: string };
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

async function readScreenshot(file: File): Promise<ImageInput> {
  const input = await readFile(file);
  await new Promise<void>((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (!image.naturalWidth || !image.naturalHeight || image.naturalWidth * image.naturalHeight > 40_000_000) {
        reject(new Error("图片尺寸不受支持"));
      } else resolve();
    };
    image.onerror = () => reject(new Error("图片无法解码"));
    image.src = input.data;
  });
  return input;
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
  const [overlay, setOverlay] = useState(false);
  const [opacity, setOpacity] = useState(50);
  const [difference, setDifference] = useState<{ width: number; height: number; mean_channel_difference: number; image_data_url: string; candidate_image_data_url?: string; warnings?: string[] } | null>(null);
  const [differenceError, setDifferenceError] = useState("");
  const [differenceBusy, setDifferenceBusy] = useState(false);
  const differenceRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    let active = true;
    setReferences([]); setSelected(0); setError("");
    request<{ references: typeof references }>(`/runs/${runId}/visual-references`)
      .then((data) => { if (active) setReferences(data.references); })
      .catch(() => { if (active) setError("无法读取本次任务的参考图。"); });
    return () => { active = false; };
  }, [runId]);
  useEffect(() => { setImageError(false); }, [runId, candidate, viewport]);
  useEffect(() => {
    differenceRequest.current?.abort(); setDifference(null); setDifferenceError(""); setDifferenceBusy(false);
    return () => { differenceRequest.current?.abort(); };
  }, [runId, candidate, viewport, selected]);
  async function comparePixels(mode: "desktop" | "mobile" | "reference") {
    const reference = references[selected];
    if (!reference) return;
    differenceRequest.current?.abort();
    const controller = new AbortController(); differenceRequest.current = controller;
    setDifferenceBusy(true); setDifferenceError(""); setDifference(null);
    try {
      const result = await request<{ width: number; height: number; mean_channel_difference: number; image_data_url: string; candidate_image_data_url?: string; warnings?: string[] }>(
        `/runs/${runId}/visual-diff/${encodeURIComponent(reference.id)}/${mode}`, { signal: controller.signal });
      if (!controller.signal.aborted) setDifference(result);
    } catch (caught) {
      if (!controller.signal.aborted) setDifferenceError(caught instanceof Error ? caught.message : "差异图生成失败。");
    } finally { if (!controller.signal.aborted) setDifferenceBusy(false); }
  }
  return <details className="d2c-visual-review"><summary>人工视觉对照</summary>
    <p className="d2c-help">参考图与构建时截图可以并排或叠加查看。尺寸和资料用途可能不同，请结合来源规则人工判断；这里不计算相似度，也不会自动判定通过。</p>
    {error && <p role="alert">{error}</p>}
    <div className="d2c-visual-controls">
      <label>参考图 <select value={selected} onChange={(event) => setSelected(Number(event.target.value))} disabled={!references.length}>
        {references.length ? references.map((item, index) => <option key={item.id} value={index}>{item.type === "figma" ? "Figma" : "截图"}：{item.name}</option>) : <option>没有图片参考</option>}
      </select></label>
      <label>生成页面 <select value={viewport} onChange={(event) => setViewport(event.target.value as "desktop" | "mobile")}><option value="desktop">桌面 1440 × 900</option><option value="mobile">手机 390 × 844</option></select></label>
      <label><span>对照方式</span><select value={overlay ? "overlay" : "side"} onChange={(event) => setOverlay(event.target.value === "overlay")}><option value="side">并排</option><option value="overlay">叠加</option></select></label>
      {overlay && <label>生成页面透明度：{opacity}%<input type="range" min="0" max="100" value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} /></label>}
    </div>
    {overlay && references[selected] && !imageError ? <><p className="d2c-help">两张图片按各自宽度等比缩放并从顶部对齐；页面尺寸或滚动长度不同时，重叠差异可能来自缩放，请结合并排视图判断。</p><div className="d2c-overlay"><img src={references[selected].data_url} alt="任务参考图" /><img className="d2c-overlay-result" style={{ opacity: opacity / 100 }} src={`${api}/runs/${runId}/inspection-image/${viewport}?candidate=${encodeURIComponent(candidate || "candidate")}`} alt="叠加的生成页面检查截图" onError={() => setImageError(true)} /></div></> : <div className="d2c-visual-grid"><div><strong>任务参考图</strong>{references[selected] ? <img src={references[selected].data_url} alt="任务参考图" /> : <p>本任务没有截图或 Figma 参考图。</p>}</div>
      <div><strong>构建时页面截图</strong>{imageError ? <p>该视口截图未生成，请检查构建和视口检查结果。</p> : <img src={`${api}/runs/${runId}/inspection-image/${viewport}?candidate=${encodeURIComponent(candidate || "candidate")}`} alt="生成页面检查截图" onError={() => setImageError(true)} />}</div></div>
    }
    <div className="d2c-pixel-diff"><button type="button" disabled={!references[selected] || imageError || differenceBusy} onClick={() => void comparePixels(viewport)}>{differenceBusy ? "正在计算…" : "比较现有截图"}</button>{" "}<button type="button" disabled={!references[selected] || differenceBusy} onClick={() => void comparePixels("reference")}>按参考图尺寸截图并比较</button>
      <p className="d2c-help">重新截图会以参考图的宽高作为浏览器视口，仅截取页面顶部可见区域；长页面其余部分不在对比范围。图片不得超过 2000×2000 像素或 400 万像素。亮色表示像素差异；字体、抗锯齿和动态内容都会影响结果，不代表视觉还原率或验收通过。</p>
      {differenceError && <p role="alert">{differenceError}</p>}
      {difference && <><p>尺寸 {difference.width} × {difference.height}；RGB 平均通道差 {difference.mean_channel_difference} / 255（越低表示像素越接近）。差异亮度放大 3 倍。</p>{!!difference.warnings?.length && <div className="d2c-error" role="status"><strong>截图提示：</strong><ul>{difference.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}<div className="d2c-visual-grid">{difference.candidate_image_data_url && <div><strong>本次比较的页面截图</strong><img src={difference.candidate_image_data_url} alt="本次比较的页面截图" /></div>}<div><strong>像素差异图</strong><img src={difference.image_data_url} alt="像素差异图" /></div></div></>}
    </div>
  </details>;
}

export default function D2CWorkbench() {
  const [images, setImages] = useState<ImageInput[]>([]);
  const [spec, setSpec] = useState("");
  const [figma, setFigma] = useState("");
  const [figmaConnection, setFigmaConnection] = useState("");
  const [figmaChecking, setFigmaChecking] = useState(false);
  const [bundle, setBundle] = useState<ImageInput | null>(null);
  const [instruction, setInstruction] = useState("");
  const [authority, setAuthority] = useState<Record<Dimension, string>>({ layout: "", style: "", content: "", behavior: "" });
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [lastRunError, setLastRunError] = useState("");
  const [pollError, setPollError] = useState("");
  const [pendingRun, setPendingRun] = useState<PendingRun | null>(null);
  const [pendingRepair, setPendingRepair] = useState<PendingRepair | null>(null);
  const [repairError, setRepairError] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [restoreId, setRestoreId] = useState("");
  const [restoreError, setRestoreError] = useState("");
  const [recentRuns, setRecentRuns] = useState<RecentRun[] | null>(null);
  const [recentError, setRecentError] = useState("");
  const [recentBusy, setRecentBusy] = useState(false);
  const [selectedFile, setSelectedFile] = useState(0);
  const [preview, setPreview] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [previewReady, setPreviewReady] = useState(false);
  const [view, setView] = useState<"preview" | "code">("preview");
  const [repairInstruction, setRepairInstruction] = useState("");
  const [selectedElement, setSelectedElement] = useState<SelectedElement | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [imageError, setImageError] = useState("");
  const [imageReads, setImageReads] = useState(0);
  const [draggingImage, setDraggingImage] = useState(false);
  const [draftReady, setDraftReady] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [draftStorageAvailable, setDraftStorageAvailable] = useState(true);
  const draftWrites = useRef<Promise<void>>(Promise.resolve());
  const imagesRef = useRef<ImageInput[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const previewRef = useRef<HTMLIFrameElement>(null);
  const selectionToken = useRef("");

  useEffect(() => {
    let active = true;
    readDraft().then((draft) => {
      if (!active || !draft) return;
      imagesRef.current = draft.images || [];
      setImages(imagesRef.current);
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
    if (!files.length) return;
    setImageError("");
    setImageReads((count) => count + 1);
    const valid = files.filter((file) => ["image/png", "image/jpeg"].includes(file.type) && file.size <= 10 * 1024 * 1024);
    try {
      const results = await Promise.allSettled(valid.map(readScreenshot));
      const incoming = results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
      const combined = [...imagesRef.current, ...incoming];
      imagesRef.current = combined.slice(0, 3);
      setImages(imagesRef.current);
      const messages: string[] = [];
      if (valid.length !== files.length) messages.push("请选择不超过 10 MiB 的 PNG 或 JPEG 图片。");
      if (results.some((result) => result.status === "rejected")) messages.push("部分图片无法读取或超过 4000 万像素，请更换图片。");
      if (combined.length > 3) messages.push("一个页面最多添加 3 张截图。");
      if (messages.length) setImageError(messages.join(" "));
    } catch { setImageError("无法读取图片，请重新选择。"); }
    finally { setImageReads((count) => count - 1); }
  }, []);

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
    // Avoid navigating away and losing the current task when a file misses the drop zone.
    const preventFileNavigation = (event: DragEvent) => {
      if (Array.from(event.dataTransfer?.types || []).includes("Files")) event.preventDefault();
    };
    const clearDrag = () => setDraggingImage(false);
    window.addEventListener("dragover", preventFileNavigation);
    window.addEventListener("drop", preventFileNavigation);
    window.addEventListener("drop", clearDrag);
    return () => {
      window.removeEventListener("dragover", preventFileNavigation);
      window.removeEventListener("drop", preventFileNavigation);
      window.removeEventListener("drop", clearDrag);
    };
  }, []);

  const restoreLastRun = useCallback(async () => {
    let lastRun: string | null;
    try { lastRun = window.localStorage.getItem("d2c_last_run"); }
    catch { setLastRunError("浏览器无法读取最近任务记录；请使用任务 ID 手动恢复。"); return; }
    if (!lastRun) return;
    try {
      const restored = await request<Run>(`/runs/${lastRun}`);
      setRun((current) => current || restored);
      setLastRunError("");
    } catch {
      setLastRunError("暂时无法恢复上次任务；服务恢复后可点击重新检查服务，或按任务 ID 恢复。");
    }
  }, []);
  const refreshCapabilities = useCallback(async () => {
    try {
      setCapabilities(await request<Capabilities>("/capabilities"));
      setConnectionError("");
    } catch {
      setCapabilities(null);
      setConnectionError("无法连接后端，请确认工作台服务已启动后重新检查。");
    }
  }, []);
  async function checkFigmaConnection() {
    setFigmaChecking(true); setFigmaConnection("");
    try {
      const info = await request<{ status: string; sessions: number }>("/figma/connection");
      if (info.status === "connected") setFigmaConnection(`检测到 ${info.sessions} 个 Figma 插件会话。请确认目标文件已正确关联。`);
      else if (info.status === "no_session") setFigmaConnection("Bridge 已启动，但未检测到插件会话。请在 Figma Desktop 中运行插件。");
      else if (info.status === "not_mcp") setFigmaConnection("当前不是 MCP 模式，请检查根目录 .env 配置。");
      else setFigmaConnection("无法连接 Bridge，请重新启动工作台。");
    } catch { setFigmaConnection("无法连接工作台后端，请先启动服务。"); }
    finally { setFigmaChecking(false); }
  }
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("d2c_pending_run");
      if (stored) {
        const pending = JSON.parse(stored) as PendingRun;
        if (typeof pending.key === "string" && typeof pending.sourceSet?.source_set_id === "string" && typeof pending.sourceSet?.source_set_revision === "number" && typeof pending.sourceSet?.source_set_hash === "string") setPendingRun(pending);
      }
    } catch { /* A new submission will report storage issues when it is saved. */ }
    try {
      const stored = window.localStorage.getItem("d2c_pending_repair");
      if (stored) {
        const pending = JSON.parse(stored) as PendingRepair;
        if (/^run_[a-f0-9]{32}$/.test(pending.runId) && typeof pending.instruction === "string" && pending.instruction.length > 0 && pending.instruction.length <= 5000 && typeof pending.key === "string") setPendingRepair(pending);
      }
    } catch { /* The submission path reports storage failures. */ }
    void refreshCapabilities();
    void restoreLastRun();
  }, [refreshCapabilities, restoreLastRun]);

  const pollingRunId = run?.run_id;
  const pollingStatus = run?.status;
  useEffect(() => {
    if (!pollingRunId || !pollingStatus || !["CREATED", "GENERATING", "BUILDING", "REPAIRING"].includes(pollingStatus)) {
      setPollError("");
      return;
    }
    let active = true;
    let timer: number;
    const poll = async () => {
      try {
        const updated = await request<Run>(`/runs/${pollingRunId}`);
        if (active) { setPollError(""); setRun(updated); }
      } catch {
        if (active) setPollError("暂时无法更新任务状态，正在重新连接；不会重新发起模型请求。");
      }
      if (active) timer = window.setTimeout(() => void poll(), 1800);
    };
    timer = window.setTimeout(() => void poll(), 1800);
    return () => { active = false; window.clearTimeout(timer); };
  }, [pollingRunId, pollingStatus]);

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
    let active = true;
    setPreview("");
    setPreviewError("");
    if (!currentRunId || !currentStatus || !["READY_FOR_REVIEW", "COMPLETE_LOCAL"].includes(currentStatus)) return;
    request<{ url: string }>(`/runs/${currentRunId}/preview`).then((value) => { if (active) setPreview(value.url); })
      .catch((caught) => { if (active) setPreviewError(caught instanceof Error ? caught.message : "预览服务启动失败，请检查本机预览端口。"); });
    return () => { active = false; };
  }, [currentRunId, currentStatus, currentCandidate, previewAttempt]);

  async function submitPendingRun(pending: PendingRun) {
    const created = await request<{ run_id: string; status?: string }>("/runs", jsonPost(pending.sourceSet, { "Idempotency-Key": pending.key }));
    setRun({ run_id: created.run_id, status: created.status || "CREATED", error: null, model_requests: 0, repairs: 0, result: null });
    try {
      window.localStorage.setItem("d2c_last_run", created.run_id);
      window.localStorage.removeItem("d2c_pending_run");
      setLastRunError("");
    } catch { setLastRunError("浏览器无法保存最近任务记录，请复制当前任务 ID 以便恢复。"); }
    setPendingRun(null);
  }

  async function recoverPendingRun() {
    if (!pendingRun) return;
    setBusy(true); setError("");
    try { await submitPendingRun(pendingRun); }
    catch { setError("仍无法确认任务是否创建。请检查服务连接后再次恢复，或查看最近的本机任务。"); }
    finally { setBusy(false); }
  }

  function discardPendingRun() {
    try { window.localStorage.removeItem("d2c_pending_run"); setPendingRun(null); setError(""); }
    catch { setError("无法清除恢复记录，请检查浏览器本地存储。"); }
  }

  async function handleGenerate() {
    if (!images.length && !spec.trim() && !figma.trim() && !bundle) { setError("请至少添加一份设计资料。"); return; }
    setBusy(true); setError(""); setSelectedFile(0); setView("preview");
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
      const pending = { sourceSet, key: crypto.randomUUID() };
      // Store before sending: a lost response can then be recovered with the same key.
      try { window.localStorage.setItem("d2c_pending_run", JSON.stringify(pending)); }
      catch { throw new Error("无法保存任务恢复信息，请允许浏览器本地存储后再生成。"); }
      setPendingRun(pending);
      try { await submitPendingRun(pending); }
      catch { throw new Error("任务创建结果尚未确认，请使用下方的恢复按钮；不要重复新建。"); }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }

  async function submitPendingRepair(pending: PendingRepair) {
    await request(`/runs/${pending.runId}/repair`, jsonPost({ instruction: pending.instruction }, { "Idempotency-Key": pending.key }));
    // The same-key replay may refer to an already finished repair; read the current state.
    try { setRun(await request<Run>(`/runs/${pending.runId}`)); }
    catch {
      setRun((current) => current?.run_id === pending.runId ? { ...current, status: "REPAIRING" } : { run_id: pending.runId, status: "REPAIRING", error: null, model_requests: 0, repairs: 0, result: null });
    }
    try {
      window.localStorage.setItem("d2c_last_run", pending.runId);
      window.localStorage.removeItem("d2c_pending_repair");
      setLastRunError("");
    } catch { setLastRunError("浏览器无法保存最近任务记录，请复制当前任务 ID 以便恢复。"); }
    setPendingRepair(null);
    setPreviewAttempt((attempt) => attempt + 1);
    setRepairInstruction("");
  }

  async function recoverPendingRepair() {
    if (!pendingRepair) return;
    setBusy(true); setRepairError("");
    try { await submitPendingRepair(pendingRepair); }
    catch { setRepairError("仍无法确认修改是否提交，请检查服务连接后再次恢复。"); }
    finally { setBusy(false); }
  }

  function discardPendingRepair() {
    try { window.localStorage.removeItem("d2c_pending_repair"); setPendingRepair(null); setRepairError(""); }
    catch { setRepairError("无法清除修改恢复记录，请检查浏览器本地存储。"); }
  }

  async function handleRepair() {
    if (!run || !repairInstruction.trim() || pendingRepair) return;
    setBusy(true); setRepairError("");
    try {
      const fullInstruction = selectedElement ? buildSelectedElementInstruction(repairInstruction, selectedElement.html, selectedElement.context) : repairInstruction;
      if (fullInstruction.length > 5000) throw new Error("修改要求和选中元素内容过长，请缩短要求或选择更小的元素。");
      const pending = { runId: run.run_id, instruction: fullInstruction, key: crypto.randomUUID() };
      try { window.localStorage.setItem("d2c_pending_repair", JSON.stringify(pending)); }
      catch { throw new Error("无法保存修改恢复信息，请允许浏览器本地存储后再提交。"); }
      setPendingRepair(pending);
      try { await submitPendingRepair(pending); }
      catch { throw new Error("修改结果尚未确认，请使用恢复按钮，不要重复提交。"); }
    } catch (caught) { setRepairError(caught instanceof Error ? caught.message : "修复请求失败。"); }
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

  async function handleRestore(selectedId?: string) {
    const id = (selectedId || restoreId).trim();
    if (!/^run_[a-f0-9]{32}$/.test(id)) { setRestoreError("请输入完整的任务 ID，例如 run_ 后跟 32 位字符。"); return; }
    setBusy(true); setRestoreError(""); setRecentError("");
    try {
      const restored = await request<Run>(`/runs/${id}`);
      setSelectedFile(0); setView("preview"); setRun(restored);
      setPreviewAttempt((attempt) => attempt + 1);
      setLastRunError("");
      try { window.localStorage.setItem("d2c_last_run", restored.run_id); }
      catch { setLastRunError("浏览器无法保存最近任务记录，请复制当前任务 ID 以便恢复。"); }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "无法恢复任务。";
      if (selectedId) setRecentError(message); else setRestoreError(message);
    }
    finally { setBusy(false); }
  }

  async function loadRecentRuns() {
    setRecentBusy(true); setRecentError("");
    try { setRecentRuns((await request<{ runs: RecentRun[] }>("/runs?limit=20")).runs); }
    catch { setRecentError("无法读取本机任务列表，请检查后端连接。"); }
    finally { setRecentBusy(false); }
  }

  const isRunning = busy || !!run && ["CREATED", "GENERATING", "BUILDING", "REPAIRING"].includes(run.status);
  const files = run?.result?.files || [];
  if (!draftReady) return <main className="d2c-shell">正在恢复本机草稿…</main>;
  return <div className="d2c-shell">
    <header className="d2c-header"><div className="d2c-brand"><span className="d2c-brand-mark"><LuLayers /></span><div><strong>Design2Code</strong><small>本地设计工作台</small></div></div><div className="d2c-header-right"><span className={`d2c-dot ${capabilities?.provider_configured ? "ready" : ""}`} />{capabilities?.provider_configured ? "模型已配置" : "检查模型配置"}<span className="d2c-local">本机运行</span></div></header>
    <main className="d2c-main"><div className="d2c-intro"><div><div className="d2c-eyebrow">DESIGN MATERIALS → WORKING PAGE</div><h1>把设计，变成可以运行的页面。</h1><p>组合截图、需求和 Figma，告诉我们各自该参考什么。</p></div><div className="d2c-intro-note"><span>输出</span><strong>React + TypeScript</strong></div></div>
      <div className="d2c-grid"><section className="d2c-card d2c-inputs">{draftError && <div className="d2c-error" role="alert">{draftError}</div>}<div className="d2c-section-heading"><div><span className="d2c-step">第一步 · 准备资料</span><h2>设计资料</h2></div><span className="d2c-count">{images.length + Number(!!spec.trim()) + Number(!!figma.trim()) + Number(!!bundle)} 份资料</span></div>
        <p className="d2c-input-guide">添加至少一种资料；可组合截图、Spec、Figma 和项目包。</p>
        <label className="d2c-label">截图 <span>可添加 3 张</span></label>
        <div className={`d2c-drop ${draggingImage ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); if (Array.from(event.dataTransfer.types).includes("Files")) setDraggingImage(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDraggingImage(false); }} onDrop={(event) => { event.preventDefault(); setDraggingImage(false); void addImages(Array.from(event.dataTransfer.files)); }}>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg" multiple hidden onChange={(event) => { void addImages(Array.from(event.target.files || [])); event.target.value = ""; }} />
          <div className="d2c-drop-icon"><LuImagePlus /></div><strong>拖入截图，或 <button type="button" onClick={() => fileRef.current?.click()}>选择图片</button></strong><span><LuClipboardPaste /> 也可以直接 Ctrl + V 粘贴</span>
        </div>
        {imageReads > 0 && <p className="d2c-help" role="status">正在读取截图…</p>}
        {imageError && <div className="d2c-error" role="alert">{imageError}</div>}
        {images.length > 0 && <div className="d2c-thumbnails">{images.map((image, index) => <div className="d2c-thumb" key={`${image.name}-${index}`}><img src={image.data} alt={image.name} /><button type="button" aria-label={`移除 ${image.name}`} onClick={() => { imagesRef.current = imagesRef.current.filter((_, i) => i !== index); setImages(imagesRef.current); }}><LuX /></button></div>)}</div>}
        <label className="d2c-label" htmlFor="d2c-spec">需求 Spec <span>文字或 Markdown</span></label><textarea id="d2c-spec" value={spec} onChange={(event) => setSpec(event.target.value)} placeholder={'例如：任务列表支持搜索、状态筛选和新建弹窗。'} rows={4} />
        <label className="d2c-label" htmlFor="d2c-figma">Figma 节点链接 <span>{!capabilities ? "正在检查配置" : capabilities.figma_mode === "mcp" ? (capabilities.figma_configured ? "MCP 模式；请在 Figma 中运行插件" : "请先安装 MCP Bridge") : (capabilities.figma_configured ? "REST 令牌已配置" : "需要配置访问令牌")}</span></label><input id="d2c-figma" value={figma} onChange={(event) => setFigma(event.target.value)} placeholder="https://www.figma.com/design/…?node-id=…" />
        {capabilities?.figma_mode === "mcp" && <div className="d2c-help"><button type="button" disabled={figmaChecking} onClick={() => void checkFigmaConnection()}>{figmaChecking ? "正在检查…" : "检查 Figma 插件连接"}</button>{figmaConnection && <p role="status">{figmaConnection}</p>}</div>}
        <details className="d2c-advanced"><summary>更多参考资料：FigmaToCode 项目包</summary><label className="d2c-label" htmlFor="d2c-bundle">FigmaToCode 项目包 <span>可选 ZIP，最多 10 MiB</span></label>
        <input id="d2c-bundle" type="file" accept=".zip,application/zip" onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          if (!file.name.toLowerCase().endsWith(".zip") || file.size > 10 * 1024 * 1024) { setError("请选择不超过 10 MiB 的 ZIP 项目包。"); return; }
          void readFile(file).then((value) => { setBundle(value); setError(""); }).catch(() => setError("项目包读取失败。"));
        }} />
        {bundle && <p className="d2c-help">已选择 {bundle.name} <button type="button" onClick={() => setBundle(null)}>移除</button>。源码和图片仅作为参考，包内脚本不会执行。</p>}</details>
        <label className="d2c-label" htmlFor="d2c-instruction">生成指令 <span>说明各份资料的用途</span></label><textarea id="d2c-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：布局按 Figma，颜色参考截图，交互按 Spec。" rows={3} />
        <details><summary>选择各维度的参考来源（可选）</summary>
          {([ ["layout", "布局"], ["style", "视觉样式"], ["content", "内容"], ["behavior", "交互"] ] as const).map(([dimension, label]) =>
            <label className="d2c-label" key={dimension}>{label}<select value={authority[dimension]} onChange={(event) => setAuthority((previous) => ({ ...previous, [dimension]: event.target.value }))}>
              <option value="">按资料角色参考</option>{images.length > 0 && <option value="screenshot">第一张截图</option>}{spec.trim() && <option value="spec">Spec</option>}{figma.trim() && <option value="figma">Figma</option>}{bundle && <option value="figma_bundle">FigmaToCode 项目包</option>}{instruction.trim() && <option value="instructions">生成指令</option>}
            </select></label>)}
        </details>
        <div className="d2c-help d2c-material-summary" aria-label="本次资料摘要">
          <strong>本次资料摘要</strong>
          <p>{images.length ? `${images.length} 张截图作为视觉参考` : "未添加截图"}；{spec.trim() ? "Spec 作为内容与交互参考" : "未添加 Spec"}；{figma.trim() ? "Figma 作为结构参考" : "未添加 Figma"}；{bundle ? "项目包作为源码和图片参考" : "未添加项目包"}。</p>
          <p>资料存在冲突时，请在生成指令中写明以哪一份为准。系统不会自动判断所有冲突。</p>
        </div>
        {error && <div className="d2c-error" role="alert">{error}</div>}
        {pendingRun && <div className="d2c-error" role="status"><strong>有一项任务的创建结果待确认</strong><p>恢复会使用原来的请求标识；如果请求尚未到达服务端，恢复会创建任务并可能调用模型。</p><button type="button" disabled={busy} onClick={() => void recoverPendingRun()}>恢复任务创建</button> <button type="button" disabled={busy} onClick={discardPendingRun}>放弃恢复</button><p>放弃只清除本机恢复记录，不会停止可能已创建的任务；请先查看最近的本机任务。</p></div>}
        <button className="d2c-generate" disabled={isRunning || !!pendingRun || !!pendingRepair || imageReads > 0 || !capabilities?.generation_available} onClick={() => void handleGenerate()}>{isRunning ? <><LuRefreshCw className="d2c-spin" /> 正在处理</> : <>确认资料并生成 <LuArrowUpRight /></>}</button>
        {run && ["CREATED", "GENERATING", "BUILDING", "REPAIRING"].includes(run.status) && <button type="button" disabled={busy} onClick={() => void handleStop()}>停止当前任务</button>}
        {!capabilities?.generation_available && <div className="d2c-help" role="status">
          <p>{connectionError || (!capabilities ? "正在检查本机服务…" : "生成暂不可用，请检查以下配置和依赖。")}</p>
          {!!capabilities?.configuration_issues.length && <ul>{capabilities.configuration_issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
          {capabilities && (capabilities.token_limit_configured || capabilities.cost_limit_configured) && <p>当前版本不执行预算上限，请将根目录 .env 中的 D2C_TOKEN_LIMIT 和 D2C_COST_LIMIT_MICRO_USD 留空后重启服务。</p>}
          {capabilities && !capabilities.configuration_issues.length && !capabilities.token_limit_configured && !capabilities.cost_limit_configured && <p>请确认 pnpm 已安装，且工程模板的锁文件存在。</p>}
          <button type="button" onClick={() => { void refreshCapabilities(); void restoreLastRun(); }}>重新检查服务</button>
        </div>}
      </section><section className="d2c-card d2c-result"><div className="d2c-section-heading"><div><span className="d2c-step">第二步 · 查看与修改</span><h2>生成结果</h2></div><span className="d2c-status"><span className={`d2c-dot ${run && ["READY_FOR_REVIEW", "COMPLETE_LOCAL"].includes(run.status) ? "ready" : ""}`} />{run ? statusText[run.status] || run.status : "等待开始"}</span></div>
        {lastRunError && <div className="d2c-error" role="status">{lastRunError}</div>}
        {pollError && <div className="d2c-error" role="status">{pollError}</div>}
        {repairError && <div className="d2c-error" role="alert">{repairError}</div>}
        {pendingRepair && <div className="d2c-error" role="status"><strong>修改请求待确认</strong><p>任务 {pendingRepair.runId} 的修改要求保存在此浏览器。恢复使用原请求标识；如果原请求未到达服务端，恢复会提交修改并可能调用模型。</p><button type="button" disabled={busy} onClick={() => void recoverPendingRepair()}>恢复修改请求</button> <button type="button" disabled={busy} onClick={discardPendingRepair}>放弃恢复修改</button><p>放弃仅清除本机记录，不会停止可能已开始的修改。请先恢复该任务并查看状态。</p></div>}
        <details><summary>最近的本机任务</summary><p className="d2c-help">从本机记录中选择，恢复只读取已有任务，不重新发起模型请求。</p><button type="button" disabled={recentBusy} onClick={() => void loadRecentRuns()}>{recentBusy ? "正在读取…" : "读取最近 20 个任务"}</button>{recentError && <p role="alert">{recentError}</p>}{recentRuns && (recentRuns.length ? <ul>{recentRuns.map((item) => <li key={item.run_id}><button type="button" disabled={isRunning} onClick={() => void handleRestore(item.run_id)}>恢复 {item.run_id}</button> {statusText[item.status] || item.status} · {new Date(item.created_at).toLocaleString()} · 模型请求 {item.model_requests} 次</li>)}</ul> : <p>本机没有任务记录。</p>)}</details>
        <details><summary>按任务 ID 恢复</summary><label className="d2c-label" htmlFor="d2c-restore">完整任务 ID</label><input id="d2c-restore" value={restoreId} onChange={(event) => { setRestoreId(event.target.value); setRestoreError(""); }} placeholder="run_…" aria-invalid={!!restoreError} aria-describedby={restoreError ? "d2c-restore-error" : undefined} /><button type="button" disabled={isRunning || !restoreId.trim()} onClick={() => void handleRestore()}>恢复任务</button>{restoreError && <div id="d2c-restore-error" className="d2c-error" role="alert">{restoreError}</div>}</details>
        {!run && <div className="d2c-empty"><div className="d2c-paper"><LuFileCode /><span>YOUR PAGE</span><i /><i /><i /></div><strong>你的页面会显示在这里</strong><p>添加一种或多种资料，填写生成指令后开始。</p><div><LuPlus /> 截图 <LuPlus /> Spec <LuPlus /> Figma</div></div>}
        {run && <div className="d2c-result-content">{run.error && <div className="d2c-error">{run.error}</div>}<div className="d2c-run-meta">任务 {run.run_id} <span>模型请求 {run.model_requests} 次</span></div>{files.length > 0 ? <><div className="d2c-result-actions"><button type="button" className={view === "preview" ? "active" : ""} onClick={() => setView("preview")}>页面预览</button><button type="button" className={view === "code" ? "active" : ""} onClick={() => setView("code")}>查看源码</button>{!!run.result?.checks?.length && <a href="#d2c-check-results">检查结果</a>}{["READY_FOR_REVIEW", "COMPLETE_LOCAL", "FAILED"].includes(run.status) && <a href={`${api}/runs/${run.run_id}/export`}>下载工程</a>}</div>{view === "preview" ? preview ? <><iframe ref={previewRef} title="生成页面预览" className="d2c-preview" sandbox="allow-scripts allow-forms" src={preview} onLoad={() => { setPreviewReady(true); setSelecting(false); setSelectedElement(null); selectionToken.current = ""; }} />{run.status === "READY_FOR_REVIEW" && run.repairs < 1 && run.model_requests < 2 && <div><button type="button" disabled={!previewReady} onClick={toggleSelection}>{selecting ? "取消选取" : "在预览中选取元素"}</button>{selecting && <span> 请点击预览中的元素</span>}{selectedElement && <p>已选：{selectedElement.label || "页面元素"} <button type="button" onClick={() => setSelectedElement(null)}>清除</button></p>}</div>}</> : <div className="d2c-preview-placeholder">{run.status === "FAILED" ? "任务未完成，暂时无法预览。请查看错误信息和检查结果。" : previewError ? <><p role="alert">预览启动失败：{previewError}</p><button type="button" onClick={() => setPreviewAttempt((attempt) => attempt + 1)}>重试预览</button></> : "等待构建并启动预览。"}</div> : <><div className="d2c-file-tabs">{files.map((file, index) => <button type="button" key={file.path} className={selectedFile === index ? "active" : ""} onClick={() => setSelectedFile(index)}>{file.path}</button>)}</div><pre className="d2c-code"><code>{files[selectedFile]?.content}</code></pre></>}{["READY_FOR_REVIEW", "COMPLETE_LOCAL"].includes(run.status) && <VisualReview runId={run.run_id} candidate={run.result?.candidate_name} />}{!!run.result?.checks?.length && <section id="d2c-check-results" className="d2c-check-results" aria-label="检查结果"><h3>检查结果</h3>{run.result.checks.map((check) => <div className="d2c-check" key={check.id}><strong>{checkStatusText[check.status] || check.status}</strong> {check.message}</div>)}</section>}{run.result?.build_details && <details><summary>构建详情</summary><pre className="d2c-code">{run.result.build_details}</pre></details>}{["READY_FOR_REVIEW", "FAILED"].includes(run.status) && run.repairs < 1 && run.model_requests < 2 && <div className="d2c-repair"><label htmlFor="d2c-repair">需要修改什么？</label><textarea id="d2c-repair" rows={2} value={repairInstruction} onChange={(event) => setRepairInstruction(event.target.value)} placeholder="例如：将主按钮改为蓝色，保持其他布局。" /><button disabled={busy || !!pendingRepair || !repairInstruction.trim()} onClick={() => void handleRepair()}>修改页面（剩余 1 次）</button></div>}</> : <><p className="d2c-help">{statusText[run.status] || "正在处理"}</p>{!!run.result?.checks?.length && <section className="d2c-check-results" aria-label="检查结果"><h3>检查结果</h3>{run.result.checks.map((check) => <div className="d2c-check" key={check.id}><strong>{checkStatusText[check.status] || check.status}</strong> {check.message}</div>)}</section>}{run.status === "FAILED" && run.result && run.repairs < 1 && run.model_requests < 2 && <div className="d2c-repair"><label htmlFor="d2c-repair-invalid">生成内容无效，可提交一次修改要求</label><textarea id="d2c-repair-invalid" rows={2} value={repairInstruction} onChange={(event) => setRepairInstruction(event.target.value)} placeholder="例如：修正返回格式，生成完整的页面文件。" /><button disabled={busy || !!pendingRepair || !repairInstruction.trim()} onClick={() => void handleRepair()}>修复生成结果（剩余 1 次）</button></div>}</>}</div>}
      </section></div><footer className="d2c-footer">DESIGN2CODE <span>设计资料保存在本机 · 模型生成通过已配置的服务执行</span></footer></main>
  </div>;
}
