import React, { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Stack } from "../../lib/stacks";
import { DesignSystem, Settings } from "../../types";
import UploadTab from "./tabs/UploadTab";
import UrlTab from "./tabs/UrlTab";
import TextTab from "./tabs/TextTab";
import ImportTab from "./tabs/ImportTab";
import { DesignSystemSelectorProps } from "../settings/DesignSystemSelector";

interface Props {
  doCreate: (
    images: string[],
    inputMode: "image" | "video",
    textPrompt?: string,
    isAssetExtractionEnabled?: boolean
  ) => void;
  doCreateFromText: (text: string) => void;
  importFromCode: (code: string, stack: Stack) => void;
  settings: Settings;
  setSettings: React.Dispatch<React.SetStateAction<Settings>>;
  designSystems: DesignSystem[];
  onAddNewDesignSystem: () => void;
  onManageDesignSystems: () => void;
}

type InputTab = "upload" | "url" | "text" | "import";

function NativeInputPane({
  doCreate,
  doCreateFromText,
  importFromCode,
  settings,
  setSettings,
  designSystems,
  onAddNewDesignSystem,
  onManageDesignSystems,
}: Props) {
  const [activeTab, setActiveTab] = useState<InputTab>("upload");

  function setStack(stack: Stack) {
    setSettings((prev: Settings) => ({
      ...prev,
      generatedCodeConfig: stack,
    }));
  }

  function setSelectedDesignSystemId(id: string | null) {
    setSettings((prev: Settings) => ({
      ...prev,
      selectedDesignSystemId: id,
    }));
  }

  const designSystemSelectorProps: DesignSystemSelectorProps = {
    designSystems,
    selectedDesignSystemId: settings.selectedDesignSystemId,
    setSelectedDesignSystemId,
    onAddNew: onAddNewDesignSystem,
    onManage: onManageDesignSystems,
  };

  return (
    <div className="w-full max-w-4xl mx-auto px-4">
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as InputTab)}
        className="w-full"
      >
        <TabsList className="grid w-full grid-cols-4 mb-6">
          <TabsTrigger
            value="upload"
            className="flex items-center gap-2"
            data-testid="tab-upload"
          >
            <UploadIcon />
            <span className="hidden sm:inline">Upload</span>
          </TabsTrigger>
          <TabsTrigger
            value="url"
            className="flex items-center gap-2"
            data-testid="tab-url"
          >
            <UrlIcon />
            <span className="hidden sm:inline">URL</span>
          </TabsTrigger>
          <TabsTrigger
            value="text"
            className="flex items-center gap-2"
            data-testid="tab-text"
          >
            <TextIcon />
            <span className="hidden sm:inline">Text</span>
          </TabsTrigger>
          <TabsTrigger
            value="import"
            className="flex items-center gap-2"
            data-testid="tab-import"
          >
            <ImportIcon />
            <span className="hidden sm:inline">Import</span>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="upload" className="mt-0">
          <UploadTab
            doCreate={doCreate}
            stack={settings.generatedCodeConfig}
            setStack={setStack}
            designSystem={designSystemSelectorProps}
          />
        </TabsContent>

        <TabsContent value="url" className="mt-0">
          <UrlTab
            doCreate={doCreate}
            screenshotOneApiKey={settings.screenshotOneApiKey}
            stack={settings.generatedCodeConfig}
            setStack={setStack}
            designSystem={designSystemSelectorProps}
          />
        </TabsContent>

        <TabsContent value="text" className="mt-0">
          <TextTab
            doCreateFromText={doCreateFromText}
            stack={settings.generatedCodeConfig}
            setStack={setStack}
            designSystem={designSystemSelectorProps}
          />
        </TabsContent>

        <TabsContent value="import" className="mt-0">
          <ImportTab importFromCode={importFromCode} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

type ProjectInputs = { screenshot: React.ReactNode; spec: React.ReactNode; figma: React.ReactNode;
  counts: { screenshot: number; spec: number; figma: number } };

function ProjectInputPane({ project }: { project: ProjectInputs }) {
  const [active, setActive] = useState("screenshot");
  return <Tabs value={active} onValueChange={setActive} className="d2c-unified-input">
    <TabsList aria-label="设计资料类型" className="d2c-input-tab-list">
      {([["screenshot", "截图"], ["spec", "Spec 需求"], ["figma", "Figma"]] as const).map(([key, label]) =>
        <TabsTrigger key={key} value={key}>{label}{project.counts[key] ? ` · ${project.counts[key]}` : ""}</TabsTrigger>)}
    </TabsList>
    <p className="d2c-help">标签用于整理资料；已添加的各类资料会一起生成。</p>
    {(["screenshot", "spec", "figma"] as const).map((key) => <TabsContent key={key} value={key} forceMount className="d2c-input-panel data-[state=inactive]:hidden">{project[key]}</TabsContent>)}
  </Tabs>;
}

function UnifiedInputPane(props: Props | { project: ProjectInputs }) {
  return "project" in props ? <ProjectInputPane project={props.project} /> : <NativeInputPane {...props} />;
}

function UploadIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function UrlIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  );
}

function TextIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17 6.1H3" />
      <path d="M21 12.1H3" />
      <path d="M15.1 18H3" />
    </svg>
  );
}

function ImportIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  );
}

export default UnifiedInputPane;
