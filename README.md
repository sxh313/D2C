# Design2Code 本地工作台

将截图、需求 Spec 和 Figma 节点单独或组合输入，按指令生成 React + TypeScript 页面。本项目以 `screenshot-to-code` 为主工程，调用根目录 `.env` 中配置的模型服务。

## 首次准备

1. 安装 Node.js、pnpm、Python 3.12 和 Poetry。
2. 在 `screenshot-to-code\backend` 运行 `poetry install` 和 `poetry run playwright install --only-shell chromium`；在 `screenshot-to-code\frontend` 运行 `pnpm install`。
3. 将 `.env.example` 复制为 `.env`，在本目录 `.env` 填写模型中转地址、API key 和模型名称。当前使用 `openai/gpt-6-luna`。Figma 默认使用本地 `figma-mcp-bridge`，不需要填写 `FIGMA_ACCESS_TOKEN`；修改后重启服务。
4. 当前不设置 token 和费用上限，留空即可；模型服务可能产生费用。每个任务最多请求模型 2 次，其中修改最多 1 次，不自动重试。当前填写预算字段会阻止生成，因为预算执行尚未接通。

## 启动和停止

在 PowerShell 执行：

```powershell
cd D:\desktop\AI\D2C\Design2Code
.\Start-Design2Code.ps1
```

浏览器打开 <http://127.0.0.1:5173>。完成后执行：

```powershell
cd D:\desktop\AI\D2C\Design2Code
.\Stop-Design2Code.ps1
```

## 使用

1. 在工作台选择或拖入最多 3 张 PNG/JPEG 截图，也可以直接按 Ctrl+V 粘贴。
2. 输入 Spec，或填写带 `node-id` 的 Figma 节点链接；至少提供一种资料。MCP 模式需要在 Figma Desktop 中打开目标文件并运行 bridge 插件。
   也可以选择 FigmaToCode 导出的 ZIP 作为参考资料，与截图和 Spec 一起使用。项目包中的 HTML、React 和 CSS 会作为生成参考；`images` 目录中的 PNG/JPEG 会复制到生成工程的 `public/images`。包内脚本和依赖不会运行。
3. 在生成指令中说明资料各自的用途，也可展开“选择各维度的参考来源”分别选择布局、样式、内容和交互的来源。确认摘要后点击“确认资料并生成”。
4. 等待模型生成和本地构建，在右侧查看预览、源码和检查结果。需要调整时可先点击“在预览中选取元素”，再点击页面上的目标，填写修改要求并使用一次修改机会；也可以直接填写整体修改要求。
5. 点击“下载工程”获取 ZIP。在解压后的目录执行 `pnpm install --frozen-lockfile`、`pnpm build` 和 `pnpm dev`。

运行中的任务可以停止等待。模型请求已经发出时，供应商仍可能继续处理和计费；本地构建停止时会请求终止该任务启动的进程树，系统正在关闭进程时可能短暂延迟。服务中断后的任务会标记中断或结果未知，不会自动重新请求模型。

## 当前范围和限制

- 本地构建以及桌面和手机视口水平溢出检查会显示结果，并保存页面截图。视觉还原和业务交互自动检查仍显示“未执行”；新任务同时列出“待人工检查”，需要人工核对。
- 截图加 Spec 已进行真实模型生成、构建、预览及导出验证；Figma 导入已接入本地 MCP bridge。真实节点验证不需要 REST token，但需要在 Figma Desktop 中运行 bridge 插件，并提供一个当前账号可访问且带 `node-id` 的链接。
- FigmaToCode 项目包限 10 MiB、250 个条目、展开后 20 MiB，源码合计不超过 300 KB，图片最多 30 张且合计不超过 5 MiB。当前按参考资料生成新工程，不能直接导入并运行原项目；模拟包已用于接口验证，真实插件导出包尚未验证。
- Figma 读取默认通过 `figma-mcp-bridge`：需要安装 Figma Desktop，在目标文件中导入并运行 bridge 插件，并在本机完成 bridge server 构建。它通过插件桥接读取节点和 PNG，不使用 REST Token；开源代码免费，但调用次数和可用性不等于官方无限额度。
- Bridge 安装：分别在 `figma-mcp-bridge\server` 和 `figma-mcp-bridge\plugin` 执行 `npm install`、`npm run build`；插件再执行 `npm run typecheck`。根目录 `.env` 使用 `D2C_FIGMA_MODE=mcp`。MCP 模式不填写 `FIGMA_ACCESS_TOKEN`；REST 仅作为兼容回退，不是当前默认路径。
- 最近一次本机浏览器检查确认：工作台可打开，Spec 与项目包可以同时添加，来源摘要会显示各自用途，生成指令可填写。该检查未点击生成，因此没有新增模型请求。
- 输入资料和运行结果保存在本机 `runtime`，关闭浏览器后可恢复最近一次任务结果；输入草稿目前不会恢复。
- 当前模板为 React、TypeScript、Vite 和 Tailwind CSS；构建后会做本机桌面/移动视口、水平溢出、资源错误和交互冒烟检查。视觉还原、业务语义和交互是否符合需求仍需人工检查。

