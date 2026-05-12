# TRPG 通用 Agent 实施计划（D&D 5e 验证版）

## 1. 项目目标

本项目的目标不是直接做一个“只能跑 D&D 5e 的主持人机器人”，而是先搭出一套通用 TRPG agent 框架，再用 D&D 5e 做第一轮验证。系统需要满足以下三类能力：

1. 通用性：规则、世界观、状态管理、工具调用彼此解耦，可以替换不同 TRPG 规则集。
2. 可控性：关键状态不藏在提示词里，而是落到 notebook memory 和显式工具调用中。
3. 可扩展性：从单主持人扩展到多 agent 协作，包括主持人、玩家、NPC、敌人等角色。

## 2. 本轮范围

### 核心范围

1. 实现一个主持人主导的 TRPG 对话循环。
2. 接入 D&D 5e 规则与部分世界设定的 RAG。
3. 实现 notebook-based memory，支持查询、更新、摘要。
4. 实现多 agent 角色体系：主持人、玩家 agent、NPC/敌人 agent。
5. 先完成 D&D 5e 的短剧本验证，再保留扩展到其他 TRPG 系统的接口。
6. 将长篇战役文本、玩家手册、怪物图鉴等 PDF 预处理为 agent 更容易阅读的中间文本。
7. 提供面向 agent 的资料阅读工具，至少支持按页/按章节浏览与关键词搜索。
8. 将角色卡整理为标准化 Markdown 文件，供玩家 agent 和 GM agent 查询使用。

### 暂不追求

1. 完整覆盖 D&D 5e 全规则。
2. 地图、路径规划、LoS、AOE 等高精度战棋模拟。
3. 长篇大型战役自动运行。

## 3. 目标架构

建议采用“由 DM 直接总控 + 工具层 + 外部状态 + 专职子 agent”的结构。

### 3.1 DM Agent / Session Director

职责：

1. 维护游戏主循环。
2. 决定当前所处模式：对话、探索、战斗、结算。
3. 调度谁在当前回合发言或行动。
4. 约束其他 agent 只能通过工具和显式状态交互。
5. 解释玩家意图。
6. 判断是否需要查规则、掷骰、读取 notebook。
7. 生成主持人口吻的叙事输出。
8. 扮演场景中的非玩家角色。

DM agent 直接承担过去 Orchestrator 与 GM agent 的控制职责，不再单独拆出一个 director。它既负责回合推进和模式切换，也负责裁定、叙事与 NPC 扮演；玩家 agent、NPC agent、规则调查 agent 和工具层都由它直接调度。

DM agent 应当是“世界裁定者”和“流程控制者”的合体，但不直接保存全部状态。所有关键事实都应落到 notebook memory 或结构化状态中。

同时：

1. 扮演重要 NPC。
2. 在战斗中根据怪物特征和局势做出合理行动。
3. 在社交场景中保持人设一致。

由 DM 直接扮演，重要 NPC 需要对应的性格文件，在参与战斗的情况下需要对应的战斗能力（属性，AC，法术列表等）。需要 DM 在合适的时机录入。

### 3.2 Player Agents

职责：

1. 代表不同玩家角色说话或行动。
2. 按角色卡、目标、性格和已知信息作出决策。
3. 与 GM 和其他角色对话。

每个玩家 agent 应有独立 persona、角色卡、短期记忆和可见信息范围。角色卡不应只保留 PDF 或图片形式，而应额外整理成结构稳定、便于检索的 Markdown 文件。

### 3.2.1 Rule Retreival Agent

这是一个独立于运行期 GM 的规则调查与规则整理 agent，名称固定为 `Rule Retreival Agent`。

它与 GM 共用同一套资料阅读与检索工具，但按任务切换两套 prompt 配置：

1. `rule_retreival_bootstrap.prompt`：用于开局前确认游戏基础循环和重要规则，并压缩成可执行的精简流程。
2. `rule_retreival_search.prompt`：用于游戏进行中的规则调查，为 GM 和玩家提供类似搜索引擎的规则问答能力。

prompt 设计原则：

1. prompt 需要提供示例和反例，例如“什么算好的规则流程总结”“什么算仅仅复述原文”。
2. prompt 只给出可能的高价值规则循环示例，不预先穷举所有必须提取的字段。
3. agent 应自行判断哪些规则循环、重复裁定、关键限制和例外值得纳入总结。
4. 在形成结论前，agent 可以多次回看原文块、章节和搜索结果，确认规则是否被误读。

任务一：开局规则整理

1. 通读至少一遍当前规则资料，不能跳过未处理分块。
2. 自行判断并提取游戏中的基础循环、重复出现的裁定模式和高频重要规则；角色创建、角色卡合规检查、探索/社交/战斗切换、短休/长休、升级与资源恢复只是典型示例，而不是固定清单。
3. 将结果压缩为一份给 GM 阅读的自然语言 Markdown 文件，重点是“可以执行、可以复查、可以继续补充”，而不是强制输出固定结构化字段。
4. 主产物写入 `rules_summary.md`，内容应保留规则来源页码与章节引用，必要时可附一个轻量索引文件辅助检索，但不应替代 Markdown 主文档。

任务二：游戏中规则调查

1. 在运行期作为规则调查工具使用，响应 GM 或玩家提出的规则问题。
2. 输出形式应接近搜索引擎：先给结论，再给简短依据，最后给原文页码或章节定位。
3. 对于“有没有可能一回合释放两个升环法术？”这类问题，应优先返回可执行裁定，而不是泛泛摘要。
4. 当规则存在冲突、例外或上下文依赖时，应明确标注“需要 GM 最终裁定”。

设计约束：

1. 它不是主持游戏的 agent，不负责叙事和场景控制。
2. 它不维护主游戏状态，只维护规则摘要文档、规则索引和引用映射。
3. 两种任务共享同一套工具，但 prompt 的目标函数不同：前者偏阅读、回看、归纳和写作，后者偏检索、核对和回答。
4. 如果规则书很长，应采用“全量分块遍历 + 分层压缩 + 自主归纳 + 原文可回查”的策略，而不是要求单次上下文读完整本书。
5. 规则总结的首要目标是帮助 GM 快速理解和执行系统，因此主输出格式应优先保证可读性，而不是机器可解析性。

