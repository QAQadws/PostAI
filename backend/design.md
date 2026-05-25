# 智能海报设计多 Agent 编排层 - 后端开发设计文档

## 0. 设计评审结论

当前方案的核心方向是合理的：后端使用 **FastAPI + 结构化状态机** 编排多 Agent，并通过 Pydantic Schema 约束 LLM 输出，适合智能海报设计这种需要“内容规划 -> 风格生成 -> 布局计算 -> 渲染 -> 视觉审查 -> 迭代修正”的任务。

但原设计存在几处需要修正的工程问题：

1. **“Cyclic DAG”表述不准确**：DAG 是无环图，当前流程存在反馈迭代，应称为“有向循环状态图”或“有限状态机”。
2. **布局树设计与 Schema 不一致**：文档要求 AST/DOM-like 布局树，但原 `layout: List[LayoutNode]` 只能表达扁平节点，不能表达容器、Flex、层级关系。
3. **Pydantic 默认值不安全**：`elements: List[...] = []` 这类可变默认值应使用 `Field(default_factory=list)`。
4. **调整向量字段不足**：原 `AdjustmentVector` 只有移动、缩放和改色的部分字段，无法表达字体、层级、透明度、重新生成背景等常见视觉修正。
5. **Agent 输出缺少包裹模型**：OpenAI Structured Outputs 更适合返回对象，不建议直接返回裸 `List`。
6. **渲染接口边界不清晰**：需要明确渲染输入、输出、资源引用、图片存储策略，以及失败时的降级策略。
7. **缺少任务级追踪字段**：SSE 流、日志、重试、前端展示都需要 `job_id`、当前阶段、错误信息、耗时等字段。
8. **LLM 与 VLM 模型能力差异未区分**：DeepSeek 等文本模型不能直接承担 VLM 任务，视觉审查需要单独配置 vision provider。

因此，本文件在保留原始思路的基础上，将设计调整为更可实现的后端编排规范。

---

## 1. 系统架构概览

后端建议采用：

- **FastAPI**：提供 HTTP API 和 SSE 流式事件。
- **Pydantic v2**：定义请求、状态、Agent 输出和事件 Schema。
- **原生 async 状态机优先**：第一版推荐手写状态机，减少 LangGraph 依赖和调试成本；后续如果流程复杂化，再迁移到 LangGraph。
- **OpenAI 兼容 SDK 封装**：文本模型、视觉模型、图像生成/渲染服务分别封装，避免业务逻辑依赖具体供应商。
- **Renderer Adapter**：渲染层作为工具节点，优先接入组内的 Pillow/图形学模块，必要时再接入 SD 或其他图像 API。
- **`.env` 配置加载**：模型、资源目录、CORS 等运行配置统一从 `backend/.env` 读取，仓库提供 `.env.example`。

### 1.1 核心工作流

```text
Generate Request
  -> ContentExtractor
  -> StyleDirector
  -> SpatialLayoutPlanner
  -> RenderInterface
  -> VLMCritic
  -> Conditional Router
       -> score >= threshold: FinalOutput
       -> iteration >= max_iterations: FinalOutput with warning
       -> layout/style issue: SpatialLayoutPlanner
       -> background/image issue: StyleDirector or RenderInterface
```

默认终止条件：

- `score >= 85`
- 或 `iteration_count >= 3`
- 或出现不可恢复错误，由 SSE 返回 `error` 事件。

### 1.2 关键设计原则

1. **结构化状态驱动**  
   Agent 之间不传递自由文本，而是读取和更新 `GraphState`。

2. **布局 AST 而非坐标列表**  
   `LayoutAgent` 输出一棵包含容器和叶子节点的布局树，支持 Flex、绝对定位、边距、层级和响应式比例。

3. **视觉调整向量可计算**  
   `CriticAgent` 输出可被程序直接应用的调整向量，例如移动、缩放、改色、改字体大小、提升对比度、调整 z-index。

4. **渲染层确定性优先**  
   对于文字、形状、布局合成，应优先用 Pillow 或本地图形学模块确定性渲染；背景图生成可以由外部模型提供。

5. **可观测性优先**  
   每个阶段都应通过 SSE、日志和状态字段暴露进度、耗时、关键输出和错误。

---

## 2. 推荐目录结构

