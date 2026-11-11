import { Tabs, TabsList, TabsTrigger, TabsContent } from "../ui/tabs";
import {
  FaDesktop,
  FaMobile,
  FaCode,
} from "react-icons/fa";
import {
  LuChevronLeft,
  LuChevronRight,
  LuExternalLink,
  LuRefreshCw,
  LuDownload,
} from "react-icons/lu";
import { MutableRefObject, ReactNode, useMemo, useState } from "react";
import { AppState, EditorTheme, Settings } from "../../types";
import CodeTab from "./CodeTab";
import { Button } from "../ui/button";
import { useAppStore } from "../../store/app-store";
import { useProjectStore } from "../../store/project-store";
import { extractHtml } from "./extractHtml";
import PreviewComponent from "./PreviewComponent";
import { downloadCode } from "./download";
import { SelectAndEditToolbarButton } from "../select-and-edit/SelectAndEditControls";
import { normalizeBabelCdn } from "../../lib/babelCdn";
import ImageScanningPreview from "./ImageScanningPreview";
import CodeMirror from "./CodeMirror";

interface ProjectPreviewProps {
  url: string;
  files: { path: string; content: string }[];
  selectedFile: number;
  onFileChange: (index: number) => void;
  view: "preview" | "code";
  onViewChange: (view: "preview" | "code") => void;
  frameRef: MutableRefObject<HTMLIFrameElement | null>;
  onLoad: () => void;
  onRefresh: () => void;
  placeholder: ReactNode;
  actions?: ReactNode;
  selection?: ReactNode;
}

// The same upstream preview, tabs and CodeMirror now accept a built multi-file
// project. Run state remains owned by the workbench; no synthetic HTML commits.
export function ProjectPreviewPane(props: ProjectPreviewProps) {
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [mode, setMode] = useState<"fit" | "actual">("fit");
  const [scale, setScale] = useState(1);
  const activeTab = props.view === "code" ? "code" : device;
  const file = props.files[props.selectedFile] || props.files[0];
  return <Tabs value={activeTab} onValueChange={(value) => {
    props.onViewChange(value === "code" ? "code" : "preview");
    if (value === "desktop" || value === "mobile") setDevice(value);
  }} className="d2c-native-preview">
    <div className="d2c-result-actions">
      <TabsList aria-label="结果视图">
        <TabsTrigger value="desktop"><FaDesktop /> 桌面预览</TabsTrigger>
        <TabsTrigger value="mobile"><FaMobile /> 手机预览</TabsTrigger>
        <TabsTrigger value="code"><FaCode /> 查看源码</TabsTrigger>
      </TabsList>
      {props.actions}
    </div>
    {props.view === "preview" && <div className="d2c-preview-controls">
      <button type="button" aria-pressed={mode === "fit"} onClick={() => setMode("fit")}>适应面板{mode === "fit" ? ` · ${Math.round(scale * 100)}%` : ""}</button>
      <button type="button" aria-pressed={mode === "actual"} onClick={() => setMode("actual")}>原始尺寸</button>
      <span>{device === "desktop" ? "1440 × 900" : "390 × 844"}</span>
      <button type="button" onClick={props.onRefresh}>重新加载预览</button>
    </div>}
    {(["desktop", "mobile"] as const).map((target) => <TabsContent key={target} value={target}>
      {props.url ? <div className="d2c-native-viewport"><PreviewComponent code="" device={target} viewMode={mode} title="生成页面预览" onScaleChange={setScale}
        project={{ url: props.url, viewport: target === "desktop" ? { width: 1440, height: 900 } : { width: 390, height: 844 }, frameRef: props.frameRef, onLoad: props.onLoad }} /></div> : props.placeholder}
      {props.url && props.selection}
    </TabsContent>)}
    <TabsContent value="code">
      <div className="d2c-file-tabs" role="group" aria-label="工程文件">{props.files.map((item, index) => <button type="button" key={item.path} aria-pressed={props.selectedFile === index} className={props.selectedFile === index ? "active" : ""} onClick={() => props.onFileChange(index)}>{item.path}</button>)}</div>
      <p className="d2c-help">当前候选源码（只读）。修改页面请使用下方的修改要求；导出内容与本次构建一致。</p>
      <CodeMirror key={file?.path} code={file?.content || ""} editorTheme={EditorTheme.COBALT} onCodeChange={() => {}} readOnly language={/\.html?$/.test(file?.path || "") ? "html" : "text"} label={`源码 ${file?.path || ""}`} className="d2c-native-code" />
    </TabsContent>
  </Tabs>;
}

