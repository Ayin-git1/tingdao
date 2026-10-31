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
        wanted = {"fmt_ts", "clean_uploaded_transcript", "summary_transcript",
                  "outline_transcript", "parse_summary_outline",
                  "run_outline_windows", "outline_rows",
                  "chapter_digest", "merge_outline_chapters", "title_anchored"}
        nodes = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
        namespace = {"re": re, "clean_uploaded_transcript": lambda text: text,
                     "OUTLINE_WINDOW_CHARS": 25000}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), "exec"), namespace)
        cls.clean_uploaded_transcript = staticmethod(namespace["clean_uploaded_transcript"])
        cls.summary_transcript = staticmethod(namespace["summary_transcript"])
        cls.outline_transcript = staticmethod(namespace["outline_transcript"])
        cls.parse_summary_outline = staticmethod(namespace["parse_summary_outline"])
        cls.run_outline_windows = staticmethod(namespace["run_outline_windows"])
        cls.chapter_digest = staticmethod(namespace["chapter_digest"])
        cls.merge_outline_chapters = staticmethod(namespace["merge_outline_chapters"])

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
            "outline_transcript": cls.outline_transcript,
            "parse_summary_outline": cls.parse_summary_outline,
            "run_outline_windows": cls.run_outline_windows,
            "chapter_digest": cls.chapter_digest,
            "merge_outline_chapters": cls.merge_outline_chapters,
            "OUTLINE_WINDOW_CHARS": 25000,
            "outline_rows": namespace["outline_rows"],
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
            def _ck(self, sid):
                return lambda: None

            def stage(self, *_args, **_kwargs):
                pass

            def tokens(self, _n):
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
        self.assertTrue(calls[1][1]["content"].startswith("[1] 正文内容\n\n（逐字稿到第 1 行为止"))
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
        self.assertNotIn("保留说话人区分", summary_system)
        self.assertIn("不写是谁讲的", summary_system)
        self.assertIn("不写谁在讲", outline_system)
        self.assertIn("只输出摘要本身", summary_system)
        self.assertNotIn("L1", summary_system)
        self.assertEqual(calls[0][1]["content"], "开场 第二部分")
        self.assertIn("[行号] H1 标题", outline_system)
        self.assertIn("[行号] H2 标题", outline_system)
        self.assertIn("★", outline_system)
        self.assertIn("第一行必须是 H1", outline_system)
        self.assertIn("一直写到逐字稿最后一行", outline_system)
        self.assertIn("[行号] H3 标题", outline_system)
        self.assertIn("由你自己判断", outline_system)
        self.assertNotIn("分钟", outline_system)
        self.assertNotIn("塔罗", outline_system)
        self.assertNotIn("一句话主题", outline_system)
        self.assertNotIn("不要 HTML 标签", outline_system)
        self.assertLess(len(outline_system), 560)
        outline_user = calls[1][1]["content"]
        self.assertTrue(outline_user.startswith("[1] 开场\n[2] ★ 第二部分\n\n"))
        # 覆盖与逐项拆分要求贴在稿尾，长稿后半段才不会被合并成一条
        self.assertIn("逐字稿到第 2 行为止", outline_user)
        self.assertIn("一直写到第 2 行附近", outline_user)
        self.assertIn("照抄讲者开始讲这个内容的那一行", outline_user)
        # 这句会把例子、背景升成章节，不能再出现
        self.assertNotIn("另起一个标题", outline_user)
        # 间隔数字会让模型凑行号，不能再出现
        self.assertNotIn("不超过", outline_user)
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

    def test_timestamped_transcript_keeps_real_times_and_drops_speaker_labels(self):
        segments = [
            {"t": 0, "text": "开场"},
            {"t": 65, "spk": "S02", "text": "第二部分"},
        ]

        self.assertEqual(
            self.summary_transcript(segments),
            "[00:00] 开场\n[01:05] 第二部分",
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

    def test_outline_transcript_numbers_rows_and_marks_speaker_transitions(self):
        text, times = self.outline_transcript([
            {"t": 0, "text": "大家好"},
            {"t": 0.6, "text": "今天我们讲背景\n顺带一句"},
            {"t": 12, "text": ""},
            {"t": 30.5, "text": "好，接下来我们讲方法"},
        ])

        self.assertEqual(text, "[1] 大家好\n[2] ★ 今天我们讲背景 顺带一句\n"
                               "[3] ★ 好，接下来我们讲方法")
        self.assertEqual(times, [0.0, 0.6, 30.5])

    def test_parser_maps_line_numbers_to_exact_segment_times(self):
        segments = [{"t": 0, "text": "开场"}, {"t": 0.6, "text": "背景"},
                    {"t": 30.5, "text": "方法"}]
        _text, times = self.outline_transcript(segments)

        _summary, outline = self.parse_summary_outline(
            "<outline>\n[1] H1 开场\n[2] H2 背景\n[3] H1 方法\n[9] H2 不存在的行\n</outline>",
            segments, times)

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "开场"},
            {"t": 0.6, "level": 2, "title": "背景"},
            {"t": 30.5, "level": 1, "title": "方法"},
        ])

    def test_parser_ignores_bare_numbers_without_line_times(self):
        _summary, outline = self.parse_summary_outline(
            "<outline>\n[1] H1 开场\n</outline>", [{"t": 0, "text": "开场"}])

        self.assertEqual(outline, [])

    def test_parser_shifts_a_colliding_h1_instead_of_merging_its_section(self):
        times = [0.0, 10.0, 20.0, 30.0]
        _summary, outline = self.parse_summary_outline(
            "<outline>\n[1] H1 第一章\n[2] H2 要点\n[2] H1 第二章\n"
            "[3] H2 第二章要点\n</outline>",
            [{"t": t, "text": "x"} for t in times], times)

        self.assertEqual(outline, [
            {"t": 0.0, "level": 1, "title": "第一章"},
            {"t": 10.0, "level": 2, "title": "要点"},
            {"t": 20.0, "level": 1, "title": "第二章"},
            {"t": 30.0, "level": 2, "title": "第二章要点"},
        ])

    def test_parser_drops_children_of_an_ungrounded_h1(self):
        times = [0.0, 10.0, 20.0]
        _summary, outline = self.parse_summary_outline(
            "<outline>\n[1] H1 第一章\n[99] H1 虚构章\n[3] H2 虚构章要点\n</outline>",
            [{"t": t, "text": "x"} for t in times], times)

        self.assertEqual(outline, [{"t": 0.0, "level": 1, "title": "第一章"}])

    def test_plain_markdown_response_still_becomes_a_summary_with_no_outline(self):
        self.assertEqual(
            self.parse_summary_outline("# 旧格式摘要", [{"t": 0, "text": "正文"}]),
            ("# 旧格式摘要", []),
        )


    def test_outline_windows_reread_from_last_chapter_and_drop_its_old_entries(self):
        numbered = "\n".join(f"[{n}] " + "字" * 18 for n in range(1, 101))
        seen = []

        def ask(text, prior):
            first = int(re.match(r"\[(\d+)\]", text).group(1))
            last = int(re.match(r"\[(\d+)\]", text.splitlines()[-1]).group(1))
            seen.append((first, last, list(prior)))
            if first == 1:
                return ("<outline>\n[1] H1 甲\n[5] H2 甲一\n[30] H1 乙\n"
                        "[31] H2 截断前的乙\n</outline>")
            # 第二窗从乙开头重读；同名 H1 不重复
            return ("<outline>\n[30] H1 乙\n[32] H2 乙一\n[60] H1 丙\n"
                    "[61] H3 丙例\n</outline>")

        merged, replies = self.run_outline_windows(numbered, ask, limit=1000)
        self.assertEqual(len(replies), len(seen))
        self.assertEqual(seen[0][0], 1)
        self.assertEqual(seen[1][0], 30)           # 从上一窗最后一个 H1 重读
        self.assertEqual(seen[1][2], ["甲", "乙"])  # 带上前文大章
        self.assertEqual(seen[-1][1], 100)          # 一直读到稿尾
        self.assertIn("[1] H1 甲\n[5] H2 甲一\n[30] H1 乙\n[32] H2 乙一", merged)
        self.assertNotIn("截断前的乙", merged)
        self.assertEqual(merged.count("H1 乙"), 1)

    def test_outline_windows_keep_title_of_chapter_carried_into_next_window(self):
        # 下一窗从上一窗最后一章重读，模型常拿这章里的案例给它改名，主对象就丢了
        numbered = "\n".join(f"[{n}] " + "字" * 18 for n in range(1, 201))

        def ask(text, prior):
            first = int(re.match(r"\[(\d+)\]", text).group(1))
            if first == 1:
                return "[1] H1 开场\n[30] H1 星牌"
            return f"[{first}] H1 某个案例\n[{first + 1}] H2 案例细节\n[150] H1 月牌"

        merged, _ = self.run_outline_windows(numbered, ask, limit=1000)
        self.assertIn("[30] H1 星牌", merged)
        self.assertNotIn("[30] H1 某个案例", merged)
        self.assertIn("[31] H2 案例细节", merged)

    def test_outline_windows_never_loop_when_a_window_is_one_chapter(self):
        numbered = "\n".join(f"[{n}] " + "字" * 18 for n in range(1, 201))
        starts = []

        def ask(text, prior):
            first = int(re.match(r"\[(\d+)\]", text).group(1))
            starts.append(first)
            return f"<outline>\n[{first}] H1 整窗一章\n[{first + 1}] H2 要点\n</outline>"

        merged, _ = self.run_outline_windows(numbered, ask, limit=1000)
        self.assertEqual(starts, sorted(set(starts)))
        self.assertEqual(merged.count("H1 整窗一章"), 1)
        self.assertIn("[2] H2 要点", merged)

    def test_long_transcript_outline_runs_windows_in_order_with_original_prompt(self):
        calls = []

        def fake_cloud_chat(_cfg, messages, **_kwargs):
            system, user = messages[0]["content"], messages[1]["content"]
            calls.append((system, user))
            if "写摘要" in system:
                return "# 概括\n\n摘要"
            if "逐章拿它" in system:
                n = len(re.findall(r"(?m)^\[\d+\]", user))
                return "<labels>\n" + "\n".join(
                    f"[{k}] {'附' if k == 2 else '主'}" for k in range(1, n + 1)) + "\n</labels>"
            body = [l for l in user.splitlines() if re.match(r"\[\d+\]", l)]
            first = int(re.match(r"\[(\d+)\]", body[0]).group(1))
            return (f"<outline>\n[{first}] H1 {first}号章\n[{first + 1}] H2 点\n"
                    f"[{first + 2}] H3 例\n</outline>")

        class DummyApp:
            def _ck(self, sid):
                return lambda: None

            def stage(self, *_args, **_kwargs):
                pass

            def tokens(self, _n):
                pass

            def _write_md(self, *_args, **_kwargs):
                pass

            def emit(self, **_kwargs):
                pass

        self.method_namespace["cloud_chat"] = fake_cloud_chat
        segments = [{"t": n * 10, "text": f"第{n}句" + "讲解" * 60} for n in range(1000)]
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.json"
            session.write_text(json.dumps({"segments": segments}, ensure_ascii=False),
                               encoding="utf-8")
            # 分段生成默认关: 长稿也整篇一次写目录
            self.cloud_summary_bg(DummyApp(), Path(tmp), {
                "provider": "test", "model": "test-model"})
            self.assertEqual(len([c for c in calls if "写目录" in c[0]]), 1)
            self.assertIn("outline", json.loads(
                (Path(tmp) / "outline_raw.json").read_text(encoding="utf-8")))
            calls.clear()
            self.cloud_summary_bg(DummyApp(), Path(tmp), {
                "provider": "test", "model": "test-model", "summary_windows": True})
            saved = json.loads(session.read_text(encoding="utf-8"))
            raw = json.loads((Path(tmp) / "outline_raw.json").read_text(encoding="utf-8"))

        windows = [c for c in calls if "写目录" in c[0]]
        merges = [c for c in calls if "逐章拿它" in c[0]]
        self.assertEqual(len(merges), 1)
        self.assertIn("    - 点", merges[0][1])          # 只给标题，不给原文
        self.assertIn("merge", raw)
        self.assertGreater(len(windows), 1)
        # 每窗都用短稿那份原提示词，后续窗带前文大章
        self.assertTrue(all(s == windows[0][0] for s, _u in windows))
        self.assertNotIn("前面已经写好的大章", windows[0][1])
        self.assertIn("前面已经写好的大章", windows[1][1])
        self.assertEqual(len(raw["windows"]), len(windows))
        levels = [o["level"] for o in saved["outline"]]
        self.assertEqual(levels[0], 1)
        self.assertEqual(set(levels), {1, 2, 3})
        self.assertEqual(levels.count(1), len(windows))   # 第 2 章标了附，但标题主角对不上，不并
        self.assertEqual(saved["outline"][0]["title"], "1号章")
        times = [o["t"] for o in saved["outline"]]
        self.assertEqual(times, sorted(times))

    def test_merge_outline_chapters_folds_adjacent_chapters_without_losing_items(self):
        outline = [
            {"t": 0, "level": 1, "title": "甲牌含义"},
            {"t": 1, "level": 2, "title": "甲正位"},
            {"t": 2, "level": 1, "title": "甲牌案例"},
            {"t": 3, "level": 2, "title": "案例背景"},
            {"t": 4, "level": 3, "title": "细节"},
            {"t": 5, "level": 1, "title": "乙牌"},
        ]
        digest, n = self.chapter_digest(outline)
        self.assertEqual(n, 3)
        self.assertEqual(digest, "[1] 甲牌含义\n    - 甲正位\n[2] 甲牌案例\n    - 案例背景\n[3] 乙牌")
        merged = self.merge_outline_chapters(outline, "<labels>\n[1] 主\n- **[2]** 附\n[3]：主\n</labels>")
        self.assertEqual([(o["t"], o["level"], o["title"]) for o in merged], [
            (0, 1, "甲牌含义"), (1, 2, "甲正位"), (2, 2, "甲牌案例"),
            (3, 3, "案例背景"), (4, 3, "细节"), (5, 1, "乙牌")])
        self.assertEqual(outline[2]["level"], 1)    # 不改原列表

    def test_merge_outline_chapters_never_folds_main_chapters_or_unlabeled_ones(self):
        titles = ["甲牌含义", "甲牌逆位", "甲牌案例", "甲牌答疑"]
        outline = [{"t": n, "level": 1, "title": t} for n, t in enumerate(titles)]
        self.assertIs(self.merge_outline_chapters(outline, "没有标注"), outline)
        # 第 1 章标附也不动；漏标的第 3 章当主章；主章之间不合并
        merged = self.merge_outline_chapters(outline, "[1] 附\n[2] 主\n[4] 附")
        self.assertEqual([o["level"] for o in merged], [1, 1, 1, 2])

    def test_merge_outline_chapters_keeps_chapters_whose_subject_differs(self):
        # 便宜模型会把各讲各的章全标附；标题开头的主角对不上就不并，描述词撞上不算
        titles = ["甲牌的需求解析", "甲牌逆位", "乙牌的需求解析", "丙牌应用", "丙牌逆位"]
        outline = [{"t": n, "level": 1, "title": t} for n, t in enumerate(titles)]
        merged = self.merge_outline_chapters(outline, "[1] 主\n[2] 附\n[3] 附\n[4] 附\n[5] 附")
        self.assertEqual([o["level"] for o in merged], [1, 2, 1, 1, 2])

    def test_stream_reader_counts_thinking_and_returns_only_content(self):
        import time as _time
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        node = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "_cloud_stream_read")
        ns = {"json": json, "time": _time}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP), "exec"), ns)

        class FakeResp:
            def iter_lines(self):
                yield b": keep-alive"
                yield b'data: {"choices":[{"delta":{"reasoning_content":"\u60f3\u4e00\u60f3"}}]}'
                yield b""
                yield b'data: {"choices":[{"delta":{"content":"<outline>"}}]}'
                yield b'data: {"choices":[{"delta":{"content":"[1] H1 \u5f00\u573a</outline>"},"finish_reason":"stop"}]}'
                yield b'data: {"choices":[],"usage":{"completion_tokens":42}}'
                yield b"data: [DONE]"

        calls = []
        content, fr, usage = ns["_cloud_stream_read"](
            FakeResp(), lambda est, final=None: calls.append((est, final)))
        self.assertEqual(content, "<outline>[1] H1 开场</outline>")
        self.assertEqual(fr, "stop")
        self.assertEqual(usage["completion_tokens"], 42)
        self.assertGreater(calls[0][0], 0)              # 思考阶段就开始计数
        self.assertEqual(calls[-1], (0, 42))            # 收完用实数校正

if __name__ == "__main__":
    unittest.main()
