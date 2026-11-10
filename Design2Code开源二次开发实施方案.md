# Design2Code 开源二次开发实施方案

更新日期：2026-11-10  
版本：v2.3，按用户要求暂不设置 token 和费用上限，保留每次任务的请求次数限制。  
状态：主工作台可本地启动；截图、Spec、Figma 和项目包输入，以及生成、构建、预览、修复、导出和 MCP Bridge 已接入。真实 Figma 导入和三资料真实模型生成、修复已有验收记录；当前状态及尚未验证事项见《项目使用与验收记录》“当前验收清单”。以下章节保留历史方案和阶段记录。
目标目录：`D:\desktop\AI\D2C\Design2Code`  
项目定位：个人开发的通用 Design2Code 工具，不绑定电商行业。

本文阅读方式：第 1～17 节说明产品范围与实施顺序；第 18 节给出逐模块接口、字段、调用顺序、文件落点、错误处理和联调案例；18.20 专门说明多种资料如何在一个任务中共同使用。所有“拟新增”接口均为本项目设计，不应当作上游已有接口调用。

### 当前源码基线

| 本机目录 | origin | 已拉取 commit | 在本项目中的职责 |
| --- | --- | --- | --- |
| `screenshot-to-code/` | `git@github.com:abi/screenshot-to-code.git` | `a8139779f7c5ae231b7f2a86fa7f83ddc5f7badc` | 主前端、FastAPI、供应商适配与预览基础 |
| `FigmaToCode/` | `git@github.com:bernaferrari/FigmaToCode.git` | `f5c4831d5de6cffc19a73fe2823c56b4bb551281` | Figma 插件转换参考、可选独立导入路径 |
| `onlook/` | `git@github.com:onlook-dev/onlook.git` | `423e2e924366419e418ee049093872d535eea41a` | 元素定位、跨 iframe 通信和源码修改参考 |

旧的 `server.py`、`web/index.html` 是演示壳：确定性生成 HTML、接口内存返回结果；当前预览容器是 `div`，给它设置 `srcdoc` 不会成为 iframe。运行接口健康检查不能证明浏览器预览已通过。它没有集成三个开源仓库，也没有完成截图上传、粘贴、图片压缩或输入持久化。这些缺口在迁移时由真正的 React 前端替代，不继续扩大演示壳职责。

### 接口阅读导航

| 原方案部分 | 详细对接章节 |
| --- | --- |
| 1 产品目标、2 开源复用、4 架构目录 | 18.1、18.6、18.7、18.14 |
| 3 旧项目迁移 | 18.18 |
| 5 三种输入及组合使用 | 18.2～18.6、18.20 |
| 6 代码工程化 | 18.7、18.8 |
| 7 接口与状态 | 18.9、18.10 |
| 8 构建预览 | 18.11 |
| 9 验收、10 修复 | 18.12、18.13 |
| 11 前端、12 配置与导出 | 18.15～18.17 |
| 13～17 实施、测试、交接 | 18.19、第 19、20 节 |

## 1. 最终要做成什么

用户可以单独或同时上传截图、选择 Figma 设计节点、输入 Markdown/文字 Spec，并通过本次指令指定每份资料的用途。系统将这些资料合成同一个任务的输入，生成一个可以启动、预览、修改和导出的前端工程，并能对生成结果做检查、给出失败原因，执行有上限的修复。

核心过程是：输入设计或需求 → 整理生成上下文 → 生成代码 → 构建和预览 → 检查结果 → 必要时修复 → 导出源码与报告。

可以生成落地页、后台管理页面、仪表盘、表单、内容展示页、个人主页等。电商只是一种可选样例，不是架构前提，也不再把价格、商品身份等规则作为所有页面的必检项。

第一版的“通用”指输入和页面业务类型不绑定行业，不代表同时支持所有框架、复杂业务系统和原生移动应用。

### 1.1 第一版固定边界

- 三种输入：PNG/JPEG 截图、Figma 指定节点、Markdown/文字 Spec；支持单独使用、任意两种组合或三种一起使用，均可附加本次指令。
- 组合输入仍以一个页面为范围：首版最多 3 张有明确用途的截图、1 个 Figma Frame、1 份主 Spec，不能把不相关的页面混为一个生成任务。
- 输出技术栈：React + TypeScript + Vite + Tailwind；版本在起步阶段选定并锁定。
- 输出范围：一个页面及其组件，允许表单、筛选、切换、弹窗等前端交互。
- 运行范围：本机单用户、同时执行一个生成任务。
- 数据范围：静态数据或明确标注的本地 mock adapter，不默认接真实业务数据库。
- 成品范围：可运行源码、依赖锁文件、资源文件、运行说明、检查报告和截图。
- 不默认部署公网，不把“浏览器能预览”写成“生产上线”。

### 1.2 暂不做的内容

- Android、iOS、鸿蒙原生代码与真机验收。
- Vue、Flutter、SwiftUI、Next.js 等多输出后端同时支持。
- 支付、真实登录、订单等业务后端自动开发。
- 多租户、多人审批、独立 reviewer 平台、企业权限中心。
- 通用拖拽编辑器、完整设计系统、Figma 双向同步。
- 无限自动修复、多模型并行比稿、复杂多 Agent 编排。
- 录屏输入、整站批量生成和任意现有仓库自动重构。

## 2. 开源项目怎么用

### 2.1 screenshot-to-code：优先验证的主底座

