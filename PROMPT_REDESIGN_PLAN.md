# PostAI Prompt 与 JSON 重设计分阶段方案

## 目标

当前项目已经跑通了“内容解析 -> 风格规划 -> HTML/CSS 布局 -> 浏览器渲染 -> VLM 评审 -> 迭代”的闭环，但 prompt 和 JSON 结构仍然带着“广告卡片/落地页”的惯性：`title`、`subtitle`、`main_visual`、`cta` 被强制存在，布局 prompt 又要求 ContentPlan 中每个元素必须出现在画面里，最终会把很多需求压成“标题 + 副标题 + 主图 + 按钮”的固定模板。

本方案的目标是把系统从“宣传物料生成器”调整为真正面向“海报”的设计系统：允许文字海报、展览海报、活动海报、艺术海报、信息海报、产品海报、招聘海报、实验性排版等多种形态；CTA、主图、副标题、时间地点等都应由海报意图决定，而不是 schema 默认强制。

## 当前工作流理解

后端入口：

```text
POST /api/v1/generate 或 /api/v1/generate/stream
  -> routes_generate._state_from_request
  -> GraphRunner.run_events
```

生成流水线：

```text
GraphState
  -> ContentExtractor
       输出 ContentPlan(JSON)
  -> StyleDirector
       输出 StyleGuide(JSON)
  -> loop iteration_count < max_iterations
       -> SpatialLayoutPlanner
            输出完整 HTML/CSS 文档
       -> AssetStore.save_html
       -> HTMLPainter
            Playwright 截图为 PNG
       -> AssetStore.save_render
       -> HeuristicVLMCritic
            VLM 或启发式评审，输出 CritiqueResult(JSON)
       -> route_after_critique
            final / layout / style
  -> GenerateResponse
```

前端入口：

```text
frontend/index.html
  用户输入 prompt、画布尺寸、迭代次数、目标分数、参考图
frontend/app.js
  调用 /generate 或 /generate/stream
```

## 当前内置 Prompt 与约束清单

### 1. Frontend 默认输入

位置：`frontend/index.html`、`frontend/app.js`

默认 prompt：

```text
制作一张科技风 AI 会议海报
```

影响：默认场景偏“会议宣传”，天然鼓励标题、副标题、CTA、科技渐变模板。

### 2. ContentExtractor

位置：`backend/app/agents/content_extractor.py`

当前 system prompt 要点：

```text
You are a senior poster copy planner.
Return only JSON matching ContentPlan.
Create 4 to 8 stable poster elements.
Required ids: title, subtitle, main_visual, cta.
Use type values: text, image, shape, group.
Keep Chinese text concise.
```

代码级强制：

```text
_validate_required_elements:
  必须包含 title, subtitle, main_visual, cta

_normalize_content_payload:
  缺 title/subtitle/main_visual/cta 时自动补齐

_run_rules:
  默认生成 title/subtitle/main_visual/info/cta
```

问题：

- CTA 被强制存在，即使用户只想要艺术海报、展览视觉、纯文字海报或氛围海报。
- `main_visual` 被强制存在，限制了 typographic poster、信息密集型海报、极简文字海报。
- `subtitle` 被强制存在，导致标题层级固定。
- `ContentPlan` 只有 element list，缺少“海报类型、传播意图、信息层级、可省略内容、视觉策略”等设计语义。

### 3. StyleDirector

位置：`backend/app/agents/style_director.py`

当前 system prompt 要点：

```text
You are an art director for poster design.
Return only JSON matching StyleGuide.
All colors must be valid 6-digit HEX values.
The background prompt must reserve clean readable areas for text.
```

fallback 风格：

```text
科技：technology / neon / clean
音乐：music / energy / stage
招聘：campus / fresh / friendly
默认：minimal / balanced / poster
```

问题：

- `StyleGuide` 更像主题色板，不像完整海报 art direction。
- `background_prompt` 强调“给文字预留干净区域”，适合可读性，但容易把海报变成安全的背景板。
- 缺少版式流派、图像处理方式、材质、排版密度、留白策略、视觉风险等级等字段。

