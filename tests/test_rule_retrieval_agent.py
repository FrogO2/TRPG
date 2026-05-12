from __future__ import annotations

import os
from pathlib import Path
import unittest
import warnings

from langchain_core.messages import HumanMessage

from src.agents.rule_retrieval import RuleRetrievalAgent


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_TEST_LOG_PATH = PROJECT_ROOT / "notebooks" / "history" / "debug" / "rule_retrieval_agent.live_test.log.md"
LIVE_BOOTSTRAP_LOG_PATH = PROJECT_ROOT / "notebooks" / "history" / "debug" / "rule_retrieval_agent.bootstrap_live_test.log.md"
LIVE_BOOTSTRAP_SUMMARY_PATH = PROJECT_ROOT / "notebooks" / "rules_summary.live_test.md"
LIVE_COMPRESSED_NOTES_PATH = PROJECT_ROOT / "notebooks" / "compressed_rule_notes.live_test.md"
LIVE_FULL_COMPRESSED_NOTES_PATH = PROJECT_ROOT / "notebooks" / "compressed_rule_notes.dmg2024.full.live_test.md"
LIVE_FULL_COMPRESSED_NOTES_COMPLETE_PATH = PROJECT_ROOT / "notebooks" / "compressed_rule_notes.dmg2024.full.complete.live_test.md"
LIVE_MAIN_MODEL_LOG_PATH = PROJECT_ROOT / "notebooks" / "history" / "debug" / "rule_retrieval_agent.main_model_integration.live_test.log.md"
LIVE_MAIN_MODEL_SUMMARY_PATH = PROJECT_ROOT / "notebooks" / "rules_summary.main_model_integration.live_test.md"
LIVE_MAIN_MODEL_COMPRESSED_LOG_PATH = PROJECT_ROOT / "notebooks" / "history" / "debug" / "rule_retrieval_agent.main_model_compression.live_test.log.md"
LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH = PROJECT_ROOT / "notebooks" / "rules_summary.dmg2024.main_model_compression.live_test.md"
TARGET_DOC_ID = "城主指南2024"


# Mock tests are intentionally commented out.
#
# from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
# from langchain_core.messages import AIMessage
#
#
# class BindableFakeMessagesListChatModel(FakeMessagesListChatModel):
#     def bind_tools(self, tools, *, tool_choice=None, **kwargs):
#         return self
#
#
# class RuleRetrievalAgentReactTest(unittest.TestCase):
#     def setUp(self) -> None:
#         available = RuleRetrievalAgent(llm=BindableFakeMessagesListChatModel(responses=[AIMessage(content="placeholder")])).list_available_doc_ids()
#         self.assertTrue(available, "expected at least one markdown document")
#         self.doc_id = available[0]
#
#     def test_answer_rule_query_uses_react_agent_and_logs_tool_calls(self) -> None:
#         model = BindableFakeMessagesListChatModel(
#             responses=[
#                 AIMessage(
#                     content="",
#                     tool_calls=[
#                         {
#                             "id": "call_1",
#                             "name": "search_rule_document",
#                             "args": {"doc_id": self.doc_id, "query": "长休", "top_k": 1},
#                         }
#                     ],
#                 ),
#                 AIMessage(content="结论：最相关段落表明长休相关恢复需要回看原文页码确认。\n依据：已检索到相关章节和页面。"),
#             ]
#         )
#
#         with tempfile.TemporaryDirectory() as temp_dir:
#             log_path = Path(temp_dir) / "rule_retrieval_agent.log.md"
#             agent = RuleRetrievalAgent(llm=model, log_path=log_path)
#             with warnings.catch_warnings():
#                 warnings.simplefilter("ignore")
#                 result = agent.answer_rule_query("长休会恢复什么？", doc_ids=[self.doc_id], top_k=1)
#
#             self.assertIn("结论：", result)
#             self.assertTrue(log_path.exists())
#             log_text = log_path.read_text(encoding="utf-8")
#             self.assertIn("search_rule_document", log_text)
#             self.assertIn("长休会恢复什么？", log_text)
#             self.assertIn("Result Summary", log_text)