当前实现状态（2026-05）：

1. `src/agents/rule_retrieval.py` 已实现独立的 `RuleRetrievalAgent`，不再只是设计稿。
2. 已落地两个统一入口：`compile_rules_summary()` 负责开局规则整理，`answer_rule_query()` 负责运行期规则调查。
3. 开局整理模式已实现“两阶段摘要”流程：先由小模型 `qwen3.5-flash` 生成 compressed rule notes，再由主模型 `qwen3-max` 结合工具和 prompt 写出最终 `rules_summary.md`。
4. 运行期规则调查模式已可复用同一套工具完成目录定位、关键词搜索、按页阅读、按章节阅读，并输出带引用的结论。
5. bootstrap/search 两种模式都从 `prompts/` 目录读取 prompt；小模型压缩笔记阶段也会复用 `rule_retreival_bootstrap.prompt` 作为基础指令。
6. 当前实现已带可审计日志，默认输出到 `notebooks/history/debug/rule_retrieval_agent.log.md`，记录 prompt snapshot、可见消息、工具调用、工具输出和结果摘要。
7. 已补充在线测试，当前重点验证文档为 `城主指南2024`，覆盖 100 个 block 压缩、整本压缩、主模型整合、主模型进一步压缩和端到端 bootstrap 规则总结。


### 3.4 Rule & Lore RAG

这部分已经实现为当前可用的 RAG 基础设施，代码主入口位于 `src/rag/rag.py`。

当前实现方法：

1. 索引输入统一改为 Markdown，优先读取 `data/clean_markdown/<doc_id>.md`，其次按 `doc_id` 匹配 `documents/*.md`。
2. 切块策略为分层切块：先按 Markdown 标题层级与 `{242}------------------------------------------------` 这类页码标记拆块，再按段落、句号、逗号继续细分，最后才退回固定窗口切块。
3. 向量索引使用 LlamaIndex `VectorStoreIndex` 持久化到 `data/indices/<index_name>/`。
4. 当前 embedding 已支持 OpenAI、HuggingFace，以及通过 DashScope OpenAI-compatible API 调用的 Qwen `text-embedding-v4`。
5. 检索结果会保留 `doc_id`、`source`、`page_num`、`sections`、`chunk_idx` 等元数据，便于调试和后续裁定。

当前已实现函数：

1. `build_index(index_name, doc_ids)`
2. `load_index(index_name)`
3. `query(index_name, query_text, top_k, filters)`
4. `query_rules(query_text, top_k, filters)`
5. `query_lore(query_text, top_k, filters)`
6. `_resolve_markdown_path(doc_id)`
7. `_iter_markdown_blocks(doc_id, path)`
8. `_load_markdown_nodes(doc_id, path)`
9. `_split_structured_markdown_chunk(body, sections, chunk_size)`

当前验证方式：

1. `src/rag/test.py` 已改为城主指南 2024 专用转换/构建/查询脚本，可把离线网站目录直接转换为单一 Markdown，并构建 `dmg_2024` 索引。
2. 玩家手册、怪物图鉴、奥德赛玩家手册、奥德赛 GM 手册、城主指南 2024 均已完成 Markdown-only 索引构建验证。
3. `rag.py` 与 `test.py` 的结果输出已取消固定 400/500 字符截断，便于调试完整命中片段。

### 3.4.1 长文档预处理要求

这部分已经有第一版实现，代码主入口位于 `src/documents/extract.py`。

当前实现方法：

1. PDF OCR 后端已从 marker 切换为本地 Chandra HuggingFace backend。
2. 当前主流程已经转为 Markdown-first：规则书、模组和角色卡优先以 `documents/*.md` 作为后续 RAG 和浏览工具的直接输入。
3. Markdown 输出保留统一页码标记，格式兼容后续 RAG 读取。
4. `src/rag/test.py` 已补充一个网站转 Markdown 的专用流程，用于把 `documents/城主指南2024/` 这种 WinCHM 风格离线网站遍历并合并成 `documents/城主指南2024.md`。
5. 网站转换阶段会按目录/文件层级补出 Markdown 标题，并修正 HTML 软换行，避免段落或条目被误拆。

当前已实现函数：

1. `slugify(name)`
2. `_extract_headings(md)`
3. `_normalize_paginated_markdown(text)`
4. `_merge_chandra_markdown(results)`
5. `parse_paginated_markdown(text)`
6. `convert_pdf(pdf_path, model, batch_size, max_output_tokens, include_images, include_headers_footers)`
7. `main(argv)`

当前 CLI 参数：

1. `--device`
2. `--batch-size`
3. `--max-output-tokens`
4. `--model-checkpoint`
5. `--include-images`
6. `--include-headers-footers`

### 3.4.2 资料阅读工具

这组工具已经在 `src/tools/tools.py` 中实现第一版。

当前已实现函数：

1. `read_document_page(doc_id, page)`：直接从 `documents/*.md` 或 `data/clean_markdown/*.md` 解析页标记并返回指定页的所有块。
2. `read_document_section(doc_id, section_title)`：按章节标题子串匹配并返回命中块内容。
3. `search_document(doc_id, query, top_k)`：在单文档 Markdown 块中做精确字符串搜索并返回片段。
4. `lookup_index(doc_id, keyword)`：从解析得到的标题层级动态生成 TOC，再返回匹配页码。

当前状态说明：

1. 这组工具已从旧的 `page_jsonl/chunk_index` 路径迁移到当前 markdown-only 工作流，不再依赖已经移除的中间目录。
2. `read_document_page`、`read_document_section`、`search_document`、`lookup_index` 已在 `城主指南2024` 上完成回归验证。
3. `lookup_index` 已对“同页、同标题、不同层级”的重复项做二次去重，避免如“采购毒药”这类条目重复显示。

### 3.4.3 RAG 与阅读工具的分工

建议不要只做单一 RAG，而是同时保留“检索式问答”和“浏览式阅读”两条路径：

