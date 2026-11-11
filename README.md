# Design2Code

## 本地启动

在项目根目录配置已有的 `.env`（不要提交），运行 `.\Start-Design2Code.ps1`；
停止运行 `.\Stop-Design2Code.ps1`。所有服务仅供本机使用。

## FigmaToCode 接入（2026-11-11）

- 项目包：导入真实插件导出的 ZIP，保存原包和源码/图片哈希，生成统一 FigmaCodeArtifact。旧 ZIP 没有转换版本时标记未知，不伪造来源。
- 直连：在 Figma Desktop 中运行本项目的 Bridge 插件，选中链接对应的一个画板。工作台默认调用 `figma_code`；保留勾选“仅读取节点/截图参考”的旧路径。
- 原插件的下载功能与 Bridge 共用 `FigmaToCode/apps/plugin/plugin-src/projectExport.ts`，沿用 `nodesToJSON`、HTML 转换、图片导出和 `generateProjectZip`；不是用普通节点 JSON 模拟转换。
- ZIP 与直连结果都进入同一 SourceSet。官方 Agent 收到实际转换源码、图片引用、Spec 和用户指令；原始 ZIP 可以独立下载，包内脚本不执行。
- 直连校验请求 ID、文件会话和选区，返回空选区、无会话、超时、转换失败、资源失败等状态，不自动重试。

构建 Bridge（先安装各目录依赖及 FigmaToCode 工作区依赖）：

```powershell
cd figma-mcp-bridge/server
npm run build
cd ../plugin
npm run build
```

在 Figma Desktop 导入 `figma-mcp-bridge/plugin/manifest.json`。插件重新启动后，若开发环境无真实 fileKey，按现有 `Bind-FigmaBridge.ps1` 流程绑定当前文件。

## 转换工程保留与本次验证（2026-11-11）

- React/Vite Figma Artifact 作为可运行的 TSX 多文件工程起点。官方 Agent 的 `create_file` / `edit_file` 依原工具算法修改指定源码文件，未修改的文件保留；原始 ZIP 单独保存。
- 单独 Figma 且没有附加指令时直接构建，模型调用为 0 次。图片 URL 为本地嵌套预览规范化，依赖、入口和构建配置使用受控 React 18 / Vite / Tailwind 3 模板。Tailwind 4 样式暂不支持，HTML/Next 包仍为参考输入，不能声称兼容所有上游输出。
- 保存 Artifact → 工程源码 → 候选的文件关系与文本哈希；导出报告另含候选实际文件字节哈希，以识别历史 Windows 换行差异。新候选源码直接以 UTF-8 字节写入。
- 每 Run 最多 2 次模型请求、1 次修复、无自动重试。首轮与修复分别最多一次供应商请求，关闭会额外调用供应商的工具；文件工具执行后未追加模型读取反馈，完整 Agent 反馈闭环标记未执行。
- 真实保存的插件包零调用构建：`run_084fe1b0dfa3437db6e626982826938f`。
- 真实图片 + 保存的插件包 + Spec 联合生成：`run_2c121f0a34df4291bfa86e263b209b12`，使用官方 Agent 和配置模型，首轮 1 次、修复 1 次。首轮缺样式且弹窗存在同名关闭按钮，唯一一次修复后构建、搜索与弹窗检查通过。
- 上述联合工程导出到干净目录，实际执行 `pnpm install --frozen-lockfile --ignore-scripts`、`pnpm build` 和本地 Vite preview。实际操作搜索、状态筛选、组合筛选空状态、空值错误、有效提交和弹窗关闭通过；桌面和手机视口无横向溢出，图片已加载。依赖安装复用了本机 pnpm 缓存，不等于全新机器验证。
- 已自行启动 Figma Desktop 和现有 Bridge 开发插件，绑定真实文件并从工作台完成选区直连：`run_b8bf8b28ba9344fb859d5925d9d10485`。来源为 `plugin_execution`、传输为 `desktop_bridge`，带本次 request_id 和原转换器版本；该 Run 0 次模型请求，构建和导出后干净目录安装/构建通过。这次选区是单图画板，不代表多节点设计的完整验收。
- 上述直连原始布局实际显示为空白，不能仅凭构建通过认定视觉通过。原因是百分比高度缺少父级高度；现在为缺少全局 CSS 的导入工程补齐高度链，保留原 App 源码并记录规范化警告。重建同一真实 Artifact 的 `run_d8abacdca0824bda89165c13ed43a520` 使用 0 次模型请求，浏览器确认 1000×700 原图可见，导出工程的原 ZIP、图片字节、文本/文件哈希和干净目录安装/构建通过；响应式还原仍需检查。
- 本次实时直连 Artifact + 导出截图 + Spec 的联合 Run 为 `run_d2b6a8ebf6f34ea5a9d373def603bcda`，共 2 次模型请求、1 次修复，实际工具分别修改 `src/App.tsx` 与 `src/index.css`。独立目录安装、构建、启动后，真实搜索、状态筛选、组合空状态、表单错误、有效提交和关闭弹窗通过，桌面/手机图片加载及横向溢出检查通过。视觉还原和通用交互冒烟仍不能标为全部通过。

Python 全量测试本阶段 404 通过、2 跳过；前端 lint 和生产构建通过。FigmaToCode 原 ZIP 测试历史为 10 项通过。
Bridge 全量类型检查仍报告 99 个上游 backend 源码类型错误；Python 全量类型检查也有历史测试文件错误，不能宣称全量静态检查通过。
本阶段 Python 全量类型检查为 6 个错误、54 个警告，工程适配核心改动的定向检查为 0 错误、0 警告。

当前首页仍为中文 `Workbench.tsx`；以 screenshot-to-code 原生前端工作流为基础的完整迁移尚未完成。七种输入模式的逐项实时验收、原生同条件对照和多节点 Figma 验收仍需继续；构建成功不等于视觉还原通过。

## 上游来源与许可

- screenshot-to-code：MIT，保留 `screenshot-to-code/LICENSE`，基线 `a8139779f7c5ae231b7f2a86fa7f83ddc5f7badc`。
- FigmaToCode：GPL-3.0，保留完整 `FigmaToCode/LICENSE`，基线 `f5c4831d5de6cffc19a73fe2823c56b4bb551281`。
- 本次新增的 Bridge 转换适配及提取出的共享导出模块按 GPL-3.0 分发；包含该转换器的插件组合构建不能仅标为 MIT。源码、构建入口和修改说明随仓库保留，原组件版权声明不删除；不提交生成的插件二进制。
- Bridge 原项目的 MIT 声明保留于 `figma-mcp-bridge/LICENSE`；内嵌 HTML renderer 的 MIT 声明保留于 `figma-mcp-bridge/plugin/src/html-figma/NOTICE`。二者从原 Markdown 声明逐字保留为无扩展名文件，满足本仓库仅提交 README Markdown 的规则。
- 修改范围：从 FigmaToCode 原插件入口提取共享导出函数，原下载功能继续调用同一函数；新增 Bridge 调用、后端产物契约、工作台入口与回归测试。未更改旧 platform 审批流程。

## 示例对比

以下是使用工作台截图生成 React 页面的一次真实结果。两张图的视口尺寸不同，布局、文字和间距存在差异。

<table>
  <tr>
    <th width="50%">输入截图</th>
    <th width="50%">生成页面</th>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/example-reference.png" alt="输入的设计截图" width="100%"></td>
    <td width="50%"><img src="docs/images/example-generated.png" alt="根据截图生成的页面" width="100%"></td>
  </tr>
</table>
