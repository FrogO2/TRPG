#!/usr/bin/env python3
"""CLI entrypoint for testing the GM-driven TRPG dialogue runtime."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import Any

from src.agents import DialogueCoordinator, GMAgent, HumanPlayer, LLMPlayerAgent
from src.agents.runtime_common import invoke_tool
from src.tools.tools import (
    PLAYER_IDS,
    advance_turn,
    answer_rule_query,
    approve_interrupt,
    append_dialogue_history,
    compile_rules_summary,
    get_upcoming_speakers,
    initialize_dialogue_state,
    jump_player_notebook,
    nominate_next_speaker,
    read_dialogue_state,
    read_player_notebook,
    request_interrupt,
    search_player_notebook,
    set_temporary_speaking_order,
    summarize_dialogue_history,
    update_player_notebook,
)


def _dialogue_state() -> dict[str, Any]:
    return json.loads(invoke_tool(read_dialogue_state))


def _upcoming_order(lookahead: int = 5) -> str:
    return invoke_tool(get_upcoming_speakers, lookahead=lookahead)


def _shared_context(extra_context: str = "", *, window: int = 12) -> str:
    parts: list[str] = []
    summary = invoke_tool(summarize_dialogue_history, window=window)
    if summary.strip() and summary.strip() != "No dialogue history yet.":
        parts.append(summary.strip())
    if extra_context.strip():
        parts.append(extra_context.strip())
    return "\n\n".join(parts)


def _require_active_speaker(expected: str) -> dict[str, Any]:
    state = _dialogue_state()
    actual = state.get("active_speaker")
    if actual != expected:
        raise RuntimeError(f"Current active speaker is {actual!r}, not {expected!r}.")
    return state


def _print_result(text: str) -> None:
    print(text.rstrip())


def _default_gm_instruction(turn_number: int) -> str:
    return (
        f"这是第 {turn_number} 个对话回合。"
        "请基于当前共享历史、规则摘要、战役文本与 notebook，像真实 GM 一样推进场景，"
        "给出世界反馈、必要裁定，并把话题明确交给下一位合适的玩家。"
    )


def _default_player_instruction(actor_id: str, turn_number: int) -> str:
    return (
        f"这是 {actor_id} 的第 {turn_number} 个对话回合。"
        "请基于当前共享历史、你的个人 notebook、玩家手册与当前场景，"
        "以真实玩家的口吻给出自然、可执行的发言或行动意图。"
    )


def _run_gm_turn(*, message: str, context: str = "", auto_advance: bool = True) -> tuple[str, str]:
    _require_active_speaker("gm")
    gm = GMAgent()
    reply = gm.take_turn(
        message,
        active_speaker="gm",
        upcoming_order=_upcoming_order(),
        extra_context=_shared_context(context),
    )
    invoke_tool(append_dialogue_history, speaker_id="gm", message=reply)
    advance_message = invoke_tool(advance_turn) if auto_advance else ""
    return reply, advance_message


def _run_player_turn(actor_id: str, *, message: str = "", context: str = "", auto_advance: bool = True) -> tuple[str, str]:
    _require_active_speaker(actor_id)
    player = LLMPlayerAgent(actor_id)
    prompt = message or _default_player_instruction(actor_id, 0)
    reply = player.take_turn(
        prompt,
        active_speaker=actor_id,
        upcoming_order=_upcoming_order(),
        extra_context=_shared_context(context),
    )
    invoke_tool(append_dialogue_history, speaker_id=actor_id, message=reply)
    advance_message = invoke_tool(advance_turn) if auto_advance else ""
    return reply, advance_message


def _run_human_turn(*, message: str = "", auto_advance: bool = True) -> tuple[str, str]:
    _require_active_speaker("human_player")
    human = HumanPlayer()
    submitted_message = message.strip()
    if not submitted_message:
        print("\n[Human Turn]")
        print(human.get_prompt_text().strip())
        print()
        submitted_message = input("human_player> ").strip()
    result = human.submit_turn(submitted_message)
    advance_message = invoke_tool(advance_turn) if auto_advance else ""
    return result, advance_message


def cmd_init(args: argparse.Namespace) -> int:
    order_csv = ",".join(args.order) if args.order else ""
    _print_result(invoke_tool(initialize_dialogue_state, default_order_csv=order_csv))
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    state = _dialogue_state()
    if args.pretty:
        _print_result(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        _print_result(json.dumps(state, ensure_ascii=False))
    return 0


def cmd_upcoming(args: argparse.Namespace) -> int:
    _print_result(_upcoming_order(args.lookahead))
    return 0


def cmd_set_order(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            set_temporary_speaking_order,
            actor_id="gm",
            order_csv=",".join(args.order),
            reason=args.reason,
        )
    )
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    _print_result(invoke_tool(advance_turn))
    return 0


def cmd_gm_turn(args: argparse.Namespace) -> int:
    reply, advance_message = _run_gm_turn(message=args.message, context=args.context, auto_advance=not args.no_advance)
    _print_result(reply)
    if advance_message:
        print()
        _print_result(advance_message)
    return 0


def cmd_player_turn(args: argparse.Namespace) -> int:
    actor_id = args.actor_id
    message = args.message or "请基于当前共享历史、你的个人 notebook 和记忆，以玩家身份给出本回合的发言或行动。"
    reply, advance_message = _run_player_turn(
        actor_id,
        message=message,
        context=args.context,
        auto_advance=not args.no_advance,
    )
    _print_result(reply)
    if advance_message:
        print()
        _print_result(advance_message)
    return 0


def cmd_human_turn(args: argparse.Namespace) -> int:
    reply, advance_message = _run_human_turn(message=args.message, auto_advance=not args.no_advance)
    _print_result(reply)
    if advance_message:
        print()
        _print_result(advance_message)
    return 0


def cmd_playtest(args: argparse.Namespace) -> int:
    if args.reset:
        order_csv = ",".join(args.order) if args.order else ""
        _print_result(invoke_tool(initialize_dialogue_state, default_order_csv=order_csv, reset_history=True))
        print()

    for turn_number in range(1, args.turns + 1):
        state = _dialogue_state()
        active_speaker = state.get("active_speaker", "")
        print(f"\n=== Turn {turn_number}/{args.turns} ===")
        print(f"Active speaker: {active_speaker}")
        print(f"Upcoming: {_upcoming_order()}\n")

        if active_speaker == "gm":
            reply, advance_message = _run_gm_turn(
                message=_default_gm_instruction(turn_number),
                context=args.context,
                auto_advance=True,
            )
            print("[GM]")
            _print_result(reply)
        elif active_speaker == "human_player":
            reply, advance_message = _run_human_turn(auto_advance=True)
            print("[Human Result]")
            _print_result(reply)
        elif active_speaker in PLAYER_IDS:
            reply, advance_message = _run_player_turn(
                active_speaker,
                message=_default_player_instruction(active_speaker, turn_number),
                context=args.context,
                auto_advance=True,
            )
            print(f"[{active_speaker}]")
            _print_result(reply)
        else:
            raise RuntimeError(f"Unknown active speaker: {active_speaker!r}")

        if advance_message:
            print()
            _print_result(advance_message)

    print("\n=== Playtest Complete ===")
    _print_result(invoke_tool(summarize_dialogue_history, window=min(max(1, args.summary_window), args.turns)))
    return 0


def cmd_request_interrupt(args: argparse.Namespace) -> int:
    _print_result(invoke_tool(request_interrupt, actor_id=args.actor_id, reason=args.reason))
    return 0


def cmd_approve_interrupt(args: argparse.Namespace) -> int:
    _print_result(invoke_tool(approve_interrupt, actor_id="gm", speaker_id=args.actor_id))
    return 0


def cmd_nominate_next(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            nominate_next_speaker,
            actor_id=args.actor_id,
            next_speaker=args.next_speaker,
            reason=args.reason,
        )
    )
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    _print_result(invoke_tool(summarize_dialogue_history, window=args.window))
    return 0


def cmd_notebook_read(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            read_player_notebook,
            actor_id=args.actor_id,
            owner_id=args.owner_id,
            notebook_name=args.notebook_name,
        )
    )
    return 0


def cmd_notebook_search(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            search_player_notebook,
            actor_id=args.actor_id,
            owner_id=args.owner_id,
            notebook_name=args.notebook_name,
            query=args.query,
        )
    )
    return 0


def cmd_notebook_jump(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            jump_player_notebook,
            actor_id=args.actor_id,
            owner_id=args.owner_id,
            notebook_name=args.notebook_name,
            heading=args.heading,
        )
    )
    return 0


def cmd_notebook_update(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            update_player_notebook,
            actor_id=args.actor_id,
            owner_id=args.owner_id,
            notebook_name=args.notebook_name,
            content=args.content,
            mode=args.mode,
            heading=args.heading,
        )
    )
    return 0


def cmd_rule_query(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            answer_rule_query,
            query=args.query,
            doc_ids=args.doc_ids,
            top_k=args.top_k,
        )
    )
    return 0


def cmd_compile_rules(args: argparse.Namespace) -> int:
    _print_result(
        invoke_tool(
            compile_rules_summary,
            doc_ids=args.doc_ids,
            output_path=args.output_path,
        )
    )
    return 0


def cmd_repl(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    print("TRPG CLI REPL. Type 'help' for commands, 'exit' to quit.")
    while True:
        try:
            line = input("trpg> ").strip()
        except EOFError:
            print()
            return 0
        if not line:
            continue
        if line in {"exit", "quit"}:
            return 0
        if line == "help":
            parser.print_help()
            continue
        try:
            repl_args = parser.parse_args(shlex.split(line))
        except SystemExit:
            continue
        if repl_args.command == "repl":
            print("Already inside REPL.")
            continue
        try:
            return_code = run_command(repl_args, parser)
            if return_code:
                print(f"Command exited with code {return_code}")
        except Exception as exc:
            print(f"Error: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI for the GM-driven TRPG dialogue runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize dialogue state and notebook placeholders")
    init_parser.add_argument("order", nargs="*", help="Optional custom speaker order")

    state_parser = subparsers.add_parser("state", help="Print dialogue state")
    state_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    upcoming_parser = subparsers.add_parser("upcoming", help="Show upcoming speakers")
    upcoming_parser.add_argument("--lookahead", type=int, default=5)

    set_order_parser = subparsers.add_parser("set-order", help="Set a temporary GM-controlled speaking order")
    set_order_parser.add_argument("order", nargs="+", help="Temporary player order")
    set_order_parser.add_argument("--reason", default="")

    subparsers.add_parser("advance", help="Advance to the next speaker")

    gm_turn_parser = subparsers.add_parser("gm-turn", help="Run the GM LLM for the current GM turn")
    gm_turn_parser.add_argument("message", help="Instruction for the GM turn")
    gm_turn_parser.add_argument("--context", default="", help="Additional runtime context")
    gm_turn_parser.add_argument("--no-advance", action="store_true", help="Do not auto-advance after the turn")

    player_turn_parser = subparsers.add_parser("player-turn", help="Run one LLM player turn")
    player_turn_parser.add_argument("actor_id", choices=[actor_id for actor_id in PLAYER_IDS if actor_id != "human_player"])
    player_turn_parser.add_argument("message", nargs="?", default="")
    player_turn_parser.add_argument("--context", default="", help="Additional runtime context")
    player_turn_parser.add_argument("--no-advance", action="store_true", help="Do not auto-advance after the turn")

    human_turn_parser = subparsers.add_parser("human-turn", help="Submit the human player's turn")
    human_turn_parser.add_argument("message", nargs="?", default="")
    human_turn_parser.add_argument("--no-advance", action="store_true", help="Do not auto-advance after the turn")

    interrupt_parser = subparsers.add_parser("request-interrupt", help="Request an interrupt for a player")
    interrupt_parser.add_argument("actor_id", choices=PLAYER_IDS)
    interrupt_parser.add_argument("--reason", default="")

    approve_parser = subparsers.add_parser("approve-interrupt", help="Approve a pending interrupt as GM")
    approve_parser.add_argument("actor_id", choices=PLAYER_IDS)

    nominate_parser = subparsers.add_parser("nominate-next", help="Nominate the next speaker")
    nominate_parser.add_argument("actor_id", choices=[*PLAYER_IDS, "gm"])
    nominate_parser.add_argument("next_speaker", choices=[*PLAYER_IDS, "gm"])
    nominate_parser.add_argument("--reason", default="")

    history_parser = subparsers.add_parser("history", help="Print rolling shared dialogue summary")
    history_parser.add_argument("--window", type=int, default=20)

    notebook_read_parser = subparsers.add_parser("notebook-read", help="Read a player notebook with ACL checks")
    notebook_read_parser.add_argument("actor_id")
    notebook_read_parser.add_argument("owner_id")
    notebook_read_parser.add_argument("notebook_name", choices=["character_sheet", "events", "private_notes"])

    notebook_search_parser = subparsers.add_parser("notebook-search", help="Search a player notebook")
    notebook_search_parser.add_argument("actor_id")
    notebook_search_parser.add_argument("owner_id")
    notebook_search_parser.add_argument("notebook_name", choices=["character_sheet", "events", "private_notes"])
    notebook_search_parser.add_argument("query")

    notebook_jump_parser = subparsers.add_parser("notebook-jump", help="Read one heading section from a player notebook")
    notebook_jump_parser.add_argument("actor_id")
    notebook_jump_parser.add_argument("owner_id")
    notebook_jump_parser.add_argument("notebook_name", choices=["character_sheet", "events", "private_notes"])
    notebook_jump_parser.add_argument("heading")

    notebook_update_parser = subparsers.add_parser("notebook-update", help="Update a player notebook")
    notebook_update_parser.add_argument("actor_id")
    notebook_update_parser.add_argument("owner_id")
    notebook_update_parser.add_argument("notebook_name", choices=["character_sheet", "events", "private_notes"])
    notebook_update_parser.add_argument("content")
    notebook_update_parser.add_argument("--mode", default="append", choices=["append", "replace", "replace_heading"])
    notebook_update_parser.add_argument("--heading", default="")

    rule_query_parser = subparsers.add_parser("rule-query", help="Ask the Rule Retreival Agent a rules question")
    rule_query_parser.add_argument("query")
    rule_query_parser.add_argument("--doc-ids", default="")
    rule_query_parser.add_argument("--top-k", type=int, default=5)

    compile_rules_parser = subparsers.add_parser("compile-rules", help="Build a GM-facing rules summary")
    compile_rules_parser.add_argument("--doc-ids", default="")
    compile_rules_parser.add_argument("--output-path", default="")

    playtest_parser = subparsers.add_parser("playtest", help="Run an interactive multi-turn CLI playtest")
    playtest_parser.add_argument("--turns", type=int, default=30, help="Number of dialogue turns to simulate")
    playtest_parser.add_argument("--reset", action="store_true", help="Reinitialize dialogue state before the playtest")
    playtest_parser.add_argument("--context", default="", help="Additional shared context passed into AI turns")
    playtest_parser.add_argument("--summary-window", type=int, default=30, help="Dialogue history lines to show after the playtest")
    playtest_parser.add_argument("order", nargs="*", help="Optional custom order used with --reset")

    subparsers.add_parser("repl", help="Start interactive CLI mode")
    return parser


def run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "init":
        return cmd_init(args)
    if args.command == "state":
        return cmd_state(args)
    if args.command == "upcoming":
        return cmd_upcoming(args)
    if args.command == "set-order":
        return cmd_set_order(args)
    if args.command == "advance":
        return cmd_advance(args)
    if args.command == "gm-turn":
        return cmd_gm_turn(args)
    if args.command == "player-turn":
        return cmd_player_turn(args)
    if args.command == "human-turn":
        return cmd_human_turn(args)
    if args.command == "request-interrupt":
        return cmd_request_interrupt(args)
    if args.command == "approve-interrupt":
        return cmd_approve_interrupt(args)
    if args.command == "nominate-next":
        return cmd_nominate_next(args)
    if args.command == "history":
        return cmd_history(args)
    if args.command == "notebook-read":
        return cmd_notebook_read(args)
    if args.command == "notebook-search":
        return cmd_notebook_search(args)
    if args.command == "notebook-jump":
        return cmd_notebook_jump(args)
    if args.command == "notebook-update":
        return cmd_notebook_update(args)
    if args.command == "rule-query":
        return cmd_rule_query(args)
    if args.command == "compile-rules":
        return cmd_compile_rules(args)
    if args.command == "playtest":
        return cmd_playtest(args)
    if args.command == "repl":
        return cmd_repl(args, parser)
    parser.error(f"Unknown command: {args.command}")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_command(args, parser)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())