1. RAG 适合回答“火球术伤害是多少”这类精确裁定问题。
2. 按页/章节阅读适合理解长战役上下文、章节剧情和连续事件。
3. 搜索工具适合从几百页模组中快速定位候选页面。

也就是说，agent 的资料使用策略应是：先搜索定位，再按页或章节阅读，必要时再把局部内容送入 RAG 或总结器。

对 `Rule Retreival Agent` 来说，这条链路需要拆成两种工作模式：

1. 开局整理模式：按目录和分块顺序遍历全书，生成 `rules_summary.md` 与精简流程草案。
2. 运行期检索模式：收到具体问题后，先搜索定位，再精读相关页或章节，最后输出结论与引用。

这意味着当前 RAG 与阅读工具不只是给 GM 使用，也应当作为 `Rule Retreival Agent` 的统一底座。

同时，开局整理模式不应被限制为固定字段抽取，而应允许 agent 在提示示例的引导下，自主判断“哪些循环值得被总结、哪些规则需要反复提醒、哪些例外必须单独标注”。

### 3.5 Notebook Memory

建议将 notebook 设计为一组可读写 Markdown/JSON 文件，而不是单一长上下文。

设计原则补充：

1. notebook 需要区分“玩家可见记录”和“系统内部记录”，避免把调试信息与角色视角内容混在一起。
2. 每个玩家应拥有自己的 notebook 子集，用于沉淀角色成长、重要经历和长期弧光，而不是只保留全局战役摘要。
3. agent 间对话历史与调试历史应长期留档，便于复盘、重放和定位错误。
4. 原始日志和便于阅读的导出格式需要同时保留，前者保证可追溯，后者保证人工检查成本可控。

建议拆分为：

1. `campaign_summary.md`：章节摘要、近期事件、现在的游戏进度（页数）。
2. `scene_state.json`：当前地点、时间、参与者、场景模式。
3. `character_sheet.json`：玩家 HP、法术位、状态、背包(即角色卡)。
4. `npc_registry.json`：关键 NPC 的身份、关系、目标、态度。
5. `combat_state.json`：战斗轮次、先攻、敌我状态、条件效果。
6. `players/<player_id>/journal.md`：玩家个人日志，只记录该角色已知的重要时刻（角色成长/弧光、被拯救、连续击杀、立誓、关系变化等高价值节点）与主观视角。
7. `history/dialogue/`：agent 之间的原始对话历史，按回合或场景落盘。
8. `history/debug/`：调试历史，记录 agent 路由、工具调用、输入输出摘要、状态变更，以及尽量细的决策过程摘要。
9. `memory_index.json`：摘要指针、更新时间、检索标签。
10. `rules_summary.md`: 记录整体玩法循环和 GM 认为重要的游戏规则，特别是重复出现的，并保留引用位置方便回看原文。

推荐目录细化：

```text
notebooks/
  campaign_summary.md
  scene_state.json
  combat_state.json
  npc_registry.json
  memory_index.json
  players/
    player_1/
      character_sheet.md
      journal.md
      moments.json
    player_2/
      character_sheet.md
      journal.md
      moments.json
  history/
    dialogue/
      scene_001.md
      scene_002.md
    debug/
      scene_001.jsonl
      scene_002.jsonl
  exports/
    scene_001_review.md
```

记录策略建议：

1. 玩家 notebook 只写入玩家已知事实和可回忆的关键时刻，避免泄漏 GM 隐藏信息。
2. `moments.json` 需要提供稳定事件类型，便于后续做角色成长总结、角色弧光分析和剧情回顾。
3. 对话历史优先使用 Markdown 追加式记录，保证人可以直接阅读。
4. 调试历史优先使用 JSONL 记录逐步事件，字段至少包含时间戳、agent、阶段、工具名、参数摘要、结果摘要、状态 diff、决策备注。
5. `exports/` 负责把 `dialogue` 与 `debug` 汇总为单个便于查看的文件，默认一份 Markdown；若需要更强可视化再补 HTML 渲染器。

### 3.6 Tool Layer

工具层已经在 `src/tools/tools.py` 中实现为 LangChain `@tool` 集合，可直接通过 `ALL_TOOLS` 接入 agent。

当前实现方法：

1. 所有工具函数均使用 `@tool` 装饰，便于直接作为 LangChain / LangGraph 工具注册。
2. Notebook 采用 `notebooks/` 目录下的 Markdown/JSON 文件组合，而不是隐藏在 prompt 中。
3. Turn 管理采用 `scene_state.json` 中的 `scene_order` / `initiative_order` 进行推进。
4. 当本地环境未安装 `langchain_core` 时，`src/tools/tools.py` 会退回到兼容包装器，保证工具模块仍可导入和本地验证。

下一步工具层补充要求：

1. 增加玩家 notebook 读写工具，支持按玩家读取日志、追加关键事件、读取角色成长摘要。
2. 增加 `append_dialogue_history` / `append_debug_trace` / `export_scene_review` 一类工具，把 agent 对话与调试轨迹写入统一格式。
3. 调试轨迹默认记录工具调用链、调用参数摘要、结果摘要和状态变更；若框架允许，再补充 agent 中间决策摘要。
4. 所有日志工具应支持按场景、按轮次、按 agent 过滤读取，避免上下文窗口被原始日志直接撑爆。
5. 将现有 `Rule Retreival Agent` 入口继续接入未来 DM 主循环，而不是只作为独立模块使用。
6. 为现有 bootstrap/search prompt 补充少量高质量示例，进一步减少模型输出漂移。
7. 将目前测试侧的“主模型进一步压缩压缩笔记”流程沉淀为正式公共接口，避免后续继续依赖测试代码复用。

`Rule Retreival Agent` 已落地的工具层扩展：

1. 已补充统一入口 `compile_rules_summary` / `answer_rule_query`，底层继续复用阅读、搜索和索引工具。
2. 两种任务已经共用同一套工具集，只通过不同 prompt 文件和运行时规则切换执行目标。
3. 开局整理流程已经支持“先压缩局部规则笔记，再由主模型整合，必要时回看原文，最后写入总文档”的迭代，而不是单次上下文直接定稿。

Prompt 文件约定：

