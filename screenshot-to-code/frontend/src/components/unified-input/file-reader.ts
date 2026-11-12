export function fileToDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") { reject(new Error("File did not produce a data URL")); return; }
      const result = reader.result;
      const mimeType = file.type || (file.name.toLowerCase().endsWith(".mov") ? "video/quicktime" : "");
      resolve(result.startsWith("data:application/octet-stream") && mimeType
        ? result.replace("data:application/octet-stream", `data:${mimeType}`) : result);
    };
    reader.onerror = (error) => reject(error);
    reader.readAsDataURL(file);
  });
}
