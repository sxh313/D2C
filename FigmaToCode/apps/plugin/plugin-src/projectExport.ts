import { flutterMain, tailwindMain, swiftuiMain, htmlMain, extractProjectImageNodeIds, generateProjectZip, replaceProjectImagePlaceholders } from "backend";
import { nodesToJSON } from "backend/src/altNodes/jsonNodeConversion";
import { oldConvertNodesToAltNodes } from "backend/src/altNodes/oldAltConversion";
import { exportNodeAsPNG } from "backend/src/common/images";
import type { DownloadProjectFormat, PluginSettings } from "types";

// Extracted from the original plugin download path; shared by download and D2C Bridge.
type ExportedProjectImage = {
  name: string;
  bytes: Uint8Array;
  nodeId: string;
};

const allowedFormatsByFramework: Record<
  "Flutter" | "HTML" | "SwiftUI" | "Tailwind",
  DownloadProjectFormat[]
> = {
  Flutter: ["flutter"],
  HTML: ["html", "nextjs", "vite"],
  SwiftUI: ["swiftui"],
  Tailwind: ["html", "nextjs", "vite"],
};

const toKebab = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");

const getRootSelectionName = (selection: readonly SceneNode[]) => {
  if (selection.length === 0) {
    return "figma-export";
  }

  if (selection.length === 1) {
    return toKebab(selection[0].name) || "figma-export";
  }

  return (
    toKebab(selection[0].parent?.name ?? "figma-selection") || "figma-selection"
  );
};

const createImageName = (nodeId: string, nodeName: string) => {
  const cleanName = toKebab(nodeName);
  const suffix = nodeId.replace(/[^a-z0-9]+/gi, "-").replace(/(^-|-$)/g, "");
  return `${cleanName || "image"}-${suffix}.png`;
};

const isImageNode = (node: SceneNode): boolean => {
  if ("fills" in node) {
    const fills = node.fills;
    if (fills && fills !== figma.mixed && Array.isArray(fills)) {
      return fills.some((fill) => fill.type === "IMAGE");
    }
  }

  return false;
};

const exportProjectImages = async (
  selection: readonly SceneNode[],
  requiredNodeIds: ReadonlySet<string>,
): Promise<ExportedProjectImage[]> => {
  const images: ExportedProjectImage[] = [];
  const missingNodeIds = new Set(requiredNodeIds);

  const visit = async (node: SceneNode) => {
    if (node.visible === false) {
      return;
    }

    if (missingNodeIds.has(node.id)) {
      if (!isImageNode(node) || !("exportAsync" in node)) {
        throw new Error(
          `Node ${node.name || node.id} cannot be exported as an image.`,
        );
      }

      const hasChildren = "children" in node && node.children.length > 0;
      const bytes = await exportNodeAsPNG(node, hasChildren);
      images.push({
        bytes,
        name: createImageName(node.id, node.name),
        nodeId: node.id,
      });
      missingNodeIds.delete(node.id);
    }

    if ("children" in node) {
      for (const child of node.children) {
        await visit(child);
      }
    }
  };

  for (const node of selection) {
    await visit(node);
  }

  if (missingNodeIds.size > 0) {
    throw new Error(
      `Could not find ${missingNodeIds.size} image layer${
        missingNodeIds.size === 1 ? "" : "s"
      } in the selected content.`,
    );
  }

  return images;
};

const getConvertedSelectionForDownload = async (
  nodes: readonly SceneNode[],
  pluginSettings: PluginSettings,
): Promise<SceneNode[]> => {
  if (nodes.length === 0) {
    return [];
  }

  const convertedSelection = pluginSettings.useOldPluginVersion2025
    ? oldConvertNodesToAltNodes(nodes, null)
    : await nodesToJSON(nodes, pluginSettings);
  return convertedSelection as unknown as SceneNode[];
};

const generateDownloadCode = async (
  nodes: readonly SceneNode[],
  format: DownloadProjectFormat,
  pluginSettings: PluginSettings,
) => {
  const convertedSelection = await getConvertedSelectionForDownload(
    nodes,
    pluginSettings,
  );

  if (convertedSelection.length === 0) {
    return "<div>No content to export</div>";
  }

  const settings = {
    ...pluginSettings,
    embedImages: false,
    imagePlaceholderMode: "asset" as const,
  };
  const isReactProject = format === "nextjs" || format === "vite";

  if (pluginSettings.framework === "Flutter") {
    return flutterMain(convertedSelection, {
      ...settings,
      flutterGenerationMode: "fullApp",
    });
  }

  if (pluginSettings.framework === "SwiftUI") {
    return swiftuiMain(convertedSelection, {
      ...settings,
      swiftUIGenerationMode: "preview",
    });
  }

  if (pluginSettings.framework === "Tailwind") {
    const result = await tailwindMain(convertedSelection, {
      ...settings,
      tailwindGenerationMode: isReactProject ? "jsx" : "html",
    });
    return result || "<div>Failed to generate Tailwind</div>";
  }

  const result = await htmlMain(
    convertedSelection,
    {
      ...settings,
      htmlGenerationMode: isReactProject ? "jsx" : "html",
    },
    true,
  );
  return result?.html || "<div>Failed to generate HTML</div>";
};

export const createProjectExport = async (selection: readonly SceneNode[], format: DownloadProjectFormat, pluginSettings: PluginSettings) => {
  if (!["flutter", "html", "nextjs", "swiftui", "vite"].includes(format)) {
    throw new Error(`Invalid download format: ${format}.`);
  }

  if (
    pluginSettings.framework === "Compose" ||
    !allowedFormatsByFramework[pluginSettings.framework].includes(format)
  ) {
    throw new Error(
      `${format} export is not available for ${pluginSettings.framework}.`,
    );
  }

  if (selection.length === 0) {
    throw new Error("Please select at least one layer to export.");
  }

  const rawCode = await generateDownloadCode(selection, format, pluginSettings);
  const requiredImageNodeIds = extractProjectImageNodeIds(rawCode);
  let images: ExportedProjectImage[];
  try {
    images = await exportProjectImages(selection, requiredImageNodeIds);
  } catch (error) {
    throw new Error("ASSET_FAILED: " + (error instanceof Error ? error.message : String(error)));
  }
  const code = replaceProjectImagePlaceholders(rawCode, images, format);
  const rootName = getRootSelectionName(selection);
  const rawAssetSize = images.reduce(
    (sum, image) => sum + image.bytes.byteLength,
    0,
  );
  const maxRawAssetSizeBytes = 25 * 1024 * 1024;
  if (rawAssetSize > maxRawAssetSizeBytes) {
    throw new Error(
      `Images are too large (${Math.round(rawAssetSize / 1024 / 1024)}MB). Try selecting fewer images or smaller components.`,
    );
  }
  const zipData = generateProjectZip(
    code,
    pluginSettings.framework,
    images,
    format,
    rootName,
  );

  const maxMessageSizeBytes = 10 * 1024 * 1024;
  if (zipData.byteLength > maxMessageSizeBytes) {
    throw new Error(
      `Project too large (${Math.round(zipData.byteLength / 1024 / 1024)}MB). Try selecting fewer images or smaller components.`,
    );
  }

  return { zipData, rootName };
};