@unittest.skipUnless(os.getenv("OPENAI_API_KEY"), "requires OPENAI_API_KEY for live model testing")
class RuleRetrievalAgentLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        available = RuleRetrievalAgent().list_available_doc_ids()
        if TARGET_DOC_ID not in available:
            raise unittest.SkipTest(f"expected markdown document {TARGET_DOC_ID!r}")
        cls.doc_id = TARGET_DOC_ID

    def setUp(self) -> None:
        LIVE_TEST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LIVE_TEST_LOG_PATH.exists():
            LIVE_TEST_LOG_PATH.unlink()
        if LIVE_BOOTSTRAP_LOG_PATH.exists():
            LIVE_BOOTSTRAP_LOG_PATH.unlink()
        if LIVE_BOOTSTRAP_SUMMARY_PATH.exists():
            LIVE_BOOTSTRAP_SUMMARY_PATH.unlink()
        if LIVE_COMPRESSED_NOTES_PATH.exists():
            LIVE_COMPRESSED_NOTES_PATH.unlink()
        if LIVE_MAIN_MODEL_LOG_PATH.exists():
            LIVE_MAIN_MODEL_LOG_PATH.unlink()
        if LIVE_MAIN_MODEL_SUMMARY_PATH.exists():
            LIVE_MAIN_MODEL_SUMMARY_PATH.unlink()
        if LIVE_MAIN_MODEL_COMPRESSED_LOG_PATH.exists():
            LIVE_MAIN_MODEL_COMPRESSED_LOG_PATH.unlink()
        if LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH.exists():
            LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH.unlink()

    def _load_first_n_blocks_for_doc(self, agent: RuleRetrievalAgent, n: int):
        original_load_blocks = agent._load_blocks
        selected_blocks = original_load_blocks(self.doc_id)[:n]
        self.assertEqual(len(selected_blocks), n, f"expected at least {n} blocks in document {self.doc_id!r}")

        def _load_selected_blocks(doc_id: str):
            if doc_id == self.doc_id:
                return selected_blocks
            return original_load_blocks(doc_id)

        agent._load_blocks = _load_selected_blocks
        return selected_blocks

    @staticmethod
    def _render_compressed_notes_markdown(doc_id: str, notes, *, source_blocks: int) -> str:
        rendered_lines = [f"# Compressed Rule Notes: {doc_id}", "", f"- source_blocks: {source_blocks}", ""]
        for note in notes:
            rendered_lines.extend(
                [
                    f"## {note['note_id']}",
                    "",
                    f"- doc_id: {note['doc_id']}",
                    f"- section_title: {note['section_title']}",
                    f"- page_range: {note['page_range']}",
                    f"- headings: {' > '.join(note['headings']) if note['headings'] else '(none)'}",
                    "",
                    note["summary"],
                    "",
                ]
            )
        return "\n".join(rendered_lines).strip() + "\n"

    @staticmethod
    def _render_complete_compressed_notes_markdown(doc_id: str, notes, *, source_blocks: int, summary_model: str) -> str:
        rendered_lines = [
            f"# Complete Compressed Rule Notes: {doc_id}",
            "",
            f"- source_blocks: {source_blocks}",
            f"- note_count: {len(notes)}",
            f"- summary_model: {summary_model}",
            "",
        ]
        for note in notes:
            rendered_lines.extend(
                [
                    f"## {note['note_id']}",
                    "",
                    f"- doc_id: {note['doc_id']}",
                    f"- section_title: {note['section_title']}",
                    f"- page_range: {note['page_range']}",
                    f"- pages: {', '.join(str(page) for page in note['pages'])}",
                    f"- headings: {' > '.join(note['headings']) if note['headings'] else '(none)'}",
                    "",
                    "### Summary",
                    "",
                    note["summary"],
                    "",
                ]
            )
        return "\n".join(rendered_lines).strip() + "\n"

    @staticmethod
    def _is_compressed_notes_file_complete(text: str) -> bool:
        return "- note_count:" in text and "- pages:" in text and "### Summary" in text

    def _bootstrap_prompt_text(self) -> str:
        return RuleRetrievalAgent(llm=object()).get_prompt_text("bootstrap").strip()

    def _ensure_full_compressed_notes_file(self) -> str:
        if LIVE_FULL_COMPRESSED_NOTES_PATH.exists() and LIVE_FULL_COMPRESSED_NOTES_COMPLETE_PATH.exists():
            return LIVE_FULL_COMPRESSED_NOTES_PATH.read_text(encoding="utf-8")

        agent = RuleRetrievalAgent()
        all_blocks = agent._load_blocks(self.doc_id)
        self.assertTrue(all_blocks, f"expected at least one block in document {self.doc_id!r}")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            notes = agent._build_compressed_rule_notes([self.doc_id])

        LIVE_FULL_COMPRESSED_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
        markdown = self._render_compressed_notes_markdown(self.doc_id, notes, source_blocks=len(all_blocks))
        LIVE_FULL_COMPRESSED_NOTES_PATH.write_text(markdown, encoding="utf-8")
        complete_markdown = self._render_complete_compressed_notes_markdown(
            self.doc_id,
            notes,
            source_blocks=len(all_blocks),
            summary_model=agent._model_name(agent.summary_llm),
        )
        LIVE_FULL_COMPRESSED_NOTES_COMPLETE_PATH.write_text(complete_markdown, encoding="utf-8")
        return markdown

    def test_live_build_compressed_rule_notes_uses_summary_model(self) -> None:
        agent = RuleRetrievalAgent()
        self._load_first_n_blocks_for_doc(agent, 100)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            notes = agent._build_compressed_rule_notes([self.doc_id])

        LIVE_COMPRESSED_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIVE_COMPRESSED_NOTES_PATH.write_text(
            self._render_compressed_notes_markdown(self.doc_id, notes, source_blocks=100),
            encoding="utf-8",
        )

        self.assertTrue(notes)
        first_note = notes[0]
        self.assertEqual(first_note["doc_id"], self.doc_id)
        self.assertTrue(first_note["note_id"].startswith(f"{self.doc_id}::note::"))
        self.assertTrue(first_note["summary"].strip())
        self.assertIn("page_range", first_note)
        self.assertIn("section_title", first_note)
        self.assertTrue(LIVE_COMPRESSED_NOTES_PATH.exists())
        output_text = LIVE_COMPRESSED_NOTES_PATH.read_text(encoding="utf-8")
        self.assertIn("source_blocks: 100", output_text)
        self.assertIn(first_note["note_id"], output_text)
        self.assertEqual(
            agent._model_name(agent.summary_llm),
            os.getenv("TRPG_RULE_SUMMARIZER_MODEL") or "qwen3.5-flash",
        )

    def test_live_build_compressed_rule_notes_for_full_dmg2024_and_write_markdown(self) -> None:
        output_text = self._ensure_full_compressed_notes_file()
        self.assertTrue(LIVE_FULL_COMPRESSED_NOTES_PATH.exists())
        self.assertTrue(LIVE_FULL_COMPRESSED_NOTES_COMPLETE_PATH.exists())
        self.assertIn("source_blocks:", output_text)
        self.assertIn("城主指南2024::note::1", output_text)
        self.assertIn("##", output_text)
        complete_text = LIVE_FULL_COMPRESSED_NOTES_COMPLETE_PATH.read_text(encoding="utf-8")
        self.assertTrue(self._is_compressed_notes_file_complete(complete_text))

    def test_live_main_model_further_compresses_full_dmg2024_notes(self) -> None:
        compressed_notes_text = self._ensure_full_compressed_notes_file()
        complete_compressed_notes_text = LIVE_FULL_COMPRESSED_NOTES_COMPLETE_PATH.read_text(encoding="utf-8")
        agent = RuleRetrievalAgent(log_path=LIVE_MAIN_MODEL_COMPRESSED_LOG_PATH)
        base_prompt = self._bootstrap_prompt_text()
        source_text = complete_compressed_notes_text if self._is_compressed_notes_file_complete(complete_compressed_notes_text) else compressed_notes_text
        prompt = "\n\n".join(
            [
                base_prompt,
                "补充说明：你现在不直接阅读原始规则书，而是基于已经由小模型压缩过的《城主指南2024》规则笔记继续压缩。",
                "请延续同样的写作目标和取舍标准，只输出更短、更适合 GM 快速执行的摘要。",
                "保持精简，优先保留强制流程、高频裁定、重要限制和待复核点，不要重复同义内容。",
                "如果压缩笔记里信息已经足够，不要要求回看原文。",
                "以下是可复用的压缩笔记文件内容：",
                source_text,
            ]
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            response = agent.llm.invoke([HumanMessage(content=prompt)])

        summary_text = str(getattr(response, "content", response)).strip()
        LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH.write_text(summary_text + "\n", encoding="utf-8")

        agent._append_log(
            mode="main-model-compression",
            prompt_name="inline:test_live_main_model_further_compresses_full_dmg2024_notes",
            prompt_text=prompt,
            invocation_source="test:live_main_model_further_compresses_full_dmg2024_notes",
            inputs={
                "doc_id": self.doc_id,
                "compressed_notes_path": str(LIVE_FULL_COMPRESSED_NOTES_PATH),
                "complete_compressed_notes_path": str(LIVE_FULL_COMPRESSED_NOTES_COMPLETE_PATH),
                "output_path": str(LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH),
            },
            messages=[HumanMessage(content=prompt), response],
            result_summary={
                "output_path": str(LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH),
                "final_response": summary_text,
            },
        )

        self.assertTrue(summary_text)
        self.assertTrue(LIVE_MAIN_MODEL_COMPRESSED_SUMMARY_PATH.exists())
        self.assertIn("#", summary_text)
        self.assertTrue(LIVE_MAIN_MODEL_COMPRESSED_LOG_PATH.exists())
        log_text = LIVE_MAIN_MODEL_COMPRESSED_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn("test:live_main_model_further_compresses_full_dmg2024_notes", log_text)
        self.assertIn("main-model-compression", log_text)

   
    def test_live_main_model_integrates_compressed_notes(self) -> None:
        note_agent = RuleRetrievalAgent()
        self._load_first_n_blocks_for_doc(note_agent, 100)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            notes = note_agent._build_compressed_rule_notes([self.doc_id])

        LIVE_COMPRESSED_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIVE_COMPRESSED_NOTES_PATH.write_text(
            self._render_compressed_notes_markdown(self.doc_id, notes, source_blocks=100),
            encoding="utf-8",
        )

        agent = RuleRetrievalAgent(log_path=LIVE_MAIN_MODEL_LOG_PATH)
        self._load_first_n_blocks_for_doc(agent, 100)
        agent._build_compressed_rule_notes = lambda doc_ids: notes

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = agent.compile_rules_summary(
                doc_ids=[self.doc_id],
                output_path=LIVE_MAIN_MODEL_SUMMARY_PATH,
                invocation_source="test:live_main_model_integrates_compressed_notes",
            )

        self.assertEqual(result["output_path"], str(LIVE_MAIN_MODEL_SUMMARY_PATH))
        self.assertEqual(result["compressed_note_count"], len(notes))
        self.assertTrue(LIVE_MAIN_MODEL_SUMMARY_PATH.exists())
        summary_text = LIVE_MAIN_MODEL_SUMMARY_PATH.read_text(encoding="utf-8")
        self.assertTrue(summary_text.strip())
        self.assertIn("#", summary_text)

        self.assertTrue(LIVE_MAIN_MODEL_LOG_PATH.exists())
        log_text = LIVE_MAIN_MODEL_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn("test:live_main_model_integrates_compressed_notes", log_text)
        self.assertIn("compressed_note_count", log_text)
        self.assertIn("list_compressed_rule_notes", log_text)
        self.assertIn("write_rules_summary", log_text)

    def test_live_compile_rules_summary_writes_summary_and_log(self) -> None:
        agent = RuleRetrievalAgent(log_path=LIVE_BOOTSTRAP_LOG_PATH)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = agent.compile_rules_summary(
                doc_ids=[self.doc_id],
                output_path=LIVE_BOOTSTRAP_SUMMARY_PATH,
                invocation_source="test:live_compile_rules_summary",
            )

        self.assertEqual(result["output_path"], str(LIVE_BOOTSTRAP_SUMMARY_PATH))
        self.assertTrue(LIVE_BOOTSTRAP_SUMMARY_PATH.exists())
        summary_text = LIVE_BOOTSTRAP_SUMMARY_PATH.read_text(encoding="utf-8")
        self.assertTrue(summary_text.strip())
        self.assertIn("#", summary_text)

        self.assertTrue(LIVE_BOOTSTRAP_LOG_PATH.exists())
        log_text = LIVE_BOOTSTRAP_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn("### Prompt Snapshot", log_text)
        self.assertIn("### Message Trace", log_text)
        self.assertIn("### Result Summary", log_text)
        self.assertIn("test:live_compile_rules_summary", log_text)
        self.assertIn("write_rules_summary", log_text)

    # def test_live_answer_rule_query_writes_auditable_log(self) -> None:
    #     agent = RuleRetrievalAgent(log_path=LIVE_TEST_LOG_PATH)
    #     with warnings.catch_warnings():
    #         warnings.simplefilter("ignore")
    #         result = agent.answer_rule_query(
    #             "请基于文档给出一个需要回看原文确认的规则点，并说明你引用了哪些证据。",
    #             doc_ids=[self.doc_id],
    #             top_k=5,
    #             invocation_source="test:live_answer_rule_query",
    #         )

    #     self.assertTrue(result.strip())
    #     self.assertTrue(LIVE_TEST_LOG_PATH.exists())
    #     log_text = LIVE_TEST_LOG_PATH.read_text(encoding="utf-8")
    #     self.assertIn("### Prompt Snapshot", log_text)
    #     self.assertIn("### Message Trace", log_text)
    #     self.assertIn("### Result Summary", log_text)
    #     self.assertIn("test:live_answer_rule_query", log_text)
    #     self.assertRegex(log_text, r"search_rule_document|lookup_rule_index|read_rule_page|read_rule_section")


if __name__ == "__main__":
    unittest.main()