## 2026-11-10 状态同步

- `figma-mcp-bridge/server` 已完成 `npm install`、`npm run build`。
- `figma-mcp-bridge/plugin` 已完成 `npm install`、`npm run build` 和 `npm run typecheck`；可直接导入 `figma-mcp-bridge/plugin/manifest.json`。
- MCP bridge 的模拟适配测试已通过；真实节点读取仍取决于 Figma Desktop 插件已启动和目标文件权限，不能用模拟测试替代真实联调。
- 后端最新完整测试为 308 项通过，Pyright 为 0 errors；导出工程已在独立目录重新执行 `pnpm build` 通过。
- 当前仍未完成：截图 + Spec + Figma 三资料的真实模型运行，以及视觉相似度自动验收。真实 Figma 节点读取已完成，见下方联调记录。
- 2026-11-10 修复了 Windows 下 MCP bridge 的 `file://` 路径转换；未运行 Figma 插件时，导入接口现在会明确返回“Bridge 未连接”，不会把进程启动错误伪装成节点解析错误。
- 真实联调进展：插件已连接本机 bridge，工作台导入接口已成功读取真实 Figma Frame 的节点结构和 PNG，状态为 `READY`。插件无法提供文件 key 时，使用根 `.env` 中 `D2C_FIGMA_MCP_BOUND_FILE_KEY` 与 `D2C_FIGMA_MCP_SESSION_KEY` 显式绑定；仅匹配指定文件，不根据文件名自动猜测。插件重新运行后临时会话标识可能改变，需要重新绑定。工作台启动脚本会自动管理 bridge，具体操作见下文。
- 启动脚本会在启动进程后立即写入 `runtime/workbench-processes.json`，即使健康检查被中断，停止脚本仍能找到并清理本次启动的进程。

详细方案见 [Design2Code开源二次开发实施方案.md](./Design2Code开源二次开发实施方案.md)。






本地工作台统一通过任务接口调用模型。上游独立生成和批量模型评测入口在此启动模式下不启用；已有上游源码仍保留。



## Figma bridge 启动与文件关联

1. 在根目录 `.env` 中设置 `D2C_FIGMA_MODE=mcp`，运行 `.\Start-Design2Code.ps1`。脚本会自动启动本机 bridge、后端和前端，打开 http://127.0.0.1:5173。
2. 在 Figma Desktop 打开目标文件并运行 Figma MCP Bridge 插件，保持插件窗口打开，确认显示已连接。
3. 当插件只能提供临时会话标识时，将目标文件链接交给绑定脚本：

   ```powershell
   .\Bind-FigmaBridge.ps1 -FigmaUrl 'https://www.figma.com/design/文件标识/文件名?node-id=节点标识'
   ```

   请确认 Figma 中打开的就是该链接对应的文件。只有一个插件会话时，脚本会在执行绑定命令时选择它；多个会话时脚本会列出会话，需要通过 `-SessionKey` 指定。绑定结果保存在根目录 `.env`，其他配置保持不变。插件重新运行后临时标识可能变化，此时重新执行绑定命令。真实文件标识匹配时无需绑定。
4. 工作台中输入带 `node-id` 的 Figma 链接。停止时运行 `.\Stop-Design2Code.ps1`。脚本只停止本次工作台启动的进程；如果启动时复用了已运行的 bridge，不会关闭那个外部进程。

bridge 健康检查成功只表示服务已启动；读取设计还需要目标 Figma 文件可访问、插件连接和正确的文件关联。插件的匿名临时标识不包含文件身份，因此不会自动猜测文件并静默绑定。

### 输入组合与验收进展（2026-11-10）

截图、Spec、Figma 节点可单独使用，也可任选两种或三种一起使用。已通过本机接口实际导入一张示例图片、一份 Spec 和一个真实 Figma 节点，并分别创建全部 7 种资料集合；这只验证了输入与组合，没有发起模型请求，也不能证明 7 种组合的生成效果。

根目录 `.env` 的 token 和费用上限目前留空。现有实现的调用次数限制为每次任务最多 2 次模型请求、1 次修复、0 次自动重试；token 和费用上限执行尚未接通，填写上限会阻止生成。当前目标对真实模型验收要求先配置预算，因此三资料真实生成尚未进行。

交互冒烟检查与业务交互验收分别报告：仅在实际操作至少一个支持的控件且未发现页面错误时冒烟项显示 PASS；没有可操作控件时显示 NOT_RUN。搜索、筛选、弹窗是否符合 Spec 仍需实际核验。
