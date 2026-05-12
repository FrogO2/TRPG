# TRPG

一个本地运行的 TRPG 多代理实验项目，包含 GM / 玩家对话运行时、规则检索代理，以及命令行入口。

## 环境准备

建议使用 Python 3.11 或更高版本。

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 配置 OPENAI_API_KEY

运行带 LLM 的 CLI 命令前，至少需要设置一个可用的 API key。最简单的方式是设置 `OPENAI_API_KEY`。

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "你的_api_key"
```

如果你使用兼容 OpenAI 的第三方端点，也可以额外设置：

```powershell
$env:TRPG_OPENAI_BASE_URL = "https://your-compatible-endpoint/v1"
```

项目里的 GM、玩家和规则检索默认都会读取这些环境变量；如果没有设置，会在运行时直接报错并提示缺少 key。

## CLI 用法

CLI 入口是 `trpg_cli.py`。

查看全部命令：

```powershell
python .\trpg_cli.py --help
```

初始化对话状态：

```powershell
python .\trpg_cli.py init
python .\trpg_cli.py init gm human_player llm_player_1 llm_player_2 llm_player_3
```

查看当前状态：

```powershell
python .\trpg_cli.py state --pretty
python .\trpg_cli.py upcoming --lookahead 5
```

推进回合与发言：

```powershell
python .\trpg_cli.py human-turn "我先检查房间里的脚印"
python .\trpg_cli.py gm-turn "根据当前局势推进场景" --context "队伍刚进入遗迹入口"
python .\trpg_cli.py player-turn llm_player_1 "基于当前信息做出行动" --context "注意队伍资源紧张"
python .\trpg_cli.py advance
```

规则检索：

```powershell
python .\trpg_cli.py rule-query "长休如何恢复生命值？"
python .\trpg_cli.py rule-query "如何制作魔法物品？" --doc-ids "城主指南2024" --top-k 5
python .\trpg_cli.py compile-rules --doc-ids "城主指南2024" --output-path "notebooks/rules_summary.md"
```

Notebook 读写：

```powershell
python .\trpg_cli.py notebook-read gm human_player character_sheet
python .\trpg_cli.py notebook-search gm human_player events "遗迹"
python .\trpg_cli.py notebook-update gm human_player events "队伍抵达遗迹入口" --mode append
```

快速跑一段 playtest：

```powershell
python .\trpg_cli.py playtest --reset --turns 10
```

进入交互模式：

```powershell
python .\trpg_cli.py repl
```

## requirements 说明

当前 `requirements.txt` 已覆盖代码里的直接运行时依赖，包括：

- LangGraph / LangChain 运行时
- LlamaIndex 检索与 embedding 适配
- `openai` 客户端
- Chandra OCR
- FastAPI 相关依赖

其中 `openai` 被显式列出，是因为检索模块会直接导入该包，而不应该只依赖 `langchain-openai` 的传递依赖。