### 4. SpatialLayoutPlanner

位置：`backend/app/agents/layout_planner.py`

当前 system prompt 要点：

```text
You are a poster designer.
Output a COMPLETE, self-contained HTML document.
The body is exactly the poster canvas.
Use CSS gradients, shadows, border-radius, opacity.
Load fonts via Google Fonts CDN.
For images, use inline SVG or placeholder images.
Every element from the ContentPlan MUST appear in the poster.
Use colors from StyleGuide.
The design must be visually impressive.
Reference images should avoid covering title/CTA.
```

问题：

- “Every element MUST appear” 与强制 ContentPlan 叠加，进一步固定画面结构。
- “avoid covering title/CTA” 暗示 CTA 是核心元素。
- “gradients, shadows, border-radius” 默认现代 UI 质感，不一定符合海报，比如瑞士网格、粗野主义、纯字体、复古印刷、拼贴、展览海报。
- prompt 没有要求先选择海报构图策略，只是直接写 HTML。

### 5. HTMLPainter fallback

位置：`backend/app/render/html_painter.py`

fallback HTML 固定结构：

```text
title
subtitle
visual
cta
```

问题：即使 LLM 失败，兜底也会回到 CTA 卡片海报。

### 6. HeuristicVLMCritic

位置：`backend/app/agents/vlm_critic.py`

当前 system prompt 要点：

```text
You are a strict visual art director reviewing a generated poster.
Describe what you literally see.
Score readability, hierarchy, overlap, margins, style consistency, topic expression.
List visible issues.
Write actionable suggestions for HTML/CSS.
Return JSON: score, passed, reasoning, vision_description, issues, suggestions.
```

问题：

- 评审项偏工程可读性，缺少海报特有标准：记忆点、视觉张力、媒介感、信息取舍、构图意图、类型匹配。
- suggestions 是自然语言，router 只能用英文关键词扫描 style/background，中文反馈或更复杂的修订意图难以路由。

### 7. StructuredLLMClient JSON schema hint

位置：`backend/app/core/llm_client.py`

当前 schema hint 要点：

```text
Return a single JSON object that validates against this JSON Schema.
Do not return markdown, explanations, layout canvas specs, or fields outside the schema.
```

问题：这个约束本身合理，但如果 schema 太窄，它会把模型输出锁死。真正要改的是各 agent 的 response model。

## 核心设计原则

1. 海报不是默认营销卡片。它可以是邀请、公告、艺术表达、信息组织、观点表达、品牌形象、活动传播，也可以只是视觉实验。
2. CTA 不是海报的必需元素。只有当用户明确要求报名、购买、扫码、预约、了解更多，或 poster_type 明确是商业转化时，才生成 CTA。
3. 内容 JSON 应表达“信息层级”和“出现必要性”，而不是固定元素名。
4. 风格 JSON 应表达“海报语言”，包括版式流派、视觉密度、图像策略、字体策略、留白策略、材质与风险，而不是只给几种颜色。
5. 布局 prompt 应先选择构图策略，再写 HTML。HTML 是渲染手段，不是设计思路本身。
6. 评审 prompt 应判断“这是不是一张成立的海报”，而不只是“元素有没有都出现、文字有没有对齐”。
7. fallback 也要尊重 poster_type，不能只兜底成固定 CTA 模板。

## 建议的新 JSON 结构

### PosterBriefV2

替代当前 `ContentPlan`，或先作为兼容字段加入。