function prepareHtmlForNewTab(code: string) {
  const html = normalizeBabelCdn(code);
  if (/<base\s/i.test(html)) return html;

  const baseTag = `<base href="${window.location.origin}/">`;
  return html.replace(/<head(\s[^>]*)?>/i, (match) => `${match}${baseTag}`);
}

function openInNewTab(code: string) {
  const blob = new Blob([prepareHtmlForNewTab(code)], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

interface Props {
  settings: Settings;
  onOpenVersions: () => void;
}

function PreviewPane({ settings, onOpenVersions }: Props) {
  const { appState } = useAppStore();
  const { inputMode, head, commits, setHead } = useProjectStore();
  const [activeTab, setActiveTab] = useState("desktop");
  const [desktopScale, setDesktopScale] = useState(1);
  const [desktopViewMode, setDesktopViewMode] = useState<"fit" | "actual">("fit");

  // Sorted commit list for version navigation
  const sortedCommits = useMemo(() =>
    Object.values(commits).sort(
      (a, b) => new Date(a.dateCreated).getTime() - new Date(b.dateCreated).getTime()
    ), [commits]);

  const currentVersionIndex = sortedCommits.findIndex(c => c.hash === head);
  const totalVersions = sortedCommits.length;
  const canGoPrev = currentVersionIndex > 0;
  const canGoNext = currentVersionIndex < totalVersions - 1;

  const currentCommit = head && commits[head] ? commits[head] : "";
  const currentCode = currentCommit
    ? currentCommit.variants[currentCommit.selectedVariantIndex].code
    : "";

  const isSelectedVariantComplete =
    head &&
    commits[head] &&
    commits[head].variants[commits[head].selectedVariantIndex].status ===
      "complete";

  const previewCode =
    inputMode === "video" && appState === AppState.CODING
      ? extractHtml(currentCode)
      : currentCode;
  const sourceImage = currentCommit ? currentCommit.inputs?.images[0] : undefined;
  const showImageScanningPreview =
    appState === AppState.CODING &&
    currentCommit !== "" &&
    currentCommit.type === "ai_create" &&
    inputMode === "image" &&
    !previewCode.trim() &&
    !!sourceImage;

  const canSelectAndEdit =
    appState === AppState.CODE_READY || !!isSelectedVariantComplete;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="flex-1 flex flex-col min-h-0"
      >
        <div className="relative flex items-center justify-between px-4 py-2 shrink-0 border-b border-gray-200 dark:border-zinc-800 bg-white dark:bg-zinc-950">
          <div className="flex items-center gap-2">
            <TabsList>
              <TabsTrigger value="desktop" title="Desktop" data-testid="tab-desktop">
                <FaDesktop />
              </TabsTrigger>
              <TabsTrigger value="mobile" title="Mobile" data-testid="tab-mobile">
                <FaMobile />
              </TabsTrigger>
              <TabsTrigger value="code" title="Code" data-testid="tab-code" className="gap-2">
                <FaCode />
                Code
              </TabsTrigger>
            </TabsList>
            {(activeTab === "desktop" || activeTab === "mobile") && (
              <div className="hidden sm:inline-flex items-center gap-2">
                {activeTab === "desktop" && (
                  <div className="inline-flex items-center rounded-lg bg-gray-100 p-1 dark:bg-zinc-800">
                    <button
                      type="button"
                      onClick={() => setDesktopViewMode("fit")}
                      title="Scale down to fit the screen"
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                        desktopViewMode === "fit"
                          ? "bg-white text-gray-900 shadow-sm dark:bg-zinc-600 dark:text-zinc-100"
                          : "text-gray-500 hover:text-gray-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                      }`}
                    >
                      Scale
                      {desktopScale < 1 && (
                        <span className="ml-1 text-violet-600 dark:text-violet-300 font-bold">
                          ({Math.round(desktopScale * 100)}%)
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => setDesktopViewMode("actual")}
                      title="View at original size (100%)"
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                        desktopViewMode === "actual"
                          ? "bg-white text-gray-900 shadow-sm dark:bg-zinc-600 dark:text-zinc-100"
                          : "text-gray-500 hover:text-gray-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                      }`}
                    >
                      100%
                    </button>
                  </div>
                )}
                <Button
                  onClick={() => openInNewTab(previewCode)}
                  variant="ghost"
                  size="icon"
                  title="Open in New Tab"
                  className="h-8 w-8"
                >
                  <LuExternalLink />
                </Button>
              </div>
            )}
          </div>

          {/* Version navigation */}
          {totalVersions > 0 && (
            <div className="hidden md:flex shrink-0 items-center justify-center gap-1 bg-gray-100/50 dark:bg-zinc-800/50 rounded-full p-1 border border-gray-200/50 dark:border-zinc-700/50 backdrop-blur-sm">
              <Button
                onClick={() => canGoPrev && setHead(sortedCommits[currentVersionIndex - 1].hash)}
                variant="ghost"
                size="icon"
                title="Previous version"
                className={`h-6 w-6 rounded-full hover:bg-white dark:hover:bg-zinc-700 ${!canGoPrev ? "opacity-30 cursor-not-allowed" : ""}`}
                disabled={!canGoPrev}
              >
                <LuChevronLeft className="w-3.5 h-3.5" />
              </Button>
              <div
                onClick={onOpenVersions}
                className="flex items-center justify-center gap-2 px-1 cursor-pointer hover:opacity-70 transition-opacity w-32"
                title="View all versions"
              >
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 leading-none">
                  Version {currentVersionIndex + 1}
                </span>
                {currentVersionIndex === totalVersions - 1 && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300 leading-none flex items-center h-4">
                    Latest
                  </span>
                )}
              </div>
              <Button
                onClick={() => canGoNext && setHead(sortedCommits[currentVersionIndex + 1].hash)}
                variant="ghost"
                size="icon"
                title="Next version"
                className={`h-6 w-6 rounded-full hover:bg-white dark:hover:bg-zinc-700 ${!canGoNext ? "opacity-30 cursor-not-allowed" : ""}`}
                disabled={!canGoNext}
              >
                <LuChevronRight className="w-3.5 h-3.5" />
              </Button>
            </div>
          )}

          <div className="flex items-center gap-1">
            {canSelectAndEdit &&
              (activeTab === "desktop" || activeTab === "mobile") && (
                <SelectAndEditToolbarButton />
              )}
            {(appState === AppState.CODE_READY || isSelectedVariantComplete) && (
              <Button
                onClick={() => downloadCode(previewCode)}
                variant="ghost"
                size="icon"
                title="Download Code"
                className="h-9 w-9"
                data-testid="download-code"
              >
                <LuDownload />
              </Button>
            )}
            <Button
              onClick={() => {
                const iframes = document.querySelectorAll("iframe");
                iframes.forEach((iframe) => {
                  if (iframe.srcdoc) {
                    const content = iframe.srcdoc;
                    iframe.srcdoc = "";
                    iframe.srcdoc = content;
                  }
                });
              }}
              variant="ghost"
              size="icon"
              title="Refresh Preview"
              className="h-9 w-9"
            >
              <LuRefreshCw />
            </Button>
          </div>
        </div>
        <TabsContent value="desktop" className="flex-1 min-h-0 mt-0 data-[state=active]:flex data-[state=active]:flex-col">
          {showImageScanningPreview ? (
            <ImageScanningPreview imageUrl={sourceImage} />
          ) : (
            <PreviewComponent
              code={previewCode}
              device="desktop"
              onScaleChange={setDesktopScale}
              viewMode={desktopViewMode}
            />
          )}
        </TabsContent>
        <TabsContent value="mobile" className="flex-1 min-h-0 mt-0 data-[state=active]:flex data-[state=active]:flex-col">
          {showImageScanningPreview ? (
            <ImageScanningPreview imageUrl={sourceImage} />
          ) : (
            <PreviewComponent
              code={previewCode}
              device="mobile"
              viewMode="actual"
            />
          )}
        </TabsContent>
        <TabsContent value="code" className="flex-1 min-h-0 mt-0 overflow-auto">
          <CodeTab
            code={previewCode}
            setCode={() => {}}
            settings={settings}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default PreviewPane;