1. `prompts/rule_retreival_bootstrap.prompt`：用于开局规则整理，后续需要补充少量高质量示例，示范如何识别关键循环、如何引用原文、如何写成 GM 可读的 Markdown。
2. `prompts/rule_retreival_search.prompt`：用于运行期规则调查，后续需要补充少量问答示例，示范如何给出结论、依据和引用定位。
3. 如后续需要把 DM 的控制策略单独外置，可再补 `prompts/dm_director.prompt`，但不影响 `Rule Retreival Agent` 独立存在。

当前已实现函数列表：

1. `roll_dice(expression)`
2. `read_document_page(doc_id, page)`
3. `read_document_section(doc_id, section_title)`
4. `search_document(doc_id, query, top_k)`
5. `lookup_index(doc_id, keyword)`
6. `query_rules_tool(query, top_k)`
7. `query_lore_tool(query, top_k)`
8. `read_notebook(section, keys)`
9. `update_notebook(section, patch_json)`
10. `append_log(event)`
11. `summarize_log(window)`
12. `advance_turn()`
13. `ALL_TOOLS`

## 4. 多 Agent 对话与发言顺序

这是本轮必须单独设计的模块，不能只交给 prompt 自发处理。

### 4.1 核心原则

1. 发言顺序由主持人系统控制，而不是让各 agent 自由抢答。
2. 所有 agent 只能在被调度到时发言，或在满足“打断/反应”规则时插入。
3. 对话顺序必须和游戏模式绑定：战斗按速度，平时按一般顺序。

### 4.2 Turn Manager

建议实现一个显式 `TurnManager`，由 DM agent 直接调用。它维护两个主要模式：

1. `combat_mode`
2. `scene_mode`

### 4.3 战斗中的顺序

战斗中使用 `initiative_order`：

1. 开战时统一掷先攻。
2. 依据先攻值排序。
3. 每轮按排序后的顺序行动。
4. 同先攻时使用固定 tie-break 规则，例如敏捷调整值、感知被动值或角色注册顺序。
5. 反应类动作作为受限插入事件处理，不打乱主顺序。

这里的“主持人决定顺序”应理解为：主持人负责启动战斗、维护先攻表、宣布当前行动者，但实际次序由规则和工具确定，不应完全交给 LLM 自由裁定。

### 4.4 非战斗中的顺序

平常使用 `scene_order`，即一般顺序说话：

1. 默认按场景参与者顺序轮转，可采用“玩家队伍顺序 + 当前场景活跃 NPC 顺序”。
2. 当某角色被直接提问、点名、触发事件时，主持人可临时将其提前。
3. 如果某 agent 没有实质输出，可跳过并记录 `pass`。
4. 主持人可以在任意轮次插入旁白、环境反馈或 NPC 反应。

建议把“主持人决定顺序”实现为两层：

1. `TurnManager` 先给出合法候选人集合。
2. `DM Agent Policy` 再从候选人中选择下一位发言者。

这样既满足主持人控制顺序，也避免完全无约束的对话漂移。

### 4.5 推荐的数据结构

```python
SceneState = {
    "mode": "scene" | "combat",
    "round": int,
    "active_speaker": str | None,
    "scene_order": list[str],
    "initiative_order": list[str],
    "interrupt_window": list[str],
    "pending_actions": list[dict],
}
```

### 4.6 一次完整回合的建议流程

1. DM agent 读取 `SceneState`。
2. `TurnManager` 根据当前模式给出下一位或候选集合。
3. DM agent 判断是否需要插入旁白、规则裁定或环境响应。
4. 当前角色 agent 生成“意图”。
5. DM agent 判断是否要检索规则、掷骰、更新状态。
6. 工具层执行并写入 notebook。
7. DM 输出结果叙事。
8. `advance_turn()` 推进到下一位。

## 5. D&D 5e 验证方案

建议不要一开始就尝试完整模组，而是做三层验证。

### 阶段 A：规则验证

目标：验证工具和规则检索是否可靠。

任务：

1. 攻击检定、伤害掷骰。
2. 豁免检定。
3. 法术施放合法性检查。
4. 常见技能检定。
5. 从玩家手册中搜索并阅读指定法术、职业或状态条目。

### 阶段 B：场景验证

目标：验证 notebook memory 和非战斗对话顺序。

任务：

1. 酒馆对话。
2. 商店交涉。
3. 线索搜集。
4. NPC 长对话的人设一致性。
5. 从长篇战役文本中定位当前章节并读取局部剧情信息。

### 阶段 C：短剧本验证

目标：验证完整游戏循环。

建议使用一个 30 至 90 分钟的微型 D&D 5e 冒险，覆盖：

1. 开场叙事。
2. 一段探索。
3. 一段社交。
4. 一场 3 至 5 回合的战斗。
5. 收尾总结与 notebook 摘要更新。

## 6. 代码实施阶段

### Phase 0: 基础设施

当前状态：这一阶段的核心底座已经完成，可作为后续继续开发的稳定起点。

已完成交付物：

1. 项目目录结构已建立，当前已落地 `src/documents/`、`src/rag/`、`src/tools/`。
2. 文档解析脚本已实现为 `src/documents/extract.py`，采用 Chandra HF OCR。
3. 向量检索接口已实现为 `src/rag/rag.py`，支持索引构建、加载、查询。
4. 规则书与模组当前以 `documents/*.md` 作为主输入，已完成玩家手册、怪物图鉴、奥德赛玩家/GM 手册、城主指南 2024 的 Markdown-only 索引构建。
5. 玩家手册、怪物图鉴、角色卡、奥德赛资料、城主指南 2024 等 Markdown 文件已经整理到 `documents/`。
6. `src/rag/test.py` 已实现城主指南 2024 网站转 Markdown、索引构建和查询验证脚本。
7. `src/tools/tools.py` 中的资料阅读工具已迁移到当前 markdown-only 流程并完成回归验证。

当前已完成的关键文件：

1. `src/documents/extract.py`
2. `src/rag/rag.py`
3. `src/rag/test.py`
4. `src/tools/tools.py`
5. `documents/5eDnD_玩家手册PHB_中译v1.72版.md`
6. `documents/5eDnD_怪物图鉴MM_中译 v1.3.2（配图）.md`
7. `documents/5eDnD_角色卡_中译.md`

