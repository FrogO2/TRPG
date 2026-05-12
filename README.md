# TRPG

一个本地运行的 TRPG 多代理实验项目，包含 GM / 玩家对话运行时、规则检索代理、命令行入口。

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

运行带 LLM 的 CLI 命令前，至少需要设置一个可用的 API key。最简单的方式是设置环境变量 `OPENAI_API_KEY`。

如果你还没有可用 key，建议直接去阿里云百炼注册：

1. 打开 https://bailian.console.aliyun.com/
2. 注册或登录阿里云账号
3. 在百炼控制台创建并复制 API Key并设置在环境变量中。

项目默认使用`deepseek-v4-flash`模型，阿里云百炼拥有一些免费额度供测试。

## CLI 用法

CLI 入口是 `trpg_cli.py`。


Quick Start：

```powershell
python .\trpg_cli.py playtest --reset --turns 10
```

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

进入交互模式：

```powershell
python .\trpg_cli.py repl
```