优先复用其输入界面、模型接入、生成结果展示和预览能力。官方说明其采用 React/Vite 前端与 FastAPI 后端，可本地运行，并提供可选的浏览器截图检查能力。[官方仓库](https://github.com/abi/screenshot-to-code)

实施方式：直接以当前 `screenshot-to-code/` 为主工程，在其分支中开发，保留原始历史、许可证和上游 remote。旧规划里的 `app/` 只是候选目录名，本版统一使用已存在的仓库目录，不再重复克隆或另建 `app/`。

先验证以下问题，再确认是否以整个仓库作为长期底座：

1. 选定提交能否在当前 Windows/WSL 环境运行。
2. 生成结果实际是完整工程、单文件页面还是代码片段。
3. 能否限制为一个候选，而不是并行生成多个版本。
4. 模型 SDK、Agent 循环、资源提取和图片生成是否暗含额外请求。
5. 能否把供应商调用统一收口到一个预算入口。
6. 预览能力是否可与固定的 React 工程模板结合。

不能把“支持 React 输出”等同于“已经支持我们需要的多文件 TypeScript 工程导出”。后者必须实际验证；不足部分由工程包装器补齐。

已检查的上游生成路由存在候选模型选择和 Agent 生成阶段，因此不能假设点击一次按钮只发起一次供应商请求。[上游生成路由](https://github.com/abi/screenshot-to-code/blob/main/backend/routes/generate_code.py)

本机源码进一步确认：`backend/config.py` 默认 `NUM_VARIANTS = 4`；`ModelSelectionStage` 更新模式固定选择 2 个候选；`agent/engine.py` 的工具循环上限为 30 步。只改一个候选配置无法同时限制更新分支和每个候选内部的模型请求。

已有的 `POST /api/export` 根据客户端提交的 HTML 收集图片并导出 ZIP，不能直接作为“已构建、已检查、多文件 TSX 工程”的权威导出入口。

若完整底座适配成本过高，先形成评估记录，再选择保留上游 UI 与供应商适配、替换生成执行路径的方案；不要一边复用一边再建设第二套完整工作台。

### 2.2 Figma to Code：结构化设计转换参考

参考其“读取节点 → 标准化 → 布局处理 → 目标代码生成”的方式，不在第一版直接整合其整个工程。其官方说明明确区分视觉骨架与应用逻辑，源码采用 GPL-3.0。[官方仓库](https://github.com/bernaferrari/FigmaToCode)

执行原则：

- 可以研究公开架构和功能，但不把复制的代码改名后当作自主实现。
- 首版优先通过 Figma 官方数据接口或用户导出的设计资料接入。
- 如决定直接复用 GPL 源码，先确定项目分发方式与许可证兼容方案；不能默认与 MIT 底座任意合并，也不能仅靠“放在独立目录”判断合规。
- 不承诺 Figma 转换器自动生成状态管理、数据请求或业务行为。

### 2.3 Onlook：后续交互参考

仅参考元素定位、代码与页面联动、可视化修改等交互。它的开源实现面向 Next.js/Tailwind，并与后续托管产品区分；本方案不依赖其托管服务，也不首期引入完整工程。[官方仓库](https://github.com/onlook-dev/onlook)

### 2.4 上游版本管理

- 记录上游 URL、完整 commit、许可证文件与本地修改范围。
- 不跟随浮动 `main` 自动升级；升级单独执行构建、生成、预算和导出回归。
- README 中明确“基于 screenshot-to-code 二次开发”，列出新增能力。
- 本文引用的是检索时的上游能力，具体开发以克隆后锁定提交为准。

### 2.5 三个仓库采用什么连接方式

- screenshot-to-code：直接在 Python/React 工程内增加适配模块，属于源码级集成。
- Figma 官方接口：由 FastAPI 后端通过 HTTP 读取选定节点，属于数据级集成；无需运行 FigmaToCode 的 Web 站点。
- FigmaToCode：默认以用户导出的设计包/项目包作为文件级输入；若选择直接修改和分发插件源码，再单独落实许可证方案，不在 Python 中直接 import TypeScript 插件代码。
- Onlook：先沿用主底座已有的选中修改功能；未来增加独立 `postMessage` 事件和 AST 适配器，属于协议/源码能力迁移，不把整个 Next.js、Supabase、Bun 服务同时作为首版依赖。

“仓库已拉取”“代码已接入”“接口联调通过”“真实案例通过”分别记录，不能相互替代。

## 3. 与旧 D2C 工程的关系

新工程是面向通用页面的独立产品方向，不是把旧商品卡片任务改名后宣称完成。

### 3.1 可以选择性迁移

- 运行日志、模型用量记录和候选版本绑定的思路。
- 构建超时、进程清理、取消和错误分类。
- 多视口截图、基础可访问性、页面溢出检查。
- 限次修复、失败诊断结构和交付哈希索引。
- 不依赖电商数据的测试用例和可独立提取的纯函数。

### 3.2 不整套搬迁

- 旧审批 revision、PlanApproval、operator gate 与签署数据库。
- 商品价格、商品身份、搜索分页等特定业务的固定 17 项规则。
- 必须同时运行 PostgreSQL、S3、Keycloak 和多 Worker 的部署组合。
- 依赖旧 Evidence 表、审批状态和角色体系的完整导出类。

当前 `platform/services/backend/src/d2c/bootstrap/product_acceptance.py` 的检查装配依赖 PostgreSQL Evidence writers，`application/product_delivery_export.py` 也依赖审批和交付数据模型，不能当作独立库直接接入新底座。迁移应从规则、输入输出协议和测试样例开始，不从旧服务启动链开始。

### 3.3 旧工程处理原则

- 本轮不删除、不改名、不清理旧项目及其 `.local`、数据库和报告。
- 不复用旧任务审批、模型调用额度或验收状态作为新任务的证明。
- 本方案不改写旧项目治理规则，也不降低旧商品卡片任务的验收分母。
- 新版稳定后，再由用户决定停止维护哪些旧模块；归档与删除单独执行。

## 4. 最小架构与目录

优先在上游单仓库中新增模块，不新增微服务、第二套 Agent 框架或任务中间件。

目录以已拉取的仓库为准。`design2code/`、模板、运行数据及新增脚本是后续拟新增内容：

```text
Design2Code/
  Design2Code开源二次开发实施方案.md
  .env                         # 本项目唯一实际配置文件，已创建待填写
  server.py                    # 已有演示服务，迁移期间保留
  web/                         # 已有演示页面
  screenshot-to-code/          # 已存在；主开发仓库
    frontend/                  # 沿用上游界面，增加输入和报告页
    backend/
      design2code/
        inputs/                # screenshot / figma / spec 适配
        contracts/             # 输入、输出、检查、运行记录
        generation/            # Prompt 装配、结果解析、预算入口
        workspace/             # 候选文件、路径校验、模板包装
        runner/                # 构建、预览、停止、截图
        checks/                # 通用规则与输入类型专属规则
        repair/                # 失败反馈与修复次数限制
        reports/               # JSON、HTML 与 ZIP 导出
    templates/react-vite/      # 固定、可复现的输出工程模板
    examples/                  # 无秘密的示例输入和 Spec
    tests/                     # 单元、集成、E2E
    scripts/                   # 本机启动、检查、停止
    docs/                      # 来源、使用、架构与验证记录
    .gitignore
    LICENSE                    # 保留上游版权及许可证
  FigmaToCode/                 # 已存在；插件参考/独立导出路径
  onlook/                      # 已存在；后续可视化编辑参考
  runtime/                     # 任务资料与产物；不提交
    runs/<run_id>/
    metadata.sqlite
```

初期持久化建议使用 SQLite 存运行元数据，本地目录存大文件。这里是待实现的简化方案，不是已有能力。仅一个后台执行者负责修改任务状态；不同时引入 PostgreSQL 和 S3。未来确有多人访问或共享部署需求时再评估迁移。

应用前端与生成页面必须运行在不同 origin。预览 iframe、浏览器采集器和导出目录不能读应用的 `.env` 或模型凭据。

## 5. 三种输入如何统一

### 5.1 统一 DesignBrief，而不是建设完整设计编译器

三类适配器分别保存不可变的原始输入，再通过 SourceSet 组合成同一个任务的资料集合，形成统一的轻量 DesignBrief。明确哪些字段来自哪份资料、哪些来自用户指令、哪些只是推断。单输入也是只有一个元素的 SourceSet，不建设另一套执行流程。

建议字段：

```text
DesignBrief
  schema_version
  source_set_id + source_set_revision + source_set_hash
  input_types[]: screenshot | figma | spec（可同时出现）
  instructions: 本次任务指令
  authority_by_dimension: 布局、样式、内容、交互、响应式分别采用的来源
  resolutions[]: 资料冲突的明确处理结论
  source_refs[]: 本地资源引用、摘要、来源类型
  viewport: 原始画面宽高（如有）
  target_stack: 固定的输出模板版本
  sections[]: 区块及其内容/布局描述
  design_tokens: 颜色、字体、间距（可缺省）
  assets[]: 文件引用、尺寸、来源、可用状态
  interactions[]: 触发动作、前置条件、预期结果
  responsive_rules[]: 已声明的响应式要求
  acceptance_criteria[]: 可追踪的验收条目
  assumptions[]: 未确认的生成假设
  unresolved[]: 缺图、缺状态、信息冲突等问题
```

为重要字段记录 `provenance = source | user | inferred`。截图推测的字号、Spec 自动补充的布局不能标成设计稿的精确值。

提交生成前展示一页“输入摘要”，允许用户确认内容、响应式行为和关键交互。缺少非关键设计细节时采用模板默认值并记录假设，不为每个像素弹出确认。

### 5.2 ScreenshotAdapter

处理步骤：

1. 检查实际文件类型、解码结果、尺寸和文件大小，不只检查扩展名。
2. 保留原图及 SHA-256；生成供模型使用的受限尺寸副本，记录缩放关系。
3. 接收可选补充说明，例如“按钮打开弹窗”“移动端列表改单列”。
4. 原图/副本与说明直接参与首次生成，首版不额外调用模型做一轮布局解析。
5. 将没有来源的交互记录为假设；不从截图虚构真实 API 或登录行为。
6. 生成后按原始视口截图，先对齐尺寸、字体加载和资源状态，再比较布局。

首版限制：最多 3 张 PNG/JPEG 共同描述一个页面，每张标注用途、区域、视口与状态；可以是桌面图、移动图或局部样式参考，不自动推导跨页面流程或任意状态关联。超长图分块和录屏理解后置。缺少原始图片资源时明确使用占位或用户提供资源，不把占位图当作还原完成。

验收：图片损坏可解释地拒绝；宽高可追踪；生成代码能运行；截图对比绑定同一候选；原图与生成结果可并排查看。

### 5.3 SpecAdapter

这里的 Spec 指文字/Markdown 页面需求说明，不限定某种协议。

建议用户描述以下信息：

```text
页面目标：项目任务管理
内容：标题、搜索框、状态筛选、任务列表、新建任务按钮
交互：搜索按标题过滤；筛选待办/进行中/完成；新建打开弹窗
状态：加载中、没有任务、保存失败、保存成功
视觉：浅色、紧凑布局、蓝色强调色
响应式：桌面左右布局；窄屏上下排列
数据：本地演示数据，不连接真实任务系统
```

处理步骤：

1. 接收文本或 `.md`；保留原始版本及哈希。
2. 按标题、列表和已知字段做确定性整理；自由文本无法可靠解析时保留原文。
3. 提取可以确认的验收条目；有歧义的行为让用户补充，不额外默认调用解析模型。
4. 把模板规则、Spec、确认后的交互与验收条目一起交给生成模型。
5. 同时展示生成结果与条目覆盖情况，不能只展示一张好看的预览图。

验收：声明的功能能执行；缺失需求被报告；没有参考图时不展示“视觉还原率”。Spec-only 的视觉对比标记为“不适用”，不是通过，也不是失败；基础布局和可访问性仍需检查。

### 5.4 FigmaAdapter

区分两种交付级别：

- 资料导入：用户提供 Figma 导出的图片及资源，可作为 screenshot 输入，但不能宣传成完整节点解析。
- 直接接入：输入文件/节点链接，在用户具备访问权限的情况下取得指定节点资料与渲染图，才算 Figma 输入功能完成。

直接接入实施步骤：

1. 解析受支持的 Figma 链接形式，提取文件标识和节点标识，拒绝把它当作任意 URL 抓取入口。
2. 后端使用本机配置的访问凭据请求官方接口；凭据不发送到生成页面。
3. 只读取选定 Frame/组件及必要子树，不默认读取整个设计文件。
4. 获取节点布局、文字、样式、Auto Layout、尺寸、图片引用以及该节点的渲染图。
5. 标准化进 DesignBrief，保留 node id、源版本标识（如可用）和快照摘要。
6. 下载生成所需的资源并改为本地引用；处理资源链接过期，不把临时 URL 直接写进交付物。
7. 将结构信息和渲染图一并交给模型；遇到复杂矢量、不可用字体和组件语义缺失时显式报告。
8. 根据同一快照渲染图检查结果；执行期间设计更新不能偷偷替换当前任务输入。

开始实现前重新核对 Figma 官方接口、授权方式、账号权限和限流规则。用户无法提供可访问文件时，降级为资料导入，并明确直接接入尚未验收。

重要限制：Figma 的视觉结构不天然包含完整产品行为，交互逻辑仍需要 Spec 补充。

## 6. 生成代码怎样成为可运行工程

### 6.1 固定模板先行

先制作一个不依赖模型即可构建的 React/Vite 模板，锁定 Node、包管理器、React、TypeScript 和 Tailwind 版本，并保存 lockfile。

模型主要生成：`src/App.tsx`、`src/components/**`、允许的样式文件和本地数据适配文件。

默认不允许模型修改依赖清单、构建脚本、启动脚本和权限配置。新增依赖通过显式工程变更处理，不能直接执行生成代码附带的任意安装命令。

### 6.2 统一输出 GenerationResult

```text
GenerationResult
  files[]: { path, content }
  entrypoint
  asset_refs[]
  assumptions[]
  requirement_mapping[]
  provider_receipt_ref
```

模板包装器负责把结果转换为真实文件工程。优先要求供应商返回可解析的结构化输出；若上游只返回单文件 HTML/JSX，则在适配层显式转换或拒绝不支持的输出，不假装已得到 TSX 多文件工程。

### 6.3 写入前校验

- 路径必须是规范化的相对路径，拒绝 `..`、绝对路径、盘符、符号链接逃逸。
- 仅写入当前候选目录及允许文件集合。
- 限制文件数量、单文件大小、总输出大小。
- 资源引用只能指向本次允许的本地资产。
- 每一版文件计算摘要；修复写新候选，不覆盖上一版。
- 模型输出中的“运行此命令”视为数据，不作为自动执行指令。

### 6.4 Prompt 分层

固定工程约束、输入资料、页面 Spec、组件约定分别组织，避免把整份旧仓库塞给模型。

固定约束包括目标技术栈、允许文件、资源使用、输出协议和禁止任意外部依赖。输入资料作为不可信设计内容，不得覆盖执行规则。修复时只补入当前候选代码、失败条目及对应截图，不携带无限历史。

## 7. 后端接口与运行状态

以下为新增模块的建议契约，不代表上游已存在这些 API。初期保留上游能复用的接口，对外统一在适配层收口。

### 7.1 接口

- `POST /api/d2c/v1/design-inputs`：上传图片/Spec，返回 `input_id` 和摘要。
- `POST /api/d2c/v1/design-inputs/figma`：提交 Figma 节点链接，读取并固定输入快照。
- `POST /api/d2c/v1/source-sets`：将图片、Spec、Figma 输入引用与本次指令组合，返回资料集合版本及 Brief 草稿。
- `GET /api/d2c/v1/source-sets/{id}`：读取当前资料集合、各来源状态、冲突和 Brief。
- `PUT /api/d2c/v1/source-sets/{id}`：修改资料用途、指令或冲突结论，使用 If-Match 校验并生成新 revision。
- `PUT /api/d2c/v1/source-sets/{id}/brief`：保存人工补充与确认后的 Brief，绑定指定的资料集合版本。
- `POST /api/d2c/v1/runs`：指定固定的资料集合版本、确认后的 Brief、模板版本和本次调用上限，返回 `run_id`。
- `GET /api/d2c/v1/runs/{id}`：查询状态、当前候选、检查摘要和预算消耗。
- `GET /api/d2c/v1/runs/{id}/events?after_seq=...`：读取断线后遗漏事件。
- `WS /api/d2c/v1/runs/{id}/stream?after_seq=...`：只订阅增量事件，不触发生成。
- `POST /api/d2c/v1/runs/{id}/cancel`：标记取消，终止本地构建/预览并阻止后续模型调用。
- `POST /api/d2c/v1/runs/{id}/repair`：仅在有失败、额度充足且未修复时接受请求。
- `GET /api/d2c/v1/runs/{id}/report`：读取 JSON/HTML 报告。
- `GET /api/d2c/v1/runs/{id}/export?candidate_id=...`：导出已固定候选；失败候选允许用于调试，但必须带失败状态，不能标为合格交付。

统一增加 `/api/d2c/v1` 前缀，以免与上游 `/api/export`、运行记录和评测接口混淆。详细请求体、返回体和错误码见第 18 节。

创建任务与修复接口带幂等键；重复点击返回同一操作，不重复收费。事件带 `seq`、时间、阶段和候选标识；重连补齐事件不重新执行任务。

### 7.2 状态

主要阶段：`CREATED`、`INPUT_READY`、`GENERATING`、`BUILDING`、`CHECKING`、`REPAIRING`、`READY_FOR_REVIEW`。

结束状态：`COMPLETE_LOCAL`、`FAILED`、`CANCELLED`、`UNKNOWN_EXTERNAL`。

- `COMPLETE_LOCAL`：必要检查完成且用户确认本地演示结果，不表示旧系统的正式验收或上线授权。
- `UNKNOWN_EXTERNAL`：供应商可能已接收请求，但本地未取得确定结果；不得自动重新提交。
- 没有失败时直接进入人工查看，不为了展示自动修复而故意修改真实候选。
- 必须演示失败拦截时，单独建立故障注入测试，并与真实模型运行记录区分。

### 7.3 最小存储

SQLite 建议仅建立 inputs、runs、candidates、events、checks、provider_calls 六类记录。源码、截图、日志保存在运行目录，用相对路径和哈希引用，不把大文件直接塞入数据库。

任务恢复只恢复可确定的阶段。进程崩溃时先检查遗留进程与调用状态；不能因为没有成功记录就假设外部请求没发出去。

## 8. 构建、预览和基础安全

### 8.1 构建步骤

1. 为候选创建独立工作目录，复制固定模板和允许文件。
2. 使用受控依赖环境，不让模型选择可执行程序、工作目录或安装脚本。
3. 运行固定类型检查和构建命令，采集退出码、精简错误和耗时。
4. 构建成功后启动绑定本机地址的预览，校验端口与 readiness。
5. 浏览器访问预览，等待字体和必要资源就绪，收集截图、控制台错误和 DOM 观测。
6. 任务结束或取消时停止进程树、释放端口，保留报告需要的产物。

### 8.2 执行边界

- 独立目录不等于安全沙箱；锁定模板和路径校验也不能替代进程隔离。
- 代码执行环境不得继承模型/Figma 凭据，不可写宿主源码和用户目录。
- 对新依赖安装、任意脚本与外网请求默认禁用；必要资源在输入阶段受控下载。
- 优先评估复用现有 WSL/受管 runner，或采用具备文件、网络、进程限制的隔离方式；只选择一种首版实现，不建设多套执行系统。
- 若本机隔离暂未就绪，只做代码生成/静态检查与人工启动，不把自动执行功能写成安全可用。
- 浏览器预览与应用控制台分离 origin，并限制 iframe 能力；展示页面不得读取运行管理 API 中的秘密。

## 9. 验收体系：通用规则加输入专属规则

### 9.1 所有输入都检查

- TypeScript 检查与生产构建。
- 页面可加载，无未处理的关键 JavaScript 异常。
- 主要资源可加载，缺少字体、图片要可见地报告。
- 页面没有明显水平溢出、内容遮挡和不可点击的主要控件。
- 已声明交互可执行，键盘焦点和表单标签基本可用。
- 导出的工程在新的工作目录中能按文档启动。

建议视口基线为 1440、768、390 px。这是 Web 响应式测试，不是三端真机验证。没有小屏设计稿时只能验证合理响应式行为，不能宣称小屏像素级还原。

### 9.2 截图/Figma 的视觉检查

- 先统一视口、设备缩放、字体、截图时机和动画状态。
- 对比布局分区、位置尺寸、间距、文字、颜色与图片。
- 像素 diff 作为诊断信号，不能把抗锯齿差异直接判成业务失败。
- 对动态内容使用预先声明的屏蔽区，不允许模型事后随意扩大屏蔽范围。
- 第一版采用确定性检查加用户并排复核；额外视觉模型评审后置，并单独计算调用次数。
- 相似度阈值通过小样本校准后固定，不能先编造“95% 还原率”。

### 9.3 Spec 的功能检查

每个验收项有稳定 ID，例如 `SPEC-SEARCH-01`。为已支持的交互类型实现固定测试模板：文本过滤、Tab 切换、弹窗开关、表单必填、列表排序等。

模型可以建议测试映射，但不能自行决定需求通过。未支持自动检查的交互标记为待人工检查，不能自动算作成功。对于页面根本未声明的功能，不凭空增加必检要求。

### 9.4 检查记录

```text
CheckResult
  check_id / category
  applicability: applicable | not_applicable
  status: PASS | FAIL | UNKNOWN | NOT_RUN
  expected / observed
  evidence_refs[]
  candidate_hash / rule_version
  reason
```

不适用项必须有理由且从统计分母排除；适用但没执行、没证据的检查不得排除来美化通过率。检查计划在生成前确认，不能根据结果临时删失败项。

## 10. 自动修复与调用预算

第一版建议“一个候选生成 + 最多一次修复”，并在供应商 HTTP/SDK 调用边界计数，而不是只数 UI 操作或 Agent 轮次。

修复步骤：

1. 从构建/运行/视觉/交互检查中提取失败条目。
2. 反馈包含具体文件错误、期望与实际值、必要截图，不只写“页面不好看”。
3. 生成新版本候选，保留旧候选和差异。
4. 重新执行所有适用的必检项，而不只重跑上一次失败项。
5. 再次失败则结束并输出报告，不进入无限循环。

用户指定代码模型请求最多 2 次、自动重试 0 次、禁用多候选并发和额外模型调用；当前不设置 token 或费用上限。首次生成和修复通过中转统一使用 `openai/gpt-6-luna`，不自动切换其他模型。实际协议、图片输入支持和用量返回方式仍需核验。

如果上游 Agent 工具循环需要额外模型请求，必须改为单次生成路径，或者明确重新商定上限；不能仅修改一个 `max_iterations` 就宣称符合两次请求限制。SDK 内置重试也必须核对。

修复重入、双击按钮、网络重连和后台恢复应共用同一预算记录。取消只代表本地停止后续工作，不保证供应商已停止计费。

## 11. 前端页面怎么改

尽量复用上游页面，不另外设计一套庞大的工作台。

### 11.1 输入区

- Screenshot / Figma / Spec 三个添加入口，已添加资料共同保留，不互斥。
- 截图上传、Figma 链接输入、Spec Markdown 编辑。
- 资料列表：每份资料的用途、适用区域、视口/状态、读取状态和删除/替换操作。
- 本次指令：明确布局、样式、交互分别采用什么，以及需要增删的内容。
- 可选补充资源和交互说明。
- 固定输出技术栈提示。
- 合并后的输入摘要、采用来源、冲突处理与假设确认。

### 11.2 运行区

- 当前阶段、耗时、调用次数与用量。
- 本轮候选版本、取消操作。
- 错误分为输入、供应商、生成格式、构建、预览、检查六类。
- 明确显示“结果未知”，不要转圈后默默重试。

### 11.3 结果区

- 原图/设计预览与生成页面并排；Spec 模式展示需求条目。
- 视口切换、源码查看、候选差异。
- 检查结果及对应截图/错误。
- 一次修复按钮，额度耗尽后禁用并说明原因。
- 导出源码、报告和问题清单。

## 12. 配置与导出

### 12.1 单一 `.env`

按用户偏好，实际本机配置统一保存在 `D:\desktop\AI\D2C\Design2Code\.env`，可以包含模型与 Figma 凭据。后端显式加载该文件；Vite 只使用启动所需公开端口设置，不向浏览器注入秘密。三个上游的 `.env` 示例仅作字段参考，不分别维护实际配置。

所有需要手动填写的运行配置集中在这一个文件：中转 API 地址、key、接口协议、模型名称、可选 Figma 凭据、应用与预览端口、runtime 路径、输入限制、检查视口、超时、调用和 token/费用上限。完整模板与填写说明只在 18.16 维护，其他文档引用该节，不再提供容易漂移的第二份配置表。

不使用 `.env.local`、`.env.development` 等后缀，不在三个上游目录分别维护实际配置。截图、Spec、Figma 页面链接与本次生成指令属于任务资料，在工作台中输入并由 SourceSet 保存；模型/Figma 服务的连接参数统一来自根 `.env`。

实施时适配上游变量名，避免维护两套同义变量。秘密变量不能使用会被前端打包的 `VITE_` 前缀；`.env` 加入忽略和导出排除列表，启动诊断只报告字段是否齐全，不打印值。

### 12.2 ZIP 内容

- 固定候选的源码、模板和 lockfile。
- 本地静态资源及必要来源/使用说明。
- README：安装、启动、已实现功能、已知限制。
- `report.json` / `report.html`：适用检查、结果、失败原因。
- 截图、源码差异和内容哈希索引。
- 输入类型集合、资料集合版本和摘要、逐项来源映射、冲突结论、模板和规则版本、实际用量与费用是否已核实。

不包含 `.env`、访问令牌、模型原始秘密配置、宿主绝对私有路径或旧项目数据库。对用户设计原稿是否一起导出提供明确选项，不默认公开原始 Figma 文件资料。

## 13. 分阶段执行任务与完成条件

以下是实施顺序，不是已经完成的工作。时间只能在底座运行和兼容性摸底后估算，暂不承诺固定日期。

### 阶段 0：锁定底座与可行性验证

任务：

1. 核验已存在的 `Design2Code/screenshot-to-code` 来源、提交和许可证，不重复克隆。
2. 记录固定 commit，读取其开发约束及依赖清单。
3. 检查环境和启动命令，不直接搬用旧工程环境。
4. 在不调用供应商的条件下启动界面、验证接口和固定输出样例。
5. 梳理所有可能触发模型/图片服务请求的入口。
6. 选择统一调用入口、模板包装方案和本地 runner。

交付：上游基线记录、可启动应用、复用/新增模块清单、调用路径清单。

完成条件：明确“直接复用什么、必须改什么”；没有付费调用也能检查本地环境；不需要第二套完整服务架构。

### 阶段 1：截图与 Spec 的最小生成链

任务：

1. 完成固定 React/Vite 模板及结构化文件输出协议。
2. 实现 ScreenshotAdapter、SpecAdapter 与输入摘要。
3. 实现供应商统一调用、预算记录和输出校验。
4. 实现候选落盘、固定构建、受控预览。
5. 在用户确认本次调用配置后，分别运行截图和 Spec 各一个真实样例。

交付：输入 → 生成 → 构建 → 预览的可运行链，以及失败报告。

完成条件：两种输入至少各有一个可启动工程；代码来源、模型调用和候选可追踪；不能只在 iframe 中显示一段 HTML 就算工程化完成。

### 阶段 2：通用检查与一次修复

任务：

1. 实现类型、构建、控制台、资源和布局检查。
2. 接入三档视口截图和并排对比。
3. 为 Spec 的首批交互类型实现固定测试模板。
4. 实现失败反馈、一次修复、新候选与全量复验。
5. 验证双击修复、取消、超时、供应商结果未知和预算耗尽。

交付：检查报告、一次修复记录、回归测试。

完成条件：能拒绝坏候选；修复不会覆盖旧记录或增加隐式调用；没有参考图时不伪造视觉分数。

### 阶段 3：Figma 指定节点接入

任务：

1. 核对当前官方接口及实际账号权限。
2. 完成节点链接解析、授权读取、渲染图与资源下载。
3. 实现 FigmaAdapter 与来源快照。
4. 复用阶段 1、2 的生成、检查、修复链，不再写第二套流程。
5. 测试无权限、节点不存在、资源失效、限流与设计版本变化。

交付：Figma 节点 → 同一 DesignBrief → 可运行工程。

完成条件：至少一个真实可访问节点通过整个链；导出图片输入与直接节点接入在界面和报告中明确区分。

### 阶段 4：交付、复现和样例评测

任务：

1. 完成 ZIP、报告、资源引用和敏感内容排除。
2. 在新的工作目录按 README 启动导出工程。
3. 增加任务历史和断线事件补齐。
4. 整理至少 9 个固定样例：截图、Spec、Figma 各 3 个。
5. 使用相同输入、模型、模板和调用上限比较首次生成与修复后结果。
6. 录制演示并完善开源来源、个人改动与已知限制说明。

交付：可复现的个人项目、真实案例、评测记录和演示资料。

完成条件：三种输入均有证据；小样本中失败、未知和未执行均如实展示；不把 9 个样例的结果推广成任意页面成功率。

## 14. 测试用例与验证方法

### 14.1 单元测试

- 图片类型/大小/解码、Spec 空输入、Figma 链接解析。
- DesignBrief 校验、来源标记和输入摘要。
- 输出协议解析、路径穿越、重复文件和超大输出。
- 预算预留/结算、请求幂等、修复上限。
- 检查适用性、分母统计、候选摘要绑定。
- 导出排除 `.env`、ZIP 路径和哈希校验。

### 14.2 集成测试

- 固定模型响应进入候选目录、真实构建和浏览器预览。
- 构建失败、缺图、运行异常、端口冲突和进程清理。
- SQLite 状态与文件内容一致，崩溃后不重复发送模型请求。
- Figma 网络响应使用受控样例测试权限/限流分支；真实文件另测。
- 用 mock provider 验证请求次数边界，但不把它算作真实模型生成。

### 14.3 真实 E2E 与评测

- 截图：落地页、仪表盘、设置页等不同布局。
- Spec：任务列表、表单、内容筛选页等可交互页面。
- Figma：具有 Auto Layout、图片资源和嵌套结构的指定节点。
- 记录首次构建成功、最终构建成功、适用交互通过情况、人工视觉结论、修复次数、总耗时和实际 token。
- 未拿到确定账单时只展示估算费用及口径，不宣称精确成本。
- 不额外增加一轮模型“裁判”来美化结果；如引入，必须计入预算并说明裁判局限。

### 14.4 项目完成定义

只有以下事项均满足，才称“个人 Design2Code 第一版完成”：

- 三种输入单独使用、图片 + Spec、Figma + Spec、图片 + Figma + Spec 均可走通到固定技术栈工程；组合验收见 19.4。
- 有受控自动构建、预览、检查及一次修复能力，或明确披露未自动化的边界。
- 有真实供应商运行记录，而不是只有 mock/fixture。
- 有失败拦截案例、完整修复回归和导出后复现结果。
- 配置、运行、停止和问题定位文档可由用户照着执行。
- 已知限制与未支持场景可见；无生产上线主张。

## 15. 最容易踩的坑与处理决策

1. **三个开源工程整套融合。** 首版仅一个主底座，另外两个作为能力参考。
2. **先接 Figma、再做任何生成。** 先用截图/Spec 验证执行链，Figma 仅增加输入适配。
3. **只得到好看的单文件预览。** 优先固定可构建工程模板和导出复现。
4. **一次操作包含多次付费请求。** 在最低供应商调用边界计数并禁止隐式重试。
5. **截图中没有的信息靠模型猜测后当真。** 记录假设，区分设计事实与推断。
6. **把视觉相似当作功能正确。** 两类检查分开报告。
7. **为了通用而删掉全部验收。** 改为按输入与需求选择适用规则，而不是取消验证。
8. **直接移植旧工程全部治理。** 只迁移能独立证明价值的模块；旧任务状态原样保留。
9. **把本地隔离目录当作安全执行环境。** 在自动执行生成代码之前落实 runner 隔离。
10. **先清理旧代码再验证新路线。** 新版可复现之后再讨论归档，避免失去参考和回退材料。

## 16. 下一次实施应从哪里开始

先做阶段 0，不直接把三种输入、自动修复、导出和可视化编辑同时展开。

第一批工程任务按顺序是：

1. 使用已拉取的 `screenshot-to-code` 仓库建立开发分支，记录源码基线。
2. 给出当前环境和依赖安装清单，检查本机已有工具。
3. 启动前后端，用固定输出验证预览，不调用模型。
4. 找出最小可复用的生成入口及全部隐式请求路径。
5. 固定模板、输出协议和隔离 runner 方案。
6. 给出一次真实样例所需的模型、请求次数和预算，再开始真实生成。

用户现阶段只需准备：一张有权使用的页面截图、一段简单 Spec；Figma 样例可在阶段 3 前再提供。无需为开始这个新项目先补齐旧电商项目的部署身份和审批材料。

## 17. 本文的事实与变更边界（初始基线）

本节记录方案编写时的初始状态。当前实现状态以文末“2026-11-10 文档与环境同步记录”为准。

- 已完成：三个仓库 SSH 克隆、来源/提交核对，以及独立本地演示服务的创建。
- 已核对：主底座输入、WebSocket、Agent、ProviderSession、预览、上传资源和导出源码；Figma 插件消息与转换入口；Onlook preload、Penpal 和 AST 修改入口。
- 当时尚未完成：主底座依赖安装和浏览器联调、真实模型、Figma 读取、工程构建、一轮修复和统一导出；这些项目后续已分批推进，仍未完成的部分在文末明确列出。
- 当时的演示服务没有截图粘贴能力；当前主工作台已提供截图选择、拖放和 Ctrl+V 入口，旧演示壳仍不作为验收入口。
- 此文中的新增 API、目录、协议、状态与模块均为实施设计；下文示例中的 ID 和哈希仅为协议示例，不是实际业务记录。
- 本轮仅更新本文件。所有真实秘密配置仍由唯一 `.env` 提供，不写入本文。

## 18. 各部分接口对接与集成实施细则

本节是开发时的接口手册。路径从 `Design2Code/` 开始；标为“已有”的文件已在本机源码中核对，标为“新增”的文件和协议需要实际实现。示例均使用无秘密的演示值。

### 18.1 集成后的运行关系与入口切换

对应第 1、2、4 节。

首版只启动两项应用服务：React/Vite 前端和 FastAPI 后端。任务执行器作为后端单进程内的一个顺序队列运行；同一后端只能启动一个执行者，启动参数固定 `workers=1`。生成页面由隔离 runner 的独立端口提供预览。

建议端口：

| 用途 | 地址 | 如何使用 |
| --- | --- | --- |
| 主工作台 | `http://localhost:5173` | 用户打开的唯一主界面 |
| FastAPI | `http://127.0.0.1:7001` | Vite 在开发环境代理 HTTP/WS |
| 候选预览 | 由 runner 分配本机端口 | 后端返回 preview URL，前端 iframe 加载 |
| 旧演示壳 | `http://127.0.0.1:8787` | 迁移期间保留历史入口，不参与新版任务链 |

端口可由根目录 `.env` 覆盖；预览 origin 要与工作台分开，后端根据实际启动的 runner 记录验证预览地址。

已有主入口：

- `screenshot-to-code/frontend/src/App.tsx`：工作台组件装配。
- `screenshot-to-code/frontend/src/components/unified-input/UnifiedInputPane.tsx`：上传、URL、文本、代码导入入口。
- `screenshot-to-code/frontend/src/generateCode.ts`：原 `/generate-code` WebSocket 客户端。
- `screenshot-to-code/backend/main.py`：环境加载、FastAPI 实例与路由注册。
- `screenshot-to-code/frontend/vite.config.ts`：已有 `/api`、`/generate-code`、`/local-assets` 代理。

新增后端入口：`backend/design2code/api/router.py`，声明统一前缀 `/api/d2c/v1`。在 `main.py` 中注册 router，并在 lifespan 中启动/停止唯一任务执行者。新增代码放进主仓库内部，不通过 `sys.path` 或跨仓库相对导入依赖另两个仓库。

新增前端入口：`frontend/src/features/design2code/`，内部放 API 客户端、运行 Store、输入摘要、检查报告等组件。原上传、代码编辑、预览外观可以继续复用；生成按钮由新的 `createRun()` 驱动。

关键规则：新版页面创建 Run 后，只订阅事件；不再同时调用原 `generateCode()` 触发第二次模型执行。旧接口可以保留供上游功能使用，但首版产品按钮只能走一条调用路径。

实际切换步骤：先启动上游原界面并确认静态资源、代理和健康接口；接入新版输入与任务接口；最后让主界面默认进入新版流程。浏览器端验证通过后再更改 README 的默认启动入口。

### 18.2 跨模块契约与数据归属

对应第 5、6、7、9 节。

建议在 `backend/design2code/contracts/` 定义 Pydantic 模型：`inputs.py`、`brief.py`、`runs.py`、`generation.py`、`checks.py`、`events.py`。前端在 `features/design2code/contracts.ts` 使用同版本类型；可由受控脚本导出 JSON Schema，再生成或核对 TypeScript 类型。

统一使用以下标识：

- `input_id`：原始资料及其资源快照，输入内容不可变。
- `source_set_id + source_set_revision + source_set_hash`：本次组合的输入引用、资料用途、指令与冲突结论；单输入同样通过资料集合进入 Run。
- `brief_id + brief_revision + brief_hash`：用户补充信息后的生成说明；修改需新 revision。
- `run_id`：一次完整任务；一个 Run 可产生多个候选。
- `candidate_id + candidate_hash`：某一组完整源码、资源和模板的固定快照。
- `check_plan_hash`：生成前确定的适用检查清单。
- `call_id`：一次实际供应商请求，关联 run、阶段与用量。
- `seq`：某个 Run 内递增的事件序号，与供应商事件 ID 无关。

输入接口返回的简化对象：

```json
{
  "input_id": "inp_demo_01",
  "input_type": "screenshot",
  "source_hash": "sha256:<服务端计算的完整摘要>",
  "assets": [
    {
      "asset_id": "asset_demo_01",
      "role": "reference",
      "mime_type": "image/png",
      "width": 1440,
      "height": 900,
      "url": "/api/d2c/v1/assets/asset_demo_01"
    }
  ],
  "status": "READY",
  "warnings": []
}
```

后端掌握文件路径、哈希、模型身份、实际调用次数和状态。前端只能提交输入、说明与允许的操作，不能上传 `PASS`、账单、文件绝对路径或自行计算的“权威候选摘要”。

文件摘要包含模板版本、源码与本地资源摘要，按规范化路径排序后计算。构建结果另有 `build_hash`，避免源码哈希与构建哈希混为一谈。

统一错误对象：

```json
{
  "error": {
    "code": "INPUT_INVALID_IMAGE",
    "message": "无法读取图片，请重新选择 PNG 或 JPEG 文件。",
    "request_id": "req_demo_01",
    "retryable": false,
    "details": { "field": "files" }
  }
}
```

HTTP 状态建议：400 请求格式错误；404 输入/任务不存在；409 状态冲突或幂等键内容不同；413 输入过大；422 可解析但不支持的内容；429 Figma 读取限流或本地输入频率限制；503 缺少配置/runner。供应商已受理后的运行失败写入 Run 状态，不把 HTTP 重试变成另一次收费操作。

### 18.3 截图选择、拖拽、Ctrl+V 如何接入

对应第 5.2、11.1 节，也是当前用户要求的截图粘贴入口。

**已有落点：**`frontend/src/components/unified-input/tabs/UploadTab.tsx` 内已有 `handleAddFiles`、react-dropzone 和预览资源释放逻辑。当前源码未发现该入口的图片粘贴监听，应补入同一文件处理链。

**新增落点：**`features/design2code/inputs/useScreenshotInput.ts`、后端 `design2code/inputs/screenshot.py`。

浏览器处理顺序：

1. 文件选择/拖拽得到 `File[]`；粘贴从 `ClipboardEvent.clipboardData.items` 提取图片，转成 `File`。
2. 三个入口统一调用 `acceptScreenshot(file)`，避免粘贴绕过类型、大小和数量限制。
3. 每个文件单独保存为输入；同一资料集合最多 3 张 PNG/JPEG。替换时释放旧 Object URL，用新 input_id 更新资料集合并使原 Brief 确认失效，不覆盖已运行任务的输入。
4. 使用 Object URL 显示缩略图，支持删除/替换，显示实际宽高和字节大小。
5. 图片粘贴可以在 Spec 文本框内处理，但只有剪贴板确含图片时才阻止默认事件；普通文字照常粘贴。监听在组件卸载时解除，避免一个粘贴动作上传两遍。
6. 按“生成”或“解析输入”时，使用 `FormData` 上传原始文件；不要只上传文件名。

请求约定：

```text
POST /api/d2c/v1/design-inputs
Content-Type: multipart/form-data; boundary=浏览器自动设置

input_type = screenshot
files = <真实图片文件>
supplemental_spec = 按钮打开详情弹窗；窄屏改为单列
```

前端调用示意：

```ts
const data = new FormData();
data.set("input_type", "screenshot");
data.set("files", file, file.name);
data.set("supplemental_spec", supplementalSpec);
const response = await fetch("/api/d2c/v1/design-inputs", {
  method: "POST",
  body: data,
});
```

不要手动设置 multipart 的 Content-Type，否则可能缺失 boundary。上游后端依赖清单未声明 `python-multipart`，实现该接口时需要按 Poetry 工作流加入并更新锁文件，不能仅写一个 `UploadFile` 参数就认为接口能启动。

服务端：限制总字节与解码像素 → Pillow 实际解码 → 记录尺寸/格式/摘要 → 保存原图 → 必要时生成模型用副本 → 写 input/asset 元数据 → 返回输入摘要。像素上限和字节上限为可配置工程限制，先给保守默认，再用样例调整。

模型副本缩放属于服务端确定性处理，不额外占模型调用。保存 `original_size`、`model_size`、缩放比例和副本 hash；视觉对比仍使用固定原始参考视口。

主底座 `backend/uploaded_assets/store.py` 已有 data URL 解析、摘要和临时资源提升逻辑，可复用其图像解析与存储思路，但新增输入仍需关联 input_id/run_id；不能只保存在上游全局资源目录就称为任务快照。

资源接口：`GET /api/d2c/v1/assets/{asset_id}`，仅按数据库中可信引用读取文件，返回正确 MIME 与 `X-Content-Type-Options: nosniff`。不要直接挂载整个 runtime 目录。

联调条件：剪贴板图片、文件选择、拖拽各成功一次；损坏图片、过大图片、普通文本粘贴、删除后再生成均行为明确。报告应能证明真实图片 bytes 已保存，不能只显示“截图已记录”。

### 18.4 Spec 文本与 Markdown 如何接入

对应第 5.3、9.3 节。

**已有落点：**`TextTab.tsx` 已通过 `doCreateFromText(text)` 发起文本生成。复用编辑输入外观，将回调替换成新版输入保存与 Run 创建。

**新增落点：**`design2code/inputs/spec.py`、`features/design2code/inputs/SpecInput.tsx`。

与图片接口共用一个 multipart 协议：

```text
POST /api/d2c/v1/design-inputs

input_type = spec
spec_text = # 任务管理\n- 搜索任务\n- 状态筛选\n- 新建任务弹窗
```

上传 `.md` 时使用 `files` 字段；同一请求中 `spec_text` 和 Markdown 主文件只能选一个作为主内容。`supplemental_spec` 可作补充。后端拒绝空内容，统一为 UTF-8，并保留原文；解析出的结构是附加结果，不能覆盖原始 Spec。

Brief 确认接口，截图、Figma 与组合资料也复用；先按 18.20 创建 SourceSet：

```text
PUT /api/d2c/v1/source-sets/{source_set_id}/brief
If-Match: "<当前 brief_hash>"
```

```json
{
  "source_set_revision": 1,
  "source_set_hash": "sha256:<当前资料集合摘要>",
  "title": "任务管理页面",
  "supplemental_spec": "所有数据为本地演示数据",
  "interactions": [
    {
      "id": "SPEC-DIALOG-01",
      "kind": "dialog_open",
      "trigger": { "role": "button", "name": "新建任务" },
      "expected": { "role": "dialog", "name": "新建任务" }
    }
  ],
  "responsive_rules": ["390px 下列表改为单列"]
}
```

后端返回新的 brief_revision/hash 和检查计划摘要；前端如果拿着旧 hash 保存，返回 409，提示刷新摘要。Spec 的每个明确条目分配稳定 ID，`interactions.kind` 只接受已支持的动作枚举；复杂自然语言保留为人工检查条目。

在同一个 Run 内 Brief 不可再改。用户改需求创建新的 Run，避免修复阶段顺便改变验收标准。

联调条件：同一 Spec 的原文、Brief、检查项可相互定位；文本框中普通粘贴不丢字；未支持自动化的条目不被计为自动通过。

### 18.5 Figma 官方接口如何接入

对应第 5.4 节。主路径为 FastAPI 后端读取官方数据，不在浏览器中发 Figma token。

**新增落点：**`design2code/inputs/figma_client.py`、`figma_normalizer.py`、前端 `FigmaInput.tsx`。

应用请求：

```text
POST /api/d2c/v1/design-inputs/figma
Content-Type: application/json
```

```json
{
  "url": "https://www.figma.com/design/DEMO_FILE/Page?node-id=12-34",
  "supplemental_spec": "点击保存后展示成功提示"
}
```

后端解析主机、文件 key 和 node-id。只接受已明确支持的 Figma 文件 URL；对常见 URL node-id `12-34` 规范为接口节点 ID `12:34`，保留原始值；不能把任意字符串中的所有连字符无差别替换。

FigmaClient 的实际请求：

1. `GET https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}`：读取指定节点与文件版本。
2. `GET https://api.figma.com/v1/images/{file_key}?ids={node_id}&format=png&scale=1`：获取该节点参考渲染图的下载地址。
3. 如节点包含 image fill，按需要使用 `GET /v1/files/{file_key}/images` 获取图片资源映射，再只下载被选中子树引用的资源。

以上是官方现有 API，应用的 `/api/d2c/v1/...` 则为拟新增路由；节点映射可返回 null，必须按节点缺失处理。[Figma 文件接口文档](https://developers.figma.com/docs/rest-api/file-endpoints/)

个人项目使用已配置的个人访问 token 时，由后端写 `X-Figma-Token`；OAuth 路径单独使用 Bearer token。需要的文件内容读取权限与实际账号文件访问权限均由官方规则决定。[认证与权限文档](https://developers.figma.com/docs/rest-api/authentication/)

节点字段映射：

| Figma 来源字段 | DesignBrief 内容 | 处理方式 |
| --- | --- | --- |
| `id`、`name`、`type` | section/node 来源 | 保留 ID，不能作为宿主文件路径 |
| `absoluteBoundingBox` | 初始视口与矩形信息 | 画布绝对坐标转相对根节点坐标 |
| `layoutMode`、padding、`itemSpacing` | 布局规则 | HORIZONTAL/VERTICAL 映射 flex 方向，不能强制一律 absolute |
| `characters`、`style` | 文案与字体属性 | 字体不可用时记录替代与警告 |
| `fills`、`strokes`、圆角等 | 设计 token 与样式 | 记录精确原值及来源 |
| image references | assets | 下载为内容寻址的本地文件 |
| component/instance 信息 | 组件参考 | 没有代码映射时仅作提示，不声称复用了既有 React 组件 |

读取和渲染应尽可能固定同一版本；检查所选 endpoint 是否支持 `version`，支持时传入已取得的版本。无法确保参考图与节点 JSON 属于同一版本时，重新获取一致快照或报告不一致，不能混用后继续计算视觉结论。

输入读取可能较慢，建议该路由返回 202 与 input_id，输入状态为 `IMPORTING`，通过 `GET /design-inputs/{id}` 查询；读取完成变 `READY`，失败记录在输入上。只有全部纳入来源 READY、Brief 已确认的 SourceSet 能创建 Run。此时还没有模型调用。

对权限错误、缺节点、无渲染图分别返回 `FIGMA_FORBIDDEN`、`FIGMA_NODE_NOT_FOUND`、`FIGMA_RENDER_UNAVAILABLE`。429 返回可展示的 next_allowed_at/等待秒数；遵循官方 `Retry-After`，不在界面刷新时持续重复读取。[Figma 限流文档](https://developers.figma.com/docs/rest-api/rate-limits/)

联调条件：一个真实选中 Frame 的 JSON、参考图、本地资源、version 和 input_id 可绑定；无权限链接不会创建可生成输入；同一输入刷新页面不重新下载全部设计文件。

### 18.6 FigmaToCode 的代码和导出能力怎么衔接

对应第 2.2 节。它不是 HTTP 微服务；`packages/backend` 这个目录名不代表 FastAPI 可以直接调用。

已确认的源码入口：

- `apps/plugin/plugin-src/code.ts`：`figma.ui.onmessage`、`download-project`、`get-selection-json`。
- `packages/backend/src/code.ts`：`run(settings)`，内部访问 `figma.currentPage.selection`。
- `packages/backend/src/altNodes/jsonNodeConversion.ts`：`nodesToJSON`，依赖真实插件节点能力。
- `packages/backend/src/index.ts`：导出 `htmlMain`、`tailwindMain`、`generateProjectZip` 等。
- `packages/types/src/types.ts`：`ConversionMessage`、`ProjectZipMessage` 和 `PluginSettings`。
- `manifest.json`：当前插件网络配置为 `allowedDomains: ["none"]`。

因此优先采用文件级连接，步骤如下：

1. 用户在 Figma 插件中选中 Frame，通过插件已有下载功能导出 Vite/HTML 等项目。
2. 新版工作台增加“导入 Figma 项目包”，调用拟新增 `POST /api/d2c/v1/design-inputs/figma-bundle`，使用 multipart 上传 ZIP 和可选参考 PNG。
3. 后端在临时目录检查 ZIP：条目数、展开体积、路径、重复名称、符号链接和不支持文件；不运行包里的安装脚本。
4. 读取允许的源码/资源，形成 `ReferenceProject`，记录原始 ZIP hash、导出工具、格式与警告。
5. 将它作为种子代码传给固定 React 模板包装器；只在文件格式兼容时直接采用，否则作为参考输入参与模型生成。
6. 报告保留“插件转换”“模型新增”“用户补充”的来源，后续与通用构建、检查和导出共用流程。

仅导出的 ZIP 通常不包含完整设计语义树和检查参考图；缺什么字段就记录缺口，不因来自 Figma 插件自动标为视觉验收完备。

若后续直接二开插件：保持当前无网络边界，新增“导出 Design2Code 资料包”按钮，把标准 JSON、参考 PNG、资源和可选 JSX 放入 ZIP；由用户在工作台上传。插件 UI 与主线程通过 `parent.postMessage({pluginMessage: ...}, "*")` 和 `figma.ui.postMessage(...)` 通信，不能把它等同于普通网页直接访问后端。

上游已有消息：UI 发 `download-project`，插件回 `project-zip`/`project-download-error`；`get-selection-json` 对应 `selection-json`。新增本项目消息应使用独立名称和 request_id，不能改变已有消息语义。直接做插件源码复用与分发时，保留来源并先明确 GPL-3.0 的项目采用方案；本阶段默认只把资料包作为输入。

REST JSON 与插件 SceneNode 不是同一种对象，不能直接将 REST 响应传入 `nodesToJSON`；如确需纯 Node 转换服务，必须提取不依赖 figma 全局对象的中间表示与转换器，并补齐其测试，这是单独工作项。

联调条件：导入一个真实插件导出包可以成为可追踪输入；恶意/损坏 ZIP 明确拒绝；导入过程无安装、无生成费用；缺少参考图时检查适用性正确。

### 18.7 供应商生成入口如何接入与收口

对应第 2.1、6、10 节。

原有链路：`generateCode.ts` → `WS /generate-code` → Pipeline → `AgenticGenerationStage.process_variants()` → `Agent.run()` → `AgentEngine` → `ProviderSession.stream_turn()` → 供应商 SDK。

本项目链路：`POST /runs` → RunService → 单执行者 → `GenerationProvider.generate()` → 供应商 session → 结构化 GenerationResult → 候选固化。前端 WS 仅接收事件。

新增接口形状：

```python
class GenerationProvider(Protocol):
    async def generate(
        self,
        request: GenerationRequest,
        emit: Callable[[GenerationEvent], Awaitable[None]],
    ) -> GenerationResult: ...
```

GenerationRequest 包含：run_id、call_id、purpose（generate/repair）、固定 Brief、参考图/资源、模板版本、当前候选（修复时）、失败反馈、预算和取消信号。它不携带来自浏览器的 API key 或任意供应商 URL；供应商配置从后端 Settings 注入。

具体适配文件：

- 新增 `design2code/generation/provider.py`：领域接口。
- 新增 `single_shot.py`：一次请求产生一个文件集合。
- 复用/适配 `agent/providers/base.py` 的 stream event 和 ProviderTurn 结构。
- 对 `agent/providers/factory.py` 增加显式 policy 或由新增工厂直接构建所选 session。
- 第一版只实现实际使用的一家供应商；其他 session 不在菜单中虚假显示“已支持”。

首版选择一次结构化生成路径：tools 为空，调用一次 `stream_turn()`，取最终 assistant_text，按 GenerationResult Schema 解析。`stream_turn` 内部对不同模型/参数的兼容需实测；现有 OpenAI session 使用 Responses 路径，不是任意 Chat Completions 代理都能兼容。中转协议由根 `.env` 的 `D2C_API_PROTOCOL` 明确选择，字段契约见 18.16；若中转只支持 Chat Completions，应新增对应适配器，不能仅替换 base URL 或填写协议字段就承诺可用。

现有 factory 会自动开放可用的图片编辑/资源提取/截图工具，因此新工厂必须显式控制 tool policy；仅传 `should_generate_images=False` 不足以关闭所有工具。空工具时还要适配工具选择字段，不能无条件保留不兼容的 `tool_choice`。

每次实际网络请求之前：原子预留 request slot、token/费用额度 → 写 provider_calls 的 `PREPARED` → 标记 `SENT` → 调 SDK → 收到结果写 `SUCCEEDED`/`REJECTED`/`UNKNOWN` → 结算实际 usage。超时发生在发送后时保留 UNKNOWN，不补发。preflight 未发请求就失败可释放预留额度。

上游 OpenAI session 当前写死 `max_output_tokens=50000`，新版需按所选模型允许的参数传入；用户当前未设置 token/费用上限，不以缺少价格拦截生成。供应商未返回价格或账单时，费用显示未知，不能把未知当作零费用。

SDK 自带重试、重连、模型 fallback、图片生成和视觉裁判均需纳入调用审计。首版关闭自动重试/多候选/额外工具循环；请求上限来自后端确认的 RunPolicy，客户端只能申请更低额度。

用量适配需补充统一 `UsageReceipt`：request_id（若有）、model、input_tokens、output_tokens、cached/reasoning 字段（若有）、计价版本、估算费用、账单确认状态。上游 `total_cost_usd()` 可能返回 None，缺少价格时不得把 None 当 0。

联调条件：mock transport 断言首次生成只产生一次供应商 HTTP 请求；真实供应商样例另行执行；不支持协议、未知模型、额度耗尽在发请求前明确失败；流式中断后不会创建第二个 call_id 自动重试。

### 18.8 从生成结果到固定 React 工程怎么接

对应第 6 节。

已有 `AgentFileState` 只有 `path/content`，默认 `index.html`；`setCode` 流中也可能是半截输出。这与多文件 React 工程不同，需要增加工程结果契约。

建议 GenerationResult：

```json
{
  "schema_version": "d2c.generation.v1",
  "target_template": "react-vite-v1",
  "entrypoint": "src/App.tsx",
  "files": [
    { "path": "src/App.tsx", "content": "export default function App() { return <main>Demo</main>; }" },
    { "path": "src/styles.css", "content": "@tailwind base;\n@tailwind components;\n@tailwind utilities;" }
  ],
  "asset_refs": [],
  "requirement_mapping": [
    { "requirement_id": "SPEC-DIALOG-01", "files": ["src/App.tsx"] }
  ],
  "assumptions": []
}
```

此处样例只演示协议，不能证明功能已实现。字段使用 Pydantic 校验，并校验路径/体积/数量、默认导出、允许 imports、assets 和固定依赖集合。

新增文件：`generation/parse_result.py`、`workspace/candidate_writer.py`、`workspace/template.py`。

包装过程：

1. 固定模板中提供 package.json、lockfile、index.html、main.tsx、tsconfig、Vite/Tailwind 配置。
2. 将经过校验的 src 文件和资源写入临时候选目录。
3. 模型引用资源使用稳定 `/assets/<id>.<ext>`；包装器映射到 `public/assets/`。
4. 生成 candidate manifest；资源、模板和源码均计入摘要。
5. 临时目录原子发布为 c001/c002，SQLite 关联 candidate_hash 与状态。
6. 只有完整输出解析并发布成功后发送 `candidate.created`；流式 chunk 仅作界面进度。

上游 HTML Prompt 与我们的 JSON 文件输出 Prompt 不能混用。`backend/prompts/pipeline.py` 可复用输入消息构造机制，但固定输出协议提示需由新增 `design2code/generation/prompts.py` 单独负责。

不要使用正则把任意 HTML 中的 script 自动改成 TSX；无法可靠转换的旧 HTML 只走标明格式的兼容导入路径，不进入“React 工程已构建成功”的统计。

上游 `Stack.REACT_TAILWIND` 值为 `react_tailwind`，不是我们的模板 ID。新增 `target_template` 字段处理两者的映射，不把模板名硬塞进上游枚举导致前后端校验不一致。

联调条件：固定 JSON 样例可成为真实可构建工程；无效 JSON、输出截断、重复路径、越界路径和未批准依赖均在执行前可解释失败；输入文件和旧候选不会被覆盖。

### 18.9 创建任务、SQLite、幂等与取消怎么接

对应第 7 节。新增 `application/run_service.py`、`storage/sqlite.py`、`execution/worker.py`；目录均位于 `backend/design2code/` 内。

创建请求：

```text
POST /api/d2c/v1/runs
Idempotency-Key: create-demo-001
Content-Type: application/json
```

```json
{
  "source_set_id": "srcset_demo_01",
  "source_set_revision": 1,
  "source_set_hash": "sha256:<固定资料集合摘要>",
  "brief_id": "brief_demo_01",
  "brief_revision": 2,
  "brief_hash": "sha256:<当前说明摘要>",
  "target_template": "react-vite-v1",
  "requested_limits": { "model_requests": 2, "repairs": 1 },
  "execution_mode": "generate_and_check"
}
```

响应 202：

```json
{
  "run_id": "run_demo_01",
  "status": "CREATED",
  "state_version": 1,
  "check_plan_hash": "sha256:<固定检查计划摘要>",
  "events_url": "/api/d2c/v1/runs/run_demo_01/events?after_seq=0",
  "stream_url": "/api/d2c/v1/runs/run_demo_01/stream?after_seq=0"
}
```

RunService 在事务中核对 SourceSet 版本/hash、所有纳入来源 READY、Brief 绑定同一资料集合版本且已确认、阻断冲突已解决、模板存在、运行模式和调用配置可用，保存资料集合、Brief、实际 RunPolicy 与检查计划快照。相同幂等键且相同请求摘要返回原 run_id；相同键不同内容返回 409。首版已有活动任务时返回 `RUN_BUSY`，避免同时触发两个执行者。

元数据表最小字段：

| 表 | 核心字段 | 约束 |
| --- | --- | --- |
| inputs | id、type、status、source_hash、manifest_ref | 原始内容不可变；Brief 属于组合后的资料集合 |
| source_sets | id、revision、source_set_hash、manifest_ref、created_at | `(id, revision)` 唯一；旧版本不可覆盖 |
| briefs | id、revision、source_set_id、source_set_revision、source_set_hash、brief_hash、manifest_ref、confirmed_at | 确认仅对绑定的资料集合版本有效 |
| runs | id、source_set_id、source_set_revision、source_set_hash、brief_hash、policy_json、check_plan_hash、status、state_version、idempotency_key、request_hash | 幂等键唯一，状态比较后更新 |
| candidates | id、run_id、parent_id、manifest_ref、candidate_hash、build_ref、state | 同 run/revision 唯一 |
| events | run_id、seq、type、candidate_id、payload_json、created_at | `(run_id, seq)` 唯一 |
| checks | run_id、candidate_id、check_id、rule_version、status、evidence_ref | 按候选和规则版本定位 |
| provider_calls | call_id、run_id、purpose、status、reserved limits、usage_json、provider_request_id | 调用状态和计数由服务端维护 |

输入资源/Brief/check plan 可先以本地 JSON 文档配合表记录，不必每个字段再建一张表。文件引用一律在可信 runtime 根下解析。

状态变更与对应事件在同一 SQLite 事务内提交。生成/构建这些慢动作在事务外执行；完成时检查 state_version 与取消标记再提交结果，避免任务已取消却被慢请求覆盖成成功。

候选文件与数据库不能形成真正跨系统事务，采用“临时目录 → 完整 manifest → 原子发布目录 → 元数据提交”的顺序；崩溃后根据 manifest 和数据库重整。孤立完整目录不自动认作已交付候选，残缺目录不进入构建。

`GET /runs/{id}` 返回当前状态、候选摘要、实际预算、最后 seq、preview URL、失败原因与 `allowed_actions`。前端按钮依据 allowed_actions 显示，后端仍独立校验。

取消：`POST /runs/{id}/cancel` 幂等接受；标记取消 → 停止后续步骤 → 终止受管本地进程树 → 追加事件。供应商请求已发出且结果不明时，在 provider_calls 保留 UNKNOWN，Run 中显示外部调用未确认；不能把点击取消当作计费已撤销。

重启恢复：未发供应商请求的任务可重新排队；已 SENT 无回执的调用进入 `UNKNOWN_EXTERNAL`；构建中断可在清理进程并校验候选后重建，重建不增加模型请求。状态由 SQLite 还原，不依赖浏览器一直开着。

联调条件：重复提交、双击、进程退出和页面刷新均不重复收费；数据库中状态和事件一致；无法确定的供应商结果在 UI 可见。

### 18.10 实时事件和上游 WebSocket 怎么衔接

对应第 7.1、11.2 节。新增 `api/events.py`、`features/design2code/api/runEvents.ts`。

上游已有消息为 `chunk`、`setCode`、`status`、`variantComplete`、`variantError`、工具事件等；这些消息没有本项目完整 Run 的持久化语义。上游 `eventId` 不能替代 Run 的递增 seq。

本项目统一事件示例：

```json
{
  "schema_version": "d2c.event.v1",
  "run_id": "run_demo_01",
  "seq": 12,
  "type": "candidate.created",
  "stage": "generating",
  "candidate_id": "cand_demo_001",
  "occurred_at": "2026-11-09T14:00:00Z",
  "payload": { "file_count": 3, "candidate_hash": "sha256:<候选摘要>" }
}
```

主要类型：`run.started`、`stage.changed`、`generation.delta`、`provider.call_finished`、`candidate.created`、`build.completed`、`check.completed`、`repair.started`、`run.ready_for_review`、`run.failed`、`run.cancelled`、`run.complete`。

事件桥接原则：

- assistant/chunk 可以转成批量节流的 generation.delta，仅用于展示。
- `setCode` 可能多次出现且内容不完整，不直接转成 candidate.created。
- `variantComplete` 只代表该模型生成结束，不代表构建、检查和人工查看完成。
- 正常关闭原 WS 不直接转成 run.complete；异常断线也不默认取消后端任务。

建议 `GET /events` 返回 `{events, next_seq, has_more}`，分页限制单次数量；WS 接收 after_seq 后从数据库顺序发送，接近实时末尾时等待通知再查库，不使用会漏掉注册窗口事件的“先拉历史、后订阅”实现。

客户端记录已应用最大 seq，忽略重复事件；发现缺口先通过 GET 补齐，不创建新 Run。重连指数退避并在任务完成/组件卸载后关闭连接。一个 Run 只保留一个活动订阅。

代码增量可以节流后保存在事件中，完整文件以候选 manifest 为准；首次刷新根据 `GET /runs/{id}` 读取状态和当前候选，再回放后续事件。不要在 Zustand 和 SQLite 各维护一套不可协调的完成真值。

联调条件：断线期间任务继续；重新进入页面能补齐检查结果；重复事件不会重复追加候选；订阅断开不会再次调用模型。

### 18.11 构建与预览 runner 的具体接口

对应第 8 节。新增 `runner/protocol.py`、`runner/local_runner.py` 或选定的一种受管 runner 适配器；不要同时维护多套首版实现。

接口草案：

```python
class BuildRunner(Protocol):
    async def build(self, candidate: CandidateRef) -> BuildResult: ...
    async def start_preview(self, build: BuildRef) -> PreviewHandle: ...
    async def capture(self, preview: PreviewHandle, request: CaptureRequest) -> CaptureResult: ...
    async def stop(self, handle: PreviewHandle) -> None: ...
```

CandidateRef 由服务端查询得到，包含 candidate_id/hash、可信工作目录和模板 ID。BuildResult 返回 exit_code、build_hash、日志引用、开始结束时间和错误摘要；PreviewHandle 返回受管进程 ID/引用、origin、readiness 与到期时间，不包含秘密环境变量。

进程命令来自模板固定 scripts，执行参数列表而不是模型生成 shell。模板固定 Node/pnpm 版本与 lockfile；依赖环境在模板准备阶段建立，构建每个候选时无需重新联网安装全套依赖。

构建命令建议分开记录类型检查和 bundle：`pnpm exec tsc --noEmit`、模板固定的 `pnpm run build`。命令是否重复类型检查由模板 scripts 明确定义。运行前验证工作目录、模板锁摘要、允许依赖和进程执行环境。

预览使用构建后的静态 dist；固定静态服务和显式 host/port。readiness 检查既确认进程仍在运行，也确认页面资源能加载；不能拿到一个未监听端口就返回 preview.ready。

上游 `preview_screenshot/ScreenshotBackend.capture(html, device, full_page)` 已支持单文件 HTML 截图，可作为兼容能力；它并不接收工程 build URL。多文件工程需要新增 CaptureRequest，明确 `url`、width、height、device_scale_factor、等待条件和动画策略，不强行把 URL 当 HTML 传进去。

上游后端视口是 desktop `1280×832`、mobile `342×684`；前端 PreviewComponent 的桌面宽度是 1366，与本项目 1440/768/390 计划不一致。应在本项目统一 viewports 配置，由预览、采集、报告同时读取，不能沿用设备标签却测了不同尺寸。

Playwright 采集应包含：实际 viewport、完整截图、控制台 error、pageerror、失败资源、页面尺寸和必要 DOM 观测；等待字体就绪并设置总超时。卡住时输出超时原因，关闭 context/browser 并清理进程。

用户仍在查看结果时保留一个有时限的预览租期；任务切换、显式关闭或 TTL 到期才停止。否则“任务结束即停止预览”会造成刚生成就无法查看。完成导出不依赖预览进程一直存活。

联调条件：固定工程真实构建并显示；编译错、浏览器异常、端口冲突、取消和超时都有稳定返回；连续生成不会累积孤立进程。

### 18.12 检查服务、视觉 diff、Spec 交互怎么对接

对应第 9、14 节。新增 `checks/planner.py`、`checks/service.py`、`checks/visual.py`、`checks/interactions.py`。

CheckPlanner 在生成前基于输入类型和 Brief 返回固定 CheckPlan；模型生成的 requirement_mapping 只是索引，不能作为实际检查结论。

调用契约：`CheckService.evaluate(candidate_ref, build_ref, observations, check_plan) -> list[CheckResult]`。检查函数拿采集到的事实和固定规则，不自行触发供应商模型。

首批可实际落地的检查：

| 检查 ID | 输入事实 | 输出及失败依据 |
| --- | --- | --- |
| `build.typescript` | tsc 退出码/日志 | 非零即 FAIL |
| `build.bundle` | build 退出码/dist manifest | 无产物或失败即 FAIL |
| `runtime.page` | pageerror/加载状态 | 未处理异常或加载失败 |
| `assets.available` | 必需资源清单/请求结果 | 缺图、缺字体、资源失败 |
| `layout.overflow` | scrollWidth/clientWidth | 超出预先设定的容差 |
| `a11y.basics` | 允许的标签/焦点/表单观测 | 对应基础规则失败；不声称全面无障碍认证 |
| `visual.reference` | 同视口参考图/候选截图 | 指标和差异图；未校准门限时为待人工确认 |
| `spec.<criterion_id>` | 固定交互步骤与断言 | 实际交互未满足期望 |

适用性示例：截图有原图，视觉检查适用；Spec-only 无参考图，标 `not_applicable` 并写理由；有参考图但浏览器没启动，视觉检查为 `NOT_RUN`，不得当不适用。

支持的 Spec 交互以模板执行：dialog_open、tab_switch、text_filter、required_field 等。建议选择器优先 role/label，必要时模板约定 data-testid。测试动作来自已经确认的 Brief，模型输出不能临时重新定义期望结果。

交互样例：找到 role=button/name=新建任务 → click → 断言 role=dialog/name=新建任务 可见。对于不可唯一定位或复杂行为输出 UNKNOWN/人工待查；不直接执行模型写出的任意测试脚本。

视觉 diff 步骤：检查尺寸/缩放一致 → 统一截图条件 → 应用预先确认 mask → 计算确定性差异 → 输出参考/实际/diff 三张图与指标。用户查看后可提交明确的人工结论；自动视觉 PASS 需要先有已校准的门限和规则版本。

人工本地查看接口：`POST /runs/{id}/review`，带 candidate_id、candidate_hash、check_plan_hash、verdict、逐项人工检查结果和备注。先核对候选与计划，再只为计划中 `mode=manual` 的条目写入有操作者/时间/依据的人工结论；自动检查失败或执行未知不能被这个接口覆盖。最后重算必要检查，全部有确定结论且通过时才设 COMPLETE_LOCAL。这样视觉人工待查项可以完成复核，而真实构建失败仍然阻断。旧候选通过的人工结论不自动转移到修复后的候选。

人工结果以 `source=human` 保存，不伪装成机器检查；拒绝重复提交不同内容却覆盖原结论，修正结论需形成新记录。纯人工确认不触发新的模型请求。

联调条件：向固定样例注入 TS 错、缺图、溢出、按钮失效各能失败；恢复后可通过对应规则；没有执行的检查绝不因为源码里存在媒体查询就显示 PASS。

### 18.13 一次修复如何串回生成与检查

对应第 10 节。新增 `repair/service.py`、`repair/feedback.py`。

请求：

```text
POST /api/d2c/v1/runs/run_demo_01/repair
Idempotency-Key: repair-demo-001
```

```json
{
  "candidate_id": "cand_demo_001",
  "candidate_hash": "sha256:<当前候选摘要>",
  "state_version": 7
}
```

失败列表从服务端检查记录读取，不接受浏览器提交一套替代的 PASS/FAIL。修复接口用事务核对 candidate/hash/version、有效失败、修复次数、剩余预算、外部调用是否存在 UNKNOWN。满足后预留唯一修复名额并排队，返回 202 与同一个 run_id。

Feedback 包含：failed_check_id、问题分类、期望/实际、文件行列、精简日志、必要截图、当前文件集合、模板允许修改范围。对重复日志去重，对超长错误截断并保留完整日志引用。

修复再次调用同一 GenerationProvider，`purpose=repair`；输出完整受控文件集合，生成 c002 并链接 parent=c001。首版不要求模型返回复杂 patch 格式，减少 diff 应用失败。

c002 必须重新构建、重新采集、运行所有适用检查；原 c001 的 PASS 不能复制给新版本。若二次仍失败，报告最终 FAIL，按钮显示额度已用尽；用户后续修改需求应创建新 Run。

重复幂等请求只返回原操作；如果第一次请求响应丢失，查询 Run 确认，不能通过换幂等键再获得第二次修复名额。预留名额和预算的释放只在能够证明未发供应商请求时进行。

状态上允许“可修复的 FAILED → REPAIRING”，这是显式状态转移，需 state_version 条件；不可恢复错误和 UNKNOWN_EXTERNAL 不允许通过此接口绕过。

联调条件：并发双击只有一条 repair 调用；修复中取消不会提交成功状态；c001/c002 的源码、检查和截图可分别查看；修复后回归问题能被再次发现。

### 18.14 Onlook 的元素定位和源码修改怎样集成

对应第 2.3、11.3 节，按两层实施。

**第一层：选中元素后给模型补充修改上下文。** 主底座已经有 `select-and-edit/`、`PreviewComponent.tsx`、`buildSelectedElementInstruction()` 等，无需为了选中一个元素就整套运行 Onlook。复用其中的元素描述与交互外观，把选中元素与当前 candidate 绑定，作为一次修复的补充反馈。

主底座旧预览会读取 iframe.contentWindow.document；当预览改为不同 origin 后，这种读取方式会受同源限制。需要在候选预览中注入受控 bridge，通过消息将可选元素信息发送给工作台。

新增消息示例：

```json
{
  "channel": "design2code.preview.v1",
  "type": "element.selected",
  "session_id": "preview_demo_01",
  "candidate_id": "cand_demo_001",
  "element": {
    "source_id": "srcnode_42",
    "instance_key": "item_03",
    "tag": "button",
    "text": "保存",
    "rect": { "x": 24, "y": 160, "width": 80, "height": 36 }
  }
}
```

父页面校验 event.origin、event.source、预览会话和 schema，限制文本长度；消息只能选中/高亮/描述，不能授权写源码、启动 shell 或更改预算。预览脚本属于生成产物，不能因消息带 session_id 就视其可信。

**第二层：确定性样式/文案编辑与源码保存。** 参考以下 Onlook 实际落点：

- `apps/web/preload/script/index.ts`：iframe 连接。
- `packages/penpal/src/parent.ts` 与 `child.ts`：父子方法协议。
- `packages/parser/src/ids.ts`：JSX 源码标识注入。
- `packages/parser/src/parse.ts`：TSX 解析/输出。
- `packages/parser/src/code-edit/style.ts`：`addClassToNode`、`replaceNodeClasses`。
- `packages/parser/src/code-edit/text.ts`：`updateNodeTextContent`。

Onlook preload 依赖自己的 models/constants/utility/Penpal，并且当前连接中允许 `allowedOrigins: ['*']`；不能直接复制 script/index.ts 进入本项目就认为协议与依赖已兼容。本项目桥接要使用显式 origin。

源码定位由构建前 AST 工具注入 `data-d2c-source-id`，生成 mapping.json：source_id → 文件/JSX 节点/源码摘要。映射由工具计算，不要求模型随意生成文件行号；React 列表重复实例通过 instance_key 区分，源码位置可能仍指向同一模板节点。

样式编辑接口草案：`POST /runs/{id}/edits`，提交 expected_candidate_hash、source_id、操作类型（set_text/set_class）和新值。后端解析 current candidate → 调用受限 AST 操作 → 生成新候选 → 全量检查 → 更新预览。不能只修改 DOM 后显示“已保存到源码”。

AST 工具运行在 Node 进程，通过 stdin/stdout JSON 连接 Python；错误分别包含解析失败、source_id 不存在、旧摘要冲突、不支持动态表达式。只支持简单静态节点，遇到复杂表达式返回不支持，不做字符串全局替换。

这一层属于后续范围。第一版先完成截图/Spec/Figma 到工程的链路；手动编辑也必须失效旧检查和人工结论，候选版本限制在启用前明确设置。若在 Onlook 仓库内部直接改代码，使用其 Bun 工作流；迁移到本项目的独立工具使用主工程选定的工具链并显式列出依赖。

联调条件：跨 origin 选中有效、错误 origin 被忽略；重建后位置映射正确；编辑后源码与预览一致；复杂 TSX 不被误改。

### 18.15 前端组件、Store、API 客户端如何组织

对应第 11 节。

新增模块建议：

```text
frontend/src/features/design2code/
  api/client.ts                 # HTTP 请求、统一错误处理
  api/runEvents.ts              # WS、seq、补齐、关闭
  contracts.ts                  # 与后端 Schema 对齐的类型
  store.ts                      # 输入草稿、当前 run、候选和 UI 状态
  inputs/useScreenshotInput.ts  # 文件/拖拽/粘贴统一处理
  inputs/FigmaInput.tsx
  inputs/SpecInput.tsx
  inputs/SourceList.tsx         # 多来源列表、用途、视口和状态
  inputs/InstructionEditor.tsx  # 本次任务指令
  inputs/ConflictPanel.tsx      # 冲突与采用的处理结论
  BriefSummary.tsx
  RunProgress.tsx
  ResultPane.tsx
  CheckReport.tsx
```

主底座 `project-store.ts` 已经保存 commits/variants/referenceImages，不能再建两份完整候选源码状态。新版 Store 只持久化服务器 ID 和显示状态；代码内容按 candidate_id 获取并缓存。旧 commits 仅作上游兼容外观，不作为 Run 真值。

客户端最小方法：

```ts
uploadInput(form: FormData): Promise<InputSummary>
readInput(inputId: string): Promise<InputSummary>
importFigma(request: FigmaImportRequest): Promise<InputSummary>
createSourceSet(value: SourceSetDraft): Promise<SourceSetSnapshot>
readSourceSet(sourceSetId: string): Promise<SourceSetSnapshot>
updateSourceSet(sourceSetId: string, value: SourceSetDraft, hash: string): Promise<SourceSetSnapshot>
saveBrief(sourceSetId: string, value: BriefDraft, hash: string): Promise<BriefSummary>
createRun(value: CreateRunRequest, idempotencyKey: string): Promise<RunSnapshot>
readRun(runId: string): Promise<RunSnapshot>
readFiles(runId: string, candidateId: string): Promise<CandidateFiles>
requestRepair(runId: string, value: RepairRequest, key: string): Promise<RunSnapshot>
cancelRun(runId: string): Promise<RunSnapshot>
```

为源码查看新增 `GET /runs/{id}/candidates/{candidate_id}/files`；返回有体积上限的允许源码，二进制资源仅返回 asset 引用。readFiles 必须校验 candidate 属于 run。

工作台事件顺序：添加一种或多种资料 → 各自校验/保存 → 保存 SourceSet 与本次指令 → 展示用途与冲突 → 确认 Brief → createRun 一次 → 订阅该 run → build 完成后加载 preview URL → 检查显示 → 用户查看/一次修复 → 导出。上传入口可分标签，已加入的资料必须共同保留在 SourceList，切换标签不能清空其他来源。

显示规则：生成中可展示文本增量；尚未构建成功的代码不直接执行；checks 未返回前显示“检查中”；修复按钮根据 allowed_actions；失败可下载调试包，但包与界面均显示失败状态。

旧 PreviewComponent 主要接收 HTML `srcdoc`，需新增工程模式 `src=preview_url`；CodeMirror 可复用但增加文件列表。不要把整个 GenerationResult JSON 作为 HTML 渲染。

健康/能力接口新增 `GET /api/d2c/v1/capabilities`，返回 provider_configured、figma_configured、runner_ready、template_ready、supported_inputs、unsupported_reasons。只暴露可用性，不返回 `.env` 内容；UI 据此禁用暂不可用入口。

联调条件：用户看得清正在用哪种输入；刷新可找回 Run；没有调用两条生成链；缺配置时能看到具体缺少的能力，而不是反复点击后空转。

### 18.16 单一 `.env`、启动与代理怎么对接

对应第 12.1 节。本节是全部运行配置的唯一字段说明，其他章节不再维护独立模板。

#### 18.16.1 唯一填写位置与当前状态

```text
D:\desktop\AI\D2C\Design2Code\.env
```

文件名就是 `.env`，没有其他后缀，也不能保存成 `.env.txt`。模型与 Figma 的 key 可按用户选择明文写在这个本机文件中。三个上游目录中的示例文件只作参考，不需要分别填写。

**当前状态：根 `.env` 已创建；中转地址、key 和模型已配置，用户选择暂不设置 token 和费用上限。后端已增加根配置读取，真实模型生成链尚在开发。**

#### 18.16.2 集中配置模板

根 `.env` 已按下面这一份模板创建。空值表示尚未配置；数字是拟定工程默认，只有完成 Settings、启动和调用链对接后才生效。

```dotenv
# ===== 1. 模型与中转：按 OpenAI 兼容中转填写 =====
D2C_PROVIDER=openai
# openai_responses 或 openai_chat_completions，必须与中转实际协议一致
D2C_API_PROTOCOL=openai_responses
# 填中转平台给出的 API 基础地址，例如 https://relay.example.com/v1
OPENAI_BASE_URL=
OPENAI_API_KEY=
# 填中转平台实际提供、支持图片输入的准确模型 ID
D2C_MODEL=openai/gpt-6-luna
D2C_PROVIDER_TIMEOUT_SECONDS=180

# ===== 2. 其他供应商：不使用则留空，不会自动切换 =====
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# ===== 3. Figma：不用 Figma 时留空 =====
FIGMA_ACCESS_TOKEN=
D2C_FIGMA_TIMEOUT_SECONDS=60

# ===== 4. 工作台、后端、预览 =====
D2C_WEB_HOST=127.0.0.1
D2C_WEB_PORT=5173
D2C_BACKEND_HOST=127.0.0.1
D2C_BACKEND_PORT=7001
D2C_PREVIEW_HOST=127.0.0.1
D2C_PREVIEW_PORT_START=7100
D2C_PREVIEW_PORT_END=7199

# ===== 5. 本地数据与固定工程模板 =====
# 相对路径统一相对于 Design2Code 根目录
D2C_RUNTIME_DIR=./runtime
D2C_TEMPLATE=react-vite-v1

# ===== 6. 输入限制与默认检查视口 =====
D2C_MAX_SCREENSHOTS=3
D2C_MAX_IMAGE_BYTES=10485760
D2C_MAX_IMAGE_PIXELS=40000000
# JSON 字符串；单引号由 dotenv 解析器移除
D2C_VIEWPORTS='[{"width":1440,"height":900},{"width":768,"height":1024},{"width":390,"height":844}]'

# ===== 7. 整个 Run 的调用和预算上限 =====
D2C_MODEL_REQUEST_LIMIT=2
D2C_REPAIR_LIMIT=1
D2C_AUTO_RETRY_LIMIT=0
# 以下为可选上限；留空表示当前不设置相应上限
D2C_TOKEN_LIMIT=
D2C_COST_LIMIT_MICRO_USD=

# ===== 8. 本地执行超时 =====
D2C_BUILD_TIMEOUT_SECONDS=120
D2C_PREVIEW_TIMEOUT_SECONDS=60
D2C_CHECK_TIMEOUT_SECONDS=120
```

用户已指定统一模型 `openai/gpt-6-luna`，根 `.env` 已保存该值；初次生成与修复共用此配置，不为图片、Spec、Figma 另选模型，不启用其他模型 fallback。模型 ID 按中转要求原样发送，保留 `openai/` 前缀；该前缀本身不决定使用 Responses 还是 Chat Completions，协议仍由 D2C_API_PROTOCOL 指定。模型可用性与图片支持尚未实测。

只用一种中转时，在第 1 组填写基础地址、key 并核对接口协议。第 7 组的 token/费用上限按用户要求暂时留空；请求次数与修复次数限制仍生效。模型实际支持的图像/上下文上限还需由适配器校验，不由上述上传限制替代。

#### 18.16.3 中转字段怎么填

| 字段 | 填写内容 | 读取与约束 |
| --- | --- | --- |
| `D2C_PROVIDER` | OpenAI 兼容中转填 `openai` | 表示适配器类型，不代表请求一定发送到 OpenAI 官方 |
| `D2C_API_PROTOCOL` | `openai_responses` 或 `openai_chat_completions` | 明确协议，不以失败后自动换协议的方式重复发请求 |
| `OPENAI_BASE_URL` | 中转提供的 API 基础地址 | 是否包含 `/v1` 以平台说明为准；不填登录页面或完整生成 endpoint |
| `OPENAI_API_KEY` | 该中转平台的 key | 由后端发送给所配置中转，不要求另外填写官方 key |
| `D2C_MODEL` | 中转公布的准确模型 ID | 不能只凭系列名称推测；需支持本次图片与代码生成输入 |
| `D2C_PROVIDER_TIMEOUT_SECONDS` | 单次模型请求超时秒数 | 超时不自动重试；请求是否受理不明确时保留未知记录 |

base URL 是“接口前缀”；协议适配器负责拼接 `responses` 或 `chat/completions`。不要手工把完整 endpoint 写进 base URL 再重复拼接，也不要统一给所有平台强行添加 `/v1`。

上游 `OpenAIProviderSession` 目前走 Responses。`openai_chat_completions` 是本项目拟新增的配置选项，需补对应多模态消息序列化、流式结果、usage 与错误映射；仅在文件里填这个值不会让现有代码自动兼容。未实现的协议应显示 `PROTOCOL_NOT_IMPLEMENTED` 并禁止发请求。

中转模型 ID 不能被上游固定的 Llm 枚举无条件拦截。新版适配器应读取经校验的 D2C_MODEL 字符串及能力配置；不为名称未知的中转模型套用另一个模型的价格或上下文额度。价格缺失时显示预算校验缺口，不用零价格假装已核实费用。

Anthropic/Gemini 路径仍是可选扩展，不额外创建另一份 `.env`；如果将来选用它们，应先补齐对应协议与地址契约。单填其 key 不代表当前首版已验证该路径。

#### 18.16.4 其余配置如何统一消费

| 配置组 | 使用方 | 行为约定 |
| --- | --- | --- |
| Figma token/超时 | 后端 FigmaClient | token 空时仅禁用 Figma 远程导入，图片和 Spec 仍可使用 |
| WEB/BACKEND host/port | 根启动脚本、Vite、FastAPI | 从同一配置读取；端口占用报错，不悄悄换端口后留下旧代理 |
| PREVIEW host/port 范围 | 受管 Runner | 从范围内分配空闲端口；不能与工作台/后端端口重叠 |
| RUNTIME_DIR | Store、SQLite、Runner、ExportService | 用根目录解析相对路径；SQLite 路径派生为 runtime 下文件，不再要求重复填写 |
| TEMPLATE | 固定工程模板选择器 | 校验模板存在；不是模型可以随意指定的安装命令 |
| 图片数量/字节/像素上限 | 上传 API 与前端公开能力 | 前端提示与后端校验使用同一数值；后端仍做真实解码 |
| VIEWPORTS | 预览、截图、CheckService、报告 | 同一份 JSON 默认值；若任务明确要求其他尺寸，在固定检查计划中记录覆盖值 |
| 请求/修复/重试/token/费用上限 | RunPolicy、ProviderAdapter | 对整个 Run 生效；修复共享额度；客户端只能申请更低上限 |
| 各类超时 | 对应客户端或执行器 | 使用正整数秒；模型、Figma、构建、预览和检查分别计时 |

`D2C_TOKEN_LIMIT` 的口径为整个 Run 的输入与输出 token 预留总额；图像用量按供应商口径计入估算和实际记录。`D2C_COST_LIMIT_MICRO_USD` 为内部美元微单位预算，1 美元对应 1000000 微美元；它不直接代表中转最终账单。用户明确要求暂不设置上限，两者为空时不阻止真实生成；仍展示实际用量及费用是否已知。

首版固定最多 3 张截图、2 次模型请求、1 次修复、0 次自动重试；配置可收紧，上调超出已实现边界时应拒绝启动相关能力，不能仅改数字就宣称支持更多行为。图片限制默认每张 10 MiB、4000 万像素，超限时明确提示缩小图片，不静默丢图。

所有 D2C_* 新字段由本项目 Settings 读取，上游 config.py 不会自动识别。Settings 统一完成字段类型、允许值、跨字段关系、缺失项与路径解析，并生成不含秘密的公开能力子集。

#### 18.16.5 加载与启动约定

1. 新增一个集中 Settings 模块，负责确定唯一根 `.env` 路径并校验配置；业务模块不自行查找其他 `.env`。
2. FastAPI `main.py` 在导入 config/routes 前显式加载根文件。按当前目录结构，可由 `Path(__file__).resolve().parents[2] / '.env'` 定位；不再依赖启动工作目录与无参 `load_dotenv()` 自动搜索。
3. 根 `.env` 中声明的项目配置值优先于同名父进程变量，避免终端遗留 key/地址覆盖用户填写内容；仅对已声明的项目字段应用这一约定，不覆盖 PATH 等系统环境。
4. Vite 从同一路径读取白名单中的启动参数、公开端口和代理目标；不把完整 env 展开到 define/import.meta.env。关闭 Vite 按模式自动叠加其他 env 文件的路径，不另设 frontend/.env。
5. 浏览器只使用同源 `/api/d2c/v1`；已有 `/api` 代理增加 WS 支持。前端 Settings/localStorage 中旧 key 不再作为新版调用来源，界面显示“服务端已配置/未配置”。
6. 后端调用供应商时读取 key；Runner 启动生成工程时只传构建所需的环境白名单，不继承整份配置。根 `.env` 加入 Git 忽略和 ZIP 排除。
7. 修改 `.env` 后重启受影响服务再生效；有活动 Run 时先完成或取消该 Run，不在生成途中热换模型、地址或预算。

最终新增根目录 `Start-Design2Code.ps1`/`Stop-Design2Code.ps1`。目标使用方式为：

```powershell
cd D:\desktop\AI\D2C\Design2Code
.\Start-Design2Code.ps1
# 停止时执行
.\Stop-Design2Code.ps1
```

**上述脚本尚未创建，目前不能当作已有启动命令执行。** 实施时由启动脚本读取集中配置 → 检查工具和固定依赖 → 用指定 host/port 启动两个服务 → 等待健康 → 记录进程引用。后台进程使用隐藏窗口；启动诊断不输出配置全文、key 或 token。真实模型执行使用单 worker，不使用 `--reload`。

#### 18.16.6 配置联调完成条件

- 只有根 `.env` 一份实际配置；从任意工作目录启动均读取相同值，不依赖其他同名文件。
- 修改根端口后，服务监听地址、Vite HTTP/WS 代理和浏览器入口同步生效；预览保持独立 origin。
- 修改 key、URL 或模型并重启后，供应商适配器消费新值；通过 mock transport 先验证路径与模型参数，不打印 key。
- 分别核验 Responses/Chat Completions 的实际适配状态；未实现的选项不能显示已支持，不因协议失败自动发起第二次请求。
- 空 key、模型或 URL 时仍可打开界面，真实生成明确显示缺失字段；预算可留空；Figma token 空时只影响 Figma 导入。
- 预览、导出 ZIP、日志和浏览器存储不包含配置秘密；报告保留实际模型、协议和脱敏来源说明。

本节测试完成后才能把“统一配置已实现”写入进度记录；当前仅完成配置设计与文档整理。

### 18.17 工程 ZIP、报告、资源怎样集成导出

对应第 12.2 节。新增 `reports/export_service.py`、`reports/render.py`，修改前端 download.ts 的新版调用入口。

原 `downloadCode(code)` 把浏览器中的 HTML 发送到 `POST /api/export`，失败时回退下载 HTML。新版应提交固定 run/candidate 标识，服务端读取已经保存的文件；不能继续接受浏览器任意改过的 code 作为“已验收工程”。

接口：

```text
GET /api/d2c/v1/runs/{run_id}/report?candidate_id={candidate_id}&format=json
GET /api/d2c/v1/runs/{run_id}/report?candidate_id={candidate_id}&format=html
GET /api/d2c/v1/runs/{run_id}/export?candidate_id={candidate_id}&include_sources=false
```

导出步骤：核对 candidate 归属与摘要 → 固定本次 report/check snapshot → 读取允许文件 → 组装源码/lockfile/资源/README/报告/截图/hash 索引 → 再核对候选和快照 → 返回 application/zip。

文件布局建议：

```text
design2code-export/
  project/               # 完整可构建前端工程
  evidence/              # 实际截图、diff、必要日志
  report.json
  report.html
  manifest.json          # 候选、模板、输入摘要、规则版本
  hashes.json
  README.md
```

失败候选的报告和 README 必须写 `delivery_status=FAILED_DEBUG`；通过必要检查并完成本地查看的包写 `COMPLETE_LOCAL`。用户主动指定历史 candidate 可导出其历史报告，但不能附上当前新候选的检查结果。

资源在输入/构建阶段已本地化，导出时优先只读本地快照。上游导出会扫描 URL 并在导出时请求外网下载图片，这个行为不直接继承为新版默认，以免 ZIP 内容受临时远程变化影响。

HTML 报告对 Spec、模型文本、错误日志做转义，不把用户输入直接作为 HTML 注入。ZIP 使用允许路径和数量/体积限制；显式排除 .env、metadata.sqlite、秘密配置、临时凭据、node_modules 和无关上游源码。

联调条件：下载 ZIP 后在干净目录按 README 安装锁定依赖并构建；hashes 可复算；导出失败不会静默退回一个 HTML 文件却仍显示“工程导出成功”。

### 18.18 旧项目的能力怎样小范围迁移

对应第 3 节。迁移单位是“规则/采集器/测试案例”，不是完整旧服务。

步骤：

1. 选一个独立问题，例如水平溢出或键盘焦点。
2. 阅读旧实现依赖，区分纯计算、浏览器采集和数据库写入。
3. 将纯规则改成 `evaluate(observation, expectation) -> CheckResult`，数据模型使用新版 contracts。
4. 原 PostgreSQL Evidence writer 不迁移，由新版 SQLite 统一保存结果。
5. 把相关 fixture/故障案例迁移为新版测试；记录来源文件、旧版本与改动说明。
6. 用真实浏览器观测验证，保留输入/候选/规则摘要。

具体例子：旧 `application/acceptance/` 中的基础布局与键盘检查可研究；商品 identity、价格与 Medusa 数据契约留在旧项目。旧 `product_delivery_export.py` 的路径/摘要检查思路可借鉴，但其审批表查询和发布条件不进入新版导出。

如果独立提取仍需要大量旧领域对象，优先在新版用小而明确的规则重新实现，不通过 runtime import 把整个 platform 拉入新服务。

联调条件：停止旧 PostgreSQL/S3/Keycloak 后，新版仍可生成和检查通用页面；导出包和检查报告中不会出现旧商品任务审批 ID。

### 18.19 各部分的完成证据与实施依赖

对应第 13～17 节。每项合并时记录源码 commit、验证入口、结果和剩余缺口，避免只完成接口壳就写成已集成。

| 工作包 | 上游/新增代码落点 | 依赖 | 必须展示的完成证据 |
| --- | --- | --- | --- |
| A 主底座运行 | main.py、vite.config.ts、启动脚本 | 固定环境 | 真实 React 页面、后端健康、HTTP/WS 代理 |
| B 输入与资源 | UploadTab/TextTab、inputs、asset API | A | 粘贴真实截图；Spec 保存；资源摘要 |
| C 统一任务 | contracts、RunService、SQLite/events | A/B | 幂等创建、状态查询、断线补齐 |
| D 真实生成 | ProviderSession 适配、single_shot | B/C | 实际供应商调用与结构化文件输出 |
| E 工程与 runner | 固定模板、candidate writer、runner | C/D | 类型检查、bundle、真实预览 URL |
| F 检查与修复 | CheckService、RepairService | D/E | 坏候选拒绝、一次修复、全量复验 |
| G Figma | FigmaClient、Normalizer | B/C | 真实节点 JSON/图/资源进入同一链 |
| H 插件资料包 | ZIP importer | B/E | 真实 FigmaToCode 导出包安全解析 |
| I 导出交付 | ExportService、报告页 | E/F | 干净目录复现、哈希一致 |
| J 可视化编辑 | preview bridge、AST worker | E/F/I | 点选定位、源码修改、新候选复验 |

首版推进顺序：A → B/C → D/E → F → G → I。H 是 Figma 导入补充，J 是首版完成后的扩展。B/C 和 D/E 内部按字段和调用依赖先后实现，不要求另外引入多人或多个 Agent。

修改 screenshot-to-code 的 Python 代码时按仓库 AGENTS 使用 Poetry 环境，执行后端 pytest 与 pyright；前端修改执行 pnpm lint/build 与相关交互验证，记录已有基线问题。FigmaToCode 的 Node/pnpm 版本与主底座不同，应隔离其工具链。仅研究 Onlook 不需要安装/运行其完整依赖。

文档、仓库拉取、静态接口样例、mock transport、真实构建、真实供应商、人工查看分别记录验证层级。测试通过数量不能替代输入到交付的实际案例。

### 18.20 图片 + Spec + Figma + 指令如何共同生成

#### 18.20.1 用户实际怎么操作

同一任务保留一份资料列表，用户可按任意顺序添加：

1. Ctrl+V 粘贴或上传图片，标记为“桌面视觉目标”“移动端布局目标”或“某区块的样式参考”。
2. 粘贴 Figma 节点链接，选定本页 Frame，读取布局、设计变量、组件信息和资源快照。
3. 输入或上传 Spec，描述页面内容、交互、状态、响应式与验收要求。
4. 填写本次指令，说明哪些地方采用哪份资料、需要增删什么。
5. 查看组合摘要与冲突结论后，点击一次生成，得到同一个 React 工程。

例子：“做一个任务管理页面。整体布局和间距按 Figma；配色和圆角参考图片 A；搜索、状态筛选、新建弹窗按 Spec。桌面宽度 1440，移动端 390；移动端按 Spec 改成单列；使用 React + TypeScript，数据先用本地 mock。”

三份资料不要求完全相同，但必须属于同一页面的目标。只给其中一种也能生成；Figma 未配置时仍可用图片 + Spec + 指令。用户已加入且标记必需的 Figma 读取失败时不能静默忽略，需移除该来源并重新确认，或等待读取成功。

#### 18.20.2 按维度决定采用什么，避免整份资料互相覆盖

| 维度 | 未另行指定时的建议 | 用户可明确覆盖的例子 |
| --- | --- | --- |
| 页面结构、尺寸、间距 | 选定的 Figma Frame；缺少 Figma 时采用对应截图 | “侧栏删掉，主体保持 Figma 布局” |
| 配色、字体、圆角、阴影 | Figma 已声明样式；图片作为补充 | “颜色参考图片 A，间距保持 Figma” |
| 标题、文案、字段、演示数据 | Spec 中明确声明的内容，再补设计文本 | “标题改为项目工作台，保留其余文案” |
| 交互、校验、加载/空/错误状态 | Spec 中明确声明的行为 | “第一版只做搜索和新建，不接登录” |
| 响应式 | 明确的响应式规则；对应宽度的设计图作参考 | “390 下单列，不显示桌面侧栏” |
| 资源 | 来源中可用且被选定的图片/图标 | “封面使用我上传的这张图片” |

本次明确指令可覆盖上述维度的默认来源；指令自身冲突时仍需解决。记录采用来源的 input_id、JSON 字段/节点/Spec 条目和适用区域。默认来源不足以解决所有语义冲突，不能声称仅靠规则就能自动理解任意资料。

举例：Figma 为蓝色按钮、图片为绿色按钮，指令已写“配色按图片”，则记录绿色为有意变更；Spec 同一位置要求两个互斥的点击结果且用户未指定取舍，则列为阻断冲突。缺少阴影细节可采用模板默认值，进入 assumptions。

输入摘要展示“将采用什么”，让用户能一次修改。首版依靠确定性提取、已知字段规则与用户确认；图片中不能机械提取的精确信息由首次生成模型共同理解，不另开隐藏的分析请求。首次生成才发现未解决的关键矛盾时，Run 结束为 FAILED，原因码为 `NEEDS_INPUT`，展示需补充的问题，不发布虚构完整结果；该请求照实计数，用户调整输入后建立新 Run，不自动增加调用额度。

#### 18.20.3 SourceSet 接口与固定版本

独立的图片/Spec/Figma 输入接口保持不变，每个来源各有 input_id 和摘要。新增组合请求：

```text
POST /api/d2c/v1/source-sets
Content-Type: application/json
```

```json
{
  "sources": [
    {
      "input_id": "inp_figma_01",
      "role": "structure_reference",
      "scope": { "page": "task-board", "region": "page", "state": "default" },
      "required": true
    },
    {
      "input_id": "inp_image_01",
      "role": "style_reference",
      "scope": {
        "page": "task-board", "region": "page", "state": "default",
        "viewport": { "width": 1440, "height": 900 }
      },
      "required": true
    },
    {
      "input_id": "inp_spec_01",
      "role": "behavior_and_content",
      "scope": { "page": "task-board", "region": "page" },
      "required": true
    }
  ],
  "instructions": "布局和间距按 Figma，颜色与圆角按图片，交互与内容按 Spec；390px 下单列，使用本地 mock。",
  "authority_by_dimension": {
    "layout": "inp_figma_01",
    "style": "inp_image_01",
    "content": "inp_spec_01",
    "behavior": "inp_spec_01",
    "responsive": "instructions"
  },
  "resolutions": []
}
```

source 的 type、hash 和尺寸由服务端按 input_id 读取，客户端不能冒充另一种来源。role 表达用途；更细的区块覆盖规则进入 resolutions，记录 dimension、scope、chosen_source、reason 和用户结论。资料顺序只控制展示，不能通过拖动列表暗中改变优先级。

响应示例：

```json
{
  "source_set_id": "srcset_demo_01",
  "source_set_revision": 1,
  "source_set_hash": "sha256:<规范化资料集合摘要>",
  "status": "DRAFT",
  "brief_id": "brief_demo_01",
  "brief_revision": 1,
  "brief_hash": "sha256:<合并后的生成说明摘要>",
  "conflicts": [],
  "assumptions": ["未提供真实 API，采用本地演示数据"],
  "ready_for_confirmation": true
}
```

保存 Brief 时用其当前 brief_hash 作 If-Match，并提交 source_set_revision/hash。服务端确认所有纳入来源 READY、无阻断冲突后，返回已确认的 Brief 与资料集合可运行状态。来源仍在 IMPORTING 时可保存草稿，但不能创建 Run。`required=false` 的来源读取失败时也不能悄悄消失：显式排除、生成新 revision 并展示给用户确认。

更改资料、指令或采用规则时，`PUT /source-sets/{id}` 使用当前 source_set_hash 作 If-Match，新增 revision 并生成新的 Brief 草稿。原有确认不沿用；旧 Run 仍使用旧快照。摘要覆盖输入的内容摘要、角色/范围、指令、来源规则与冲突结论；采用规范化 JSON 规则，不依赖本机绝对路径、临时下载 URL 或更新时间。

18.9 的 Run 请求使用 source_set_id/revision/hash，不再用单个 input_id 表达整项任务。需要兼容历史单输入调用时，可在服务端适配成单元素 SourceSet，但不得绕过 Brief 确认和相同校验。

#### 18.20.4 后端如何组装并调用一次生成

建议新增 `contracts/source_sets.py`、`inputs/source_set_service.py`、`inputs/merge.py`；在 prompt 组装模块新增 `context_builder.py`。调用链：

```text
ScreenshotAdapter / SpecAdapter / FigmaAdapter
  → 不可变 InputSnapshot + 资源
  → SourceSetService（组合、版本、用途、冲突）
  → BriefComposer（来源映射、假设、验收需求）
  → 用户确认 Brief
  → RunService 固定资料集合与检查计划
  → ContextBuilder（选定子树、图片标号、Spec 条目、任务指令）
  → 已有统一 ProviderAdapter
  → 同一 Candidate / Runner / CheckService / ExportService
```

ContextBuilder 的顺序：生成输出协议 → 已确认任务目标与采用规则 → 相关 Figma 结构/token/资源映射 → Spec 内容与交互条目 → 带用途标号的图片 → 已确认假设与限制。资料正文作为输入数据，不能用其中夹带的文字更改执行预算、工具权限或文件写入边界。

不直接把整份 Figma 文件、任意长 Spec 和原尺寸图片全部拼入请求。选取指定 Frame 子树，过滤无关节点，图片生成受限副本并保留原图；对上下文总大小、模型支持的图像数量和分辨率做预检。超限时指出超出的是哪份资料，让用户缩小范围；不能截掉关键验收条目后继续声称输入完整。

供应商需支持所需的多模态输入。只有文字能力时必须显示图片能力不可用，不能仅发送文件名或图片 URL 字符串就声称理解了截图。文件来源、图片编号和 prompt 中的标号要一一对应。

预算按整个 Run 计算：三种资料一起使用依然最多初次生成 1 次 + 修复 1 次、自动重试 0 次；不变成每种输入各生成一遍。Figma 网络读取不是模型请求，但单独记录读取失败与限流。合并上下文会增加 token/图片用量，仍受同一 token 与费用上限约束；不新增 OCR/预分析模型调用。

#### 18.20.5 组合目标如何验收

检查计划按“区域 + 视口 + 状态 + 维度”绑定来源，避免拿两张不一致的整页参考图同时要求像素一致：

- 布局采用 Figma 时，检查结构、间距等对应来源；图片仅参考配色时，不将整张图片作为布局像素基准。
- 原始 Figma 渲染或截图仅在其仍是该范围的完整目标时做整图 diff。融合后没有完整目标图时，可展示差异供人工查看，但视觉结论不能自动标 PASS。
- 桌面参考用于桌面，移动参考用于移动；没有移动图时按声明的响应式约束检查，不把桌面图缩小就当移动端标准。
- Spec 中搜索、筛选、弹窗分别产生可追踪的交互检查；静态截图不能证明这些交互已经实现。
- 用户指令修改的颜色/文案等记录为有意变更，并按修改后的目标检查；该记录不能豁免其他尚未检查的部分。
- 每条检查保留来源引用、目标、候选 ID、结果和证据；无法可靠自动验证的视觉要求保留人工待检查状态。

导出包含 source_set/Brief 摘要、指令、来源角色映射、冲突结论和检查来源映射，设计原稿仍按 12.2 的显式导出选项处理。

#### 18.20.6 首版完成条件

工作包 B/C 增加 SourceSet 合并、版本与指令输入；G 完成后，Figma 输入直接加入同一列表。至少验证：图片 + Spec；Figma + Spec；三类一起；只有一种资料；修改指令导致原确认失效；来源未就绪阻止生成；互斥要求提示解决；超出上下文上限可解释拒绝；生成与修复共享预算；混合视觉目标不会误报整图 PASS。

**当前进度：本节为待实施方案。仅把文档、仓库或接口样例准备好，不代表现有应用已经可以组合输入。**

## 19. 四条端到端联调脚本思路

下面是开发完成后应执行的操作序列。它们是联调清单，当前新增接口尚未实现，不能直接在旧 server.py 上请求。

### 19.1 截图粘贴生成

1. 打开新版 `localhost:5173`，查询 capabilities 确认截图/模型/runner 可用。
2. 截图后 Ctrl+V：显示缩略图、真实尺寸和可替换入口。
3. multipart 保存原图，返回 input_id；前端建立只有该输入的 SourceSet，取得 Brief 草稿。
4. 用户补充交互后保存并确认 Brief，得到新 revision/hash。
5. 用唯一幂等键创建 Run，只提交一次；WS 从 seq=0 开始订阅。
6. 检查 provider_calls 首次请求只有一条，收到 GenerationResult 后写 c001。
7. 固定模板构建，成功后加载独立 origin 预览，显示原图与实际截图。
8. 全部适用检查运行；有失败且预算允许时一次修复形成 c002，再全量复验。
9. 用户查看并提交当前候选结论，导出该候选 ZIP。
10. 在新目录复现；结果不达标则保留失败原因，不把示例完成当作平台全面完成。

### 19.2 Spec 生成功能页

1. 输入“任务列表、搜索、状态筛选、新建弹窗”的 Markdown。
2. SpecAdapter 保存原文，创建单来源 SourceSet，用户确认首批可自动检查的交互条目及 Brief。
3. 创建 Run；生成工程后运行固定交互模板。
4. 视觉参考检查明确不适用；页面溢出、键盘、构建与资源检查继续执行。
5. 点开新建按钮、输入搜索词、切换筛选，以截图/断言记录实际行为。
6. 导出报告同时展示自动已测和待人工条目；不展示凭空计算的视觉还原率。

### 19.3 Figma 指定节点生成

1. 提交可访问的节点 URL；后端读取，界面显示 IMPORTING。
2. 取得同版本节点快照、参考 PNG 和资源，状态变 READY。
3. 创建单来源 SourceSet；Brief 展示原始尺寸、字体替代、缺少资源、推断的交互并确认。
4. 复用同一个 Run/Provider/Runner/CheckService，不能出现第二套 Figma 专属任务状态机。
5. 原始视口用于视觉对比，其他视口用于响应式检查。
6. 导出保留来源节点和设计快照摘要，默认不附原始秘密配置和不必要的原稿。

### 19.4 图片 + Spec + Figma 共同生成

1. 选择一个真实可访问的 Figma Frame；粘贴一张同页面的配色参考图；保存搜索/筛选/新建弹窗 Spec。
2. 指令填写“布局按 Figma，配色按图片，交互按 Spec，390px 下单列”。三个输入分别 READY 后创建 SourceSet。
3. 摘要展示五个维度采用的来源；故意加入互斥的按钮行为，验证阻止生成；解决冲突、保存并确认 Brief。
4. 绑定 SourceSet 版本创建 Run；核验只出现一条首次生成供应商请求，三个来源共同进入该请求。
5. 构建真实工程，验证桌面布局、颜色、移动单列、搜索、筛选、弹窗；视觉融合部分显示人工待检查，不能要求两张原始参考整图同时一致。
6. 一次修复后总模型请求不超过 2；导出可追踪每个关键要求采用的来源。
7. 修改指令后验证新资料集合 revision 产生、Brief 需重新确认；旧 Run 的资料与候选不改变。

## 20. 开发交接与下一批具体改动

第一批只完成 A/B/C 的基础接口和真实前端：

1. 在 screenshot-to-code 主仓库记录环境与开发分支，核对现有依赖和锁文件。
2. 将根 `.env` 显式加载接到 main.py 与 Vite 启动配置。
3. 新增 contracts、`/api/d2c/v1/capabilities` 和输入/资源接口。
4. 在 UploadTab 加入 Ctrl+V，并让选择/拖拽/粘贴复用同一条文件处理路径。
5. 接入 TextTab 保存 Spec；新增 SourceList/InstructionEditor 与 SourceSet API，让图片和 Spec 可以同时保留并形成 Brief；Figma 适配就绪后接入同一资料集合。
6. 实现绑定资料集合版本的最小 SQLite Run 与事件查询，使用固定 GenerationResult 验证界面和候选处理。
7. 浏览器验证输入、缩略图、状态、错误和重连后，再接真实 Provider 与构建 runner。

每次交接必须回答：改了哪些主仓库文件；用了哪些上游能力；新增了什么契约；实际运行了哪些接口；结果落在哪里；哪些仍为样例/未执行。用户下一步可直接按本节开始实施，无需重新讨论是否限定电商。

## 2026-11-09 实施状态补充（历史快照）

- 当前根目录 `.env` 的 token / 费用预算上限按个人项目需求留空；系统每个 Run 最多两次模型请求、一次修复，不自动重试。若填写预算字段，现阶段会阻止生成，预算执行功能尚未接通。
- 图片加 Spec 已完成一次真实模型生成、构建、预览、导出和一次真实修复。修复候选页面标题与搜索已在浏览器复核；视觉与交互自动检查目前仍显示 NOT_RUN。
- 已加入运行停止和服务重启后的中断状态恢复。停止等待无法保证已经发出的供应商请求被取消，构建进程可能短暂继续；不会自动重新请求。
- 固定模板已加入 Tailwind CSS，模拟候选构建通过。该历史快照中的 Figma 节点导入已有模拟测试；当前 MCP 路径不要求 REST 令牌，真实节点仍待 Figma Desktop 插件连接和节点链接验证。
- 后端测试 285 项通过；pyright 0 错误、36 条上游原有警告；上游完整前端 lint 仍有 19 个原有错误和 6 条警告。
- 后续仍需完成（截至该快照）：资料确认和来源冲突提示、自动检查、真实 Figma 验证、修复后导出复验及其余端到端验收。当前状态以文末 2026-11-10 记录为准。

### 视口检查进展

新任务在构建成功后会尝试用本机 Chromium 对桌面和手机视口截图并检测水平溢出；检查不能代表视觉还原或业务功能通过。修复后的真实候选已使用该检查，两个视口均无水平溢出。新任务报告才会自动记录该结果；旧任务报告不会被追溯改写。

### 组合输入与导出复验

截图、Spec、模拟 Figma 节点和指令已通过同一任务的接口测试；这是模拟 Figma 服务及模拟模型的测试，不等于真实 Figma 端到端联调。工作台已展示资料摘要，并提示用户在指令中处理冲突；自动识别语义冲突与逐维度来源选择尚未实现。修复候选 ZIP 已在干净目录安装并构建，确认包含修改后的标题。最新后端测试为 289 项通过。

### 来源选择进展

工作台已支持分别为布局、视觉样式、内容和交互选择截图、Spec、Figma 或生成指令作为参考来源，选择会写入资料集合及导出报告。截图选项当前指第一张截图。系统仍不会自动发现或阻止所有语义冲突，用户需要检查资料并在指令中明确取舍。

### 本地预览稳定性与浏览器检查

预览服务已复用一个本地端口，并通过任务及候选路径分发页面；两个不同任务和各自资源的隔离路由已测试。桌面与手机视口检查会记录水平溢出以及页面脚本或资源错误；存在错误时不报告通过。使用真实修复候选复测通过，使用模拟故障页面验证返回 FAIL。粘贴和拖放入口通过了浏览器合成事件测试，尚不等于操作系统剪贴板及人工拖放实测。当前后端测试 290 项通过。

### 预览中选中元素进行修改

工作台已接入预览选取：在仍有修改机会时点击“在预览中选取元素”，然后点击页面元素。选取时拦截点击及常见指针事件，避免触发页面原有操作；按 Escape 可取消。选中元素的 HTML 与位置描述会结合修改指令，按主工程已有的 `buildSelectedElementInstruction` 组织后发送。桥接代码仅由本地预览服务临时提供，不写入导出工程。浏览器联调使用真实候选及拦截的修复接口，已验证选取按钮不会打开弹窗且请求包含目标上下文；该测试未调用模型，尚不能证明模型每次都精准修改选中元素。

### 本地停止与连接释放

运行停止时，本地构建使用任务对应的进程引用，请求终止其进程树；任务取消后不会启动下一条构建命令。Windows 实测覆盖父进程、子进程和取消后禁止再次启动。供应商请求已发出时仍无法保证远端取消或不计费。SQLite 连接现按事务提交或回滚后立即关闭；真实临时工程构建及临时目录清理均已验证。启动脚本失败时也会清理本次启动的进程树。最新后端测试 293 项通过。

### 模型入口与配置核对（历史快照）

本地工作台服务不挂载上游独立 `/generate-code` 和 `/run_evals`、`/run_evals_stream` 模型执行入口，避免绕过工作台的模型设置及每任务请求次数限制；上游源码仍保留，只读评测与输入比较接口仍可用。该段记录的是当时的配置核对结果；当前服务能力以 `/api/d2c/v1/capabilities` 的实时响应和文末最新记录为准。

### FigmaToCode 项目包接入进展

工作台增加 ZIP 项目包输入，可与截图、Spec 和 Figma 节点共同作为参考。接口通过 JSON 上传 Base64 内容，读取 HTML、TSX、JSX 和 CSS 作为模型参考；从 `images` 目录读取 PNG/JPEG 并复制到生成工程的 `public/images`。不会安装或执行包内依赖和脚本，也不会直接以原项目为种子工程。上传限制为 10 MiB、250 个条目、展开后 20 MiB，源码总计 300 KB，图片最多 30 张且合计不超过 5 MiB。模拟 Vite、Next.js、HTML 结构用于验证；真实 FigmaToCode 插件导出包、真实 Figma 节点及三资料真实模型联调仍待具备资料后验证。自动视觉相似度和业务交互检查仍未实现，检查结果应如实显示未执行或待人工检查。

本机浏览器检查已验证工作台可以同时添加 Spec 和项目包，页面摘要正确显示来源角色与用途，生成按钮保持可用；本次仅验证输入编排，没有发起新的模型请求。

### Figma MCP Bridge 接入

Figma 输入现在支持 `D2C_FIGMA_MODE=mcp`。后端通过本地 Node MCP 客户端启动 `figma-mcp-bridge/server/dist/index.js`，调用 `get_node` 和 `get_screenshot`，将节点结构与 PNG 快照转换为现有 `figma` 输入格式，后续组合输入和模型上下文不变。Bridge 仓库为 MIT 开源项目，使用前需要 Figma Desktop、导入插件并在目标文件中运行插件；服务默认只监听本机地址。它避免了本项目直接调用 Figma REST API，不需要 `FIGMA_ACCESS_TOKEN`，但不代表 Figma 官方承诺免费无限调用，仍受插件、账号权限、客户端和项目实现稳定性影响。

安装与运行：

```powershell
cd D:\desktop\AI\D2C\Design2Code\figma-mcp-bridge\server
npm install
npm run build
```

根目录 `.env`：

```env
D2C_FIGMA_MODE=mcp
```

完成后在 Figma Desktop 导入 `figma-mcp-bridge/plugin/manifest.json`，打开目标文件并运行插件，再在工作台填写带 `node-id` 的 Figma 链接。没有运行插件时，后端会明确返回 Bridge 未连接，不会退回伪造数据。当前已完成 MCP 返回节点和 PNG 的模拟适配测试；真实插件连接和真实节点三资料模型联调仍需在 Figma Desktop 中执行。

截至 2026-11-10 的验收记录：后端完整测试为 308 项通过，Pyright 为 0 errors；项目包与导出相关测试为 12 项通过；已有导出工程在独立目录重新执行 `pnpm build` 通过。构建成功后会追加本机交互冒烟检查，报告会区分自动通过与人工核对；这不代表业务语义已经验收。此前文档中“289/293/297 项”等历史数字仅对应当时的阶段快照，以本段和最新测试输出为准。

### 检查报告状态

新任务报告区分 PASS（通过）、FAIL（失败）、NOT_RUN（未执行）和 MANUAL_REVIEW（待人工检查）。构建通过时会列出待人工核对视觉和交互；构建失败时该项显示未执行。前端四种状态已通过模拟数据展示验证；历史任务的检查结果保留原快照，不会追溯改写。本轮后端测试 297 项通过。

### 2026-11-10 文档与环境同步记录

本节是当前实施状态的权威补充，若本方案前文仍出现旧阶段测试数字或旧的 Figma token 表述，以本节为准。

1. **Figma MCP bridge 服务端**：已在 `figma-mcp-bridge/server` 完成 `npm install` 和 `npm run build`，产物为 `server/dist/index.js`。
2. **Figma MCP bridge 插件端**：已在 `figma-mcp-bridge/plugin` 完成 `npm install`、`npm run build` 和 `npm run typecheck`。插件导入入口为 `figma-mcp-bridge/plugin/manifest.json`，构建产物在 `figma-mcp-bridge/plugin/dist`。
3. **当前接入方式**：根目录 `.env` 使用 `D2C_FIGMA_MODE=mcp`。MCP 路径由本机 Node 客户端启动 bridge server，读取 `get_node` 和 `get_screenshot`；默认不依赖 `FIGMA_ACCESS_TOKEN`。REST token 只保留为兼容回退，不作为当前验收路径。
4. **真实联调步骤**：在 Figma Desktop 导入上述 manifest，打开有权限的目标文件并运行插件；再向工作台提供带 `node-id` 的 Figma 链接。插件未运行、链接无节点标识或文件无权限时，应显示明确错误并停止该来源，不得用模拟数据冒充成功。
5. **已验证范围**：MCP 返回节点和 PNG 的模拟适配测试通过；后端完整测试 308 项通过；Pyright 0 errors；导出工程在独立目录执行 `pnpm build` 通过。
6. **尚未完成范围**：真实 Figma 节点读取、截图 + Spec + Figma 三资料真实模型运行、视觉相似度自动评分，以及完整业务语义验收。它们需要真实 Figma 文件和一次明确的人工视觉核对，不能由单元测试数字替代。
7. **Windows 稳定性修复**：bridge 客户端使用 `fileURLToPath` 转换本地路径，避免 `spawn ... ENOENT`；未连接插件时，导入接口返回明确的 503 及 bridge 原因。启动脚本在健康检查前写入进程归属文件，停止脚本可清理启动后尚未完成探活的进程。

最新本机验证：后端 `poetry run pytest -q` 为 308 项通过；新增 bridge 错误分支所在输入测试为 20 项通过；前端 `pnpm build` 成功；`poetry run pyright` 为 0 errors（44 条上游/类型推断 warning）。工作台健康接口返回 200，前端页面返回 200，且仅绑定 `127.0.0.1`。

本节不记录任何 key、token 或完整 `.env` 内容；秘密只允许保留在本机根目录 `.env`，文档只描述字段和操作步骤。


### 2026-11-10：真实 Figma 与输入组合补充记录

Figma Desktop 插件经本机 bridge 连接后，工作台真实读取指定 Frame 的节点结构及 PNG，导入状态为 READY。启动与停止脚本现可管理工作台启动的 bridge；匿名插件会话需由用户明确绑定文件链接，插件重启后标识可能变化。

使用本机接口，分别以示例截图、Spec 和真实 Figma 节点创建了 7 种资料集合：三种单独输入、三种两两组合、三种一起。七种集合均创建成功；此验证没有调用模型，不代表生成、交互及导出已完成。

目前 token 与费用上限为空，预算执行代码尚未实现；依照当前目标对真实验收的预算要求，尚未发起三资料模型生成。已有请求次数、修复次数和自动重试约束不等同于 token 或费用上限。视觉还原与业务语义仍需人工核验。


### 2026-11-10 工作台验收与草稿恢复补充

真实三资料任务 `run_088c57637c2743c9b34ff636f8322a4b` 已完成一次生成与一次修复，共两次模型请求；最终构建、桌面及移动视口、交互冒烟检查通过。搜索、筛选和新增弹窗经过浏览器操作，导出工程在干净目录安装、构建并启动。视觉自动对比仍未执行，视觉质量仍待人工检查。早期关于真实 Figma 和三资料未运行的陈述是历史记录。

工作台通过浏览器 IndexedDB 自动保存截图、Spec、Figma 链接、项目包、指令和来源选择。刷新恢复已实测截图、Spec 与指令；其余字段使用相同存储机制，尚需逐项实测。浏览器存储被清除或跨浏览器时不保证恢复，多标签同时编辑可能覆盖草稿。读取或写入失败时提示，读取失败时不覆盖旧草稿。

### 人工视觉对照补充

工作台增加参考图与构建截图并排查看：使用任务保存的截图或 Figma 节点图，可切换桌面与手机检查截图。该功能不计算相似度，不改变视觉检查 NOT_RUN 或人工待检查状态。对真实三资料任务直接调用接口函数，确认截图、Figma 参考图和两个视口截图存在；前端构建通过。新界面的浏览器实测仍待完成。

### 按任务 ID 恢复与视觉对照浏览器复核

结果区展示完整任务 ID，并可通过该 ID 找回保存在本机的任务；成功恢复后记为本浏览器最近任务。使用真实三资料任务在本机浏览器验证按 ID 恢复及刷新后恢复；视觉对照的截图/Figma 来源和桌面/手机视口切换可操作。未发起模型请求，视觉与业务语义仍需人工验收。

### Spec 单独输入真实验收（2026-11-10）

复用已有 Spec，创建任务 `run_7bf8942da640452582c27abf4b6d6662`。初次生成构建通过，但视口检查因页面脚本或资源错误失败，交互冒烟未执行；按本地资源和交互要求执行一次真实修复后，构建和桌面/手机视口检查通过。共模型请求 2 次、修复 1 次，自动重试 0 次。

修复后的真实页面通过浏览器操作：搜索“邮件”后只显示对应任务，筛选“已完成”显示对应任务，打开新建弹窗并创建“验证任务”后，切回全部任务可看到新任务。页面数据为示例状态，不代表持久化业务系统。自动交互冒烟仍为 NOT_RUN，视觉自动对比为 NOT_RUN，视觉及完整业务语义仍需人工检查。此记录仅证明本次 Spec 样例，不证明所有 Spec 均可成功。

### 交互冒烟检查修正（2026-11-10）

修正连续操作同一页面时弹窗遮挡后续控件的问题：每个控件从页面初始状态开始检查，最多处理前 30 个控件；个别操作未完成或控件超过检查上限时报告 NOT_RUN，不虚报通过。已有页面错误仍报告 FAIL。该冒烟只检查有限操作和页面错误，业务结果仍需人工验证。

使用新检查直接复查已有真实候选：Spec 单独任务 `run_7bf8942da640452582c27abf4b6d6662` 尝试 12 个控件，三资料任务 `run_088c57637c2743c9b34ff636f8322a4b` 尝试 6 个控件，均返回 PASS；相关现有测试 2 项通过。未发起模型请求。历史任务的检查报告为原始快照，不会自动改写；新任务使用更新后的检查。

### 截图单独输入真实验收（2026-11-10）

使用已有截图创建任务 `run_548ec7fdcbff4d76ba380d202193a9af`。初次构建通过，但外部字体被本机预览策略拦截，视口和交互冒烟检查失败。一次真实修复后，构建、桌面/手机视口和交互冒烟检查通过；模型请求共 2 次、修复 1 次。视觉自动对比和业务交互检查为 NOT_RUN，视觉和业务仍需人工核对。此结果只针对该截图样例。

针对多次出现的外部字体问题，生成和修复共用的模型提示已明确要求使用系统字体及本地资源。此提示不能保证模型遵守；尚未通过新真实生成验证其效果，检查仍会如实报告外部资源错误。相关后端输入测试 22 项通过。运行中的后端重启后读取新提示。

### Figma 单独输入真实验收（2026-11-10）

复用先前通过 MCP Bridge 真实导入的 Figma 节点快照，创建任务 `run_f85e09257c0d48f99844df3b76612ed0`；本次没有重新读取 Figma 插件。使用更新后的本地资源提示，初次生成即构建通过，桌面/手机视口及交互冒烟通过；模型请求 1 次，修复 0 次。自动视觉及业务语义检查仍为 NOT_RUN。

对 390 像素宽的节点参考图和手机检查截图进行了人工对照：标题、搜索、排序、错误提示和按钮的位置与整体配色接近；下拉箭头、文字细节和截图高度存在差异，未计算相似度，也未确认所有像素或业务行为。该样例未出现前几次的外部字体拦截，不能据此保证新提示对其他生成均有效。

### 两种双资料真实生成（2026-11-10）

使用已保存的真实输入快照进行模型生成，没有重新读取 Figma 插件：

- 截图 + Figma：`run_03359cab880f49ffa482725e757baf95`；以 Figma 为布局参考、截图为样式参考。模型请求 1 次，构建、桌面/手机视口和交互冒烟通过；视觉自动对比和业务语义检查未执行，需人工核对。
- Spec + Figma：`run_5fcf31c3e2ae4e7fa1186a7140d99148`；以 Figma 为布局及视觉参考、Spec 为内容和交互参考。模型请求 1 次，构建、桌面/手机视口和交互冒烟通过；视觉自动对比和业务语义检查未执行，需人工核对。

服务一次仅允许一个任务运行；并发发起第二个任务返回 409，第二次在前一任务结束后提交。以上结果针对具体快照，不代表所有组合都能满足所有设计要求。

### Spec + Figma 交互人工复核（2026-11-10）

在真实生成任务 `run_5fcf31c3e2ae4e7fa1186a7140d99148` 的预览中：搜索 `groceries` 后仅显示对应任务；选择 Completed 后显示已完成任务；打开 New task 弹窗并创建 `Review example`，切回 All tasks 后看到新增任务。该复核未重新调用模型，只覆盖这三个示例交互；页面数据存于前端示例状态，完整业务语义及视觉仍需人工检查，原自动业务检查报告仍为 NOT_RUN。

### 当前验收清单

2026-11-10：重新通过 MCP Bridge 导入已有真实 Figma 节点，获得 READY 状态、本机节点数据和 390×960 图片（`inp_78e35ab80045455fa1c591d5af162a8c`），未调用模型。前端跳过的 6 项属于上游旧工作台的模拟 WebSocket 测试。

2026-11-10：整体回归后端 325 项通过，前端 42 项通过、6 项跳过。七种输入组合的本机任务记录、输入类型、次数及构建产物均可读取；历史报告仍以原检查快照为准。本次未调用模型。

2026-11-10：新增最近 20 条本机任务的元数据列表和恢复入口。实际浏览器列出 7 条任务并恢复其中一条；接口测试验证数量限制且不返回生成文件。本次未调用模型。

2026-11-10：使用临时配置和模拟模型验证超限配置、负数配置及首次生成和修复的重复调度，8 项针对性检查通过；未调用供应商。

2026-11-10：参考尺寸截图增加脚本与资源错误、外部资源阻止、视口溢出提示。模拟页面经真实 Chromium 验证了脚本错误、404 和横纵溢出；界面展示使用模拟接口验证，未调用模型。

2026-11-10：按参考尺寸比较时并排显示本次页面截图和差异图。真实任务浏览器验证两图均为 390×960；不改变检查报告的人工核验状态，未调用模型。

2026-11-10：可按参考图尺寸重新截取页面顶部视口再生成像素差异图。真实截图 + Figma 任务已在 390×960 下完成浏览器验证，平均通道差 5.7/255；该数值不是还原率或验收结论，长页面视口外区域不在比较范围。本次未调用模型。

2026-11-10：增加手动触发的同尺寸像素差异图及 RGB 平均通道差，不设通过阈值、不作为视觉还原率。合成图片测试覆盖相同、不同、尺寸不符及任务资料校验；真实任务在参考图与页面尺寸不符时正确提示。尚未用同尺寸真实任务验证，详情见《项目使用与验收记录》。

2026-11-10：人工复核截图 + Figma 任务 `run_03359cab880f49ffa482725e757baf95`：手机结构接近 Figma，字体及下拉控件有差异；搜索、排序只能改变控件状态，重试只模拟等待，没有商品数据或业务结果。直接打开预览有 favicon 404；未调用模型。详细对照见《项目使用与验收记录》。

2026-11-10：独立浏览器会话刷新后，截图、Spec、Figma 链接、项目包名称、指令及四个维度的来源选择均成功恢复。项目包是占位文件，未验证其导入或内容；未调用模型。

2026-11-10：后端输入与任务流程测试文件 26 项通过；确认无活动任务后，根目录停止与启动脚本执行成功。重启后前端、已有三资料任务预览及 Bridge 健康接口正常，历史任务仍为两次模型请求、一次修复；本次未请求模型，Bridge 健康状态不代表插件已连接。

2026-11-10：首次模型返回的文件格式无效时，保留最多 100,000 个字符供用户主动修复，报告构建和检查未执行。模拟模型及浏览器验证了修复入口和次数限制；尚未用真实供应商异常返回验证。

2026-11-10：预览启动失败新增结果区错误提示和手动重试。用真实三资料任务模拟首次接口失败，重试后真实本地预览成功显示；没有调用模型。

2026-11-10：浏览器合成拖放事件验证了有效 PNG 缩略图、非法文件提示、三张数量限制及移除操作；操作系统文件管理器的人工拖放仍待验证。没有调用模型。

2026-11-10：改善任务创建及修改后的状态恢复：先显示已确认任务，再轮询状态；本地存储不可用时提示复制任务 ID。使用浏览器模拟接口验证创建成功、存储禁用及状态接口断开的组合，任务 ID 和恢复提示可见；该验证未调用模型。

2026-11-10：视觉对照增加叠加与透明度调节。真实三资料任务的浏览器验证确认两图加载和透明度变化；它是人工对照工具，不是自动视觉评分。两图宽度各自等比缩放、顶部对齐，不同尺寸下可能出现缩放差异。

2026-11-10：修复执行在模型调用前通过 SQLite 事务持久化领取，同一任务只能领取一次。模拟模型的针对性验证覆盖重复调度、重复提交、停止和重启恢复；6 项检查通过。尚未进行多进程真实供应商并发压测；真实调用仍按已有验收记录统计。

七种输入组合的真实任务 ID、各检查状态和未覆盖事项集中维护在 [当前验收清单](./项目使用与验收记录.md#当前验收清单2026-11-10)。该清单依据本机 SQLite 任务快照与已有人工验证记录整理；历史记录中的状态不会被后续复查改写。

### 恢复任务异常提示（2026-11-10）

任务 ID 格式错误或任务不存在时，错误显示在恢复输入框旁，并与输入框关联；修改输入后提示清除，失败时保留当前任务。已在本机浏览器验证两种错误提示，前端构建通过；该验证未调用模型。

### 服务与配置异常提示（2026-11-10）

生成不可用时，工作台展示后端返回的配置问题，并针对预算字段非空说明处理方式；后端断开时可在服务恢复后点击“重新检查服务”。已在本机浏览器验证断开提示、生成按钮禁用及重连后按钮恢复，前端构建通过。断线期间未能恢复的上次任务仍需刷新页面或按任务 ID 恢复；具体配置错误和预算字段提示本次未逐项实测。

### 运行中状态重连（2026-11-10）

任务状态轮询改为串行，连接失败时在结果区提示正在重新连接；查询成功后清除该提示。切换任务或离开运行状态后，旧请求的返回值不会覆盖当前状态；该重连只查询已有任务，不重发模型请求。前端构建通过；运行中断网再恢复的浏览器端到端场景尚未实测。

### 截图 + Spec 旧候选复查（2026-11-10）

对任务 `run_69abb4ce51ab47ffb997dce12a6606fe` 的修复候选直接运行当前检查：桌面/手机视口 PASS，交互冒烟 PASS（尝试 3 个控件）。该复查未调用模型，未改写任务原报告；检查截图已保存到本机运行目录。人工对照参考图和桌面截图，主要区域和配色接近，但标题文字不同、搜索文字有截断，且两图宽度不同；视觉还原仍需人工检查，未计算相似度。

### 状态重连模拟验证（2026-11-10）

使用独立本地模拟服务和隔离前端端口，返回运行中状态后让状态查询返回 503，再恢复并返回等待查看。浏览器中观察到重连提示出现，服务恢复后提示消失且状态更新；未调用模型，未修改真实任务。此为模拟接口验证，不能证明真实供应商请求中断后的结果。

### 预览切换保护

任务、候选或状态变化时清空旧预览，并忽略已经失效的预览请求返回值，避免旧请求覆盖当前预览。前端生产构建通过；人为延迟请求并快速切换任务的浏览器竞态场景尚未实测。

### 真实任务预览切换复核

在本机浏览器通过任务 ID 在 `run_f85e09257c0d48f99844df3b76612ed0` 和 `run_088c57637c2743c9b34ff636f8322a4b` 间切换，观察到任务编号、导出链接和预览地址分别对应所选任务。未调用模型。此为正常响应下的切换验证，延迟响应竞态尚未实测。

### 服务恢复时找回最近任务

“重新检查服务”同时尝试读取浏览器记录的最近任务；已有显示中的任务不会被该自动恢复覆盖。前端构建通过；后端断开、恢复并点击按钮的完整浏览器流程尚未复测。该操作仅查询任务，不重新发起模型请求。

### 服务恢复后找回任务复核

本机无运行中任务时，停止后端并保留前端：浏览器提示连接失败及无法恢复最近任务。重新启动后端后点击“重新检查服务”，真实任务 `run_088c57637c2743c9b34ff636f8322a4b`、其预览和下载链接恢复，未重新发起模型请求。验证后已用根目录启动脚本恢复工作台。此次没有模拟任务运行中的供应商中断。

### Figma 插件连接状态入口（2026-11-10）

工作台可手动检查 Bridge 和插件会话。真实本机 Bridge 与浏览器检查均返回 1 个插件会话；无会话及 Bridge 异常通过模拟接口响应验证。会话在线不等于目标文件已关联，仍需在 Figma 中确认。未发起模型请求；前端构建通过。

### 工作台首屏易用性调整（2026-11-10）

明确截图、Spec、Figma 可单选或组合，调整空结果区高度及恢复入口，并改善按钮和键盘焦点的可见性。浏览器查看桌面和 390 像素视口，前端构建通过；其他页面状态和交互仍需分别检查。未调用模型。

### 结果区易用性调整（2026-11-10）

结果区增加检查结果直达入口，明确恢复任务控件、状态颜色与报告区域。复用本机三资料真实任务验证恢复和报告跳转，390 像素视口页面无水平溢出；前端构建通过，未调用模型。报告仍区分通过、未执行和待人工检查。

### 失败状态展示（2026-11-10）

无生成文件时将已有检查项集中显示；任务失败的预览提示不再统一归因于构建失败。前端构建通过，浏览器使用模拟失败响应确认检查状态和修复入口显示，真实供应商失败未复现，未调用模型。

### 后端连接恢复复核（2026-11-10）

浏览器通过拦截请求模拟服务不可用，确认连接失败和任务恢复提示；解除拦截后，“重新检查服务”恢复已有三资料真实任务。原任务保持 2 次请求和 1 次修复；未调用模型。这不是运行中断网的真实网络验证。

### 连续添加截图提示（2026-11-10）

修复异步读取多张截图时数量提示可能遗漏的问题。浏览器合成快速拖放验证三张限制、提示和移除；并非操作系统人工拖放验证。前端构建通过，未调用模型。

### 预览资源策略修正（2026-11-10）

预览 CSP 不再允许远程 HTTPS 图片，和模型提示中的本地资源要求一致。重启服务后，真实三资料任务预览返回 200；浏览器确认数据图片可加载、远程图片被 CSP 拦截。未调用模型。

### 项目目标核对（2026-11-10）

启动、输入组合、真实三资料生成与一次修复、导出和恢复的证据及限制，统一见 [项目目标逐项核对](./项目使用与验收记录.md#项目目标逐项核对2026-11-10)。用户随后确认单张图片的 Windows 文件管理器拖放成功；真实插件导出包以及自动视觉和业务语义验收仍无充分证据。

### 截图 + Figma 样例交互修复（2026-11-10）

真实任务 `run_03359cab880f49ffa482725e757baf95` 使用一次模型修改后，构建、视口与冒烟通过。浏览器验证重试显示五条本地模拟数据、搜索、价格升降序及无结果状态；累计两次模型请求、一次修改。视觉仍待人工核对，标题文案与五条数据数量不一致；详情见《项目使用与验收记录》。

### 修改后 Figma 视觉复核（2026-11-10）

真实任务 `run_03359cab880f49ffa482725e757baf95` 修改后错误状态按 390×960 参考尺寸对照，主要布局与配色接近，字体字重、原生下拉箭头及按钮位置存在差异；像素平均通道差 5.7/255 不是验收评分。参考文案为四项而修改后的模拟数据为五项；成功列表没有参考图。未调用模型。

### 项目包图片路径提示（2026-11-10）

模型提示补充页面相对图片路径和构建 CSS 路径的区别，推荐 JSX 图片或行内背景使用页面相对路径。临时模板与模拟图片验证了本机样例构建和页面解析；真实插件包、模型是否遵循和其他图片名称仍待验证。未调用模型。

### 项目包图片特殊字符（2026-11-10）

模型上下文的图片 URL 正确编码，预览服务对 URL 路径仅解码一次；模拟文件名包含百分号、井号和中文时验证可取回。真实插件导出包尚未验证，未调用模型。

特殊字符修复后，项目包相关检查 10 项和候选预览路由检查 1 项通过；使用模拟项目包，不替代真实插件导出包验证。

### FigmaToCode 打包器兼容性与损坏图片（2026-11-10）

使用本地 FigmaToCode 真正的 ZIP 生成函数和模拟设计内容分别生成 Vite、Next.js、HTML 包，导入器均识别源码与图片；未经过真实 Figma 插件流程。修复损坏 PNG 校验导致的未处理异常，截图、项目包和 Figma 图片校验均转为可读错误；项目包检查 11 项通过。未调用模型。

### Figma 链接异常提示（2026-11-10）

MCP 和 REST 共用节点链接校验，格式损坏时返回 422；四项针对性模拟检查通过，重启后的 MCP 本机接口验证通过。未调用 Figma 或模型。

统一链接校验后，已有真实 Figma 节点经 MCP 接口重新导入成功，节点数据和 390×960 参考图已确认；未调用模型。

### 项目包与真实模型生成复核（2026-11-10）

使用 FigmaToCode 打包器生成的模拟 Vite 包与 Spec 发起真实任务 `run_625124a2378a4191b0a93195326388ca`。初次因 Tailwind 4 写法构建失败；一次修改后构建通过，但根绝对图片路径导致原检查失败。现明确 Tailwind 3 模板约束，并对生成文件中的静态 JSX `src="/images/..."` 使用相对路径；真实生成文件经隔离重建后，子路径下图片加载和切换操作通过。原报告仍为失败，动态表达式和 CSS 图片路径仍有局限；累计请求 2 次、修改 1 次。

### 项目包真实生成复核与工作台界面（2026-11-10）

- 真实任务 `run_4d8acc7390254c9b92628d4ece6daa65` 使用 FigmaToCode 真实 ZIP 打包函数产生的模拟设计内容与 Spec；并非真实 Figma 插件导出。模型请求 1 次、修复 0 次，构建、桌面/手机视口及交互冒烟报告通过；视觉自动检查与业务语义自动检查未执行，仍需人工核对。
- 浏览器直接打开该任务的子路径预览：4×4 示例图片成功加载；点击“隐藏图片”后出现隐藏状态，再点击“显示图片”后图片重新加载。浏览器还请求了不存在的 `/favicon.ico` 并记录 404；这与示例图片加载分开记录。最终文件是相对图片路径，无法仅凭此结果断言本次一定触发了路径规范化；上一任务的隔离重建记录保留。
- 工作台界面调整后，在浏览器查看桌面页面和 390×844 页面，窄屏文档宽度为 390 像素，无水平溢出；未覆盖所有设备和所有任务状态。前端生产构建及工作台文件 ESLint 通过；全项目 lint 仍因其他既有文件问题失败。

### 截图输入体验（2026-11-10）

截图读取时显示状态并暂时禁用生成；文件类型和大小错误显示在截图区域旁；拖入文件时突出投放区，文件落在投放区外时阻止浏览器默认导航。浏览器以合成拖放和人为延迟文件读取验证了上述行为，未发起模型请求；不能代替 Windows 文件管理器的真实拖放验证。前端生产构建与修改文件 ESLint 通过。

### 首次安装文档补充（2026-11-10）

README 首次准备已补充后端、前端、Bridge server 和插件构建命令，以及根目录 `.env` 的字段说明；保留已有配置。当前 Figma MCP Bridge 窗口显示 WebSocket Connected，但窗口自动操作无法取得输入位置，真实 FigmaToCode 插件导出仍未验证。

### 截图解码提示（2026-11-10）

前端读取截图时先尝试浏览器解码并检查 4000 万像素限制，无法解码的图片不加入资料；同批有效图片仍保留并显示提示。浏览器使用合成拖放验证了有效 PNG 与损坏图片混合输入，并以合成剪贴板事件验证 JPEG；这不代替系统拖放或真实剪贴板的全部格式验证。后端仍会检查文件内容；本次未调用模型，前端构建及修改文件 ESLint 通过。

### 创建任务响应丢失后的恢复（2026-11-10）

前端在创建任务前把资料集合标识和请求幂等标识保存到浏览器本机存储。响应未确认时阻止新建，并提供“恢复任务创建”：用户点击后使用同一标识重新提交；若原请求未到达服务端，该操作可能创建任务并调用模型。也可选择放弃恢复；放弃仅清除浏览器记录，不会停止可能已创建的任务，应先查看最近任务。本地存储不可用时不会发送创建请求。

浏览器模拟创建响应丢失、刷新和再次恢复，确认保留相同标识、阻止重复新建、恢复后显示任务 ID；后端既有幂等测试 1 项通过。验证使用模拟接口，未进行真实供应商断网实验；修复请求的响应丢失恢复仍需进一步核对。

### 修改请求响应丢失后的恢复（2026-11-10）

提交修改前，浏览器本地保存任务 ID、完整修改要求（含选中元素上下文）和请求标识；响应未确认时暂停新建和重复修改。用户可主动用原标识恢复，若原请求未到达服务端则可能提交修改并调用模型；放弃恢复只清除本地记录，不会取消可能已执行的修改。恢复成功后读取任务的当前状态，避免把已完成的修改误显示成正在运行。浏览器存储不可用时不发送修改请求。

使用模拟接口验证断线、刷新、标识与请求内容保持一致、恢复后读取状态；后端修复次数及重复执行相关测试 4 项通过，前端构建和修改文件 ESLint 通过。未复现真实供应商断网，修改内容保存在本浏览器本地存储。

### 三资料任务视觉对照记录（2026-11-10）

对真实任务 `run_088c57637c2743c9b34ff636f8322a4b` 修复后候选进行本机画面对照：Figma 参考图为 390×960 商品错误状态，生成的移动端检查图为 390×844 任务列表；另一张 1000×700 截图为任务看板。资料规则指定 Figma 参考布局、截图参考样式、Spec 决定任务内容与交互，所以三者内容与状态并不相同。

- 移动端观察：页眉、标题说明、分隔线、搜索框、下拉框依次纵向排列，浅灰背景与深色文字接近参考；生成页增加新建按钮和任务卡片，原设计的错误说明及重试按钮没有出现。两者高度不同，且任务内容不同，不能据此判断是否逐像素还原。
- 桌面端观察：生成页使用白色页眉、居中内容和蓝色按钮；截图参考中的深蓝色左侧栏与白色大块布局没有出现在生成页。由于此次规则仅指定截图为样式参考，这是一处可供用户判断的明显差异，不自动认定为失败。
- 以上是对已有检查截图的人工视觉观察，不是模型生成新结果或自动相似度评分；交互验证见既有任务记录，最终设计是否符合用户预期仍需用户确认。未调用模型。

### 预览状态保留（2026-11-10）

修复新任务的资料提交失败时提前清空旧预览，以及恢复同一任务或重放已完成修改时预览不刷新的问题。浏览器复用真实三资料任务 `run_088c57637c2743c9b34ff636f8322a4b`，模拟资料提交失败和修改请求响应；确认旧预览保留、按 ID 恢复同一任务后预览显示、模拟重放已完成修改后预览显示。未重新请求模型；前端构建和修改文件 ESLint 通过。
# 2026-11-10 工作台与真实任务补充

- 优化资料输入、截图数量、结果操作栏、检查结果与窄屏布局；1440 和 390 像素视口未出现页面横向溢出，前端构建及工作台文件 ESLint 通过。
- 真实任务 `run_f0f4440a6381416e855342e5f0137feb` 使用截图、Spec 与 Figma 节点，共 2 次模型请求、1 次修复。修复后构建通过，实际操作确认搜索提示文本、搜索、状态筛选和新建任务。
- 任务报告中的自动视觉对比和正式交互检查仍为未执行，视觉还原需人工检查；交互冒烟检查不能替代业务验收。

2026-11-10 视觉补充复查：对截图单输入任务 `run_548ec7fdcbff4d76ba380d202193a9af` 按 1000 × 700 参考尺寸重新截图，RGB 平均通道差为 0.87 / 255；侧栏、背景和卡片位置接近，文字尺寸及间距有差异。三资料任务 `run_f0f4440a6381416e855342e5f0137feb` 对 Figma 390 × 960 及截图 1000 × 700 分别得到 13.57 / 255 和 3.22 / 255；两份资料的用途和内容不同，这些数字不能作为还原验收结论。比较仅覆盖对应视口可见区域，没有调用模型，也没有改写历史任务报告。

2026-11-10：检查结果增加状态颜色并保留状态文字。前端构建和工作台文件 ESLint 通过；真实任务验证了通过、未执行和待人工检查样式，失败样式尚未用真实失败任务验证。Windows 桌面操作组件初始化失败且重试仍提示系统找不到指定路径，文件管理器拖放仍待验证。

2026-11-10：修改失败、中断或结果未知时，若原候选已有构建通过记录，则可预览和导出原候选，界面说明该次修改未完成或结果未知，报告保留实际状态和错误；构建未通过时不开放这类恢复预览。后端完整测试 335 项通过，浏览器模拟中断验证了旧预览、导出入口和错误提示，未复现真实供应商中断。重启后前端和已有真实任务预览可访问；前端构建通过，工作台文件 ESLint 通过，全项目 lint 存在已有错误，Pyright 0 错误、52 条警告。

2026-11-10：用户实际从 Windows 文件资源管理器拖入图片，并确认截图区出现缩略图，覆盖单张图片的真实桌面拖放；未调用模型。

2026-11-10：新增 768 × 1024 平板视口检查与视觉对照选项，新任务检查桌面、平板、手机。对真实三资料任务 `run_088c57637c2743c9b34ff636f8322a4b` 当前候选在独立目录复查，三个视口均无水平溢出；原任务报告未更改，旧任务可能没有平板截图。前端构建、工作台 ESLint 和后端输入测试 44 项通过；未调用模型。

2026-11-10：修复后的工程构建失败时，可预览或下载修改前构建通过的版本；导出报告标注候选版本并保留任务失败状态。后端完整测试 336 项通过；浏览器以模拟失败响应检查入口、预览容器和失败提示，未复现真实供应商修复构建失败。本次未调用模型。

服务重启后，已有真实任务 `run_088c57637c2743c9b34ff636f8322a4b` 的修改前候选预览和导出接口可用，报告注明 `previous` 和 `candidate`；该任务的最终状态为 `READY_FOR_REVIEW`，不能作为真实失败场景证据。

2026-11-10：新增真实 Spec 内容筛选样例 `run_2fff6bbf071a4be5badc426b1f7b8019`，1 次模型请求、0 次修复。构建和三个视口通过；浏览器验证初始四篇文章、收藏标签、搜索叠加、空状态、取消收藏及清除筛选。数据为中文标题，大小写不敏感未直接验证。供应商报告 8,847 tokens，实际账单未知；视觉与通用业务语义自动验收未执行。可复现的需求摘要见《项目使用与验收记录》。

2026-11-10：真实截图单输入样例 `run_b73776d7f2dc49c094ef2634be704bae` 使用本项目表单任务的 768 × 1024 浏览器截图；1 次请求、0 次修复，构建及三个视口通过，输入和重置已操作。按参考尺寸比较得到 RGB 平均通道差 4.32 / 255；整体位置接近，图标和局部间距不同，截图未显示的下拉选项与原页面不同。该值不是还原率，该样例不是外部设计稿；任务报告中的视觉和交互自动验收仍未执行。

2026-11-10：同一截图加 Spec 的真实任务 `run_783af377ec0947209fecb61fbb261406`，指定截图负责布局和样式，Spec 指定两个下拉选项及校验行为。1 次请求、0 次修复，构建、三视口及冒烟通过；浏览器验证选项、必填、邮箱格式、提交和重置。相同尺寸 RGB 平均通道差为 7.08 / 255，视觉位置与间距仍有差异；两个样例各一次，不代表普遍效果。供应商报告 6,289 tokens，账单未知；正式自动视觉与业务语义验收仍未执行。

2026-11-10：结果区新增任务过程记录，手动读取并使用事件序号补读后续记录，单次最多 500 条；读取不会触发模型请求。浏览器读取真实任务 `run_088c57637c2743c9b34ff636f8322a4b` 的 7 条事件，重复刷新无重复；模拟接口 503 后保留已读记录并能在恢复后重试。该功能是手动补读，不是实时事件推送；前端构建及工作台文件 ESLint 通过。

2026-11-10：新增真实 Spec 表单样例 `run_7141ca4119c24c74aca1fe9209b2e0b6`，一次模型请求生成独立表单组件，构建和三视口检查通过。浏览器验证必填、邮箱格式、成功提交和重置；导出工程在独立目录安装及构建通过。原任务的 favicon 请求返回 404，后续工程模板加入空图标声明；在导出副本应用该模板并重新构建启动，未修改原任务。后端完整测试 336 项通过；视觉和通用业务语义自动验收仍未执行。


2026-11-10：视口和交互冒烟检查新增对 HTTP 错误响应及检查过程中被拦截外部请求的记录，发现时标记失败；明确的预览页面 HTTP 错误也标记失败。使用本地测试页面验证资源 404 和请求拦截，后端测试 338 项通过；Pyright 0 错误、52 项既有警告。此检查不保证捕获所有异步请求或验证业务正确性，不改写旧报告；未调用模型。


2026-11-10：视口检查按实际保存数量报告截图；预览首页明确返回 HTTP 错误时记录 FAIL，未收到响应则不当作 HTTP 错误。以本地模拟 404 验证视口和交互结果，确认未生成截图时显示 0 张；这不是生产环境故障复现。后端 339 项测试通过，Pyright 0 错误、52 项已有警告；未调用模型，运行中的后端重启后应用此改动。


2026-11-10：视觉截图与差异图请求增加候选版本核对；所选版本与任务当前版本不一致时返回 409，避免把另一版本的截图当作所选版本。后端接口测试覆盖匹配与不匹配，339 项测试通过；前端构建及工作台文件 ESLint 通过，完整 lint 仍有 19 个已有错误、6 个警告；Pyright 0 错误、52 个已有警告。真实浏览器中的任务切换竞态尚未实测；未调用模型。运行中的后端重启后启用。


2026-11-10：工作台新增“人工复核”：查看已构建页面后可分别记录视觉、需求和交互的“未检查 / 人工通过 / 需要修改”，并填写备注；点击保存后写入本机数据库，导出工程 report.json 包含该结论及记录时间。记录与资料哈希、候选名及生成文件内容绑定，生成内容或候选变化时需重新复核；这不是完整工程文件完整性校验，自动检查与任务状态不会被人工结论覆盖，也不会因此自动标记 COMPLETE_LOCAL。隔离接口测试验证保存、候选变化拒绝旧请求、旧结论不转移及导出报告；后端 340 项测试通过，Pyright 0 错误、52 项已有警告；前端构建和工作台文件 ESLint 通过，全项目 lint 仍有 19 个已有错误。重启后用浏览器恢复真实任务 run_088c57637c2743c9b34ff636f8322a4b，确认入口显示；没有代用户提交人工结论，也未调用模型。


2026-11-10：新任务及修改后的报告在确认资料全部为 Spec 时，将“视觉参考图对比”标为不适用，并注明仍需人工检查页面样式；有截图、Figma 或资料不完整时仍保留未执行，既有任务报告不改写。模拟任务与接口测试覆盖 Spec 单独、图片、Figma、混合和资料缺失，以及生成和修改流程；未发起真实模型请求。后端 341 项测试通过，Pyright 0 错误、52 项已有警告；前端构建和工作台文件 ESLint 通过，全项目 lint 仍有 19 个已有错误。浏览器显示新状态尚未实测；后端重启后新任务应用此规则。


2026-11-10：人工复核面板读取时增加候选版本核对；版本不一致返回 409，提示刷新后复核。接口测试覆盖版本一致及变化，尚未复现真实浏览器并发切换；后端 341 项测试通过、Pyright 0 错误和 52 项已有警告；前端构建与工作台文件 ESLint 通过，全项目 lint 仍有 19 个已有错误。未调用模型；运行中的后端重启后启用。


2026-11-10：启动脚本将 Figma Bridge 作为可选组件；未构建、端口被占用或 Bridge 启动失败时提示，继续尝试启动截图和 Spec 所需的前后端。隔离 PowerShell 模拟环境覆盖未构建和端口不可用分支；这些模拟不证明真实故障下完整运行。本机确认无运行中任务后用脚本重启，前端 HTTP 200，Figma 连接状态 connected；未调用模型。


2026-11-10：在隔离临时副本中移除 Bridge 文件、使用独立端口与不含模型凭据的配置，实际启动前端和后端；前端返回 HTTP 200，测试 PNG 和 Spec 经真实 HTTP 接口导入成功。未运行模型生成，不能据此证明无 Bridge 时模型服务可用；机器上原有 Bridge 仍在运行。测试服务已停止，原工作台保持可访问。


2026-11-10：新增可选搜索验收模板。在生成前填写搜索框 placeholder、搜索词、应保留与应隐藏的两条初始完整文本；规则随资料集合确认并传给模型。构建后在本机 Chromium 检查初始可见、输入搜索词后的保留和隐藏；构建失败标记未执行，修改候选后重新执行。该模板仅验证一组精确文本，其他搜索场景、Tab、弹窗、排序与表单规则仍未自动验收。隔离测试覆盖规则保存、错误过滤与构建失败；真实已有页面 run_2fff6bbf071a4be5badc426b1f7b8019 复查通过，未修改旧报告。真实新任务 run_71a8f2b1bde24ed9bd17a89bdc699264 使用 Spec 和预先填写的规则，1 次模型请求、0 次修改，构建、视口、冒烟和搜索模板 PASS；浏览器恢复任务确认搜索结果显示，导出 report.json 含规则和结果。供应商报告 5025 tokens，账单未知；视觉对照不适用，页面样式和其他交互仍需人工检查。后端 344 项测试通过，Pyright 0 错误、52 项已有警告；前端构建及工作台 ESLint 通过，全项目 lint 仍有 19 个已有错误。

2026-11-10：用户确认从 Windows 文件资源管理器拖入一张图片后，截图区域显示缩略图；此项覆盖一次单图拖放，未调用模型。此前未推送的提交已同步至 GitHub；后续同步状态以发布快照的 Git 状态为准。

2026-11-10：GitHub 连接恢复，发布快照推送至 `af775b2`。通过本机接口重新下载真实三资料任务 `run_088c57637c2743c9b34ff636f8322a4b` 的当前和修改前工程：报告候选分别为 `candidate-2`、`candidate`，构建记录均为 PASS，ZIP 无重复路径；源码统一换行后与对应任务记录一致。Windows 写入导致换行字节差异；本次未调用模型，也未重新构建工程。

2026-11-10：交互冒烟新增复选框、单选框和按钮型输入的操作；可见且启用但不能安全自动操作的控件计入未完成，避免同页其他按钮可操作时错误地报告整个冒烟通过。隐藏或禁用的控件不计入操作；业务语义仍需单独验证。使用本地测试页面验证混合文件上传及三种输入控件；后端 346 项测试通过，Pyright 0 个错误、52 条已有警告，未调用模型。历史任务报告不变，重启后端后新任务生效。

2026-11-10：确认本机列出的 15 个任务无运行中任务后，通过根目录停止和启动脚本重启工作台。首页、真实任务 `run_088c57637c2743c9b34ff636f8322a4b` 的任务接口和预览页面均返回 HTTP 200；未发起模型请求。新检查规则已随重启加载，尚未用新建真实任务重新验收该规则。

2026-11-10：Figma Bridge 连接接口显示 1 个会话；本机配置接口显示 `openai/gpt-6-luna`、每任务最多 2 次模型请求和 1 次修改。用更新后的冒烟检查独立复查真实任务 `run_7141ca4119c24c74aca1fe9209b2e0b6` 与 `run_088c57637c2743c9b34ff636f8322a4b`，各尝试 6 个控件且返回 PASS；不能据此推断业务语义正确或其他页面均通过。未改写历史任务报告，未调用模型。

2026-11-10：新增真实 Spec 表单任务 `run_48b079a2a88b4679a8fad812c584a35d`，1 次模型请求、0 次修改，构建和三视口检查通过。浏览器实际操作验证空姓名提示、未勾选同意提示、选择附件后显示文件名以及勾选后提交成功；空描述提示未单独验证。文件输入隐藏在上传按钮后，冒烟的 PASS 仅表示尝试的 5 个可见控件未发现页面错误，不包含自动选择文件；业务自动检查 NOT_RUN，样式待人工检查，无图片参考。账单未知。

2026-11-10：针对上述隐藏文件输入，冒烟检查点击按钮后等待 200 毫秒并监听文件选择事件；检测到选择器时将该操作计为未完成并报告 NOT_RUN，不伪称已上传。独立复查该真实候选返回 NOT_RUN，提示 1 个上传操作未完成；原报告不改写，未调用模型。更晚触发或未触发选择器的上传逻辑仍需人工检查，后端重启后新任务使用新规则。

2026-11-10：增加可选弹窗验收规则，生成前声明打开按钮、弹窗及其关闭按钮的精确无障碍名称，保存在草稿和已确认资料集合中，并传给模型；构建通过时实际检查初始隐藏、打开和关闭，失败构建或无效生成标记未执行，修改后重新检查。规则只覆盖一组操作，不代表全部业务已验收。隔离测试覆盖规则保存及通过、关闭失效；浏览器确认填写状态与刷新恢复。真实 Spec 任务 `run_be579c8b665041139a28ccc4fd9bc938` 用 1 次模型请求生成，构建、三视口和弹窗验收 PASS；导出报告包含规则和结果，通用交互检查仍为 NOT_RUN，样式待人工检查，账单未知。后端 350 项测试通过，Pyright 0 个错误、52 条已有警告；前端构建和工作台文件 ESLint 通过，全项目 lint 有 19 个已有错误和 6 个警告。

2026-11-10：对上述真实任务执行一次修改，要求新建按钮改为深蓝并保留弹窗和保存功能。最终累计 2 次模型请求、1 次修改；修改后构建、三视口及原弹窗规则均 PASS。浏览器测得按钮背景 `rgb(25, 61, 115)`，实际新建任务后列表显示该项；两个版本导出报告均标识正确候选并包含相同规则与各自的 PASS 结果。该例未证明其他业务或视觉均正确，通用业务自动检查仍为 NOT_RUN，账单未知。

2026-11-10：新增可选标签页验收，规则包含目标标签名称及初始和切换后各一条完整文本，随资料确认并用于生成与修改后的检查；验证精确名称、选中状态与内容切换。隔离测试覆盖正确切换与内容不变，浏览器确认规则填写及刷新恢复。真实任务 `run_b622de3f56544a9a91bb5048711341e7` 首次生成的标签无障碍名称包含数量，精确匹配 FAIL；一次修改后 PASS。最终模型请求 2 次、修改 1 次，构建与三视口通过；两个版本导出报告分别保留 FAIL、PASS 和规则。通用业务检查 NOT_RUN，样式待人工检查，账单未知。后端 353 项测试通过，Pyright 0 错误、52 条已有警告；前端构建与工作台文件 ESLint 通过，全项目 lint 有 19 个已有错误和 6 个警告。

2026-11-10：结果区顶部显示失败检查数量和直达入口，检查存在失败时不显示绿色状态点；不更改后端任务状态。浏览器恢复真实任务 `run_625124a2378a4191b0a93195326388ca`，确认两项检查失败提示与链接，未调用模型。前端构建及工作台文件 ESLint 通过，全项目 lint 仍有 19 个已有错误、6 个警告。

2026-11-10：补充截图、Spec、Figma 各 3 个本机真实任务，明细和限制见 `固定样例验收记录.md`。新增任务各请求模型 1 次、修改 0 次：截图 `run_5aa9eb7911e840bf8f03c4818b565dd5` 的参考图来自本项目生成页；Figma 正常状态 `run_e5c1d3d7f55048e788fabcf64b4fe05c` 与空状态 `run_20efbe977d3544cbbdde502b95f06a7c` 为同一文件的不同节点。三个任务构建和视口 PASS，空状态交互冒烟 NOT_RUN。相同尺寸的平均通道差分别为 4.82、7.28、6.22 / 255，正常状态有视口下方内容未比较的提示；这些值不是还原率。通用业务和自动视觉检查未执行，视觉与实际需求仍需人工确认。输入样例包、全部 9 个样例的修复前后对照和演示录制仍未完成，账单未知。

2026-11-10：正常状态任务 `run_e5c1d3d7f55048e788fabcf64b4fe05c` 追加一次真实修改，要求对照原 Figma 调整商品图形并保留搜索和排序。累计 2 次模型请求、1 次修改；修改后构建和三视口 PASS，浏览器搜索 Shorts 后只显示对应商品，排序未单独验证。同参考尺寸 390×1100 下平均通道差由 7.28 变为 6.55 / 255，两个候选均提示视口下方未比较；商品形状仍有差异，不能将数值作为视觉合格结论。通用业务和自动视觉检查仍为 NOT_RUN，账单未知。


2026-11-10：搜索验收等待输入框和示例文本出现（每项最多 3 秒），减少异步渲染时的误报；超过等待时间或元素不唯一仍报告失败。以本地延迟渲染页面验证，后端 345 项测试通过，Pyright 0 错误、52 项已有警告；未调用模型。旧报告不会改写，运行中的后端重启后启用。


2026-11-10：搜索验收失败信息增加检查阶段，区分查找搜索框、初始示例、输入和过滤结果；使用本地模拟页面验证缺失搜索框和过滤未生效，后端 345 项测试通过，Pyright 0 错误、52 项已有警告。未调用模型；后端重启后新任务生效，旧报告不改写。


2026-11-10：搜索验收规则在折叠标题和资料摘要显示未设置、未填完整、示例重复或已设置，并提供清除按钮；规则仍随浏览器草稿保存。隔离浏览器验证未设置、部分填写及清除，未验证完整填写的所有状态，未调用模型。前端构建与工作台文件 ESLint 通过，全项目 lint 仍有 19 个已有错误、6 个警告。

2026-11-10：用户确认 Windows 文件管理器拖入单张图片后显示缩略图。评估页面修正键盘监听对筛选及投票状态的依赖，并修复 switch 作用域检查；修改文件 ESLint 和前端生产构建通过。完整前端 lint 仍有 18 个错误、5 个警告；评估页面键盘交互本次未进行浏览器实测。未调用模型。

2026-11-10：新增 `examples/fixed-inputs`，整理 2 个本项目页面截图和 3 个 Spec 历史输入，包含原任务指令、一个标签验收规则、文件哈希和使用说明。仅携带输入，未在干净机器重新生成；Figma 样例及所有输入组合的便携资料仍未齐全。

2026-11-10：修改前版本预览增加请求序号校验，切换任务或候选后忽略迟到的旧响应。浏览器以真实任务数据构造模拟失败状态，延迟任务 A 的旧预览响应，切换至任务 B 并打开旧预览，再释放 A 响应，确认 B 的预览地址不变；模拟地址产生的页面错误不作为真实预览结果。未调用模型。前端构建与工作台文件 ESLint 通过；真实供应商修复失败和真实预览服务竞态未复现。

2026-11-10：草稿恢复期间粘贴的图片先暂存在页面内存，待草稿读取结束后再加入，避免被旧草稿覆盖。浏览器模拟延迟 IndexedDB 读取并发送合成剪贴板图片，确认恢复后原有和新粘贴的截图均显示；未验证操作系统全部剪贴板格式，也未调用模型。前端构建与工作台文件 ESLint 通过。

2026-11-10：修复创建响应丢失后的恢复：相同请求标识和资料内容已创建过任务时，即使当前模型配置不可用，也可取回原任务 ID；新任务仍需通过配置检查，同一标识对应不同资料仍返回冲突。接口测试使用模拟模型，确认恢复不会重复调用；完整后端 353 项测试通过，Pyright 0 错误、52 项已有警告。未复现真实供应商断网，未调用模型；运行中的后端重启后生效。

2026-11-10：新增 `examples/fixed-inputs/combo-feedback`，从真实任务快照整理截图 + Spec、指令与四项来源规则，附文件哈希；参考图为本项目生成页面，输入可携带，未在干净机器重新生成。工作台重启后，对真实任务重放原创建标识返回同一任务，模型请求计数不变；未更改配置或调用模型。

2026-11-10：截图缩略图改为完整适配显示，标注顺序、文件名及实际像素尺寸；长文件名截断并可悬停查看。浏览器用 768×1024 PNG 验证名称、尺寸、完整适配样式和移除，390 像素视口无页面水平溢出；未覆盖所有尺寸和浏览器。前端构建及工作台文件 ESLint 通过，未调用模型。

2026-11-10：资料区显示草稿保存中、已保存到当前浏览器、图片读取中或未保存；仅最新一次写入完成后显示已保存，存储错误保留提示。浏览器验证编辑后的保存状态及刷新恢复，并通过模拟 IndexedDB 写入失败验证未保存提示；未测试所有浏览器或真实磁盘故障。前端构建与工作台文件 ESLint 通过，未调用模型。

2026-11-10：Bridge 当前检测到一个会话。使用历史三资料任务的同一 Figma 文件与节点，经本机 HTTP 接口重新导入成功；核对本地快照的文件与节点一致、节点结构非空，图片为有效 390×960 PNG。此次只验证该节点读取，不验证任意文件或新生成，未调用模型。此前待推送提交已通过 SSH 443 同步。

2026-11-10：资料摘要显示布局、视觉样式、内容和交互各自的来源；移除已选资料或清空已选指令时标为失效，生成前拦截并提示重新选择。浏览器模拟 Spec 与 Figma 输入，验证移除选定 Spec 后显示失效、点击生成未发送 POST、重选后摘要提示消失；未实际导入 Figma 或调用模型，也不能自动发现所有资料冲突。前端构建与工作台文件 ESLint 通过。

2026-11-10：来源失效问题解决后，相关生成错误提示会清除；浏览器以模拟输入确认，前端构建及工作台文件 ESLint 通过。未调用模型。

2026-11-10：任务及最近任务列表将模型计数标注为“已占用模型请求额度”，因为初次生成在请求准备时、修改在接受修改时先占额度；本地预检失败或请求结果未知时，此数不能单独证明供应商收到请求或发生计费。导出 `report.json` 的 `model_requests` 保留原字段名，含义相同。浏览器恢复真实三资料历史任务并查看最近任务列表，确认标注与说明；未调用模型。前端构建及工作台文件 ESLint 通过。

2026-11-10：人工复核区区分尚未保存的修改与当前已保存结论，保存后以服务端返回的内容更新表单。浏览器使用真实任务并模拟复核接口，检查修改、保存、再次修改及 409 失败后保留未保存提示；未写入真实人工结论，也未调用模型。前端构建及工作台文件 ESLint 通过。

### 当前工作台截图 + Spec 真实复验（2026-11-10）

使用 `examples/fixed-inputs/combo-feedback` 从浏览器创建真实任务 `run_0b3aa21327154024a23292d8caa9f1e4`：布局与样式选择截图，内容和交互选择 Spec。初次生成后操作确认必填提示、无效邮箱提示、两个指定下拉选项、有效提交和重置；然后要求提交按钮改为深蓝并保留表单行为。修改后按钮为 `rgb(23, 63, 104)`，再次验证有效提交和重置。修改后的无效邮箱及所有必填分支未逐项重测。

最终占用模型请求额度 2 次、修改 1 次；候选 `candidate-2` 的构建、桌面/平板/手机视口和有限交互冒烟为 PASS，视觉自动检查及通用交互自动检查为 NOT_RUN，视觉与需求仍待人工核对。当前候选供应商报告 11,302 tokens，不代表两次调用总量；实际账单未知。

同参考图 768×1024 尺寸对照，RGB 平均通道差为 7.26 / 255，无截图警告；这不是还原率或自动验收结果。观察到字段顺序及整体布局接近，卡片位置、间距和按钮颜色存在差异，其中按钮颜色为本次有意修改；只比较该视口。

导出 ZIP 的报告标识 `candidate-2` 和各检查状态；在新临时目录用锁文件安装、构建，并以本机 Vite 启动，首页 HTTP 200。安装复用了本机缓存，这不是另一台机器的验证。上述表单验证为该样例的实际操作，不代表任意页面均通过。

2026-11-10：修改进行中及修改后构建期间，工作台明确标注当前源码和检查结果属于修改前版本，并区分旧版本的失败摘要。使用真实任务数据和模拟的 REPAIRING、BUILDING 响应验证提示；未复现真实修改构建过程，未调用模型。工作台文件 ESLint 和前端生产构建通过。用户再次确认从 Windows 文件资源管理器拖入图片后出现缩略图。

2026-11-10：对真实截图 + Spec 任务 run_0b3aa21327154024a23292d8caa9f1e4 的修改后 candidate-2 重新操作：空提交时姓名、邮箱、问题类型、问题描述各自出现对应必填提示；输入无效邮箱出现格式提示；填入有效数据后显示姓名及问题类型，重置后四项清空且成功提示消失。使用本地浏览器自动操作已有预览，未调用模型；仅证明该样例和这些分支。

2026-11-10：视觉差异结果增加比较来源，区分构建时视口截图与按参考图尺寸重新截图；切换视口后清除旧结果。浏览器使用真实任务 run_0b3aa21327154024a23292d8caa9f1e4 验证两种来源和切换清除，均为 768×1024、平均通道差 7.26/255；该数值不是还原率，仍需人工判断。未调用模型。前端构建及工作台文件 ESLint 通过，全项目 lint 仍有 18 个已有错误和 5 个警告。

2026-11-10：工作台操作文案改为中文，统一使用“需求说明”，保留产品名和技术名称；调整页头、资料区、折叠设置、预览及移动布局。浏览器在 1440 和 390 像素宽度检查无页面水平溢出，确认搜索验收区域可展开、生成按钮可见；未调用模型，未覆盖全部交互。前端构建和工作台文件 ESLint 通过；全项目 lint 仍有 18 个已有错误和 5 个警告。

2026-11-10：恢复真实三资料任务 run_088c57637c2743c9b34ff636f8322a4b，在新版工作台验证预览与源码切换、下载入口及 1440/390 像素页面无水平溢出；未重新生成或下载。针对发现的人工复核表单拥挤问题，调整为桌面双列、窄屏单列，浏览器核对布局并查看截图，未保存人工结论。前端构建通过，全项目 lint 仍有 18 个已有错误和 5 个警告。

2026-11-10：工作台重新整理为资料和结果双栏，收拢可选验收设置，更新颜色、间距与窄屏布局；新增预览重新加载入口。浏览器检查 1440/390 像素无页面水平溢出、高级设置可展开，真实中文任务重新加载预览成功。生成提示新增默认简体中文，用户指定其他语言或精确文字时以用户要求为准；运行中的后端重启后生效。使用原三资料创建新任务 run_8443e2b25f2943df8301cdf531e0e492，明确要求简体中文，真实模型请求额度 1 次；构建后预览显示中文任务看板并打开新建弹窗，未覆盖全部交互与视觉验收。原英文任务未修改。前端构建与修改文件 ESLint 通过，完整前端 lint 有 18 个已有错误和 5 个警告；后端 353 项测试通过，Pyright 0 错误、52 个已有警告。

重启补充：确认没有运行中任务后，已停止并重新启动工作台；首页 HTTP 200，中文任务仍为待查看，新的默认语言提示已由重启后的后端加载。

2026-11-10：对真实中文三资料任务 run_8443e2b25f2943df8301cdf531e0e492 的预览进行浏览器操作：搜索“回复”只显示匹配任务；筛选“已完成”隐藏待办并显示已完成项；新建“验证中文任务”后标记完成，再筛选已完成可见该任务。数据是页面内存中的示例状态；未检查持久化、全部边界和视觉细节。此次未调用模型，历史自动交互检查仍为 NOT_RUN，不能将本次样例操作推广为通用验收。

2026-11-10：导出中文任务 run_8443e2b25f2943df8301cdf531e0e492，在独立目录解压，报告保留 candidate、请求额度 1 次、构建及视口 PASS、视觉与通用交互 NOT_RUN、人工复核待检查。使用锁文件安装（复用本机缓存）、构建成功，启动本机 Vite 首页 HTTP 200 后停止；未在干净机器验证，也未重新调用模型。

2026-11-10：复查中文三资料任务的参考图和构建截图：截图为任务看板，Figma 为 390 像素商品错误页。实际来源规则指定截图为颜色参考、Figma 为布局参考、需求说明为内容与交互参考。生成页采用浅灰背景、白色卡片和蓝色操作色；未包含截图的深色侧栏，但截图并未被指定为布局来源，不能仅据此判定违反规则。Figma 和需求描述场景不同，生成的手机任务列表不能作为该 Figma 页面逐项还原成功的证据。该观察比较截图参考与桌面检查图，以及 Figma 与手机检查图，尺寸和内容不同；视觉自动检查仍为 NOT_RUN，用户最终判断仍待记录。本次未调用模型。

2026-11-10：模型提示明确解释来源编号、图片顺序及布局、样式、内容、交互四项优先规则，未指定的维度仍结合资料角色和用户指令。用现有真实三资料集合检查发送前数据：布局对应 Figma、样式对应截图、内容及交互对应需求说明，附带两张图；未调用模型，不能证明模型实际遵循。后端 353 项测试通过，Pyright 0 错误、52 条已有警告。确认无运行中任务后重启工作台，新提示对后续调用生效。

2026-11-10：更新来源提示后，用已有截图 + 需求说明创建真实任务 run_442fdabd72ab49e3b1f0bb2dcd239d63，布局和样式指定截图，内容和交互指定需求说明；请求额度 1 次、修改 0 次。按参考图 768×1024 截取页面，卡片、字段顺序及绿色按钮接近，背景圆形装饰与部分间距有差异；RGB 平均通道差 4.51/255，截图无警告，该数值不是还原率。浏览器实际检查四项必填提示、无效邮箱、两个可选问题类型、有效提交与重置，均符合该样例的上述要求。截图中的英文标识 FEEDBACK 被保留，未实现全部可见文字中文；此结果不证明所有模型输出或其他输入组合均遵循来源规则。未保存用户人工复核结论。

2026-11-10：默认中文提示补充普通英文标识的处理，保留用户明确指定的原文及验收所需精确文字。真实任务 run_e9edc4a47339476593096b867365f0f0 使用原截图 + 需求说明复测，首次生成仍保留 FEEDBACK，默认翻译未通过，说明提示不能保证语言结果。随后消耗一次真实修改，明确要求改为“反馈”；candidate-2 构建后显示中文，浏览器复查四项必填、无效邮箱、选项、有效提交和重置通过。共占用 2 次模型请求额度、修改 1 次；视觉自动验收未执行，账单未知。后端 353 项测试通过，Pyright 0 错误、52 条已有警告；该次修改不代表任意页面均能翻译成功。

2026-11-10：统一工作台折叠面板的箭头、边框、展开间距及按钮状态，调整嵌套验收表单和窄屏操作栏；修正仅有检查结果链接时误套用下载按钮样式。浏览器实际展开高级验收、搜索验收及最近任务，并检查表单宽度；其他结果状态及窄屏未在本次逐项验证。未调用模型。
补充：本次前端生产构建和 Workbench.tsx 单文件 ESLint 通过；构建有 Browserslist 数据过旧、依赖弃用及产物体积警告。

2026-11-10：在 390×844 浏览器视口复查新版工作台：展开和收起“最近的本机任务”，按任务 ID 恢复真实任务 run_088c57637c2743c9b34ff636f8322a4b，页面显示原任务、预览、下载入口及原检查结果；工作台文档宽度 375 像素，视口宽度 390 像素，未见页面级水平溢出。未执行下载、重新生成或所有窄屏交互；未调用模型。验证后恢复浏览器视口。

2026-11-10：按用户要求将 README 精简为项目功能介绍和真实生成结果截图；原 README 中的运行说明与历史验收记录保存在根目录“项目使用与验收记录.md”。工作台调整背景、卡片、输入区、按钮与预览的视觉层级；预览/源码切换增加 aria-pressed 状态。浏览器观察新版页面，并确认源码切换的 aria-pressed 为 true；未完整检查各结果状态。前端构建和 Workbench.tsx ESLint 通过；构建仍有依赖弃用、Browserslist 过旧及包体积警告。未发起模型请求，未停止当时正在运行的任务。
补充：按用户要求缩小大屏左右留白；1507 像素视口下内容左侧约 23 像素、右侧约 38 像素（包含滚动条），文档无水平溢出。最新前端生产构建通过，构建警告同上。
补充：README 示例改为用户提供的截图及其匹配任务 run_727d875e570145b693560260a4a9a3e8 的桌面生成截图；通过输入文件 SHA-256 匹配本机资料记录，图片视口尺寸不同，不作为还原率判定。
2026-11-10：新增“清空当前资料”入口，确认后清空输入、来源和验收规则；不删除任务记录。图片读取中或任务运行中禁用，清空时使尚未完成的项目包读取失效。浏览器确认入口显示，未在用户现有草稿上执行清空；前端生产构建和 Workbench.tsx ESLint 通过。历史任务删除尚未实现。
2026-11-10：新增历史任务单条删除与删除当前列表中可删除任务。服务端在事务中检查全部 ID，只允许待查看、已完成或失败状态；删除任务结果、事件和人工复核记录，并保留幂等标记以阻止旧创建请求再次调用模型。本机生成文件、输入资料快照及相关索引仍保留，不等同于磁盘空间清理；运行中、已取消或结果未知任务不提供删除。隔离数据库验证混合状态批量拒绝、删除后不可恢复及生成文件保留；未删除用户真实任务。后端原有 353 项测试及新增隔离检查通过，Pyright 0 错误、52 条已有警告；前端构建及 Workbench ESLint 通过。运行中的后端需重启后才提供新接口，尚未做真实浏览器端到端删除。
2026-11-10：确认无运行中任务后重启工作台，后端删除接口对无效 ID 返回 422；浏览器读取最近 20 个任务，确认单条删除与批量删除入口显示。未对真实任务执行删除，事务行为以隔离数据库检查为准。重启时发现 Windows PowerShell 5 以系统编码解析无 BOM 脚本导致停止脚本语法错误；启动、停止脚本已改为 UTF-8 BOM，PowerShell 5 分别解析通过；实际重启由 PowerShell 7 完成。
2026-11-10：修正已删除任务收到旧修复请求时仍返回已接受的问题；旧请求重放和停止请求现在返回 404，不重新调用模型。隔离测试覆盖删除后的读取、停止与旧修复重放，Pyright 0 错误、52 条已有警告。该改动需后端重启后生效。
补充：后端完整测试共 354 项通过，6 条警告。
2026-11-10：确认无运行中任务后，使用 Windows PowerShell 5 实际执行根目录停止和启动脚本，工作台及能力接口均返回 HTTP 200，不存在任务的停止接口返回 404。重启已加载已删除任务请求边界修复；没有删除真实任务或调用模型。
2026-11-10：历史记录删除成功后自动重新读取最近 20 条，避免旧记录未补入时误以为全部清空；若刷新失败会明确提示记录已删除并提供重新读取入口。前端构建与 Workbench.tsx ESLint 通过；未在真实任务上执行删除，删除后列表刷新和失败提示尚未做浏览器端到端验证。修正实施方案中指向旧 README 验收章节的失效链接。