```json
{
  "poster_intent": {
    "poster_type": "event | exhibition | campaign | editorial | announcement | recruitment | product | typographic | artistic | informational | custom",
    "communication_mode": "announce | invite | inform | persuade | evoke | provoke | celebrate | sell",
    "primary_goal": "用一句话说明这张海报要完成什么",
    "target_audience": "目标观众；未知时可为空",
    "tone": ["calm", "experimental", "premium"]
  },
  "content_strategy": {
    "headline_policy": "literal | poetic | minimal | no_headline",
    "information_density": "sparse | medium | dense",
    "cta_policy": "required | optional | omit",
    "image_policy": "required | optional | omit | reference_driven",
    "inference_policy": "do_not_invent_specific_facts"
  },
  "messages": [
    {
      "id": "headline",
      "role": "headline | subhead | body | meta | date | venue | price | logo | sponsor | cta | caption | credit | visual_label",
      "content": "文字内容",
      "importance": 10,
      "presence": "required | recommended | optional",
      "source": "user | inferred | placeholder",
      "editable": true,
      "notes": "为什么需要或可以省略"
    }
  ],
  "visual_subjects": [
    {
      "id": "key_visual",
      "role": "photo | illustration | symbol | texture | pattern | shape | frame | ornament | none",
      "description": "视觉主体或视觉隐喻",
      "presence": "required | recommended | optional | omit",
      "source": "user | reference | inferred",
      "avoid": ["不要喧宾夺主", "不要遮挡主标题"]
    }
  ],
  "must_not_do": [
    "不要凭空编造精确日期地点",
    "不要默认加入报名按钮"
  ]
}
```

兼容映射：

```text
ContentPlan.poster_goal -> poster_intent.primary_goal
ContentPlan.target_audience -> poster_intent.target_audience
ElementContent(id=title) -> messages(role=headline)
ElementContent(id=subtitle) -> messages(role=subhead)
ElementContent(id=cta) -> messages(role=cta, presence 根据 cta_policy 决定)
ElementContent(type=image) -> visual_subjects
```

### ArtDirectionV2

替代当前 `StyleGuide`，或先扩展 `StyleGuide`。

```json
{
  "style_name": "Swiss grid with cinematic contrast",
  "mood_keywords": ["precise", "quiet", "high-contrast"],
  "poster_language": {
    "composition_family": "swiss_grid | centered_iconic | diagonal_energy | editorial_spread | collage | typographic | cinematic | brutalist | minimal | ornamental | custom",
    "visual_density": "sparse | medium | dense",
    "negative_space": "generous | balanced | tight | intentionally_crowded",
    "depth_strategy": "flat | layered | photographic | 3d | print_texture",
    "risk_level": "safe | expressive | experimental"
  },
  "color_system": {
    "background": "#111111",
    "foreground": "#F6F1E8",
    "accent": "#E83F3F",
    "secondary": "#4A90E2",
    "palette_notes": "颜色如何服务主题"
  },
  "typography": {
    "headline_style": "condensed_bold | elegant_serif | grotesk | handwritten | monospace | custom",
    "body_style": "sans | serif | mono | none",
    "scale_contrast": "low | medium | high | extreme",
    "letter_case": "as_given | uppercase | lowercase | mixed"
  },
  "imagery": {
    "treatment": "none | photo_crop | illustration | symbol | abstract_geometry | texture | reference_image",
    "background_strategy": "plain | gradient | image_full_bleed | split_field | pattern | paper | custom",
    "prompt": "如果需要生成或描述图像，用这个 prompt",
    "negative_prompt": "需要避免的图像特征"
  }
}
```

### CompositionPlanV2

可选：在 HTML 生成前加一个轻量 JSON 中间层。若不想增加 agent，也可以让 LayoutPlanner 在 prompt 内部先隐式完成这些决策。

```json
{
  "canvas": {
    "width": 768,
    "height": 1152,
    "safe_margin_ratio": 0.06
  },
  "composition": {
    "archetype": "centered_iconic | asymmetric_grid | full_bleed_image | type_only | split_axis | radial | diagonal | collage | dense_info | custom",
    "reading_path": ["headline", "key_visual", "meta"],
    "focal_point": "headline | key_visual | symbol | composition",
    "balance": "symmetrical | asymmetrical | intentionally_unbalanced"
  },
  "placements": [
    {
      "target_id": "headline",
      "intent": "primary focal text",
      "zone": "top | center | bottom | left | right | full | custom",
      "scale": "small | medium | large | oversized",
      "layer": 20
    }
  ],
  "omissions": [
    {
      "target_id": "cta",
      "reason": "cta_policy is omit; this is an art/exhibition poster"
    }
  ]
}
```

