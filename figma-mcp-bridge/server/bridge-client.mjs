#!/usr/bin/env node
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import process from "node:process";
import { fileURLToPath } from "node:url";

const [fileKey, nodeId, sessionKey] = process.argv.slice(2);
if (!fileKey || !nodeId) throw new Error("Usage: bridge-client.mjs <fileKey> <nodeId>");
// URL.pathname keeps a leading slash on Windows (for example /D:/...); use
// fileURLToPath so stdio transport receives a native executable path.
const serverPath = fileURLToPath(new URL("./dist/index.js", import.meta.url));
const cwd = fileURLToPath(new URL(".", import.meta.url));
const transport = new StdioClientTransport({ command: process.execPath, args: [serverPath], cwd });
const client = new Client({ name: "design2code", version: "0.1.0" }, { capabilities: {} });
try {
  await client.connect(transport);
  const targetKey = sessionKey || fileKey;
  const node = await client.callTool({ name: "get_node", arguments: { fileKey: targetKey, nodeId } });
  const screenshot = await client.callTool({ name: "get_screenshot", arguments: { fileKey: targetKey, nodeIds: [nodeId], format: "PNG", scale: 1 } });
  process.stdout.write(JSON.stringify({ node, screenshot }));
} finally {
  await transport.close();
}
