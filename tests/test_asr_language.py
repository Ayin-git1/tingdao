import ast
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch
import importlib.util
import json
import platform
import re
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
HAS_OPENCC = importlib.util.find_spec('opencc') is not None
needs_opencc = unittest.skipUnless(HAS_OPENCC, 'opencc-python-reimplemented 未安装')
TREE = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))


def load(names, owner=None, **extra):
    nodes = TREE.body if owner is None else next(
        n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == owner).body
    selected = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    selected = [n for n in TREE.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in {'ASR_LANG', 'LANG_MAP'} for t in n.targets)] + selected
    ns = dict(lru_cache=lru_cache, Path=Path, SR=16000, json=json,
              platform=platform, re=re, threading=threading, time=time)
    ns.update(extra)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / 'app.py'), 'exec'), ns)
    return ns


class AsrLanguageTests(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        self.ns = load({'_asr_converter', 'asr_text', 'asr_result', 'asr_prompt', 'transcription_language'},
                       load_setting=lambda key, default=None: self.settings.get(key, default))

    @needs_opencc
    def test_chinese_is_simplified_and_other_languages_untouched(self):
        convert = self.ns['asr_text']
        self.assertEqual(convert('這個 API 的 response 太慢了，123。', 'zh'),
                         '这个 API 的 response 太慢了，123。')
        self.assertEqual(convert('这个 API 的 response 太慢了，123。', 'zh-tw'),
                         '這個 API 的 response 太慢了，123。')
        for lang in ('en', 'ja', 'yue', 'auto', None):
            self.assertEqual(convert('繁體 English', lang), '繁體 English')

    def test_missing_opencc_does_not_silently_ignore_script_setting(self):
        with patch.dict(sys.modules, {'opencc': None}):
            ns = load({'_asr_converter', 'asr_text'})
            with self.assertRaisesRegex(RuntimeError, 'opencc-python-reimplemented'):
                ns['asr_text']('語音識別', 'zh')

    @needs_opencc
    def test_cloud_result_and_segments_are_simplified(self):
        backend = Mock(return_value={'text': '語音識別', 'segments': [
            {'start': 0, 'end': 2, 'text': '語音識別', 'spk': 'S01'}]})
        ns = load({'cloud_asr'}, _cloud_check=lambda *a: None,
                  _cloud_asr_dashscope=backend, _cloud_asr_openai=backend, **self.ns)
        for provider in ('dashscope', 'openai'):
            result = ns['cloud_asr']({'provider': provider, 'lang': 'zh'}, 'audio.wav')
            self.assertEqual(result['text'], '语音识别')
            self.assertEqual(result['segments'][0],
                             {'start': 0, 'end': 2, 'text': '语音识别', 'spk': 'S01'})

    @needs_opencc
    def test_realtime_engines_are_simplified(self):
        ns = load({'recognize'}, 'Engine', **self.ns)
        for engine in ('sensevoice', 'whisper'):
            obj = SimpleNamespace(engine_name=engine,
                                  _recognize_sensevoice=lambda *a: '語音識別',
                                  _recognize_whisper=lambda *a: '語音識別')
            self.assertEqual(ns['recognize'](obj, [], 'zh'), '语音识别')

    def test_default_and_persisted_selection(self):
        language = self.ns['transcription_language']
        self.assertEqual(language(), 'zh')
        self.settings['asr_language'] = 'zh-tw'
        self.assertEqual(language(), 'zh-tw')
        self.assertEqual(language('en'), 'en')
        self.assertEqual(language('invalid'), 'zh')

    @needs_opencc
    def test_cloud_prompt_carries_only_hotwords_in_selected_script(self):
        ns = load({'cloud_asr_opts', '_asr_form'}, **self.ns)
        for lang, spoken, prompt in [('zh', 'zh', '以下是常用人名与术语：OpenAI、软件'),
                                     ('zh-tw', 'zh', '以下是常用人名與術語：OpenAI、軟件'),
                                     ('en', 'en', 'Names and terms: OpenAI、软件')]:
            form = ns['_asr_form']({'model': 'test', 'lang': lang, 'hotwords': ['OpenAI', '软件']})
            self.assertEqual(form['language'], spoken)
            self.assertEqual(form['prompt'], prompt)
        self.assertNotIn('prompt', ns['_asr_form']({'model': 'test', 'lang': 'zh'}))
        self.assertNotIn('language', ns['_asr_form']({'model': 'test', 'lang': 'auto'}))

    def test_local_whisper_receives_model_language_and_preserves_english(self):
        for system in ('Windows', 'Darwin'):
            for lang, spoken in [('zh', 'zh'), ('zh-tw', 'zh'), ('en', 'en'), ('auto', None)]:
                model = Mock()
                model.transcribe.return_value = (iter([SimpleNamespace(text='API test')]), None)
                mlx = SimpleNamespace(transcribe=Mock(return_value={'text': 'API test'}))
                ns = load({'_recognize_whisper'}, 'Engine', whisper_model=lambda: Path('model'), **self.ns)
                obj = SimpleNamespace(_load_windows_whisper=lambda path: model)
                with patch.object(platform, 'system', return_value=system), \
                     patch.dict(sys.modules, {'mlx_whisper': mlx}):
                    self.assertEqual(ns['_recognize_whisper'](obj, [], lang), 'API test')
                kwargs = (model.transcribe if system == 'Windows' else mlx.transcribe).call_args.kwargs
                self.assertEqual(kwargs.get('language'), spoken)
                self.assertNotIn('initial_prompt', kwargs)

    def test_sensevoice_reloads_before_recording_not_while_recognizing(self):
        recognizer = SimpleNamespace(create_stream=lambda: SimpleNamespace(
            accept_waveform=lambda *a: None, result=SimpleNamespace(text='test')), decode_stream=lambda *a: None)
        factory = Mock(return_value=recognizer)
        ns = load({'Engine'}, sv_model_dir=lambda: Path('model'),
                  sherpa_onnx=SimpleNamespace(OfflineRecognizer=SimpleNamespace(from_sense_voice=factory)))
        obj = ns['Engine']()
        for lang, spoken in [('en', 'en'), ('auto', ''), ('zh-tw', 'zh')]:
            obj.use_language(lang)
            self.assertEqual(factory.call_args.kwargs['language'], spoken)
        count = factory.call_count
        obj.use_language('zh')
        for lang in ('en', 'auto', 'zh'):
            obj._recognize_sensevoice([], lang)
        self.assertEqual(factory.call_count, count)

    @needs_opencc
    def test_local_file_segments_and_fulltext_fallback_follow_script(self):
        with tempfile.TemporaryDirectory() as temp:
            ns = load({'_whisper_segs', '_clean_tail', '_merge_segs'}, 'App',
                      cache_temp_path=lambda *a: Path(temp) / 'unused.wav', **self.ns)
            for segments in ([], [{'start': 0, 'end': 3, 'text': '這個 API 很慢'}]):
                obj = SimpleNamespace(
                    _whisper_proc=lambda *a: {'text': '這個 API 很慢', 'segments': segments},
                    _clean_tail=ns['_clean_tail'].__func__, _merge_segs=ns['_merge_segs'].__func__,
                    _is_hallucination=lambda *a: False, _drop_repeat_loops=lambda segs: (segs, []),
                    stage=lambda *a: None)
                result, _ = ns['_whisper_segs'](obj, 'video.mp4', [], 10, 'zh', pretreat=False)
                self.assertEqual(result[0]['text'], '这个 API 很慢')

    def test_import_uses_current_setting_instead_of_previous_recording(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'video.mp4'
            video.touch()
            self.settings['asr_language'] = 'zh-tw'
            ns = load({'import_audio'}, 'App', SESSIONS_DIR=root, safe_title=lambda text: text, **self.ns)
            obj = SimpleNamespace(session={'lang': 'en'}, _job_begin=lambda *a, **kw: None, _enqueue=lambda *a: None)
            result = ns['import_audio'](obj, str(video))
            self.assertEqual(json.loads((root / result['id'] / 'session.json').read_text())['lang'], 'zh-tw')

    def test_reruns_keep_project_language_instead_of_global_setting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d = root / 'project'
            d.mkdir()
            (d / 'session.json').write_text(json.dumps({'lang': 'en', 'mode': 'import'}))
            self.settings['asr_language'] = 'zh-tw'
            ns = load({'rerun', 'refine_silence', 'cloud_transcribe'}, 'App', SESSIONS_DIR=root,
                      cloud_cfg=lambda: {'enable': True}, cloud_flow=lambda: 'asr_post', ffmpeg_path=lambda: 'ffmpeg', **self.ns)
            for method in ('rerun', 'refine_silence', 'cloud_transcribe'):
                jobs, local, cloud = [], Mock(), Mock()
                obj = SimpleNamespace(state='idle', progs={}, _recording_audio_source=lambda *a: d / 'audio.m4a',
                    _uncancel=lambda *a: None, _job_begin=lambda *a, **kw: None,
                    _enqueue=lambda sid, queue, job: jobs.append(job), _import_whisper=local,
                    _refinish_whisper=local, _cloud_asr_then_post=cloud, _cloud_asr_bg=cloud,
                    cloud_cfg_full=lambda: {'enable': True})
                ns[method](obj, d.name)
                self.settings['asr_language'] = 'zh'
                jobs[0]()
                if method == 'cloud_transcribe':
                    self.assertEqual(cloud.call_args.args[1]['lang'], 'en')
                else:
                    self.assertEqual(local.call_args.args[1], 'en')
                self.settings['asr_language'] = 'zh-tw'


if __name__ == '__main__':
    unittest.main()