### CritiqueResultV2

替代自然语言 suggestions 的纯关键词路由。

```json
{
  "score": 86,
  "passed": true,
  "poster_read": "我看到的画面描述",
  "reasoning": "评分原因",
  "rubric": {
    "poster_identity": 18,
    "topic_fit": 17,
    "composition": 18,
    "typography": 16,
    "readability": 15,
    "craft": 14
  },
  "issues": [
    {
      "type": "composition | typography | content | color | imagery | rendering | style",
      "severity": "minor | major | blocking",
      "target_id": "headline",
      "description": "标题太靠近上边缘",
      "suggestion": "下移标题，并增加顶部留白"
    }
  ],
  "revision_focus": "final | layout | style | content | render",
  "do_not_change": ["保留当前黑白高对比方向"]
}
```

## 新版 Prompt 草案

### ContentExtractor V2 system prompt

```text
You are a senior poster editor and content strategist.
Return only JSON matching PosterBriefV2.

Your job is not to force a marketing template. Decide what kind of poster the user is asking for.
A poster may be typographic, image-led, information-dense, abstract, editorial, event-based, product-focused, recruitment-oriented, or purely artistic.

Do not require title, subtitle, main_visual, or CTA by default.
Create only the content units that serve the poster intent.
CTA is required only when the user explicitly asks for registration, purchase, booking, contact, QR code, call-to-action, or when the poster_type/communication_mode clearly needs conversion.

Do not invent precise factual details such as dates, locations, prices, speakers, URLs, or sponsors unless the user provides them.
If a useful detail is missing, either omit it or mark it as placeholder.

For every message or visual subject, set:
- presence: required, recommended, optional, or omit
- source: user, inferred, reference, or placeholder
- importance from 1 to 10

Reference images, when provided, are visual context. They can influence subject, mood, palette, and composition, but user intent remains the priority.
```

### ContentExtractor V2 user prompt

```text
User prompt:
{state.user_prompt}

Canvas:
{width}x{height}px

Reference images:
{reference_images_or_none}

Build a PosterBriefV2 that preserves the user's intent and leaves unnecessary poster elements out.
```

### StyleDirector V2 system prompt

```text
You are an art director specializing in posters across editorial, cultural, commercial, and experimental design.
Return only JSON matching ArtDirectionV2.

Choose a poster language that fits the PosterBriefV2.
Do not default to generic neon gradients, rounded UI cards, CTA buttons, or centered landing-page composition.

The style should describe:
- composition family
- visual density
- negative space strategy
- color system
- typography strategy
- imagery/background treatment
- what makes the poster memorable

All HEX colors must be valid 6-digit values.
If reference images are provided, extract useful palette, mood, cropping, texture, or subject cues, but do not copy them blindly.
```

### StyleDirector V2 user prompt

```text
User prompt:
{state.user_prompt}

Poster brief:
{poster_brief_json}

Reference images:
{reference_images_or_none}

Produce an ArtDirectionV2 that gives the layout planner a strong poster-specific direction.
```

### SpatialLayoutPlanner V2 system prompt