```text
backend/
  app/
    main.py
    api/
      routes_generate.py
    core/
      config.py
      llm_client.py
      events.py
      errors.py
    schemas/
      common.py
      state.py
      layout.py
      agents.py
      api.py
    agents/
      content_extractor.py
      style_director.py
      layout_planner.py
      vlm_critic.py
    orchestration/
      graph_runner.py
      router.py
      retry.py
    render/
      interface.py
      pillow_renderer.py
      asset_store.py
    tests/
      test_state_machine.py
      test_layout_adjustments.py
      test_sse_events.py
  design.md
  pyproject.toml
```

---

## 3. 核心数据模型

以下 Schema 是后端实现的基准。实际代码应拆分到 `backend/app/schemas/` 下。

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class CanvasSpec(BaseModel):
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1536, ge=256, le=4096)
    unit: Literal["px"] = "px"


class ElementType(str, Enum):
    text = "text"
    image = "image"
    shape = "shape"
    group = "group"


class ElementContent(BaseModel):
    id: str = Field(description="唯一元素 ID，如 title、subtitle、main_visual")
    type: ElementType
    content: str = Field(description="文本内容、图像提示词或形状描述")
    priority: int = Field(default=5, ge=1, le=10, description="视觉优先级，10 最高")
    alt: str | None = Field(default=None, description="图片元素的语义描述")


class ContentPlan(BaseModel):
    elements: list[ElementContent] = Field(default_factory=list)
    poster_goal: str = Field(description="海报传播目标")
    target_audience: str | None = None


class StyleGuide(BaseModel):
    theme_keywords: list[str] = Field(default_factory=list)
    background_prompt: str = Field(description="传递给背景生成模型的纯背景描述")
    negative_prompt: str | None = Field(default=None, description="不希望出现在背景中的内容")
    primary_color: str = Field(description="主色调 HEX 值")
    secondary_color: str = Field(description="辅助色 HEX 值")
    accent_color: str = Field(description="强调色 HEX 值")
    text_color: str = Field(description="默认文字色 HEX 值")
    font_family: Literal["sans-serif", "serif", "display", "tech", "handwriting"] = "sans-serif"
    mood: str = Field(description="整体视觉情绪，如 futuristic、elegant、playful")


class Box(BaseModel):
    x: float = Field(ge=0, le=1, description="相对画布左上角 X，0-1")
    y: float = Field(ge=0, le=1, description="相对画布左上角 Y，0-1")
    width: float = Field(gt=0, le=1, description="相对画布宽度，0-1")
    height: float | None = Field(default=None, gt=0, le=1, description="相对画布高度，文本可为空")


class LayoutStyle(BaseModel):
    color: str | None = None
    background_color: str | None = None
    opacity: float = Field(default=1.0, ge=0, le=1)
    font_size: float | None = Field(default=None, gt=0, description="相对画布高度的字号比例")
    font_weight: Literal["regular", "medium", "bold", "black"] | None = None
    align: Literal["left", "center", "right"] | None = None
    radius: float | None = Field(default=None, ge=0, le=1)


class FlexSpec(BaseModel):
    direction: Literal["row", "column"] = "column"
    justify: Literal["start", "center", "end", "space-between", "space-around"] = "start"
    align: Literal["start", "center", "end", "stretch"] = "start"
    gap: float = Field(default=0.02, ge=0, le=0.2)
    padding: float = Field(default=0, ge=0, le=0.2)


class LayoutNode(BaseModel):
    id: str = Field(default_factory=lambda: f"node_{uuid4().hex[:8]}")
    element_id: str | None = Field(default=None, description="叶子节点关联的 ElementContent.id")
    node_type: Literal["container", "element"] = "element"
    box: Box
    style: LayoutStyle = Field(default_factory=LayoutStyle)
    flex: FlexSpec | None = None
    z_index: int = Field(default=1, ge=0, le=100)
    children: list["LayoutNode"] = Field(default_factory=list)

    @field_validator("children")
    @classmethod
    def element_node_should_not_have_children(cls, value: list["LayoutNode"], info: Any) -> list["LayoutNode"]:
        return value


class LayoutTree(BaseModel):
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    root: LayoutNode


class AdjustmentAction(str, Enum):
    move = "move"
    resize = "resize"
    recolor = "recolor"
    typography = "typography"
    z_order = "z_order"
    regenerate_background = "regenerate_background"


class AdjustmentVector(BaseModel):
    element_id: str | None = Field(default=None, description="目标元素；若为背景可为空")
    action: AdjustmentAction
    dx: float = Field(default=0, ge=-1, le=1)
    dy: float = Field(default=0, ge=-1, le=1)
    d_width: float = Field(default=0, ge=-1, le=1)
    d_height: float = Field(default=0, ge=-1, le=1)
    scale: float | None = Field(default=None, gt=0, le=3)
    new_color: str | None = None
    new_font_size: float | None = Field(default=None, gt=0)
    z_index_delta: int = Field(default=0, ge=-20, le=20)
    reason: str = Field(description="为什么需要这个调整")


