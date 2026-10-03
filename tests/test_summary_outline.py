import ast
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "app.py"


class SummaryOutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        wanted = {"fmt_ts", "clean_uploaded_transcript",
                  "summary_transcript", "parse_summary_outline"}
        nodes = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
        namespace = {"re": re, "clean_uploaded_transcript": lambda text: text}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), "exec"), namespace)
        cls.clean_uploaded_transcript = staticmethod(namespace["clean_uploaded_transcript"])
        cls.summary_transcript = staticmethod(namespace["summary_transcript"])
        cls.parse_summary_outline = staticmethod(namespace["parse_summary_outline"])

        app_node = next(node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == "App")
        summary_method = next(node for node in app_node.body
                              if isinstance(node, ast.FunctionDef)
                              and node.name == "_cloud_summary_bg")
        start_method = next(node for node in app_node.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name == "cloud_summary")
        cls.method_namespace = {
            "re": re,
            "json": json,
            "clean_uploaded_transcript": cls.clean_uploaded_transcript,
            "summary_transcript": cls.summary_transcript,
            "parse_summary_outline": cls.parse_summary_outline,
            "cloud_think_off_for": lambda *_args, **_kwargs: None,
            "MD_RULES": "\n输出格式：只用 Markdown；不要 HTML 标签。",
            "Cancelled": type("Cancelled", (Exception,), {}),
        }
        exec(compile(ast.Module(body=[summary_method], type_ignores=[]), str(APP), "exec"),
             cls.method_namespace)
        cls.cloud_summary_bg = staticmethod(cls.method_namespace["_cloud_summary_bg"])
        cls.start_namespace = {
            "json": json,
            "cloud_cfg": lambda: {"enable": True},
        }
        exec(compile(ast.Module(body=[start_method], type_ignores=[]), str(APP), "exec"),
             cls.start_namespace)
        cls.start_summary = staticmethod(cls.start_namespace["cloud_summary"])

    def run_summary_job(self, responses, segments=None, cfg=None, capture_options=False):
        calls = []
        options = []

        def fake_cloud_chat(call_cfg, messages, **kwargs):
            calls.append(messages)
            options.append((dict(call_cfg), kwargs))
            response = responses[len(calls) - 1]
            if isinstance(response, Exception):
                raise response
            return response

        class DummyApp:
            def stage(self, *_args, **_kwargs):
                pass

            def _write_md(self, *_args, **_kwargs):
                pass

            def emit(self, **_kwargs):
                pass

        self.method_namespace["cloud_chat"] = fake_cloud_chat
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            session = session_dir / "session.json"
            session.write_text(json.dumps({"segments": segments or [
                {"t": 0, "text": "开场"},
                {"t": 65, "spk": "S02", "text": "第二部分"},
            ]}, ensure_ascii=False), encoding="utf-8")
            self.cloud_summary_bg(DummyApp(), session_dir, cfg or {
                "provider": "test", "model": "test-model", "chat_think": True,
            })
            saved = json.loads(session.read_text(encoding="utf-8"))
        return (calls, saved, options) if capture_options else (calls, saved)

    def test_summary_and_outline_receive_the_complete_transcript(self):
        tail = "Tav 后半段的独立讲解与回归逻辑"
        calls, _saved = self.run_summary_job([
            "# 全篇概括\n\n完整摘要",
            "<outline>\n[00:00] H1 全文主题\n[20:01] H2 后半段\n</outline>",
        ], segments=[
            {"t": 0, "text": "前段内容 " + "连续讲解 " * 3000},
            {"t": 1201, "text": tail},
        ])

        self.assertIn(tail, calls[0][1]["content"])
        self.assertIn(tail, calls[1][1]["content"])

    def test_summary_upload_drops_document_title_and_previous_summary(self):
        calls, _saved = self.run_summary_job([
            "# 新摘要\n\n正文摘要",
            "<outline>\n[00:05] H1 正文主题\n</outline>",
        ], segments=[
            {"t": 0, "text": "# 旧文稿标题"},
            {"t": 5, "text": "正文内容"},
            {"t": 10, "text": "## 摘要（云端生成）"},
            {"t": 15, "text": "# 旧错误标题\n旧错误摘要"},
        ])

        self.assertEqual(calls[0][1]["content"], "正文内容")
        self.assertEqual(calls[1][1]["content"], "[00:05] 正文内容")
        self.assertNotIn("旧文稿标题", calls[0][1]["content"])
        self.assertNotIn("旧错误摘要", calls[1][1]["content"])

    def test_summary_and_outline_use_independent_model_requests(self):
        calls, saved = self.run_summary_job([
            "# 全篇概括\n\n一句话主题\n\n- 关键结论",
            "<outline>\n[00:00] H1 开场主题\n[01:05] H2 第二部分\n</outline>",
        ])

        self.assertEqual(len(calls), 2)
        summary_system = calls[0][0]["content"]
        outline_system = calls[1][0]["content"]
        self.assertIn("保留说话人区分与关键结论", summary_system)
        self.assertIn("只输出摘要本身", summary_system)
        self.assertNotIn("L1", summary_system)
        self.assertEqual(calls[0][1]["content"], "开场 第二部分")
        self.assertIn("H1", outline_system)
        self.assertIn("H2", outline_system)
        self.assertIn("H3", outline_system)
        self.assertIn("唯一可解析的目录协议", outline_system)
        self.assertIn("H1/H2/H3 层级前缀必须保留", outline_system)
        self.assertIn("不得输出没有层级前缀的时间戳行", outline_system)
        self.assertNotIn("L1", outline_system)
        self.assertNotIn("L2", outline_system)
        self.assertNotIn("L3", outline_system)
        self.assertIn("H3 是可选层级", outline_system)
        self.assertIn("帮助用户快速定位", outline_system)
        self.assertIn("每个 H2 下可以生成多个 H3，也可以不生成", outline_system)
        self.assertIn("不要把每个细节都变成 H3", outline_system)
        self.assertNotIn("最多生成 1 个 H3", outline_system)
        self.assertNotIn("H3 总数不超过 30 条", outline_system)
        self.assertNotIn("逐一生成 H3", outline_system)
        self.assertIn("知识对象或核心议题", outline_system)
        self.assertIn("通读全文直到结尾", outline_system)
        self.assertIn("同一知识对象的定义、组成、属性、原理、象征、应用、比较和案例", outline_system)
        self.assertIn("不要只生成开头部分", outline_system)
        self.assertNotIn("Shin", outline_system)
        self.assertNotIn("Tav", outline_system)
        self.assertNotIn("塔罗", outline_system)
        self.assertIn("第一条必须是 H1", outline_system)
        self.assertIn("H3 必须归属于前面的 H2", outline_system)
        self.assertNotIn("一句话主题", outline_system)
        self.assertNotIn("不要 HTML 标签", outline_system)
        self.assertEqual(
            calls[1][1]["content"],
            "[00:00] 开场\n[01:05] S02｜第二部分",
        )
        self.assertEqual(saved["summary"], "# 全篇概括\n\n一句话主题\n\n- 关键结论")
        self.assertEqual(saved["outline"], [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_summary_job_saves_a_timestamped_outline_without_level_markers(self):
        _calls, saved = self.run_summary_job([
            "# 全篇概括\n\n一句话主题",
            "<outline>\n[00:00] 开场主题\n[01:05] 第二部分\n</outline>",
        ])

        self.assertNotIn("summary_error", saved)
        self.assertEqual(saved["outline"], [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_summary_and_outline_use_their_model_and_thinking_preference(self):
        think_args = []
        self.method_namespace["cloud_think_off_for"] = (
            lambda *args: think_args.append(args) or not args[2])
        try:
            _calls, _saved, options = self.run_summary_job([
                "# 全篇概括\n\n一句话主题",
                "<outline>\n[00:00] H1 开场主题\n</outline>",
            ], cfg={
                "provider": "test", "model": "refine-model", "chat_think": True,
                "summary_model": "summary-model", "summary_think": False,
                "summary_prompt": "额外保留行动项",
            }, capture_options=True)
        finally:
            self.method_namespace["cloud_think_off_for"] = lambda *_args, **_kwargs: None

        self.assertEqual([cfg["model"] for cfg, _kwargs in options],
                         ["summary-model", "summary-model"])
        self.assertEqual([kwargs["think_off"] for _cfg, kwargs in options],
                         [True, True])
        self.assertEqual(think_args, [("test", "summary-model", False)])
        self.assertTrue(all("额外保留行动项" in messages[0]["content"]
                            for messages in _calls))

    def test_summary_and_outline_are_saved_only_after_both_requests_succeed(self):
        _calls, saved = self.run_summary_job([
            "# 已生成但不应单独保存",
            RuntimeError("标题生成失败"),
        ])

        self.assertNotIn("summary", saved)
        self.assertNotIn("outline", saved)
        self.assertEqual(saved["summary_error"], "标题生成失败")

    def test_invalid_outline_error_reports_only_response_shape(self):
        _calls, saved = self.run_summary_job([
            "# 摘要\n\n一句话主题",
            "模型解释文字，没有目录行",
        ])

        self.assertIn("回复", saved["summary_error"])
        self.assertIn("时间戳", saved["summary_error"])
        self.assertIn("层级标记", saved["summary_error"])
        self.assertNotIn("模型解释文字", saved["summary_error"])

    def test_regeneration_allows_an_existing_summary_to_enter_the_queue(self):
        class DummyApp:
            state = "idle"
            progs = {}

            def _job_begin(self, sid, kind, state):
                self.started = (sid, kind, state)

            def _enqueue(self, sid, queue, fn):
                self.enqueued = (sid, queue, fn)

            def _cloud_summary_bg(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            project = sessions / "existing"
            project.mkdir()
            (project / "session.json").write_text(json.dumps({
                "segments": [{"text": "一"}, {"text": "二"}, {"text": "三"}],
                "summary": "旧摘要",
                "outline": [{"t": 0, "level": 2, "title": "旧标题"}],
            }, ensure_ascii=False), encoding="utf-8")
            self.start_namespace["SESSIONS_DIR"] = sessions
            app = DummyApp()

            with self.assertRaisesRegex(RuntimeError, "已有 AI 摘要"):
                self.start_summary(app, "existing")
            result = self.start_summary(app, "existing", True)

        self.assertEqual(result, {"ok": True, "id": "existing"})
        self.assertEqual(app.started, ("existing", "summary", "wait"))
        self.assertEqual(app.enqueued[:2], ("existing", "cloud"))

    def test_timestamped_transcript_keeps_model_sections_grounded_in_real_segments(self):
        segments = [
            {"t": 0, "text": "开场"},
            {"t": 65, "spk": "S02", "text": "第二部分"},
        ]

        self.assertEqual(
            self.summary_transcript(segments),
            "[00:00] 开场\n[01:05] S02｜第二部分",
        )

    def test_parser_returns_three_navigation_levels_at_real_timestamps(self):
        segments = [
            {"t": 0, "text": "开场"},
            {"t": 42.4, "text": "问题背景"},
            {"t": 95, "text": "解决办法"},
        ]
        reply = """<summary>
# 会议复盘

讨论问题与后续行动。
</summary>
<outline>
[00:00] H1 问题全景
[00:42] H2 形成原因
[01:35] H3 解决路径
</outline>"""

        summary, outline = self.parse_summary_outline(reply, segments)

        self.assertEqual(summary, "# 会议复盘\n\n讨论问题与后续行动。")
        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "问题全景"},
            {"t": 42.4, "level": 2, "title": "形成原因"},
            {"t": 95.0, "level": 3, "title": "解决路径"},
        ])

    def test_parser_drops_ungrounded_or_misnested_headings_without_losing_summary(self):
        segments = [
            {"t": 10, "text": "开场"},
            {"t": 70, "text": "正文"},
        ]
        reply = """<summary>有效摘要</summary>
<outline>
[00:10] H2 没有所属章节
[00:10] H1 第一章
[00:14] H2 模型虚构时间
[01:10] H3 没有父小节
[01:10] H2 有效小节
</outline>"""

        summary, outline = self.parse_summary_outline(reply, segments)

        self.assertEqual(summary, "有效摘要")
        self.assertEqual(outline, [
            {"t": 10.0, "level": 1, "title": "第一章"},
            {"t": 70.0, "level": 2, "title": "有效小节"},
        ])

    def test_parser_anchors_a_one_second_model_timestamp_offset(self):
        summary, outline = self.parse_summary_outline(
            "<outline>\n[00:01] H1 开场主题\n[01:04] H2 第二部分\n</outline>",
            [{"t": 0, "text": "开场"}, {"t": 65, "text": "正文"}],
        )

        self.assertEqual(summary, "<outline>\n[00:01] H1 开场主题\n[01:04] H2 第二部分\n</outline>")
        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_parser_anchors_the_zero_timestamp_example_before_first_segment(self):
        _summary, outline = self.parse_summary_outline(
            "[00:00] H1 开场主题\n[00:10] H2 第二部分",
            [{"t": 2.8, "text": "开场"}, {"t": 10, "text": "正文"}],
        )

        self.assertEqual(outline, [
            {"t": 2.8, "level": 1, "title": "开场主题"},
            {"t": 10.0, "level": 2, "title": "第二部分"},
        ])

    def test_parser_accepts_an_outline_without_xml_wrapper(self):
        _summary, outline = self.parse_summary_outline(
            "[00:00] H1 开场主题\n[01:05] H2 第二部分",
            [{"t": 0, "text": "开场"}, {"t": 65, "text": "正文"}],
        )

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_parser_accepts_markdown_wrapped_outline_rows(self):
        _summary, outline = self.parse_summary_outline(
            "- [00:00] # 开场主题\n## [01:05] H2 第二部分",
            [{"t": 0, "text": "开场"}, {"t": 65, "text": "正文"}],
        )

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_parser_accepts_wrapped_timestamp_rows_without_level_markers(self):
        _summary, outline = self.parse_summary_outline(
            "<outline>\n[00:00] 开场主题\n[01:05] 第二部分\n</outline>",
            [{"t": 0, "text": "开场"}, {"t": 65, "text": "正文"}],
        )

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_parser_uses_indentation_for_unmarked_outline_rows(self):
        _summary, outline = self.parse_summary_outline(
            "<outline>\n[00:00] 总览\n  [00:10] 定义\n    [00:20] 例子\n</outline>",
            [{"t": 0, "text": "开场"}, {"t": 10, "text": "定义"},
             {"t": 20, "text": "例子"}],
        )

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "总览"},
            {"t": 10.0, "level": 2, "title": "定义"},
            {"t": 20.0, "level": 3, "title": "例子"},
        ])

    def test_parser_accepts_table_wrapped_unmarked_outline_rows(self):
        _summary, outline = self.parse_summary_outline(
            "<outline>\n| [00:00] | 开场主题 |\n| [01:05] | 第二部分 |\n</outline>",
            [{"t": 0, "text": "开场"}, {"t": 65, "text": "正文"}],
        )

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_parser_uses_markdown_heading_level_before_timestamp(self):
        _summary, outline = self.parse_summary_outline(
            "# [00:00] 开场主题\n- ## [01:05] 第二部分",
            [{"t": 0, "text": "开场"}, {"t": 65, "text": "正文"}],
        )

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "开场主题"},
            {"t": 65.0, "level": 2, "title": "第二部分"},
        ])

    def test_parser_accepts_legacy_h4_as_l2_navigation(self):
        summary, outline = self.parse_summary_outline(
            "<summary>有效摘要</summary><outline>\n[00:00] H1 新章节\n[01:10] H4 旧小节\n</outline>",
            [{"t": 0, "text": "开场"}, {"t": 70, "text": "正文"}],
        )

        self.assertEqual(summary, "有效摘要")
        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "新章节"},
            {"t": 70.0, "level": 2, "title": "旧小节"},
        ])

    def test_plain_markdown_response_still_becomes_a_summary_with_no_outline(self):
        self.assertEqual(
            self.parse_summary_outline("# 旧格式摘要", [{"t": 0, "text": "正文"}]),
            ("# 旧格式摘要", []),
        )


if __name__ == "__main__":
    unittest.main()