```text
You are a senior poster designer and HTML/CSS production artist.
Output one complete self-contained HTML document, starting with <!DOCTYPE html>.
Do not wrap the answer in markdown. Do not use JavaScript.

The body is the poster canvas and must be exactly {width}px by {height}px with overflow hidden.

Design the poster according to PosterBriefV2 and ArtDirectionV2.
First decide the composition archetype internally, then implement it in HTML/CSS.

Important:
- Do not force a CTA, button, subtitle, card, or hero image unless the brief marks it required or the design genuinely needs it.
- Required content must appear.
- Recommended content should appear if it improves the poster.
- Optional content may be omitted when it weakens composition.
- Any element marked omit must not appear.
- Preserve the hierarchy from importance values.
- Make a real poster, not a web landing page, dashboard, slide, or documentation example.

Use CSS creatively where appropriate: typography, scale, alignment, masks, blend modes, texture, borders, grids, cropping, and layered composition.
Avoid generic UI cards unless the poster concept explicitly calls for them.

Images:
- Use provided reference image URLs only when the brief/art direction calls for them.
- Use object-fit and intentional cropping.
- Do not let images accidentally cover required text.
- If no image is needed, make the poster work through type, shape, color, or texture.

Rendering constraints:
- Use inline CSS or a <style> block.
- Prefer robust system font stacks for Chinese text; external font imports are optional, not required.
- Keep all visible content inside the canvas.
- Ensure text is readable unless the brief intentionally asks for experimental illegibility.

Return only the complete HTML source.
```

### SpatialLayoutPlanner V2 user prompt

```text
User prompt:
{state.user_prompt}

Canvas:
{width}x{height}px

Poster brief:
{poster_brief_json}

Art direction:
{art_direction_json}

Previous VLM feedback, if any:
{feedback_context_or_none}

Create the complete revised HTML poster now.
```

### VLMCritic V2 system prompt

```text
You are a strict poster art director reviewing a rendered poster image.
Return only JSON matching CritiqueResultV2.

Evaluate it as a poster, not as a web page.

Step 1: Describe what you literally see in poster_read: composition, text, imagery, color, hierarchy, spacing, and style.
Step 2: Judge whether the poster type and communication mode match the brief.
Step 3: Score the poster using these criteria:
- poster identity: does it feel like a finished poster?
- topic fit: does it express the user's theme?
- composition: is there a clear visual idea and hierarchy?
- typography: is type intentional and suitable?
- readability: can required information be read?
- craft: does it avoid broken rendering, accidental overlap, and generic template feel?
Step 4: List concrete visible issues with type, severity, target_id when possible, and suggestion.
Step 5: Set revision_focus to final, layout, style, content, or render.

Do not demand CTA, subtitle, or image elements unless the brief marks them required.
Do not penalize intentional minimalism, type-only design, or abstract composition when it matches the brief.
```

### VLMCritic V2 user prompt

```text
Poster brief:
{poster_brief_json}

Art direction:
{art_direction_json}

HTML layout excerpt:
{layout_html_first_3000_chars}

Review the rendered poster image and return CritiqueResultV2.
```

### JSON schema hint 微调

当前 `StructuredLLMClient` 的 schema hint 可以保留，但建议改得更强调“只遵循 schema，不继承旧模板”：

```text
Return exactly one JSON object that validates against the provided JSON Schema.
Do not include markdown or explanations.
Do not add legacy fields such as title/subtitle/main_visual/cta unless the schema and task ask for them.
Schema: ...
```

## 分阶段实施计划

### Phase 0：锁定现状与测试基线

目标：在大改前确认现有行为和约束点。

工作：

- 给当前 prompt 建立快照测试，至少覆盖 ContentExtractor、StyleDirector、SpatialLayoutPlanner、VLMCritic。
- 给 `cta` 强制逻辑建立显式测试，后续删除时能清楚看到测试迁移。
- 增加几个代表性输入作为 fixture：
  - `做一张纯文字爵士音乐节海报，不要按钮`
  - `为一个当代艺术展做极简海报`
  - `招聘海报，需要扫码报名`
  - `制作信息密集的讲座日程海报`
  - `只用抽象形状表达海边夏日`

验收：

- 文档化当前强制元素行为。
- 测试能证明“CTA 目前被强制生成”。

### Phase 1：最小解锁 CTA 与固定元素

目标：不大换 schema，先解除最限制风格的硬约束。

工作：