建议目录：

```text
src/
  agents/
    gm.py
    player.py
    npc.py
  documents/
    extract.py
    normalize.py
    build_index.py
  memory/
    notebook.py
    summarizer.py
  rag/
    ingest.py
    retrieve.py
  tools/
    dice.py
    notebook_tools.py
    retrieval_tools.py
    turn_manager.py
  core/
    models.py
    state.py
    loop.py
tests/
data/
notebooks/
```

### Phase 1: 单主持人可运行原型

目标：

1. 先不启用多玩家 agent，只支持“用户输入 -> GM 裁定 -> notebook 更新”。
2. 打通一次最小回路：输入、检索、掷骰、写状态、输出叙事。
3. 让 GM 能通过搜索和按页/章节阅读工具使用玩家手册与模组文本。

当前进度：部分完成。

已经完成的部分：

1. 规则资料和长文档的 OCR、Markdown 化、索引化已经打通。
2. GM 侧所需的规则 RAG、文档阅读工具、搜索工具已经实现。
3. 玩家手册、怪物图鉴、奥德赛玩家/GM 手册、城主指南 2024 已完成 Markdown-only RAG 构建验证。
4. 城主指南 2024 的离线网站转 Markdown 流程已完成，并修正了 HTML 软换行导致的段落/条目误拆问题。
5. 资料阅读工具已完成 markdown-only 迁移，`lookup_index` 已去除同页重复标题项。
6. `Rule Retreival Agent` 已实现为独立可运行模块，支持开局规则整理和运行期规则调查两种模式。
7. 开局规则整理已改为“小模型压缩笔记 + 大模型整合”的两阶段流程，可降低长文档直接输入主模型的成本。
8. 已补充面向 `城主指南2024` 的在线测试与文件落盘流程，可生成 compressed notes、最终规则总结和调试日志。

尚未完成的部分：

1. 单主持人主循环尚未实现。
2. GM 调用 notebook 并输出完整叙事回路尚未串联。
3. 多轮状态写回与自动裁定流程尚未闭环。
4. `Rule Retreival Agent` 虽然已经能独立完成开局整理与规则调查，但尚未正式挂接到 DM/玩家主对话链路和 DM 调度。

完成标准：

1. 能处理常见 D&D 5e 行动。
2. 能显式调用 dice 和 notebook 工具。
3. 能从长文档中定位并读取局部资料，而不是依赖一次性载入全文。
4. 开局时能由 `Rule Retreival Agent` 产出一份可执行、可阅读、可回看原文的基础规则精简流程 Markdown。
5. 游戏中能通过 `Rule Retreival Agent` 回答具体规则问题，并给出引用定位。

### Phase 2: Notebook Memory 完整化

目标：

1. 引入结构化 notebook 文件。
2. 加入日志摘要与长期记忆回收。
3. 允许人工手工编辑和恢复。
4. 将角色卡纳入 notebook 或相邻目录中的标准 Markdown 文档。
5. 为每个玩家建立独立 notebook 子集，沉淀角色成长/弧光与关键时刻。
6. 持久化 agent 间对话历史和调试历史，并提供统一导出视图。

完成标准：

1. 连续多轮后上下文不会明显漂移。
2. 改动 notebook 后系统能读回并继续运行。
3. 玩家 agent 和 GM 能从统一角色卡 Markdown 中读取关键信息。
4. 玩家 notebook 能稳定记录角色成长、被拯救、连杀等关键事件，并能被后续总结模块读取。
5. 单个场景结束后，系统能同时产出可读的对话回顾和可审计的调试轨迹。
6. 调试记录能追踪一次裁定中涉及的 agent、工具调用、状态写回和关键决策摘要。

### Phase 3: 多 Agent 对话系统

目标：

1. 引入玩家 agent 与关键 NPC agent。
2. 实现 `TurnManager` 和发言调度。
3. 在非战斗场景完成一般顺序说话。

完成标准：

1. 不出现多个 agent 同时抢答。
2. GM 能稳定控制下一个发言者。
3. 玩家 agent 说话风格与角色设定稳定。

### Phase 4: 战斗系统

目标：

1. 引入先攻、回合、状态效果、伤害结算。
2. 战斗中切换到 `combat_mode`。
3. 实现基于先攻的行动顺序。

完成标准：

1. 战斗轮次清晰。
2. 先攻顺序稳定。
3. 战后状态能正确写回 notebook。

### Phase 5: D&D 5e 短剧本评测

目标：

1. 跑通一个完整短流程。
2. 记录工具使用时机、规则命中率、角色一致性。
3. 复盘哪些部分仍然过度依赖 prompt。

## 7. 数据与评测指标

### 数据来源

当前工作区里的 PDF 可以作为第一批资料源：

1. D&D 5e 玩家手册。
2. 怪物图鉴。
3. 角色卡模板。
4. 额外模组/世界设定文本。

这些原始资料不应直接作为最终输入，而应先转换为两类可消费资产：

1. 面向 agent 阅读的清洗 Markdown。
2. 面向工具检索的逐页结构化文本和索引文件。

角色卡也应单独从模板或 PDF 转写为 Markdown，而不是只保留原始表单。

### 关键评测指标

1. 是否在合适的时候调用规则检索、notebook 查询和骰子工具。
2. 是否正确判断行动是否合法。
3. 战斗是否按先攻推进。
4. 平时对话是否按一般顺序推进，并允许主持人插入控制。
5. NPC 是否基本保持人设。
6. notebook 是否能在长对话后保持一致性。
7. 跑完短剧本时是否没有明显逻辑性 bug。

## 8. 框架选型建议

### 推荐结论

首选方案：`LangGraph + LlamaIndex` 混合。

原因：

1. LangGraph 更适合做有状态、长流程、可中断的 agent orchestration。
2. LlamaIndex 更适合快速搭建文档摄取、检索、query engine 和 agent/tool 封装。
3. 你的系统同时需要“强编排”和“强 RAG”，单押一个框架会更别扭。

### 8.1 LangGraph

适合负责：

