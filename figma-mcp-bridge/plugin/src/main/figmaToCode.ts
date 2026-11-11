// GPL-3.0: shares the actual FigmaToCode plugin export pipeline, not REST JSON.
import { createProjectExport } from "../../../../FigmaToCode/apps/plugin/plugin-src/projectExport";
import { clearWarnings, warnings } from "../../../../FigmaToCode/packages/backend/src/common/commonConversionWarnings";
import type { PluginSettings } from "../../../../FigmaToCode/packages/types/src/types";

const settings: PluginSettings = {
  framework: "HTML", showLayerNames: false, useOldPluginVersion2025: false,
  responsiveRoot: false, flutterGenerationMode: "snippet", swiftUIGenerationMode: "snippet",
  composeGenerationMode: "snippet", roundTailwindValues: true, roundTailwindColors: true,
  useColorVariables: true, customTailwindPrefix: "", embedImages: false, embedVectors: true,
  htmlGenerationMode: "jsx", tailwindGenerationMode: "jsx", baseFontSize: 16,
  useTailwind4: false, thresholdPercent: 15, baseFontFamily: "", fontFamilyCustomConfig: {},
};
let busy = false;

export const convertSelectionWithFigmaToCode = async (
  selection: readonly SceneNode[],
  format: "html" | "nextjs" | "vite" = "vite",
) => {
  if (busy) throw new Error("BUSY");
  if (!selection.length) throw new Error("EMPTY_SELECTION");
  if (selection.length !== 1) throw new Error("SELECT_ONE_FRAME");
  busy = true;
  try {
    clearWarnings();
    const { zipData } = await createProjectExport(selection, format, settings);
    return {
      zipBase64: figma.base64Encode(zipData),
      format,
      converter: "FigmaToCode",
      converterVersion: "f5c4831d5de6cffc19a73fe2823c56b4bb551281+d2c-shared-export-v1",
      nodeIds: selection.map((node) => node.id),
      nodeNames: selection.map((node) => node.name),
      warnings: [...warnings],
    };
  } finally {
    busy = false;
  }
};