- 修改 ContentExtractor prompt：删除 `Required ids: title, subtitle, main_visual, cta`。
- 删除或放宽 `_validate_required_elements`，只要求至少有一个 `priority >= 8` 的核心 message 或 visual。
- 修改 `_normalize_content_payload`：不再自动补 `cta`；只有检测到报名、购买、预约、扫码等意图时才补。
- 修改 `_run_rules`：fallback 根据 prompt 决定是否生成 CTA。
- 修改 LayoutPlanner prompt：从 `Every element MUST appear` 改为 `Required elements must appear; optional elements may be omitted if composition benefits`。
- 修改 HTML fallback：至少提供 `type_only`、`image_led`、`event_info`、`cta_campaign` 四种简单模板，而不是固定 CTA 模板。
- 更新测试中所有硬编码 `{"title", "subtitle", "main_visual", "cta"}` 的断言。

验收：

- 输入“不要 CTA”时 ContentPlan 不包含 cta。
- 输入“招聘海报，需要报名”时仍能生成 CTA。
- 没有 CTA 的 ContentPlan 也能完成 HTML 渲染和 VLM 评审。

### Phase 2：PosterBriefV2 内容模型

目标：让内容规划从“元素列表”升级为“海报编辑 brief”。

工作：

- 新增 `PosterBriefV2` schema。
- ContentExtractor 改为输出 PosterBriefV2。
- 暂时保留 ContentPlan 兼容转换层，避免一次性改断 LayoutPlanner 和 response。
- 新 prompt 使用 `poster_intent`、`content_strategy`、`messages`、`visual_subjects`。
- GenerateResponse 可同时返回 `content_plan` 与 `poster_brief`，过渡期前端不必立刻改。

验收：

- 对不同输入能得到不同 `poster_type` 与 `cta_policy`。
- 不再凭空编造精确日期地点。
- 参考图能进入 `visual_subjects` 或 art direction，而不是被当作必须插入的主图。

### Phase 3：ArtDirectionV2 风格模型

目标：让风格规划输出真正可指导版式的海报语言。

工作：

- 新增 `ArtDirectionV2` schema。
- StyleDirector 改为读取 PosterBriefV2 并输出 ArtDirectionV2。
- fallback 风格从关键词 if/else 扩展为 poster_type + tone 的模板表。
- 保留旧 StyleGuide 兼容映射：`color_system` -> primary/secondary/accent/text，`typography` -> font_family，`imagery.prompt` -> background_prompt。

验收：

- “当代艺术展极简海报”输出 minimal/negative_space/typographic 等明确版式方向。
- “音乐节海报”可以输出 dense/collage/diagonal_energy，而不是只换成舞台渐变。
- “科技会议海报”仍可走清晰商业信息风格，但 CTA 只在需要时出现。

### Phase 4：LayoutPlanner V2 与 HTML 生成策略

目标：让 HTML 生成从“放置所有元素”变成“按海报构图策略生产视觉作品”。

工作：

- LayoutPlanner prompt 使用 PosterBriefV2 + ArtDirectionV2。
- 在 prompt 中明确禁止默认 landing-page/card/button 结构。
- 加入 `omission` 规则：optional 内容可以省略，omit 内容必须不出现。
- 若需要更稳定，可新增 CompositionPlanV2 agent；若想保持简单，则让 LayoutPlanner 内部隐式做 composition decision。
- 让反馈上下文使用 CritiqueResultV2 的结构化 issues，而不是纯字符串拼接。

验收：

- type-only 海报没有占位主图。
- artistic poster 可以没有副标题和 CTA。
- recruitment poster 可以保留 CTA/二维码占位，但不像所有海报都长成招聘广告。
- HTML 渲染仍保持完整 `<!DOCTYPE html>`、固定画布、无 JS。

### Phase 5：VLMCritic V2 与路由

目标：让评审和迭代方向更懂海报，不靠英文关键词猜测。

工作：