1. 主循环。
2. 模式切换。
3. TurnManager 调度。
4. 长状态保存。
5. 人工介入与调试断点。

优点：

1. 很适合状态机式流程。
2. Durable execution 对长战役和中断恢复有价值。
3. Human-in-the-loop 很适合 notebook 可编辑方案。

缺点：

1. 比较底层，前期要自己定义较多状态和节点。

### 8.2 LlamaIndex

适合负责：

1. PDF 摄取与切块。
2. 规则/设定 RAG。
3. 查询引擎与检索工具封装。
4. 如果前期想快速验证，也可先用其 `AgentWorkflow` 或 orchestrator 模式做轻量多 agent 原型。

优点：

1. RAG 生态成熟。
2. Workflow 和 AgentWorkflow 能较快出原型。
3. 文档与 query engine 组合灵活，也适合先做文档摄取、章节索引和搜索接口。

缺点：

1. 如果你要非常严格地控制发言顺序和战斗状态机，最终还是需要自己写更多编排逻辑。

### 8.3 CAMEL

适合负责：

1. 角色扮演型多 agent 实验。
2. NPC 与玩家 agent 的对话风格原型。
3. 社会化 agent 交互的快速试验。

优点：

1. 多 agent、role-playing、society 模块天然贴近“不同角色互相说话”的需求。
2. 很适合前期验证角色协作效果。

缺点：

1. 对严格的游戏状态机、先攻顺序、notebook 一致性控制，不如 LangGraph 这种编排框架稳。
2. 如果把它作为主干框架，后面可能需要补很多显式状态约束。

### 8.4 实际建议

如果目标是“课程/项目可交付 + 结构清晰 + 后续可扩展”，建议这样落地：

1. 用 LangGraph 做主控流程。
2. 用 LlamaIndex 做 RAG、文档摄取和检索工具。
3. 把多 agent 先实现为“DM agent + sub-agents as tools”。
4. 只有在需要更强角色互演效果时，再单独参考 CAMEL 的 role-playing 设计。

## 9. 第一版开发任务清单

更新后的开发顺序（已完成项已收口为现状说明）：

已完成：

1. 文档 OCR 与清洗产物生成：`src/documents/extract.py`
2. 玩家手册 Markdown-only RAG：`src/rag/rag.py`
3. 资料阅读与基础工具层：`src/tools/tools.py`
4. 标准 Markdown 角色卡整理：`documents/5eDnD_角色卡_中译.md`
5. 手动 RAG 测试脚本：`src/rag/test.py`
6. `Rule Retreival Agent` 双模式入口与日志：`src/agents/rule_retrieval.py`
7. `Rule Retreival Agent` prompt 文件：`prompts/rule_retreival_bootstrap.prompt`、`prompts/rule_retreival_search.prompt`
8. `Rule Retreival Agent` 在线测试：`tests/test_rule_retrieval_agent.py`

下一步待做：

1. 定义统一状态对象：`GameState`、`SceneState`、`CombatState`、`CharacterState`。
2. 细化 notebook 目录，拆出玩家个人日志、关键时刻记录、对话历史和调试历史。
3. 将现有 `Rule Retreival Agent` 正式接入 DM 主循环与玩家提问链路。
4. 为现有 prompt 增补少量示例上下文，并把测试侧的大模型二次压缩流程整理为正式接口。
5. 写单主持人主循环。
6. 串联 notebook 文件结构、摘要器、日志落盘和状态回写。
7. 写日志导出器，将对话历史与调试轨迹汇总为单文件 Markdown 视图。
8. 写 `TurnManager`，先支持非战斗 `scene_order`。
9. 再加入 `initiative_order` 和战斗回合。
10. 最后把玩家/NPC agent 接进来。

## 9.1 Rule Retreival Agent 已实现文件与函数说明

本节只记录当前已经落地的 `Rule Retreival Agent` 相关文件、函数职责和主要返回值，便于后续继续开发时快速确认边界。

### `src/agents/rule_retrieval.py`

文件作用：`Rule Retreival Agent` 的主实现，负责规则整理、运行期规则调查、两阶段摘要、prompt 装载、工具构造和审计日志写入。

顶层辅助函数：

1. `_normalize_space(text) -> str`：压缩多余空白，返回适合摘要和日志展示的单行文本。
2. `_stringify_content(content) -> str`：把字符串、消息 content 列表或字典统一转成字符串，供日志和模型输出读取使用。
3. `_extract_excerpt(text, query="", width=220) -> str`：从长文本中截取命中 query 的短摘录；若没有 query，则返回前部摘要片段。
4. `_truncate_text(text, limit, suffix="\n\n...[truncated]") -> str`：按字符上限裁剪文本，并追加截断标记。
5. `_page_range_label(pages) -> str`：把页码列表压缩成单页或范围字符串，例如 `12` 或 `12-18`。
6. `_build_toc_entries(blocks) -> list[dict[str, Any]]`：根据 markdown blocks 构建目录项，返回包含 `page_num`、`title`、`heading_level` 的列表。

类与方法：

1. `RuleRetrievalAgent.__init__(llm=None, summary_llm=None, prompts_dir=None, notebooks_dir=None, log_path=None) -> None`
   作用：初始化主模型、小模型、prompt 目录、notebook 目录和日志路径。
2. `RuleRetrievalAgent.list_available_doc_ids() -> list[str]`
   作用：扫描 `documents/` 下可用 Markdown 文档，返回文档 id 列表。
3. `RuleRetrievalAgent.get_log_path() -> Path`
   作用：返回当前 agent 的日志文件路径。
4. `RuleRetrievalAgent.get_prompt_text(mode) -> str`
   作用：读取指定模式的 prompt 文本；`bootstrap` 对应开局整理，`search` 对应运行期调查。
5. `RuleRetrievalAgent.compile_rules_summary(doc_ids=None, output_path=None, invocation_source="direct") -> dict[str, Any]`
   作用：执行开局规则整理主流程。
   主要返回值：
   - `output_path`：最终 Markdown 输出路径。
   - `log_path`：日志路径。
   - `doc_ids`：本次使用的文档列表。
   - `compressed_note_count`：小模型生成的压缩笔记数量。
   - `tool_call_count`：主模型在 React 流程中的工具调用次数。
   - `message_count`：本轮消息总数。
