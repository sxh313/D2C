import { useEffect, useState } from "react";

type Artifact = {
  artifact_hash: string; transport: string; converter_version: string | null;
  provenance: string; warnings: string[];
  files: { path: string; content_hash: string }[];
  assets: { path: string; content_hash: string }[];
};
type Source = { input_id: string; artifact?: Artifact | null };
type Project = {
  mode: string; artifact_hash: string; warnings: string[]; operations: string[];
  files: { path: string; source_path: string | null; base_hash: string | null; content_hash: string; change: string }[];
};

export function FigmaArtifacts({ runId, revision }: { runId: string; revision?: unknown }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setError("");
    const get = async (path: string) => {
      const response = await fetch("/api/d2c/v1" + path, { signal: abort.signal });
      if (!response.ok) throw new Error("无法读取转换产物记录");
      return response.json();
    };
    void (async () => {
      const run = await get("/runs/" + runId) as { source_set_id: string; result?: { project?: Project | null } };
      const sourceSet = await get("/source-sets/" + run.source_set_id) as { sources: Source[] };
      if (!abort.signal.aborted) {
        setSources(sourceSet.sources.filter((source) => source.artifact));
        setProject(run.result?.project || null);
      }
    })().catch(() => { if (!abort.signal.aborted) setError("无法读取 Figma 转换产物记录，请稍后恢复任务重试。"); });
    return () => abort.abort();
  }, [runId, revision]);
  if (error) return <p role="alert">{error}</p>;
  if (!sources.length) return null;
  return <details className="d2c-advanced">
    <summary>FigmaToCode 转换产物与来源（{sources.length}）</summary>
    {sources.map(({ input_id, artifact }) => artifact && <section key={input_id}>
      <p>{artifact.transport === "desktop_bridge" ? "插件直连" : "项目包导入"} · 转换器版本：{artifact.converter_version || "未知（旧 ZIP 不含版本）"}</p>
      <p>{artifact.provenance === "plugin_execution" ? "本地插件执行记录" : "来源由用户声明，未验证转换器身份"}</p>
      <p>产物哈希：<code>{artifact.artifact_hash}</code></p>
      <p>{artifact.files.length} 个已载入源码文件 · {artifact.assets.length} 个图片资源</p>
      <a href={`/api/d2c/v1/design-inputs/${input_id}/artifact-archive`}>下载未修改的原始转换包</a>
      <ul>{artifact.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
      <details><summary>文件与资源哈希</summary><pre className="d2c-code">{[...artifact.files, ...artifact.assets].map((file) => `${file.path}  ${file.content_hash}`).join("\n")}</pre></details>
    </section>)}
    {project && <section aria-label="转换源码与当前候选的关联">
      <h3>当前候选工程</h3>
      <p>{project.mode === "conversion_only" ? "直接构建转换源码（未调用模型）" : "官方 Agent 在转换工程上修改"}</p>
      <p>基准产物：<code>{project.artifact_hash}</code> · 成功文件操作 {project.operations.length} 次</p>
      <ul>{project.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
      <details><summary>文件来源、差异与哈希（{project.files.length}）</summary>
        {project.files.map((file) => <div key={file.path}>
          <strong>{file.path}</strong> · {{ unchanged: "未修改", modified: "已修改", added: "新增" }[file.change] || file.change}
          <p>{file.source_path ? `来源：${file.source_path}` : "受控模板或新增文件"}</p>
          <pre className="d2c-code">{`基准：${file.base_hash || "无"}\n当前：${file.content_hash}`}</pre>
        </div>)}
      </details>
    </section>}
  </details>;
}