- 新增 `CritiqueResultV2`。
- VLM prompt 改为 poster-specific rubric。
- issues 从字符串改为对象：`type/severity/target_id/description/suggestion`。
- router 使用 `revision_focus`，不要再扫描 `_STYLE_KEYWORDS`。
- 对中文反馈、风格反馈、内容缺失、渲染错误分别路由。

验收：

- VLM 不会因为没有 CTA 而扣分，除非 brief 要求 CTA。
- 风格问题能稳定回到 StyleDirector。
- 内容缺失或用户事实冲突能回到 ContentExtractor 或直接 warning。

### Phase 6：前端、示例与回归集

目标：让用户输入和演示样例也支持更多海报形态。

工作：

- 前端默认 prompt 改成更开放的示例，例如：
  - `做一张当代艺术展海报，主题是“静默的机器”，极简、不要 CTA`
  - 或提供 prompt presets：活动、展览、招聘、产品、纯文字、实验视觉。
- 输出面板展示 `poster_type`、`cta_policy`、`composition_family`、`revision_focus`。
- 增加 golden prompts 回归集，保存每类海报的最终 HTML/PNG 用于人工比对。

验收：

- 演示不再默认只展示科技会议广告。
- 用户能明确控制是否需要 CTA。
- 不同 poster_type 的视觉差异足够明显。

## 建议优先改动顺序

1. 先做 Phase 1，解除 CTA 和固定元素，这是收益最大、风险最低的改动。
2. 再做 Phase 2 与 Phase 3，把 JSON 从元素清单升级为 brief + art direction。
3. 然后做 Phase 4，让 HTML prompt 真正吃到新的设计语义。
4. 最后做 Phase 5，把 VLM 与 router 改成结构化海报评审。

## 关键测试清单

```text
ContentExtractor:
  - 不需要 CTA 的 prompt 不生成 cta
  - 明确报名/购买/扫码时生成 cta
  - 不凭空编造日期地点
  - 能输出 poster_type/content_strategy

StyleDirector:
  - 不同 poster_type 输出不同 composition_family
  - 色彩字段均为合法 HEX
  - reference image 描述能影响风格但不覆盖用户意图

LayoutPlanner:
  - omit 元素不出现在 HTML
  - required 元素必须出现在 HTML
  - type-only 海报不生成 placeholder image
  - 无 CTA 海报不生成按钮样式
  - HTML 固定画布、无 JS、可被 HTMLPainter 渲染

VLMCritic:
  - 不把 CTA 当作默认评分项
  - 能按 poster_identity/topic_fit/composition/typography/readability/craft 打分
  - revision_focus 能驱动 router

GraphRunner:
  - layout/style/content/render/final 路由都能跑通
  - max_iterations 和 min_iterations 行为不变
```

## 迁移注意点

- 不建议一次性删除旧 `ContentPlan`、`StyleGuide`。先加 V2 schema，再写兼容转换，避免前端和测试同时大面积变动。
- 当前 `LayoutTree` 已经不是主路径，但 response 里仍保留 `layout_tree`。重设计时可以继续保持为空或逐步移除。
- 参考图 URL 与上传图可以保留现有机制，但 prompt 应区分“作为视觉参考”和“必须插入海报”。
- 如果继续使用 `json_object` 模式，schema hint 要跟随 V2 schema 更新，否则模型仍可能输出旧字段。
- fallback 是体验底线，必须同步改。否则 LLM 一失败，用户仍会看到固定 CTA 模板。

## 最小可行 V2 路径

如果只想快速验证“海报风格是否明显变自由”，推荐先做以下四件事：

1. 删除 ContentExtractor 的 required `cta` 校验。
2. 给 ElementContent 增加 `presence` 与 `role`，让 CTA 可选。
3. LayoutPlanner prompt 改成“required 必须出现，optional 可省略，禁止默认 landing page/button 结构”。
4. HTML fallback 增加无 CTA 的 type-only 模板。

这四步不需要完整引入 PosterBriefV2，但能立刻解除最明显的风格限制。