6. `RuleRetrievalAgent.answer_rule_query(query, doc_ids=None, top_k=5, invocation_source="direct") -> str`
   作用：执行运行期规则调查，返回最终自然语言答复字符串。
7. `RuleRetrievalAgent._build_default_llm() -> BaseChatModel`
   作用：构建主模型，默认读取 `qwen3-max` 和兼容 OpenAI 的配置。
8. `RuleRetrievalAgent._build_summary_llm() -> BaseChatModel`
   作用：构建小模型，默认读取 `qwen3.5-flash` 和压缩阶段配置。
9. `RuleRetrievalAgent._build_chat_llm(model_name, enable_thinking) -> BaseChatModel`
   作用：统一封装 `ChatOpenAI` 的模型创建逻辑，返回可直接调用的 chat model。
10. `RuleRetrievalAgent._build_tools(mode, doc_ids, destination=None, compressed_notes=None) -> list[Any]`
  作用：为 React agent 生成工具列表。
  返回值说明：
  - search/bootstrap 共用工具都返回字符串结果，便于模型直接阅读。
  - bootstrap 模式额外加入 compressed notes 工具和写文件工具。
11. `list_rule_documents() -> str`
  作用：列出当前任务允许访问的文档 id。
12. `lookup_rule_index(doc_id, keyword) -> str`
  作用：基于标题层级查目录并返回页码定位结果。
13. `search_rule_document(doc_id, query, top_k=5) -> str`
  作用：在单文档 blocks 中做字符串匹配并返回摘要命中列表。
14. `read_rule_page(doc_id, page, max_chars=DEFAULT_PAGE_READ_CHAR_LIMIT) -> str`
  作用：按页读取 Markdown 内容，并在默认字符上限处截断。
15. `read_rule_section(doc_id, section_title, max_chars=DEFAULT_SECTION_READ_CHAR_LIMIT) -> str`
  作用：按章节标题子串读取内容，并在默认字符上限处截断。
16. `read_existing_rules_summary() -> str`
  作用：读取已有 `rules_summary.md`，供增量整理或人工复查。
17. `list_compressed_rule_notes() -> str`
  作用：列出小模型生成的压缩笔记摘要，仅在 bootstrap 模式下提供。
18. `read_compressed_rule_note(note_id) -> str`
  作用：读取单条压缩笔记的详细内容，仅在 bootstrap 模式下提供。
19. `write_rules_summary(markdown) -> str`
  作用：把最终规则总结写入目标路径，并返回写入确认字符串，仅在 bootstrap 模式下提供。
20. `RuleRetrievalAgent._compose_prompt(mode, doc_ids, destination=None, compressed_note_count=0) -> str`
  作用：把 prompt 文件内容和运行时约束拼接成最终系统 prompt。
21. `RuleRetrievalAgent._bootstrap_request(doc_ids, destination, compressed_note_count) -> str`
  作用：构造 bootstrap 模式的用户请求文本。
22. `RuleRetrievalAgent._search_request(query, doc_ids, top_k) -> str`
  作用：构造 search 模式的用户请求文本。
23. `RuleRetrievalAgent._prompt_name(mode) -> str`
  作用：把模式名映射到 prompt 文件名。
24. `RuleRetrievalAgent._load_prompt(prompt_name) -> str`
  作用：从 `prompts/` 目录读取 prompt 文件；若文件不存在则返回空字符串。
25. `RuleRetrievalAgent._ensure_allowed_doc_id(doc_id, allowed_doc_ids) -> str | None`
  作用：检查文档是否超出本次任务范围；合法时返回 `None`，越界时返回错误说明。
26. `RuleRetrievalAgent._select_doc_ids(doc_ids) -> list[str]`
  作用：决定本次调用真正使用的文档列表；若未传入则默认使用全部可用 Markdown 文档。
27. `RuleRetrievalAgent._load_blocks(doc_id) -> list[dict[str, Any]]`
  作用：复用 `src/rag/rag.py` 的 Markdown block 解析结果，返回单文档的结构化 block 列表。
28. `RuleRetrievalAgent._build_compressed_rule_notes(doc_ids) -> list[dict[str, Any]]`
  作用：调用小模型为指定文档生成压缩规则笔记。
  返回值中的每条 note 至少包含：`note_id`、`doc_id`、`section_title`、`page_range`、`pages`、`headings`、`summary`。
29. `RuleRetrievalAgent._build_note_groups(doc_id, blocks) -> list[dict[str, Any]]`
  作用：把 blocks 按主题和字符预算聚合成适合小模型压缩的 group。
30. `RuleRetrievalAgent._render_block_for_note(block) -> str`
  作用：把单个 block 渲染成压缩阶段输入文本。
31. `RuleRetrievalAgent._compression_request(group) -> str`
  作用：构造小模型压缩 prompt；当前会先复用 bootstrap prompt，再追加“压缩笔记阶段”的说明。
32. `RuleRetrievalAgent._model_name(llm) -> str`
  作用：提取模型名，便于日志和测试断言。
33. `RuleRetrievalAgent._final_ai_text(messages) -> str`
  作用：从消息列表中提取最终可见 AI 输出。
34. `RuleRetrievalAgent._count_tool_calls(messages) -> int`
  作用：统计本轮消息中的工具调用次数。
35. `RuleRetrievalAgent._append_log(mode, prompt_name, prompt_text, invocation_source, inputs, messages, result_summary) -> None`
  作用：把输入、prompt snapshot、消息轨迹和结果摘要以 Markdown 形式追加到日志文件。

模块级兼容入口：

1. `RuleRetreivalAgent = RuleRetrievalAgent`：保留旧拼写的兼容别名。
2. `compile_rules_summary(doc_ids=None, output_path=None) -> dict[str, Any]`：模块级包装器，内部创建 agent 后调用实例方法。
3. `answer_rule_query(query, doc_ids=None, top_k=5) -> str`：模块级包装器，内部创建 agent 后调用实例方法。

### `prompts/rule_retreival_bootstrap.prompt`