class CritiqueResult(BaseModel):
    score: int = Field(ge=0, le=100)
    passed: bool
    reasoning: str
    issues: list[str] = Field(default_factory=list)
    adjustments: list[AdjustmentVector] = Field(default_factory=list)


class RenderResult(BaseModel):
    image_base64: str | None = None
    image_url: str | None = None
    width: int
    height: int
    mime_type: Literal["image/png", "image/jpeg"] = "image/png"


class GraphStage(str, Enum):
    init = "init"
    content = "content"
    style = "style"
    layout = "layout"
    render = "render"
    critique = "critique"
    final = "final"
    error = "error"


class GraphState(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    user_prompt: str
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    stage: GraphStage = GraphStage.init
    content_plan: ContentPlan | None = None
    style: StyleGuide | None = None
    layout_tree: LayoutTree | None = None
    render_result: RenderResult | None = None
    iteration_count: int = 0
    max_iterations: int = 3
    target_score: int = 85
    feedback_history: list[CritiqueResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
```

实现注意：

- 坐标统一使用 `0-1` 的相对数值，避免 `"10%"`、`"center"` 等字符串增加解析复杂度。
- 渲染层负责把相对坐标转换为像素坐标。
- `LayoutTree.root` 必须是 `container`，叶子节点通过 `element_id` 关联内容。
- LLM 输出 Schema 不应使用递归过深的树，第一版建议最多 3 层。

---

## 4. Agent 节点职责

### 4.1 ContentExtractor

输入：

- `GraphState.user_prompt`
- `GraphState.canvas`

输出：

- `ContentPlan`

职责：

- 解析用户需求，生成标题、副标题、时间地点、行动号召、主视觉、装饰元素等。
- 保证每个元素有稳定 `id`。
- 控制元素数量，第一版建议 4-8 个元素，避免渲染拥挤。

失败降级：

- 如果 LLM 失败，使用规则兜底：生成 `title`、`subtitle`、`main_visual`、`cta` 四个元素。

### 4.2 StyleDirector

输入：

- `user_prompt`
- `content_plan`

输出：

- `StyleGuide`

职责：

- 生成色彩、字体、背景提示词和视觉情绪。
- 明确 `text_color`，避免布局阶段无法判断文字对比度。
- 背景提示词必须强调“为海报文字预留干净区域”，降低后续可读性问题。

失败降级：

- 使用内置风格模板，例如 tech、elegant、youth、minimal。

### 4.3 SpatialLayoutPlanner

输入：

- `content_plan`
- `style`
- `layout_tree`
- `feedback_history`

输出：

- `LayoutTree`

职责：

- 初次运行时，生成布局树。
- 迭代运行时，优先对上一轮 `layout_tree` 应用 `AdjustmentVector`，只有结构性失败时才重新规划。
- 保证主标题、主视觉、CTA 等元素满足基础视觉层级。

硬约束：

- 所有元素 box 必须在画布范围内。
- 高优先级元素不能互相大面积重叠。
- 文本节点必须有 `font_size`、`color`、`align`。
- `z_index` 不得冲突到无法判断前后关系。

### 4.4 RenderInterface

输入：

- `content_plan`
- `style`
- `layout_tree`
- `canvas`

输出：

- `RenderResult`

职责：

- 调用 Pillow 或图形学模块进行确定性合成。
- 将背景、形状、图片、文字按 `z_index` 渲染。
- 返回 `image_base64` 或 `image_url`。第一版为了前端快速展示，可以返回 base64；生产环境建议落盘或对象存储后返回 URL。

渲染约定：

- 文本换行由渲染层处理。
- 如果指定字体不可用，自动回退到系统默认字体，并写入 `warnings`。
- 背景生成失败时，使用 `StyleGuide` 色彩生成渐变或纯色背景兜底。
- 渲染结果由 `AssetStore` 保存到 `ASSET_DIR`，并通过 `ASSET_URL_PATH` 暴露静态 URL；响应中同时保留 base64 方便前端预览。
- 字体查找兼容 Windows、Linux、macOS。Linux 环境建议安装 Noto CJK 字体，例如 `fonts-noto-cjk`。

### 4.5 VLMCritic

输入：

- `render_result`
- `layout_tree`
- `content_plan`

输出：

- `CritiqueResult`

职责：

- 检查文字可读性、元素遮挡、视觉层级、边距、风格一致性、主题表达。
- 输出结构化评分与 `AdjustmentVector`。
- 对无法由布局修复的问题，输出 `regenerate_background` 或改色建议。

注意：

- VLM 必须使用支持图片输入的模型或服务。文本模型提供商和视觉模型提供商需要分开配置。
- `reasoning` 可以给前端展示，但状态机只能依赖 `score`、`passed` 和 `adjustments` 做决策。

---

## 5. 状态机编排

第一版建议使用原生 async 状态机：

```python
async def run_graph(state: GraphState) -> AsyncIterator[SSEEvent]:
    yield event("job_started", {"job_id": state.job_id})

    state.stage = GraphStage.content
    state.content_plan = await content_extractor.run(state)
    yield event("agent_complete", {"agent": "ContentExtractor", "result": state.content_plan.model_dump()})

    state.stage = GraphStage.style
    state.style = await style_director.run(state)
    yield event("agent_complete", {"agent": "StyleDirector", "result": state.style.model_dump()})

    while state.iteration_count <= state.max_iterations:
        state.stage = GraphStage.layout
        state.layout_tree = await layout_planner.run(state)
        yield event("agent_complete", {"agent": "SpatialLayoutPlanner", "result": state.layout_tree.model_dump()})

        state.stage = GraphStage.render
        state.render_result = await renderer.render(state)
        yield event("render_preview", {"iteration": state.iteration_count, **state.render_result.model_dump()})

        state.stage = GraphStage.critique
        critique = await vlm_critic.run(state)
        state.feedback_history.append(critique)
        yield event("critique", critique.model_dump())

        if critique.score >= state.target_score or critique.passed:
            break

        state.iteration_count += 1
        if state.iteration_count >= state.max_iterations:
            state.warnings.append("达到最大迭代次数，返回当前最佳结果。")
            break

    state.stage = GraphStage.final
    yield event("final_output", build_final_payload(state))
```

路由规则：

- `score >= target_score`：结束。
- `score < target_score` 且存在 layout/typography/recolor/z_order 调整：回到 `SpatialLayoutPlanner`。
- `score < target_score` 且主要问题为背景复杂或主视觉失败：回到 `StyleDirector` 或 `RenderInterface`。
- 连续两轮分数没有提升：停止迭代，返回当前最佳结果，并附带 warning。

---

## 6. LLM 客户端封装

配置来源：

- 后端启动时自动读取 `backend/.env`。
- 仓库提供 `backend/.env.example` 作为模板。
- 未配置真实模型时，系统使用本地规则 Agent 和启发式 Critic。

`.env` 关键变量：

```text
APP_NAME=
APP_VERSION=
CORS_ORIGINS=
ASSET_DIR=
ASSET_URL_PATH=
ALLOW_MODEL_FALLBACK=
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_RESPONSE_FORMAT=
VISION_API_KEY=
VISION_BASE_URL=
VISION_MODEL=
IMAGE_API_KEY=
IMAGE_BASE_URL=
```

封装要求：

- 文本 LLM 和视觉 VLM 分开配置。
- 所有结构化输出通过统一方法调用，例如 `client.parse(model=..., response_format=ContentPlan)`。
- 统一重试策略：最多 2 次重试，指数退避。
- 统一错误类型：`LLMCallError`、`SchemaParseError`、`VisionCallError`、`RenderError`。
- `ContentExtractor`、`StyleDirector`、`SpatialLayoutPlanner` 优先调用 `LLM_*`；失败后写入 warning 并回退到本地规则。
- `VLMCritic` 优先调用 `VISION_*`；失败后写入 warning 并回退到启发式视觉评分。
- `ALLOW_MODEL_FALLBACK=true` 时允许远程模型失败后降级；设为 `false` 时，已配置的远程模型失败会中止状态机并通过 SSE/API 返回错误。

注意：

- 不是所有 OpenAI 兼容供应商都支持 `response_format` 或 Pydantic parse。若供应商不支持，应退化为 JSON Schema prompt + `model_validate_json` 校验。
- DeepSeek 等文本模型可用于 Content/Style/Layout，但不能替代 VLM，除非接入了支持图像输入的模型。
- 当前实现支持 `LLM_RESPONSE_FORMAT=json_schema` 和 `LLM_RESPONSE_FORMAT=json_object`。
- `json_object` 模式会在 prompt 中注入目标 JSON Schema；`ContentExtractor` 会尽量将模型误返回的设计稿/布局元素格式归一化为 `ContentPlan`，但如果 `ALLOW_MODEL_FALLBACK=false` 且仍无法校验，则中止生成。

---

## 7. FastAPI 与 SSE 接口

### 7.1 生成接口

路由：

```text
POST /api/v1/generate/stream
```

请求体：

```json
{
  "prompt": "制作一张科技风 AI 会议海报",
  "width": 1024,
  "height": 1536,
  "max_iterations": 3
}
```

响应：

```text
Content-Type: text/event-stream
```

### 7.2 SSE 事件格式

所有 SSE data 均为 JSON：

```json
{
  "event": "agent_start",
  "data": {
    "job_id": "xxx",
    "agent": "ContentExtractor",
    "message": "正在解析海报元素"
  }
}
```

事件类型：

- `job_started`
- `agent_start`
- `agent_complete`
- `render_preview`
- `critique`
- `warning`
- `final_output`
- `error`
- `job_finished`

错误事件示例：

```json
{
  "event": "error",
  "data": {
    "job_id": "xxx",
    "stage": "layout",
    "message": "LayoutAgent 输出未通过 Schema 校验",
    "recoverable": false
  }
}
```

### 7.3 非流式调试接口

建议额外提供：

```text
POST /api/v1/generate
```

用途：

- 单元测试更方便。
- 前端调试时可以直接拿最终 JSON。
- CI 中可验证状态机完整跑通。

---

## 8. 异常处理与降级策略

1. **LLM 输出 Schema 错误**  
   重试 2 次；仍失败则使用规则兜底或返回 `error`。

2. **渲染失败**  
   如果外部图像生成失败，使用本地纯色/渐变背景继续渲染；如果 Pillow 合成失败，直接返回 `error`。

3. **VLM 不可用**  
   第一版可以允许降级为启发式评分：检查 box 是否越界、重叠面积、字号是否过小、文字颜色与背景色的估算对比度。

4. **迭代无改善**  
   如果连续两轮评分未提升，停止循环，返回历史最高分对应结果。

5. **SSE 中断**  
   记录 `job_id` 和最后状态。第一版可不支持断点续传，但日志中必须能定位失败阶段。

---

## 9. 测试计划

最低测试范围：

1. **Schema 测试**
   - `GraphState` 默认值正确。
   - `LayoutTree` 可表达嵌套布局。
   - 非法坐标会被拒绝。

2. **状态机测试**
   - 正常流程能到达 `final_output`。
   - 低分 critique 会触发再次 layout。
   - 达到最大迭代次数会停止。

3. **调整向量测试**
   - `move`、`resize`、`recolor`、`typography` 能正确应用。
   - 调整后 box 不越界。

4. **SSE 测试**
   - 事件顺序稳定。
   - 失败时返回 `error` 事件。

5. **渲染接口测试**
   - 使用 mock renderer 返回固定 base64。
   - 字体缺失时有 warning。

---

## 10. 第一阶段实现范围

第一阶段目标是跑通“可演示闭环”，同时保留真实 LLM/VLM 接入能力。

必须实现：

- FastAPI 项目骨架。
- Pydantic Schema。
- 原生 async 状态机。
- Content/Style/Layout 三个文本 Agent。
- Renderer Adapter 接口和一个 Pillow/mock 实现。
- VLM Critic 接口和一个 mock/启发式实现。
- SSE 流式接口。
- 基础单元测试。
- `.env` 配置加载与 `.env.example` 模板。
- OpenAI-compatible 文本 LLM 接入，失败时回退到规则 Agent。
- OpenAI-compatible 视觉模型接入，失败时回退到启发式 Critic。
- Pillow 渲染结果落盘与 `/assets/...` 静态访问。
- Windows/Linux/macOS 字体路径兼容，Linux 推荐安装 Noto CJK。

可以延后：

- LangGraph 迁移。
- 复杂素材库管理。
- 多尺寸自动适配。
- 真实背景/主视觉图像生成模型接入。
- 复杂字体排版和中文断行优化。

---

## 11. 需要后续确认的问题

1. 渲染模块由后端直接实现 Pillow，还是由图形学同学提供独立包/API？
2. 项目演示是否必须使用真实 VLM，还是允许第一版使用 mock critic？
3. 前端希望接收 base64，还是希望后端保存图片并返回 URL？
4. 海报是否只做竖版 1024x1536，还是需要支持横版、方图和多尺寸导出？
5. 是否需要保留每轮中间图片用于对比展示？