文件作用：开局规则整理模式的基础 prompt，定义“什么是 GM 可执行的规则备忘录”、什么内容应跳过、什么内容必须附引用。

返回值说明：该文件本身不返回值；运行时通过 `RuleRetrievalAgent.get_prompt_text("bootstrap") -> str` 读取为字符串。

### `prompts/rule_retreival_search.prompt`

文件作用：运行期规则调查模式的基础 prompt，约束回答格式为“结论 -> 依据 -> 引用定位”。

返回值说明：该文件本身不返回值；运行时通过 `RuleRetrievalAgent.get_prompt_text("search") -> str` 读取为字符串。

### `tests/test_rule_retrieval_agent.py`

文件作用：`Rule Retreival Agent` 的在线测试集合，当前以 `城主指南2024` 为主验证文档，并把摘要产物和日志直接落到 `notebooks/` 目录，方便人工检查。

辅助函数：

1. `RuleRetrievalAgentLiveTest.setUpClass() -> None`：确认目标文档存在，否则跳过 live tests。
2. `RuleRetrievalAgentLiveTest.setUp() -> None`：清理本轮测试需要重建的日志和摘要输出，但保留整本压缩笔记缓存文件。
3. `RuleRetrievalAgentLiveTest._load_first_n_blocks_for_doc(agent, n) -> list[dict[str, Any]]`：把 `_load_blocks` monkeypatch 为只返回前 `n` 个 block，便于控制测试成本。
4. `RuleRetrievalAgentLiveTest._render_compressed_notes_markdown(doc_id, notes, source_blocks) -> str`：把压缩笔记列表渲染成可读 Markdown。
5. `RuleRetrievalAgentLiveTest._render_complete_compressed_notes_markdown(doc_id, notes, source_blocks, summary_model) -> str`：把压缩笔记渲染为更完整的 Markdown，额外保留 `note_count`、`pages`、`summary_model` 等信息。
6. `RuleRetrievalAgentLiveTest._is_compressed_notes_file_complete(text) -> bool`：检查完整压缩笔记文件是否包含主模型继续压缩所需的关键字段。
7. `RuleRetrievalAgentLiveTest._bootstrap_prompt_text() -> str`：读取 bootstrap prompt 文本，供测试侧主模型二次压缩复用。
8. `RuleRetrievalAgentLiveTest._ensure_full_compressed_notes_file() -> str`：若整本压缩笔记不存在，则重新构建并写入普通版与 complete 版文件；返回普通版 Markdown 文本。

在线测试：

1. `test_live_build_compressed_rule_notes_uses_summary_model() -> None`：验证小模型可对前 100 个 blocks 生成压缩笔记，并把结果写入 `notebooks/compressed_rule_notes.live_test.md`。
2. `test_live_build_compressed_rule_notes_for_full_dmg2024_and_write_markdown() -> None`：验证可对整本《城主指南2024》生成压缩笔记，并同时产出普通版和 complete 版文件。
3. `test_live_main_model_further_compresses_full_dmg2024_notes() -> None`：复用整本 compressed notes，让主模型继续压缩并写出 `rules_summary.dmg2024.main_model_compression.live_test.md` 与对应日志。
4. `test_live_main_model_integrates_compressed_notes() -> None`：复用前 100 blocks 的压缩笔记，验证主模型整合流程和 React 工具调用链。
5. `test_live_compile_rules_summary_writes_summary_and_log() -> None`：验证端到端 bootstrap 流程，确认规则总结和调试日志都能落盘。
6. 被注释的 mock tests：保留为历史参考，不再作为当前默认验证路径。

### 当前测试与日志产物

1. `notebooks/history/debug/rule_retrieval_agent.log.md`：默认运行日志。
2. `notebooks/history/debug/rule_retrieval_agent.bootstrap_live_test.log.md`：bootstrap 端到端 live test 日志。
3. `notebooks/history/debug/rule_retrieval_agent.main_model_integration.live_test.log.md`：主模型整合压缩笔记测试日志。
4. `notebooks/history/debug/rule_retrieval_agent.main_model_compression.live_test.log.md`：主模型进一步压缩 compressed notes 的测试日志。
5. `notebooks/rules_summary.live_test.md`：bootstrap live test 产出的规则总结。
6. `notebooks/rules_summary.main_model_integration.live_test.md`：主模型整合压缩笔记后的摘要产物。
7. `notebooks/rules_summary.dmg2024.main_model_compression.live_test.md`：主模型进一步压缩整本 compressed notes 后的摘要产物。
8. `notebooks/compressed_rule_notes.live_test.md`：前 100 个 blocks 的压缩笔记。
9. `notebooks/compressed_rule_notes.dmg2024.full.live_test.md`：整本《城主指南2024》的普通压缩笔记文件。
10. `notebooks/compressed_rule_notes.dmg2024.full.complete.live_test.md`：整本《城主指南2024》的完整压缩笔记文件，供主模型继续复用。

## 10. 最小可行里程碑

如果只做一个最小可行版本，建议把里程碑定为：

1. 能读取 D&D 5e 规则资料并回答规则相关裁定。
2. 能对长篇战役文本和玩家手册进行搜索，并按页或章节读取局部内容。
3. 能保存并恢复游戏 notebook。
4. 能让玩家角色信息以 Markdown 角色卡形式被 agent 查询和使用。
5. 能在单场景中让 GM 和 2 个玩家 agent 按一般顺序对话。
6. 能切换到战斗模式并按先攻完成至少 3 回合。
7. 能为每个玩家沉淀个人关键时刻记录，并在复盘时读取角色成长轨迹。
8. 能输出一个同时包含 agent 对话历史与调试轨迹摘要的场景回顾文件。
9. 能在开局前由 `Rule Retreival Agent` 产出一份基础规则循环与重要规则的自然语言 Markdown 精简流程。
10. 能在游戏中把 `Rule Retreival Agent` 当作规则搜索引擎使用，并返回结论、依据与引用位置。
11. 能跑完一个短 D&D 5e 测试剧本并输出总结。

达到这个里程碑后，再扩展到更复杂的模组、更多 NPC、更多规则系统才是合理顺序。