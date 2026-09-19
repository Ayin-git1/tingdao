#!/usr/bin/env python3
"""听道 — 本地实时转写原生窗口应用

架构: pywebview 原生窗口(WKWebView) + 内部回环 HTTP(仅媒体/API) +
      SenseVoice + Silero VAD 流式转写管道。

特性:
- 实时流式转写: 按说话停顿断句, 延迟 1-2 秒
- 句级时间戳, 结束后音轨同步播放
- 历史会话列表, 逐字稿搜索, 时间线笔记, 一键复制
"""
import base64
from collections import deque
import json
import getpass
import hashlib
import hmac
import io
import os
import platform
import re
import signal
import sys
import subprocess
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import numpy as np
import sherpa_onnx

# Finder/Dock 启动的 GUI 进程 PATH 不含 homebrew, 主动补齐(ffmpeg/SwitchAudioSource 所在)
for _p in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + ":" + os.environ.get("PATH", "")

# ---------------- 日志 ----------------
# Finder/Dock 启动时 print 全部进黑洞, 之前"预处理到底有没有生效"根本无从查证
# 数据根目录: 打包/多实例可用环境变量 TINGDAO_DATA 整体搬家; 默认 ~/Documents/transcripts
DATA_DIR = (Path(os.environ["TINGDAO_DATA"]).expanduser()
            if os.environ.get("TINGDAO_DATA") else Path.home() / "Documents/transcripts")
LOG_FILE = DATA_DIR / ".tingdao.log"


class _Tee:
    def __init__(self, *streams):
        self.streams = streams
        self._partial = ""

    def write(self, data):
        self._partial += data
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            self._emit(line)

    def _emit(self, line):
        stamp = time.strftime("%H:%M:%S")
        for s in self.streams:
            try:
                s.write("[%s] %s\n" % (stamp, line))
                s.flush()
            except Exception:
                pass

    def flush(self):
        if self._partial:
            self._emit(self._partial)
            self._partial = ""


def setup_log():
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
            old = LOG_FILE.with_suffix(".log.old")
            try:
                old.unlink()
            except Exception:
                pass
            LOG_FILE.rename(old)
        f = open(LOG_FILE, "a", encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, f)
        sys.stderr = _Tee(sys.__stderr__, f)
        print("[log] 日志已启用:", LOG_FILE, flush=True)
    except Exception:
        pass


# ---------------- 配置 ----------------
# 回环服务端口不再写死。真实端口在 main() 里向 OS 现取(bind 端口 0 = 挑一个真正空闲的),
# 避免「默认端口被别的程序占了就起不来」。被 tauri 壳拉起时, 后端再把取到的端口经
# TINGDAO_PORTFILE 指向的临时文件回报给壳; 单独跑则直接用它喂给 pywebview。这里是占位, main() 会改写。
PORT = 0
SR = 16000
# SCK 音频助手: macOS 系统声音(ScreenCaptureKit)+麦克风在助手进程内混成单轨,
# stdout 输出 s16le/SR/mono —— 与 ffmpeg avfoundation 的输出协议逐字节一致,
# _read_loop/_finish 全链路零改动。替代 BlackHole 虚拟声卡+多输出设备方案,
# 录制期间不再切换系统输出(用户正常听自己的扬声器)。
SCK_HELPER = Path(__file__).resolve().parent / "tingdao-mix"
CHUNK = 1.5                       # 流式小块秒数(前端即时显示粒度)
VAD_WINDOW = 512                  # silero 要求的窗口样本数


def sv_model_dir():
    """SenseVoice 实时模型目录必须用户配置(分发口径: 不内置默认)。未配置=None。
    改了要重启听道才生效: 识别器是启动时建的, 不做热重载(为省内存只留一份)。"""
    v = (load_setting("sv_model_dir") or "").strip()
    return Path(v).expanduser() if v else None


def vad_model_path():
    """VAD(断句)模型必须用户配置(设置 → 本地模型, 指到 silero_vad.onnx 文件)。
    兼容打包习惯: 没单独配时, SenseVoice 目录里有 silero_vad.onnx 也认。"""
    v = (load_setting("vad_model") or "").strip()
    if v:
        f = Path(v).expanduser()
        return f if f.is_file() else None
    d = sv_model_dir()
    if d:
        f = d / "silero_vad.onnx"
        if f.is_file():
            return f
    return None


SESSIONS_DIR = DATA_DIR
HOTWORDS_FILE = DATA_DIR / ".hotwords.txt"      # 全局热词表
SETTINGS_FILE = DATA_DIR / ".settings.json"     # 应用设置(预处理开关等)


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_setting(key, default=None):
    return load_settings().get(key, default)


def save_setting(key, value):
    s = load_settings()
    s[key] = value
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1),
                             encoding="utf-8")


def talk_mode():
    """single=停录后本地 Whisper 精修 | cloud=停录后弹窗确认再上传云端转写。
    （多人模型已移除: 本机实测 61 分钟课要 25 分钟以上, 效率不划算,
    多人识别交给云端——支持分离就出标签, 不支持也只是没标签, 不影响出稿。）"""
    v = load_setting("talk_mode")
    return v if v in ("single", "cloud") else "single"


def cloud_flow():
    """云端模式下的两种做法:
    asr_post = 云端转写 + 云端后制作(默认) | local_post = 本地转写 + 云端只做后制作
    后者音频不出本机, 是隐私优先时的选法。"""
    v = load_setting("cloud_flow")
    return v if v in ("asr_post", "local_post") else "asr_post"


# ---------- 云端 API Key: 加密存放(纯标准库, macOS / Windows 同一套) ----------
# 为什么不用钥匙串: 这个工具要分发给 Windows 用户, 存储层必须跨平台; 而且未签名的
# python 在 macOS 上读写登录钥匙串可能弹系统授权框, 对不懂技术的人是灾难。
# 算法说清楚(不吹): 这不是 AES。stdlib 没有块加密, 也不想为一个字段拖进第三方包。
# 做法 = SHA-256 计数器 keystream 做 XOR + HMAC-SHA256 截断做完整性校验。主密钥是
# 首次使用时随机生成、落盘 0600 的密钥文件 —— 不再从「主机名+登录名」派生(那样会随
# macOS 主机名漂移而静默失效, 见 _keybox_legacy_root 注释)。它保证的是: 配置里不再有
# 明文密钥、配置单独拷到别的机器解不开(密钥文件不在)。
# 它挡不住"能以你的身份在你这台机器上跑代码"的人 —— 那种人直接读你的输入框。
KEYBOX_TAG = "tdk1:"
KEYBOX_SALT = b"tingdao.keybox.v1"
KEYBOX_FILE = SESSIONS_DIR / ".keybox.key"      # 随机主密钥: 生成一次, 与机器身份解耦
LAST_DEC_LEGACY = False                          # 上一次 dec_secret 是否靠旧派生解开


def _keybox_hostnames():
    """本机所有可能被 platform.node() 返回的名字。
    macOS 同时维护 ComputerName / LocalHostName / HostName 三个名字, 且会随网络环境
    (连哪个 Wi-Fi、DHCP 给什么)在它们之间漂移, 所以旧密文到底是哪个值加密的并不确定。"""
    names = []
    try:
        names.append(platform.node())
    except Exception:
        pass
    if platform.system() == "Darwin":
        for k in ("LocalHostName", "ComputerName", "HostName"):
            try:
                r = subprocess.run(["scutil", "--get", k], capture_output=True,
                                   text=True, timeout=2)
                v = (r.stdout or "").strip()
                if v and v != "(null)":
                    names.append(v)
            except Exception:
                pass
    for n in list(names):
        if n and not n.endswith(".local"):
            names.append(n + ".local")
    return [n for n in dict.fromkeys(names) if n]


def _keybox_usernames():
    """getpass.getuser() 的取值链: 环境变量优先, 最后才 pwd 回落 —— 同样会随启动上下文变。"""
    us = []
    for k in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        v = os.environ.get(k)
        if v:
            us.append(v)
    try:
        us.append(getpass.getuser())
    except Exception:
        pass
    try:
        import pwd
        us.append(pwd.getpwuid(os.getuid()).pw_name)
    except Exception:
        pass
    return [u for u in dict.fromkeys(us) if u]


def _keybox_legacy_roots():
    """旧派生的全部候选根(仅作兼容回落, 用来把已经漂移过的密文救回来)。
    救回后 cloud_key() 会立刻换成随机主密钥重存, 这套候选以后不再走。"""
    out = []
    for node in _keybox_hostnames():
        for user in _keybox_usernames():
            raw = (KEYBOX_SALT + b"|" + node.encode("utf-8", "replace")
                   + b"|" + user.encode("utf-8", "replace"))
            out.append(hashlib.sha256(raw).digest())
    return list(dict.fromkeys(out))


def _keybox_file_key():
    """新主密钥: 第一次用到时随机生成并落盘(0600), 之后一直复用。
    文件被删则重新生成 → 旧密文变 stale, 上层提示重填(有提示, 不算静默失败)。"""
    if KEYBOX_FILE.exists():
        k = KEYBOX_FILE.read_bytes()
        if len(k) == 32:
            return k
    k = os.urandom(32)
    try:
        KEYBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEYBOX_FILE.write_bytes(k)
        KEYBOX_FILE.chmod(0o600)
    except Exception:
        pass
    return k


def _keybox_stream(root, salt, n):
    out = bytearray()
    i = 0
    while len(out) < n:
        out += hashlib.sha256(root + salt + i.to_bytes(4, "big")).digest()
        i += 1
    return bytes(out[:n])


def enc_secret(plain):
    """明文 -> 可落盘的密文。空值原样返回空串。只用随机主密钥文件。"""
    if not plain:
        return ""
    data = plain.encode("utf-8")
    salt = os.urandom(16)
    root = _keybox_file_key()
    body = bytes(a ^ b for a, b in zip(data, _keybox_stream(root, salt, len(data))))
    tag = hmac.new(root, salt + body, hashlib.sha256).digest()[:16]
    return KEYBOX_TAG + base64.urlsafe_b64encode(salt + tag + body).decode("ascii")


def dec_secret(blob):
    """解不开(换机器/被手改/还是旧明文)一律返回空串, 上层据此提示重填。
    依次尝试两把根: ① 随机主密钥文件(现行) ② 旧的「主机名+登录名」派生(兼容升级前存的
    密文)。靠②解开时会置 LAST_DEC_LEGACY, 由 cloud_key() 立刻换新根重存(自愈迁移),
    之后就不再受主机名漂移影响。"""
    global LAST_DEC_LEGACY
    LAST_DEC_LEGACY = False
    if not blob or not str(blob).startswith(KEYBOX_TAG):
        return ""
    try:
        raw = base64.urlsafe_b64decode(str(blob)[len(KEYBOX_TAG):].encode("ascii"))
        salt, tag, body = raw[:16], raw[16:32], raw[32:]
        file_key = _keybox_file_key()
        cands = [(file_key, False)] + [(r, True) for r in _keybox_legacy_roots()]
        for root, is_legacy in cands:
            want = hmac.new(root, salt + body, hashlib.sha256).digest()[:16]
            if not hmac.compare_digest(tag, want):
                continue
            LAST_DEC_LEGACY = bool(is_legacy)
            return bytes(a ^ b for a, b in
                         zip(body, _keybox_stream(root, salt, len(body)))).decode("utf-8")
        return ""
    except Exception:
        return ""


def key_hint(k):
    """给前端看的缩短形态, 例如 sk-ws-••••••••3f9a。真实 key 从不出后台。"""
    if not k:
        return ""
    if len(k) <= 12:
        return "•" * len(k)
    return k[:6] + "•" * 8 + k[-4:]


def looks_like_hint(v):
    """判断"这是显示用的缩短形态/密文, 不是真实 key"。
    真实 API key 不会含 •(U+2022), 也不会以密文标记开头 —— 所以按"含 •"判断。
    不能只判断开头: hint 形如 sk-ws-••••••••3f9a, 开头是正常字符。"""
    return bool(v) and ("•" in v or v.startswith(KEYBOX_TAG))


def key_problem(v):
    """把"这把 key 明显不对"变成人话。不拦的话, 含中文/空格的 key 会在写 HTTP 头时
    炸成 UnicodeEncodeError, 用起来就像服务器无缘无故认证失败。"""
    if not v:
        return "还没填密钥"
    if any(ch.isspace() for ch in v):
        return "密钥里有空格或换行，请整段重新粘贴"
    if not v.isascii():
        return "密钥含中文或全角字符，请检查是否粘贴错了"
    if len(v) < 8:
        return "密钥太短，不像一把完整的 key"
    return ""


def cloud_key():
    """取真实 key: 只认密文字段。发现老版本留在配置里的明文, 顺手加密迁走并抹掉。"""
    s = load_settings()
    k = dec_secret(s.get("cloud_api_key_enc") or "")
    if k:
        if LAST_DEC_LEGACY:
            # 旧「主机名+登录名」派生解开的: 立刻换成随机主密钥重存(自愈迁移),
            # 下次重启/换 Wi-Fi 就不会再解不开。标志不用手动复位 —— dec_secret 每次
            # 进来都会先置 False, 在这里赋值只会造出局部变量骗自己。
            cloud_key_set(k)
        return k
    legacy = (s.get("cloud_api_key") or "").strip()
    if legacy and not legacy.startswith("•"):
        save_setting("cloud_api_key_enc", enc_secret(legacy))
        s = load_settings()
        s.pop("cloud_api_key", None)
        SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        return legacy
    return ""


def cloud_key_set(value):
    """写 key: 空值=清除。只存密文, 并抹掉配置里任何明文残留。"""
    v = (value or "").strip()
    s = load_settings()
    s.pop("cloud_api_key", None)                 # 明文一律不留
    if v:
        s["cloud_api_key_enc"] = enc_secret(v)
    else:
        s.pop("cloud_api_key_enc", None)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def cloud_key_stale():
    """有密文但解不开 = 换过机器或登录名。让用户重填一次, 别让用户对着认证失败猜原因。"""
    s = load_settings()
    return bool(s.get("cloud_api_key_enc")) and not dec_secret(s.get("cloud_api_key_enc"))


# ---------- 精修进度: 能拿真数据就别猜 ----------
# Whisper 每解出一句就往 stdout 打一行 `[  0:03.45 -->  0:07.90] 文本`，
# 把最后那个"止"时间除以音频总长就是真实进度，不是安慰剂。
_SEG_LINE = re.compile(r"\[([^\[\]]*?) --> ([^\[\]]*?)\]")
_TS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)$")


def _ts_secs(s):
    """'1:23:45.67' 或 '23:45.67' -> 秒。解不开返回 None。"""
    m = _TS.match((s or "").strip())
    if not m:
        return None
    h, mi, sec = m.groups()
    return (int(h or 0) * 3600) + int(mi) * 60 + float(sec)


class Cancelled(Exception):
    """用户按了停止: 本地=子进程已被 SIGTERM; 云端=检查点主动抛出。
    与各后台任务的通用 Exception 分开处理——停止不是失败, 别报红横幅。"""


class Truncated(RuntimeError):
    """单次输出撞到模型自身上限被腰斩。精修据此把「那一片」拆细重试(而非整条判死)。
    继承 RuntimeError, 所以不特判它的旧调用方仍能按普通失败兜住。"""


WORKER_PY = str(Path(__file__).parent / "whisper_worker.py")


class WhisperStdout:
    """劫持 mlx_whisper 的 verbose 输出算进度。
    注意: 精修跑在后台线程, 而 redirect_stdout 换的是全局 sys.stdout ——
    所以凡是"不像段行"的内容必须原样转回真 stdout, 否则别的线程的日志会被吞掉
    (日志文件是 tee 到 stdout 的, 一吞就丢)。"""

    def __init__(self, on_pct, total):
        self.on_pct = on_pct
        self.total = float(total or 0)
        self.real = sys.stdout
        self.buf = ""
        self.last = -1

    def write(self, s):
        try:
            self.buf += s
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                self._one(line)
        except Exception:
            pass                      # 进度是附加信息, 绝不能把它变成崩溃原因
        return len(s)

    def flush(self):
        try:
            self.real.flush()
        except Exception:
            pass

    def _one(self, line):
        p = None
        if self.total > 0:
            m = _SEG_LINE.search(line)
            if m:
                end = _ts_secs(m.group(2))
                if end is not None:
                    p = max(0, min(99, int(end / self.total * 100)))
        if p is None:
            try:
                self.real.write(line + "\n")     # 不是段行 -> 交回原路
            except Exception:
                pass
        elif p != self.last:                     # 整数百分比变了才广播, 别刷屏
            self.last = p
            self.on_pct(p)


class CountingReader:
    """包一层文件对象, 按已读字节回调进度。上传阶段用它出真实百分比。"""

    def __init__(self, fh, total, on_pct):
        self.fh = fh
        self.total = float(total or 1) or 1.0
        self.on_pct = on_pct
        self.done = 0
        self.last = -1

    def read(self, *a):
        b = self.fh.read(*a)
        if b:
            self.done += len(b)
            p = max(0, min(99, int(self.done / self.total * 100)))
            if p != self.last:
                self.last = p
                try:
                    self.on_pct(p)
                except Exception:
                    pass
        return b

    def __getattr__(self, k):            # seek/tell/close/... 全部转给真文件
        return getattr(self.fh, k)


# ---------- 云端接口层(两种协议: 标准兼容上传 / 异步文件任务) ----------
def cloud_cfg():
    """读云端配置。所有值都以用户填的为准, 这里不做任何默认值兜底。
    provider: 'openai'=标准兼容(同步上传) | 'dashscope'=异步文件任务型"""
    s = load_settings()
    prov = (s.get("cloud_provider") or "openai").strip()
    return {
        "provider": prov if prov in ("openai", "dashscope") else "openai",
        "api_key": cloud_key(),
        "enable": bool(cloud_key()) and bool((s.get("cloud_base_url") or "").strip()),
        "base_url": (s.get("cloud_base_url") or "").strip().rstrip("/"),
        "model": (s.get("cloud_model") or "").strip(),
        # 课后笔记专用模型: 单独设一个, 空则回退到后处理模型(cloud_model)
        "note_model": (s.get("cloud_note_model") or s.get("cloud_model") or "").strip(),
        # 「深度思考」开关(默认开=提精度); 关掉才对该模型发关思考参数(且需它支持)
        "chat_think": bool(s.get("cloud_chat_think", True)),
        "note_think": bool(s.get("cloud_note_think", True)),
        "asr_model": (s.get("cloud_asr_model") or "").strip(),
        # 后处理提示词: 用户自定义的润色要求; 为空则用内置那段"逐字稿校对器"
        "prompt": (s.get("cloud_prompt") or "").strip(),
    }


# ---------- 「这模型会不会思考 / 能不能关思考」: 首次测一次并缓存, 之后不再重复探 ----------
# 摘要/笔记这类机械活, 用一个「深度思考」开关让用户自己权衡精度/成本。但开关能不能真
# 起作用取决于模型: 有的压根不思考、有的混合可关、
# 有的纯思考关不掉。用 provider|model 作键把结论缓存进 cloud_think_cap, 只在
# 「测试连接」首次遇到该模型时探一次(cloud_think_probe), 平时打开软件/重测都不再重复探测,
# 免得白烧 token。三态: "off"=可关 | "always"=只会思考、关不掉 | "none"=不思考 | ""=未知。
def _think_key(provider, model):
    return f"{provider}|{model}"


def cloud_think_cap_get(provider, model):
    """已缓存的三态结论; 没测过返回 ""。"""
    if not model:
        return ""
    d = load_settings().get("cloud_think_cap") or {}
    v = d.get(_think_key(provider, model), "")
    return v if v in ("off", "always", "none") else ""


def cloud_think_cap_set(provider, model, cap):
    if not model or cap not in ("off", "always", "none"):
        return
    s = load_settings()
    d = s.get("cloud_think_cap") or {}
    d[_think_key(provider, model)] = cap
    save_setting("cloud_think_cap", d)


def cloud_think_probe(cfg, model):
    """首次遇到该模型探一次它属哪一态并缓存; 已缓存直接返回, 绝不重复探测(省 token)。
    最多两次: ①普通调用读 reasoning_tokens 判"会不会思考"; ②只对会思考的模型再试一次带
    关思考参数, 认="off"(可关)、拒="always"(关不掉)。连不上则不缓存、返回 ""。"""
    prov = cfg.get("provider")
    if not model:
        return ""
    cached = cloud_think_cap_get(prov, model)
    if cached:
        return cached
    c2 = dict(cfg)
    c2["model"] = model
    probe_msgs = [{"role": "user", "content": "回复两个字：正常"}]
    usage = {}
    try:
        cloud_chat(c2, probe_msgs, max_tokens=256, timeout=30,
                   ignore_length=True, usage_out=usage)
    except Cancelled:
        raise
    except Exception:
        return ""                                    # 连不通: 不缓存, 下次再试
    rt = ((usage.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0
    if not rt:
        cloud_think_cap_set(prov, model, "none")     # 不思考的模型: 开关对它没意义
        return "none"
    try:
        cloud_chat(c2, probe_msgs, max_tokens=256, timeout=30,
                   ignore_length=True, think_off=True)
        cloud_think_cap_set(prov, model, "off")      # 会思考且能关
        return "off"
    except Cancelled:
        raise
    except Exception:
        cloud_think_cap_set(prov, model, "always")   # 会思考但关不掉
        return "always"


def cloud_think_off_for(provider, model, user_think_on):
    """运行时这次调用要不要发关思考参数: 仅当用户把「深度思考」关了、且该模型确实可关。"""
    return (not user_think_on) and cloud_think_cap_get(provider, model) == "off"


ASR_LANG = {"zh": "zh", "en": "en", "ja": "ja", "ko": "ko", "yue": "yue"}

# 上传格式表: ffmpeg 编码参数 + MIME。默认 mp3 —— 16k 单声道 64k 下约 28MB/小时,
# 各家接口几乎都收; m4a 是 AAC 装在 MP4 容器里, 部分厂商(如只列 wav/mp3/opus/aac 的)会拒
ASR_FMT = {
    "m4a":  (["-c:a", "aac", "-b:a", "64k"], "audio/mp4"),
    "mp3":  (["-c:a", "libmp3lame", "-b:a", "64k"], "audio/mpeg"),
    "wav":  (["-c:a", "pcm_s16le"], "audio/wav"),
    "ogg":  (["-c:a", "libopus", "-b:a", "48k"], "audio/ogg"),
    "flac": (["-c:a", "flac"], "audio/flac"),
}
# 格式类报错的降级顺序(体积从小到大可控): 所选 → mp3 → m4a
FMT_FALLBACK = ["mp3", "m4a"]


def asr_fmt():
    v = (load_setting("cloud_asr_fmt") or "mp3").strip().lower()
    return v if v in ASR_FMT else "mp3"


def to_upload(src: Path, fmt: str, dst: Path):
    """把音频转成指定上传格式(16kHz 单声道不变, 只换容器/编码)。"""
    codec, _mime = ASR_FMT[fmt]
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-vn", "-ac", "1", "-ar", str(SR)] + codec + [str(dst)],
        capture_output=True, timeout=1800)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 512:
        raise RuntimeError("转上传格式失败: " +
                           (r.stderr or b"").decode(errors="ignore").strip()[:160])
    return dst


def looks_like_format_err(text):
    t = (text or "").lower()
    return any(k in t for k in ("format", "invalidparameter", "unsupported",
                                "file type", "decode", "容器", "格式", "415"))


def cloud_asr_opts(lang=None, hotwords=None):
    """把「识别语言 + 热词库」打包成给转写接口的附加参数(两家协议各取所需)。"""
    return {"language": ASR_LANG.get((lang or "").strip(), ""),
            "prompt": "、".join(hotwords or [])}


def _cloud_check(cfg, need="chat"):
    if not cfg["base_url"]:
        raise RuntimeError("未填 API 地址（设置 → 对话模式 → 云端）")
    if not cfg["api_key"]:
        raise RuntimeError("未填 API Key")
    if need == "chat" and not cfg["model"]:
        raise RuntimeError("未填后处理模型名")
    if need == "asr" and not cfg["asr_model"]:
        raise RuntimeError("未填转写模型名")


def _chat_endpoint(cfg):
    """该服务商的聊天接口在 /compatible-mode/v1 下；用户若只填根域名则补上该路径,
    已填完整路径的原样用。"""
    base = cfg["base_url"]
    if cfg["provider"] == "dashscope":
        # 该服务商聊天接口只挂在 /compatible-mode/v1 下; 用户粘的地址常带 /api/v1 尾巴, 先归一
        for tail in ("/api/v1", "/v1"):
            while base.endswith(tail):
                base = base[: -len(tail)]
        base = base.rstrip("/")
        if "/compatible-mode" not in base:
            base = base + "/compatible-mode/v1"
    return base + "/chat/completions"


# 这些状态码是"过一会儿再打一次可能就成了"(限流/网关抖动/服务端瞬时故障);
# 401/402/404 属于配置或额度问题, 重试只是白等, 不在此列。
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# 端上的 MD 渲染器是零依赖自写的(界面要离线可用, 不引 CDN), 只认这几种语法。
# 让模型只用这些, 是为了避免它吐出图片/链接/HTML 后在我们这儿变成一堆裸文本。
# 摘要与课后笔记共用这一条约定。
MD_RULES = ("\n输出格式：只用 Markdown，且只允许这几种语法 —— "
            "# 到 #### 标题、- 无序列表、1. 有序列表、- [ ] 任务列表、"
            "> 引用、--- 分隔线、| 表格 |、**粗体**、`行内代码`；"
            "不要图片、不要链接、不要 HTML 标签、不要代码块围栏。")

# ---------- 课后笔记: 模板与 note.md ----------
# 没有"默认模板"这回事(用户定的): 每次生成都必须自己选一个, 所以这里只存清单, 不存"当前选中"。
NOTE_FILE = "note.md"
# 播放偏好侧车：倍速 / 上次播放位置。单独存小文件，避免每次记进度都重写整份
# session.json（可能几 MB）或误动 transcript.md；删项目时随文件夹一起进废纸篓。
PREF_FILE = ".pref.json"
NOTE_TPL_SEED = [
    {"id": "review-full", "name": "课后复习笔记 · 全面版",
     "prompt": "把这份逐字稿整理成一份课后可复习的全面笔记，要求事无巨细但绝不掺入稿子里没有的内容："
               "① 一句话主题；② 按讲课顺序分节（## 标题），每节保留老师的关键结论与原话要点（用 > 引用标出）；"
               "③ 出现的概念/术语给出一句话定义；④ 有对比关系的内容整理成表格；"
               "⑤ 单独一节列易错点与老师纠正过的理解；⑥ 结尾列本课留的作业或练习。"},
    {"id": "brief", "name": "考前速记 · 精简版",
     "prompt": "把这份逐字稿压成一页能背下来的速记：只留结论与记忆锚点，"
               "分「必须记住的几条」「一句话解释」「容易搞混的对照」三节，总字数控制在 400 字内。"},
    {"id": "table", "name": "对照表 · 表格版",
     "prompt": "把这份逐字稿里出现的条目（对象/概念/案例）整理成对照表："
               "每行一个条目，列包含 名称、关键特征、正面情形、反面或注意点；"
               "表格之外只允许一句总述和一行备注。"},
]


def note_templates():
    """模板清单。首次使用时铺三个内置起点；之后完全由用户增删改。"""
    ts = load_setting("note_templates")
    if not isinstance(ts, list) or not ts:
        ts = [dict(t) for t in NOTE_TPL_SEED]
        save_setting("note_templates", ts)
        return ts
    return ts


def note_tpl_get(tpl_id):
    return next((t for t in note_templates() if t.get("id") == tpl_id), None)


def note_tpl_save(tpl):
    """新建或覆盖一个模板。有 id 且存在=改，否则新建（id 用随机短串）。"""
    name = (tpl.get("name") or "").strip()
    prompt = (tpl.get("prompt") or "").strip()
    if not name or not prompt:
        return {"ok": False, "error": "模板名称和提示词都不能为空"}
    ts = note_templates()
    tid = (tpl.get("id") or "").strip()
    hit = next((t for t in ts if t.get("id") == tid), None) if tid else None
    if hit:
        hit["name"], hit["prompt"] = name[:40], prompt
    else:
        ts.append({"id": os.urandom(5).hex(), "name": name[:40], "prompt": prompt})
    save_setting("note_templates", ts)
    return {"ok": True, "templates": ts}


def note_tpl_del(tpl_id):
    ts = note_templates()
    left = [t for t in ts if t.get("id") != tpl_id]
    if len(left) == len(ts):
        return {"ok": False, "error": "模板不存在"}
    save_setting("note_templates", left)
    return {"ok": True, "templates": left}


def cloud_chat(cfg, messages, temperature=0.3, max_tokens=None, timeout=300,
               retries=0, backoff=2.0, ignore_length=False, ceiling=65536,
               think_off=False, usage_out=None):
    """调 chat/completions（两家协议该路径通用）。失败抛 RuntimeError(带可读原因)。

    输出预算策略(重要): 默认【不传 max_tokens】, 让服务商按该模型自己的上限输出。
    这样再也不会出现"max_tokens 越界"的 400(各家上限天差地别, 客户端不该去猜), 也不
    需要维护每模型上限表。只有调用方显式传了 max_tokens 时, 才把它发出去、并保留下面
    的"截断升额"能力(比如连通性探针给个小 256)。计费按实际用量, 传不传上限都不多花钱。

    截断处理: 模型单次输出到顶会返回 finish_reason=length。
    - 自动(没传 max_tokens)时: 已经是模型自身上限, 再升也没空间 → 直接抛 Truncated,
      交给上层(精修会把「那一片」拆细重试), 不空转。
    - 显式传了 max_tokens 时: 先翻倍往上升额(最多到 ceiling)重试, 顶满仍截断才抛 Truncated。

    think_off=True 才带上"关思考"参数, 并按服务商映射: 异步任务型顶层 enable_thinking=false、
    标准兼容 reasoning_effort=minimal。调用方须先确认该模型支持关(见 cloud_think_off_for)。

    retries>0 只对"可重试"失败(限流429/网关5xx/超时/网络抖动)再打一次; 401/402/404 是配置
    问题不重试。退避线性递增(第 n 次前等 n*backoff 秒)。

    ignore_length=True 只给探针类调用: 只关心通不通, 被截断不算失败。
    usage_out 传入一个 dict 时, 用最后一次响应的 usage 填充(供探测读 reasoning_tokens)。"""
    import requests
    _cloud_check(cfg, "chat")
    auto = max_tokens is None
    last = ""
    net_left = retries               # 网络/限流类可重试次数(可耗尽)
    esc_left = 0 if auto else 2      # 只有显式传了 max_tokens 才有"升额"空间可试两次
    escalated = False                # 是否已升过额 —— 升额后服务商 HTTP 报错要兜回截断提示
    attempt = 0
    while True:
        try:
            payload = {"model": cfg["model"], "messages": messages,
                       "temperature": temperature}
            if max_tokens is not None:              # 默认不传, 交给模型自身上限(绝不越界报 400)
                payload["max_tokens"] = max_tokens
            if think_off:                       # 仅当调用方确认该模型支持关思考才带上, 按服务商映射参数
                if cfg.get("provider") == "dashscope":
                    payload["enable_thinking"] = False
                else:
                    payload["reasoning_effort"] = "minimal"
            r = requests.post(
                _chat_endpoint(cfg),
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json=payload,
                timeout=timeout)
        except requests.exceptions.Timeout:
            last = "云端请求超时"
            r = None
        except Exception as e:
            last = f"网络错误: {type(e).__name__}"
            r = None
        if r is not None:
            if r.status_code in RETRYABLE_STATUS:
                last = f"服务返回 {r.status_code}（{r.request.url}）: {r.text[:120]}"
                r = None
            else:
                # 200 → 取正文 + finish_reason; 401/402/404/其它 → 由 _cloud_ok 抛人话(不重试)
                try:
                    content, fr, usage = _cloud_ok(r, cfg)
                except RuntimeError as e:
                    # 升额后服务商反而报错(多半是该模型不支持这么高的 max_tokens): 别把
                    # 400 原文甩给用户, 低额度那次的截断本就是同一症状, 退回清晰的截断提示。
                    if escalated and str(e).startswith("服务返回"):
                        raise Truncated("模型输出已达上限被截断") from None
                    raise
                if usage_out is not None:
                    usage_out.clear()
                    usage_out.update(usage or {})
                if fr == "content_filter":
                    raise RuntimeError("内容被服务商安全策略拦截，未能生成完整结果")
                if fr == "length" and not ignore_length:
                    # 显式传了 max_tokens 才有升额空间; 自动(不传)时已是模型自身上限,
                    # 直接抛 Truncated 让精修把那片拆细重试, 别空转。
                    if (not auto) and esc_left > 0 and max_tokens < ceiling:
                        prev = max_tokens
                        max_tokens = min(ceiling, prev * 2)
                        esc_left -= 1
                        escalated = True
                        print(f"[cloud] 本片输出被截断，升额 {prev}→{max_tokens} 后重试", flush=True)
                        continue
                    raise Truncated("模型输出已达上限被截断")
                return content
        # 到这里 = 网络错误 / 可重试状态码, 需要按退避再打一次
        if net_left <= 0:
            break
        net_left -= 1
        attempt += 1
        # 重试要留痕: 日志里能看到"撞限流了"还是"网络抖了", 不然只会觉得莫名变慢
        print(f"[cloud] 第 {attempt} 次重试: {last}", flush=True)
        time.sleep(backoff * attempt)     # 线性退避: 第1次重试等 3s, 第2次等 6s
    raise RuntimeError(last + (f"（已重试 {retries} 次仍失败）" if retries else ""))


# ---------- 云端"等待识别"的速度档案 ----------
# 云端异步任务接口不给进度, 这一段只能估。估的依据是这台机器自己跑出来的历史:
# 每成功一次记一条 (音频秒数, 等待秒数), 用中位数换算"每秒音频约等几秒"。
# 没历史时给保守默认值。估算只用于百分比显示, 不参与任何判定, 也不会拿它提前收尾。
CLOUD_HIST_MAX = 12
CLOUD_WAIT_RTF = 0.35          # 兜底: 每 1 秒音频约等 0.35 秒


def cloud_wait_secs(dur):
    """估一次「等待云端识别」大概要多久(秒)。拿不到时长就返回 0 = 不估。"""
    dur = float(dur or 0)
    if dur <= 0:
        return 0.0
    hist = [h for h in (load_setting("cloud_hist") or [])
            if isinstance(h, (list, tuple)) and len(h) == 2 and float(h[0] or 0) > 0]
    if not hist:
        return dur * CLOUD_WAIT_RTF
    rates = sorted(float(h[1]) / float(h[0]) for h in hist)
    return dur * rates[len(rates) // 2]          # 中位数, 抗一次网络抖动


def cloud_hist_add(dur, waited):
    """成功一次就补一条样本, 只留最近 CLOUD_HIST_MAX 条。"""
    if float(dur or 0) <= 0 or float(waited or 0) < 0:
        return
    hist = [h for h in (load_setting("cloud_hist") or [])
            if isinstance(h, (list, tuple)) and len(h) == 2]
    hist.append([round(float(dur), 1), round(float(waited), 1)])
    save_setting("cloud_hist", hist[-CLOUD_HIST_MAX:])


# ---------- 云端转写的"结果租约": 别让一次网络抖动逼你二次付费 ----------
# 转写一旦在云端跑完, 结果就存在签名 URL 里(有效期数小时), task_id 也还能继续查。
# 之前的问题是: 最后一步下载结果时 DNS 抖一下 → 整条链路判失败 → 用户重试就是
# 重新上传 + 重新转写一遍(二次计费)。这里把 task_id / res_url 暂存下来,
# 下次重试优先"续等/续取", 只有链接真过期了才重转。
_asr_lease = {}                        # sid -> {"task_id","res_url","ts"}
_asr_lease_lock = threading.Lock()
ASR_LEASE_SECS = 6 * 3600              # 保守取 6 小时, 签名 URL 通常比这更长


def _lease_get(sid):
    if not sid:
        return {}
    with _asr_lease_lock:
        v = _asr_lease.get(sid) or {}
        if v and time.time() - float(v.get("ts") or 0) > ASR_LEASE_SECS:
            _asr_lease.pop(sid, None)
            return {}
        return dict(v)


def _lease_put(sid, **kw):
    if not sid:
        return
    with _asr_lease_lock:
        v = _asr_lease.setdefault(sid, {})
        v.update(kw)
        v["ts"] = time.time()


def _lease_drop(sid):
    if not sid:
        return
    with _asr_lease_lock:
        _asr_lease.pop(sid, None)


def _looks_expired(e):
    """判断这次失败是不是"结果链接已经失效" —— 只有这种情况才值得重新转写。"""
    s = str(e).lower()
    return any(x in s for x in ("403", "404", "expired", "accessdenied",
                                "signature", "nosuchkey", "签名", "过期"))


def cloud_err_kind(e):
    """把一坨异常文本归成几类, 前端据此决定给哪个下一步按钮。
    顺序有意: 我们自己生成的人话(模型名/密钥/余额)先判, 否则 "地址或模型名不对(404)"
    会被下面的过期规则里的 404 误吞。"""
    s = str(e)
    low = s.lower()
    if any(x in s for x in ("地址或模型名不对", "API Key 无效", "余额不足", "密钥")):
        return "config"
    if any(x in low for x in ("expired", "accessdenied", "nosuchkey", "signature",
                              "签名", "过期")) or " 403" in low:
        return "expired"
    if any(x in low for x in ("namenotknown", "resolvererror", "failed to resolve",
                              "connectionerror", "connectionpool", "timed out",
                              "timeout", "readtimeout", "unreachable", "reset by peer",
                              "remotedisconnected", "网络错误", "请求超时")):
        return "network"
    return "other"


def cloud_err_text(kind, e):
    """给人看的失败原因 —— 不再把 300 字符的 URL 堆栈甩到用户脸上。
    只说"发生了什么 + 能干什么", 不承诺具体后果(计费与否各路径不同, 由横幅按钮表达)。"""
    if kind == "network":
        return "网络不稳定，连不上或超时了。稍后再点一次即可重试。"
    if kind == "expired":
        return "云端结果链接已过期，需要重新转写一次。"
    return str(e)[:160]


def _cloud_get(url, headers=None, timeout=180, tries=4, backoff=2.0, what="请求"):
    """带重试的 GET: 只对网络异常与 408/429/5xx 重试(线性退避)。
    4xx(签名失效/无权限)重试没意义, 原样返回交给上层判。"""
    import requests
    last = ""
    for i in range(tries):
        if i:
            print(f"[cloud-asr] {what}第 {i+1} 次重试: {last}", flush=True)
            time.sleep(backoff * i)
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
        except Exception as e:
            last = f"{type(e).__name__}"
            continue
        if r.status_code in RETRYABLE_STATUS:
            last = f"HTTP {r.status_code}"
            continue
        return r
    raise RuntimeError(f"{what}连续 {tries} 次失败: {last}")


def cloud_asr(cfg, audio_path, timeout=1800, prog=None, cancel=None, sid=None):
    """云端转写总入口: 按服务商分发。这是唯一会把录音送出本机的功能,
    只能由用户显式触发。返回 {'text', 'segments'}。
    cancel: 无参回调, 在天然检查点(切块之间/轮询之间)调用, 该停就抛。
    sid: 项目 id, 用于失败后暂存 task_id/结果链接, 重试时不二次计费。"""
    _cloud_check(cfg, "asr")
    if cfg["provider"] == "dashscope":
        return _cloud_asr_dashscope(cfg, audio_path, timeout, prog, cancel, sid)
    return _cloud_asr_openai(cfg, audio_path, timeout, prog, cancel)


def _cloud_asr_openai(cfg, audio_path, timeout=1800, prog=None, cancel=None):
    """标准兼容: 一次 POST 上传文件当场拿结果。
    文件超过 ~20MB(多数接口限 25MB)时自动按 15 分钟切块顺序上传再拼回。"""
    MB = 2**20
    p = Path(audio_path)
    if p.stat().st_size <= 20 * MB:
        # 这个协议是同步一次 POST, 中途服务器不给任何进度: 只给起点和返回两点,
        # 不编造中间过程
        if prog:
            prog("上传音频中", 0.05)
        out = _cloud_asr_once(cfg, p, timeout, prog)
        if prog:
            prog("识别完成", 0.9)
        return out
    dur = probe_dur(p)
    step = 900.0
    starts = list(range(0, int(dur), step))
    if len(starts) > 1 and dur - starts[-1] < 120:
        starts.pop()                      # 收尾碎块并入上一块
    print(f"[cloud-asr] 文件 {p.stat().st_size/MB:.0f}MB 超限, 切 {len(starts)} 块上传", flush=True)
    all_segs, texts = [], []
    for k, st in enumerate(starts):
        if cancel:
            cancel()                    # 块边界 = 天然检查点
        blen = min(step, dur - st)
        ck = p.parent / f".cloud_part{k}.m4a"
        r = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{st:.3f}", "-t", f"{blen:.3f}", "-i", str(p),
             "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "aac", "-b:a", "64k",
             str(ck)], capture_output=True)
        if r.returncode != 0 or not ck.exists():
            ck.unlink(missing_ok=True)
            raise RuntimeError(f"切块{k+1}失败: " +
                               (r.stderr or b"").decode(errors="ignore").strip()[:120])
        if prog:
            # 切块路径有天然进度单位: 每块是一次真实完成的工作, 不用估
            prog(f"分段识别中（{k+1}/{len(starts)}）", 0.05 + 0.85 * k / len(starts))
        try:
            res = _cloud_asr_once(cfg, ck, timeout, prog)
            for s in res["segments"]:
                all_segs.append({"start": float(s.get("start", 0)) + st,
                                 "end": float(s.get("end", 0)) + st,
                                 "text": (s.get("text") or "").strip(),
                                 "spk": s.get("spk", "")})
            texts.append(res["text"])
        finally:
            ck.unlink(missing_ok=True)
        print(f"[cloud-asr] 块{k+1}/{len(starts)} 完成", flush=True)
    return {"text": " ".join(texts), "segments": all_segs}


# ---- 异步任务型服务商: 异步任务协议, 只收 URL 不收文件字节 ----
def _ds_base(cfg):
    """该服务商原生接口都以根域名为底 + 自己拼 /api/v1。用户常照文档把 /api/v1 或
    /compatible-mode/v1 一起粘进来, 这里统一剥掉, 避免拼成 /api/v1/api/v1。"""
    b = cfg["base_url"]
    for tail in ("/compatible-mode/v1", "/compatible-mode", "/api/v1", "/v1"):
        while b.endswith(tail):
            b = b[: -len(tail)]
    return b.rstrip("/")


def _ds_upload(cfg, path, prog=None):
    """取上传凭证 → POST 到它的 OSS → 返回 oss:// 临时地址(48h 有效, 与模型绑定)。
    prog: 可选, 收 0~100 的已上传字节百分比。"""
    import requests
    r = requests.get(
        _ds_base(cfg) + "/api/v1/uploads",
        params={"action": "getPolicy", "model": cfg["asr_model"]},
        headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"取上传凭证失败 {r.status_code}: {r.text[:140]}")
    d = (r.json() or {}).get("data") or {}
    need = ["policy", "signature", "upload_dir", "upload_host", "oss_access_key_id"]
    miss = [k for k in need if not d.get(k)]
    if miss:
        raise RuntimeError("上传凭证缺少字段: " + ",".join(miss))
    key = f"{d['upload_dir']}/{Path(path).name}"
    form = {
        "OSSAccessKeyId": (None, d["oss_access_key_id"]),
        "Signature": (None, d["signature"]),
        "policy": (None, d["policy"]),
        "key": (None, key),
    }
    if d.get("x_oss_object_acl"):
        form["x-oss-object-acl"] = (None, d["x_oss_object_acl"])
    if d.get("x_oss_forbid_overwrite"):
        form["x-oss-forbid-overwrite"] = (None, d["x_oss_forbid_overwrite"])
    form["success_action_status"] = (None, "200")
    total = Path(path).stat().st_size
    with open(path, "rb") as f:
        body = CountingReader(f, total, prog) if prog else f
        form["file"] = (Path(path).name, body, "application/octet-stream")  # 官方要求 file 必须最后
        up = requests.post(d["upload_host"], files=form, timeout=1800)
    if up.status_code not in (200, 204):
        raise RuntimeError(f"音频上传失败 {up.status_code}: {up.text[:140]}")
    return "oss://" + key


def _cloud_asr_dashscope(cfg, audio_path, timeout=1800, prog=None, cancel=None, sid=None):
    """异步任务型服务商: 上传换 URL → 提交异步任务 → 轮询 → 下载结果 JSON → 解析成段。
    说话人分离等参数由云端/模型自己决定, 端上不替它做主。
    重试时先看租约: 上次已经跑完/已经提交的, 直接续取结果或续等任务, 不再重传重转。"""
    import requests
    base, model = _ds_base(cfg), cfg["asr_model"]
    lease = _lease_get(sid)
    if lease.get("res_url"):
        print("[cloud-asr] 上次转写已完成, 直接续取结果（不重传、不重转）", flush=True)
        try:
            return _ds_fetch_parse(lease["res_url"], sid, prog)
        except Cancelled:
            raise
        except Exception as e:
            if _looks_expired(e):
                print("[cloud-asr] 结果链接已失效, 重新转写", flush=True)
                _lease_drop(sid)
            else:
                raise           # 还是网络问题: 保住租约, 再点一次即可, 不产生二次计费
    if lease.get("task_id"):
        print(f"[cloud-asr] 续等上次任务 {lease['task_id'][:12]}…（不重传、不重转）", flush=True)
        if prog:
            prog("等待云端识别", 0.24)
        return _ds_wait_parse(base, cfg, lease["task_id"], sid,
                              float(cfg.get("dur") or 0), timeout, prog, cancel)
    print(f"[cloud-asr] 异步任务协议: 上传 {Path(audio_path).name} 换临时 URL", flush=True)
    src = Path(audio_path)
    fmt = cfg.get("fmt") or asr_fmt()
    up = src
    if src.suffix.lower() != "." + fmt:
        up = src.parent / f".ds_{fmt}.{fmt}"
        to_upload(src, fmt, up)
    if prog:
        prog(f"上传音频中（{fmt}）", 0.01)
    try:
        oss_url = _ds_upload(
            cfg, up,
            prog=(lambda p: prog(None, 0.02 + 0.20 * p / 100.0)) if prog else None)
    finally:
        if up != src:
            try:
                up.unlink()
            except Exception:
                pass
    headers = {"Authorization": f"Bearer {cfg['api_key']}",
               "Content-Type": "application/json",
               "X-DashScope-Async": "enable",
               "X-DashScope-OssResourceResolve": "enable"}
    # 部分 filetrans 模型收 file_url(单数), 其余模型收 file_urls(列表)
    is_filetrans_single = model.startswith("qwen3-asr-flash-filetrans")
    inp = {"file_url": oss_url} if is_filetrans_single else {"file_urls": [oss_url]}
    body = {"model": model, "input": inp}
    # 说话人分离在该服务商侧默认关闭, 不带这个参数就永远只有纯文字(用户已确认端上固定开)。
    # 人数不写死, 交给云自动判; 部分 filetrans 模型无此参数, 传了会报错所以跳过。
    opts = cloud_asr_opts(cfg.get("lang"), cfg.get("hotwords"))
    params = {} if is_filetrans_single else {"diarization_enabled": True}
    if opts["language"]:
        params["language"] = opts["language"]          # 已知语种可显著提升准确率
    if opts["prompt"]:
        params["corpus"] = {"text": opts["prompt"]}    # 官方热词位(仅部分模型支持)
    body["parameters"] = params
    r = requests.post(base + "/api/v1/services/audio/asr/transcription",
                      headers=headers, json=body, timeout=120)
    if r.status_code != 200 and "diarization" in body.get("parameters", {}):
        # 该模型不吃这些参数 → 全去掉重发一次, 宁可没标签/没热词也要出稿
        print(f"[cloud-asr] 附加参数被拒({r.status_code}), 去掉重试", flush=True)
        body["parameters"] = {}
        r = requests.post(base + "/api/v1/services/audio/asr/transcription",
                          headers=headers, json=body, timeout=120)
    if r.status_code != 200 and looks_like_format_err(r.text) and fmt != "mp3":
        print(f"[cloud-asr] 该服务商拒了 {fmt}({r.text[:80]}), 改 mp3 重试", flush=True)
        # 换格式重传: 必须带上 sid, 否则租约丢了, 失败后就只能重传重转
        return _cloud_asr_dashscope(dict(cfg, fmt="mp3"), audio_path, timeout, prog,
                                    cancel, sid)
    if r.status_code != 200:
        hint = ""
        if r.status_code == 400 and "url error" in (r.text or "").lower():
            # 实测: 模型名填成全模态/聊天模型时也是这个报错,
            # 跟 URL 本身无关 → 不提示清楚会被误导去查地址和上传
            hint = ("｜多半是【转写模型名】不对：该模型不支持异步文件转写接口。"
                    "请改用服务商文档中支持异步文件转写的模型名")
        raise RuntimeError(f"提交任务失败 {r.status_code}{hint}: {r.text[:160]}")
    task_id = ((r.json() or {}).get("output") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("提交成功但没返回 task_id")
    # 等待段云端不给进度: 按这台机器的历史速度估一个百分比, 只用于显示、不参与判定。
    dur = float(cfg.get("dur") or 0)
    est = cloud_wait_secs(dur)
    if prog:
        prog("等待云端识别", 0.24 if est > 0 else None)
    print(f"[cloud-asr] 任务已提交 {task_id[:12]}… 轮询中", flush=True)
    _lease_put(sid, task_id=task_id)      # 记下任务号: 轮询阶段断线也能续等, 不必重传重转
    return _ds_wait_parse(base, cfg, task_id, sid, dur, timeout, prog, cancel)


def _ds_wait_parse(base, cfg, task_id, sid, dur, timeout=1800, prog=None, cancel=None):
    """轮询到 SUCCEEDED → 下载结果 JSON → 解析成段。
    单独成函数是为了"续等/续取"能直接复用: 云端任务号和签名结果链接都还在,
    没必要重新上传再转一遍 —— 那是二次计费。"""
    import requests
    est = cloud_wait_secs(dur)
    t0, res_url = time.time(), ""
    while time.time() - t0 < timeout:
        time.sleep(3)
        if cancel:
            cancel()                    # 轮询圈 = 天然检查点
        if prog and est > 0:
            prog(None, min(0.92, 0.24 + 0.68 * (time.time() - t0) / est))
        try:
            q = _cloud_get(base + "/api/v1/tasks/" + task_id,
                           headers={"Authorization": f"Bearer {cfg['api_key']}"},
                           timeout=60, tries=3, what="查询任务")
        except Cancelled:
            raise
        except Exception as e:
            # 任务还在云端跑, 查询抖一下不该判死整条 —— 下一圈再试就是
            print(f"[cloud-asr] 查询任务暂时失败({type(e).__name__}), 继续等", flush=True)
            continue
        if q.status_code == 405:      # 个别文档写 POST, 兜一下
            q = requests.post(base + "/api/v1/tasks/" + task_id,
                              headers={"Authorization": f"Bearer {cfg['api_key']}"},
                              timeout=60)
        if q.status_code != 200:
            raise RuntimeError(f"查询任务失败 {q.status_code}: {q.text[:140]}")
        out = (q.json() or {}).get("output") or {}
        st = str(out.get("task_status") or "").upper()
        if st == "SUCCEEDED":
            # 结果链接在不同模型/版本下挂过三个位置, 逐个兜: result / results[0] / output 顶层
            cand = [out.get("result"), (out.get("results") or [None])[0], out]
            res_url = next((c.get("transcription_url") for c in cand
                            if isinstance(c, dict) and c.get("transcription_url")), "")
            break
        if st in ("FAILED", "UNKNOWN", "CANCELED"):
            _lease_drop(sid)
            raise RuntimeError("云端任务失败: " + str(out.get("message") or st)[:140])
    else:
        raise RuntimeError("云端任务超时未完成")
    cloud_hist_add(dur, time.time() - t0)        # 攒一条样本, 下一次估得更准
    if not res_url:
        raise RuntimeError("任务成功但没给结果文件地址")
    _lease_put(sid, res_url=res_url)    # 链接先落盘再下载: 下载失败时下次能直接续取
    return _ds_fetch_parse(res_url, sid, prog)


def _ds_fetch_parse(res_url, sid=None, prog=None):
    """下载并解析结果 JSON。失败时保留租约(链接通常还有效), 下次重试不重转。"""
    if prog:
        prog("下载识别结果", 0.94)
    jr = _cloud_get(res_url, timeout=180, tries=4, backoff=2.0, what="下载结果")
    if jr.status_code != 200:
        raise RuntimeError(f"下载结果失败 {jr.status_code}")
    j = jr.json()
    segs, texts = [], []
    for tr in (j.get("transcripts") or []):
        texts.append(tr.get("text") or "")
        for s in (tr.get("sentences") or []):
            spk_id = s.get("speaker_id")     # 不叫 sid: 与项目 id 撞名会带歪租约操作
            segs.append({"start": round(float(s.get("begin_time", 0)) / 1000, 2),
                         "end": round(float(s.get("end_time", 0)) / 1000, 2),
                         "text": (s.get("text") or "").strip(),
                         "spk": ("" if spk_id is None else f"S{int(spk_id) + 1:02d}")})
    if not segs and not any(texts):
        raise RuntimeError("结果文件里没有识别内容")
    print(f"[cloud-asr] 该服务商完成: {len(segs)} 句", flush=True)
    _lease_drop(sid)                          # 稿子到手, 租约使命完成
    return {"text": " ".join(t for t in texts if t), "segments": segs}


def _asr_form(cfg):
    """标准兼容 /audio/transcriptions 的表单参数。"""
    opts = cloud_asr_opts(cfg.get("lang"), cfg.get("hotwords"))
    form = {"model": cfg.get("asr_model") or cfg["model"],
            "response_format": "verbose_json"}
    if opts["language"]:
        form["language"] = opts["language"]
    if opts["prompt"]:
        form["prompt"] = opts["prompt"]          # whisper 系的热词位
    return form


def _cloud_asr_once(cfg, audio_path, timeout=1800, prog=None):
    """单文件一次上传(先转成所选上传格式)。"""
    import requests
    src = Path(audio_path)
    fmt = cfg.get("fmt") or asr_fmt()
    tmp = src.parent / f".up_{fmt}{('.' + fmt) if fmt != 'ogg' else '.ogg'}"
    if fmt == "m4a" and src.suffix.lower() == ".m4a":
        up = src                                   # 本来就是 m4a, 不折腾
    else:
        to_upload(src, fmt, tmp)
        up = tmp
    print(f"[cloud-asr] 上传格式 {fmt} · {up.name} · {up.stat().st_size/2**20:.1f} MB",
          flush=True)
    try:
        with open(up, "rb") as f:
            r = requests.post(
                cfg["base_url"] + "/audio/transcriptions",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                files={"file": (up.name, f, ASR_FMT[fmt][1])},
                data=_asr_form(cfg),
                timeout=timeout)
    except requests.exceptions.Timeout:
        raise RuntimeError("云端转写超时（大文件/慢接口，可稍后重试）")
    except Exception as e:
        raise RuntimeError(f"上传失败: {type(e).__name__}")
    if r.status_code == 404:
        # 实测火山方舟 /audio/transcriptions 是存在的(不带 key 返回 401), 带 key 却 404
        # 基本是模型名不对 —— 把对话模型填进了转写框。文案不能一口咬定"接口不存在"
        raise RuntimeError("404：多半是【转写模型名】不对（把对话模型填进了转写框），"
                           "也可能是该服务的音频接口路径不同。原文：" + r.text[:180])
    if r.status_code in (400, 415) and looks_like_format_err(r.text) and fmt != "m4a":
        # 该格式被拒 → 换一种格式重试一次, 并把结果记进日志
        alt = "m4a" if fmt != "m4a" else "mp3"
        print(f"[cloud-asr] {fmt} 被拒({r.text[:80]}), 改用 {alt} 重试", flush=True)
        if prog:
            prog(f"换 {alt} 格式重传")
        cfg2 = dict(cfg, fmt=alt)
        return _cloud_asr_once(cfg2, audio_path, timeout, prog)
    if r.status_code == 401:
        raise RuntimeError("API Key 无效(401)")
    if r.status_code == 402:
        raise RuntimeError("余额不足(402)")
    if r.status_code != 200:
        raise RuntimeError(f"服务返回 {r.status_code}: {r.text[:160]}")
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        j = r.json()
    except Exception:
        raise RuntimeError("返回不是 JSON")
    if not isinstance(j, dict) or not (j.get("text") or j.get("segments")):
        raise RuntimeError("返回里没有转写内容")
    return {"text": (j.get("text") or "").strip(),
            "segments": j.get("segments") or []}


def _cloud_ok(r, cfg):
    """HTTP 状态码 → 人话错误; 200 时返回 (message 文本, finish_reason, usage)。
    长度截断/安全拦截不在此处报错，交给调用方 cloud_chat 判断(可升额重试或大声失败)。
    usage 一并回传, 供"这模型到底会不会思考"的探测读 reasoning_tokens。"""
    if r.status_code == 401:
        raise RuntimeError("API Key 无效(401)")
    if r.status_code == 402:
        raise RuntimeError("余额不足(402)")
    if r.status_code == 404:
        raise RuntimeError("地址或模型名不对(404)：" + r.request.url)
    if r.status_code != 200:
        raise RuntimeError(f"服务返回 {r.status_code}（{r.request.url}）: {r.text[:160]}")
    try:
        data = r.json()
        ch = data["choices"][0]
        # 每次成功调用留一行痕: 以后再出"截断/变短"的问题, 日志里有据可查
        u = data.get("usage") or {}
        fr = ch.get("finish_reason")
        print(f"[cloud] finish={fr}"
              f" in={u.get('prompt_tokens', '?')} out={u.get('completion_tokens', '?')}"
              f" think={((u.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0)}",
              flush=True)
        return (ch["message"]["content"] or "").strip(), fr, u
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("返回格式不是标准兼容转写结构")


# 输出设备名不再写死: 启动时探测本机真实设备, 设置里可手动指定。
# 这个常量只作为"什么都探测不到"时的最后兜底。
BUILTIN_FALLBACK = "MacBook Pro扬声器"
_VIRT_OUT_PAT = re.compile(r"blackhole|多输出|multi-?output|聚合|aggregate", re.I)
LANG_MAP = {"zh": "zh", "en": "en", "auto": ""}
MODE_LABELS = {"mix": "系统声音+麦克风", "system": "仅系统声音", "mic": "仅麦克风",
               "import": "导入文件"}


def fmt_ts(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def list_audio_devices():
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=15).stderr
    except Exception:
        return []
    devs, in_audio = [], False
    for line in out.splitlines():
        if "audio devices:" in line:
            in_audio = True
            continue
        if in_audio:
            m = re.search(r"\[(\d+)\] (.+)$", line.strip())
            if m:
                devs.append((int(m.group(1)), m.group(2).strip()))
    return devs


def _trash_name(dst_dir: Path, name: str) -> Path:
    """回收站里已有同名条目就加时间戳，绝不覆盖用户可能还在的东西"""
    dst = dst_dir / name
    if not dst.exists():
        return dst
    return dst_dir / f"{Path(name).stem}-{time.strftime('%Y%m%d-%H%M%S')}{Path(name).suffix}"


def to_trash(p: Path):
    """把文件或整个文件夹移到系统回收站。成功返回落地位置(字符串)，失败抛 RuntimeError。

    铁律：这里没有任何"失败就硬删"的兜底 —— 移不进回收站就报错，让界面如实显示，
    由用户决定怎么办。宁可删不掉，不可悄悄删干净。
    三平台各走原生入口，都不需要额外安装（听道要发给 Windows 用户，不能新增依赖）。"""
    import shutil
    p = Path(p)
    if not p.exists():
        raise RuntimeError("要删除的东西不存在或已被移走")
    name = p.name
    if platform.system() == "Windows":
        # Windows 没有可靠的"搬进目录"写法，走系统自带的 VisualBasic 回收站接口
        kind = "Directory" if p.is_dir() else "File"
        ps = ("Add-Type -AssemblyName Microsoft.VisualBasic;"
              f"[Microsoft.VisualBasic.FileIO.FileSystem]::Delete{kind}"
              f"('{p}','OnlyErrorDialogs','SendToRecycleBin')")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=60)
        except Exception as e:
            raise RuntimeError(f"调用回收站失败：{type(e).__name__}")
        if not p.exists():
            return "回收站"
        raise RuntimeError("没能移到回收站：" + ((r.stderr or r.stdout or "").strip()[:180]
                                               or "系统拒绝了这次操作"))
    if platform.system() == "Linux":
        gio = shutil.which("gio")
        if gio:
            try:
                r = subprocess.run([gio, "trash", str(p)], capture_output=True,
                                   text=True, timeout=60)
            except Exception as e:
                raise RuntimeError(f"调用回收站失败：{type(e).__name__}")
            if not p.exists():
                return "回收站"
            raise RuntimeError("没能移到回收站：" + ((r.stderr or "").strip()[:180]
                                                   or "gio 拒绝了这次操作"))
        dst_dir = Path.home() / ".local/share/Trash/files"
    else:
        dst_dir = Path.home() / ".Trash"
    # macOS / 无 gio 的 Linux：直接搬进回收站目录。不走 Finder，免得首次使用弹自动化授权
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = _trash_name(dst_dir, name)
        shutil.move(str(p), str(dst))
    except Exception as e:
        raise RuntimeError(f"没能移到废纸篓：{e}")
    if p.exists():
        raise RuntimeError("移入废纸篓后原位置仍存在，已停止删除")
    return str(dst)


def probe_dur(path):
    """用 ffprobe 取媒体时长(秒), 失败返回 0"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def find_device(patterns):
    devs = list_audio_devices()
    for pat in patterns:
        for idx, name in devs:
            if pat.lower() in name.lower():
                return idx
    return None


_OUT_CACHE = {}


def list_output_devices():
    """系统输出设备清单"""
    try:
        r = subprocess.run(["SwitchAudioSource", "-a", "-t", "output"],
                           capture_output=True, text=True, timeout=10)
        return [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
    except Exception:
        return []


def current_output():
    """当前系统默认输出"""
    try:
        r = subprocess.run(["SwitchAudioSource", "-c", "-t", "output"],
                           capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def boot_output():
    """进程刚起来时的系统默认输出 —— 这是"录完该切回哪儿"最可靠的答案"""
    if "boot" not in _OUT_CACHE:
        _OUT_CACHE["boot"] = current_output()
    return _OUT_CACHE["boot"]


def detect_restore():
    """录制结束后切回的本机输出: 优先启动时的默认输出(排除 BlackHole/多输出等
    虚拟设备), 再按名称猜扬声器 / 耳机, 最后退回任意一个非虚拟设备"""
    devs = list_output_devices()
    for cand in (boot_output(), current_output()):
        if cand and not _VIRT_OUT_PAT.search(cand):
            return cand
    for pat in (r"扬声器|speakers", r"耳机|headphone"):
        for d in devs:
            if re.search(pat, d, re.I) and not _VIRT_OUT_PAT.search(d):
                return d
    for d in devs:
        if not _VIRT_OUT_PAT.search(d):
            return d
    return BUILTIN_FALLBACK


def detect_monitor():
    """录制期间的监听输出 —— 严格只认「多输出设备/Multi-Output Device」。
    不能把「聚合设备」当候选: 它是 mix 模式的采集输入(见 _capture_device),
    误选会把输出劈到输入设备上。探测不到就返回空串(录制时不切换输出),
    用户仍可在设置面板里手动指定任意设备。"""
    for d in list_output_devices():
        if re.search(r"多输出|multi-?output", d, re.I):
            return d
    return ""


def output_restore():
    return (load_setting("output_restore") or "").strip() or detect_restore()


def output_monitor():
    return (load_setting("output_monitor") or "").strip() or detect_monitor()


def mic_device():
    """设置里手动指定的麦克风名('' = 系统默认输入)。SCK 助手与仅麦克风模式共用。"""
    return (load_setting("mic_device") or "").strip()


def _win_mic_names():
    """Windows 麦克风名单 + 默认输入名(给设置面板的下拉用)。
    pyaudiowpatch 没装就返回空 —— 录音启动时会有明确的中文报错, 这里不打扰界面。"""
    try:
        import pyaudiowpatch as pyaudio
    except Exception:
        return [], ""
    names, dflt = [], ""
    p = None
    try:
        p = pyaudio.PyAudio()
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.const.WASAPI)
            lo, hi = wasapi["deviceIndex"], wasapi["deviceIndex"] + wasapi["deviceCount"]
        except Exception:
            lo, hi = 0, p.get_device_count()
        for i in range(lo, hi):
            try:
                info = p.get_device_info_by_index(i)
            except Exception:
                continue
            if int(info.get("maxInputChannels", 0) or 0) <= 0:
                continue
            if info.get("isLoopbackDevice"):
                continue                      # 环回设备是"系统声"入口, 不当麦列
            nm = (info.get("name") or "").strip()
            if nm and nm not in names:
                names.append(nm)
        dflt = (p.get_default_input_device_info() or {}).get("name", "").strip()
    except Exception:
        pass
    finally:
        if p:
            try:
                p.terminate()
            except Exception:
                pass
    return names, dflt


def _pcm_to_sr_mono(data: bytes, rate: int, channels: int):
    """int16 PCM(设备原生采样率/多声道) → float32 SR 单声道, 供混音泵消费。
    线性插值重采样对语音足够(下游本来也统一按 SR 走 ASR)。"""
    a = np.frombuffer(data, dtype=np.int16)
    if a.size == 0:
        return np.zeros(0, dtype=np.float32)
    c = max(int(channels), 1)
    n = a.size // c
    a = a[:n * c].reshape(n, c).astype(np.float32).mean(axis=1) if c > 1 \
        else a.astype(np.float32)
    a *= 1.0 / 32768.0
    if rate and rate != SR and n > 1:
        idx = np.linspace(0.0, n - 1.0, max(int(n * SR / rate), 1))
        a = np.interp(idx, np.arange(n), a).astype(np.float32)
    return a


# 预处理档位。注意 afftdn 的合法参数是 nr/nf（不是 n=）——
# 曾误写成 afftdn=n=-24, ffmpeg 直接报 Option not found, 导致预处理静默失效。
PRETREAT_FILTERS = {
    "light":  "highpass=f=80,loudnorm=I=-16:TP=-1.5",
    "strong": "highpass=f=80,afftdn=nr=12:nf=-30,loudnorm=I=-16:TP=-1.5",
}


LISTEN_FILE = "audio_listen.m4a"
# 回放专用链: 降噪 + 高通 + 响度归一, 固定用这条、不看设置档位 —— 这样即使
# 「音频预处理」设在关闭, 回放也永远比原始音频好懂。转写用的母本(audio.m4a)
# 在停录时按档位处理, 两份各司其职、互不污染。
LISTEN_FILTER = "highpass=f=80,afftdn=nr=12:nf=-30,loudnorm=I=-16:TP=-1.5"


def encode_listen(src, dst, input_opts=None):
    """生成降噪回放副本。
    input_opts 必须放在 -i **之前**: raw.s16 是没有文件头的裸数据, 把它写在 -i
    后面就成了输出选项, ffmpeg 认不出输入格式, 直接报
    "Invalid data found when processing input" 退出 —— 旧代码正是这么写的,
    于是"结束录音"的回放降噪副本从来没成功过(导入路径不传这些参数所以一直是好的)。
    失败清掉半成品、返回 (None, 报错原文), 由上层记下来, 不静默吞掉。
    统一 16kHz 单声道 64k —— 目标是"能听清谁在说什么", 不做音乐级保真。"""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    cmd += (input_opts or [])
    cmd += ["-i", str(src), "-vn", "-af", LISTEN_FILTER, "-ar", str(SR), "-ac", "1",
            "-c:a", "aac", "-b:a", "64k", str(dst)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=1800)
    except Exception as e:
        r = None
        msg = str(e)
    else:
        msg = ((r.stderr or b"").decode(errors="ignore").strip().splitlines()
               or [""])[-1][:300] if r is not None else ""
    if (r is None or r.returncode != 0) or not dst.exists() or dst.stat().st_size < 1024:
        try:
            dst.unlink()
        except Exception:
            pass
        print(f"[listen] ⚠ 降噪回放副本生成失败: {msg}", flush=True)
        return None, (msg or "ffmpeg 未产出文件")
    return dst.name, ""


def pretreat_chain():
    """返回要用的滤镜链, None=不预处理。兼容旧的布尔开关(true→strong)。"""
    v = load_setting("pretreat")
    if isinstance(v, bool):
        v = "strong" if v else "off"
    v = (v or "off").strip().lower()
    return PRETREAT_FILTERS.get(v)


# ---------------- 设备音量（CoreAudio 直控） ----------------
# 为什么不用系统音量: 录音时默认输出被切到「多输出设备」, 它没有 volm 属性,
# 系统音量键因此变灰。但那台真实扬声器仍有自己可写的 volm —— 直接写它即可。
# fourcc 一律从 SDK Headers 取, 不可猜: 默认输出=dOut 音量=volm 设备名=lnam
import ctypes


def _fcc(s):
    return int.from_bytes(s.encode()[:4].ljust(4, b"\0"), "big")


class _CAAddr(ctypes.Structure):
    _fields_ = [("sel", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("elem", ctypes.c_uint32)]


_CA_SYS = 1
_SEL_VOLM, _SEL_LNAM, _SEL_DEV, _SEL_DOUT = _fcc("volm"), _fcc("lnam"), _fcc("dev#"), _fcc("dOut")
_SEL_STRM, _SEL_DIN, _SEL_SLAY = _fcc("str#"), _fcc("dIn "), _fcc("slay")
_SCOPE_GLOB, _SCOPE_OUTP, _SCOPE_INP = _fcc("glob"), _fcc("outp"), _fcc("inpt")
_ca_cache = {}


def _ca():
    if "lib" not in _ca_cache:
        _ca_cache["lib"] = ctypes.CDLL(
            "/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        _ca_cache["cf"] = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    return _ca_cache["lib"], _ca_cache["cf"]


def _ca_get(dev, sel, scope, elem, typ):
    ca, _ = _ca()
    a = _CAAddr(sel, scope, elem)
    sz = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(dev, ctypes.byref(a), 0, None, ctypes.byref(sz)):
        return None
    if not sz.value:
        return None
    v = typ()
    if ca.AudioObjectGetPropertyData(dev, ctypes.byref(a), 0, None, ctypes.byref(sz), ctypes.byref(v)):
        return None
    return v.value


def ca_device_name(dev_id):
    _, cf = _ca()
    ref = _ca_get(dev_id, _SEL_LNAM, _SCOPE_GLOB, 0, ctypes.c_void_p)
    if not ref:
        return ""
    cf.CFStringGetLength.restype = ctypes.c_size_t
    cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char),
                                      ctypes.c_size_t, ctypes.c_uint32]
    n = cf.CFStringGetLength(ctypes.c_void_p(ref))
    buf = ctypes.create_string_buffer(4 * n + 8)
    name = ""
    if cf.CFStringGetCString(ctypes.c_void_p(ref), buf, len(buf), 0x08000100):
        name = buf.value.decode("utf-8", "ignore")
    cf.CFRelease(ctypes.c_void_p(ref))
    return name


def ca_output_devices():
    """{设备名: deviceID}（只收有输出声道的设备）"""
    ca, _ = _ca()
    a = _CAAddr(_SEL_DEV, _SCOPE_GLOB, 0)
    sz = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(_CA_SYS, ctypes.byref(a), 0, None, ctypes.byref(sz)):
        return {}
    cnt = sz.value // 4
    if cnt <= 0:
        return {}
    buf = (ctypes.c_uint32 * cnt)()
    if ca.AudioObjectGetPropertyData(_CA_SYS, ctypes.byref(a), 0, None, ctypes.byref(sz), buf):
        return {}
    out = {}
    for did in buf:
        if _ca_get(did, _SEL_VOLM, _SCOPE_OUTP, 0, ctypes.c_float) is None:
            continue                      # 没有输出音量属性 = 输入设备或纯虚拟设备
        nm = ca_device_name(did)
        if nm:
            out[nm] = did
    return out


def ca_input_devices():
    """{设备名: deviceID}（只收有输入声道的设备, 供设置里的麦克风选择）。
    输入能力用 slay(StreamConfiguration) 探: 空的 AudioBufferList 是 8 字节,
    >8 = 有输入流。str# 在 macOS 27 上对全部设备回 'what', 不可用(实测)。"""
    ca, _ = _ca()
    a = _CAAddr(_SEL_DEV, _SCOPE_GLOB, 0)
    sz = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(_CA_SYS, ctypes.byref(a), 0, None, ctypes.byref(sz)):
        return {}
    cnt = sz.value // 4
    if cnt <= 0:
        return {}
    buf = (ctypes.c_uint32 * cnt)()
    if ca.AudioObjectGetPropertyData(_CA_SYS, ctypes.byref(a), 0, None, ctypes.byref(sz), buf):
        return {}
    out = {}
    for did in buf:
        s = _CAAddr(_SEL_SLAY, _SCOPE_INP, 0)
        ssz = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(did, ctypes.byref(s), 0, None, ctypes.byref(ssz)):
            continue
        if ssz.value <= 8:                # 空 AudioBufferList = 没有输入流
            continue
        nm = ca_device_name(did)
        if nm:
            out[nm] = did
    return out


def ca_default_input():
    """系统当前默认输入设备的名字"""
    d = _ca_get(_CA_SYS, _SEL_DIN, _SCOPE_GLOB, 0, ctypes.c_uint32)
    return ca_device_name(d) if d else ""


def ca_get_volume(dev_id):
    v = _ca_get(dev_id, _SEL_VOLM, _SCOPE_OUTP, 0, ctypes.c_float)
    return None if v is None else float(v)


def ca_set_volume(dev_id, pct):
    """写设备 master 音量。只写 volm 一个属性, 不碰路由/采样率/声道/静音位。"""
    ca, _ = _ca()
    v = ctypes.c_float(max(0.0, min(1.0, float(pct) / 100.0)))
    a = _CAAddr(_SEL_VOLM, _SCOPE_OUTP, 0)
    return ca.AudioObjectSetPropertyData(dev_id, ctypes.byref(a), 0, None,
                                         ctypes.c_uint32(4), ctypes.byref(v)) == 0


def volume_target():
    """音量按钮的作用对象: 优先设置里的「本机输出」, 失效则退到任一台非虚拟可控设备"""
    devs = ca_output_devices()
    want = output_restore()
    if want in devs:
        return devs[want], want
    for nm, did in devs.items():
        if not _VIRT_OUT_PAT.search(nm):
            return did, nm
    return None, want


def volume_state():
    # 音量直控走 CoreAudio(ca_*), 是 macOS 专属能力; 其它平台如实报"不可控"而不是崩。
    if platform.system() != "Darwin":
        return {"device": "", "volume": None, "writable": False}
    did, nm = volume_target()
    v = None if did is None else ca_get_volume(did)
    return {"device": nm, "volume": None if v is None else int(round(v * 100)),
            "writable": v is not None}


def volume_set(pct):
    did, nm = volume_target()
    if did is None:
        raise RuntimeError("未找到可控制音量的输出设备")
    if not ca_set_volume(did, pct):
        raise RuntimeError("写入设备音量失败")
    return {"ok": True, "volume": int(round(max(0, min(100, float(pct))))), "device": nm}


def switch_output(name):
    try:
        return subprocess.run(["SwitchAudioSource", "-s", name],
                              capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def parse_wordlist(raw):
    """热词串解析: 换行/逗号/顿号分隔, 去空去重"""
    out = []
    for tok in re.split(r"[\n,，、]", raw or ""):
        t = tok.strip()
        if t and t not in out:
            out.append(t)
    return out


TEMPLATES_FILE = DATA_DIR / ".hotword-templates.json"


def load_templates():
    """热词模板库: {templates:[{id,name,words[]}], active}
    首次调用自动把旧 .hotwords.txt 迁移为「默认」模板"""
    try:
        data = json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
        if isinstance(data.get("templates"), list):
            return data
    except Exception:
        pass
    old = []
    try:
        old = parse_wordlist(HOTWORDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    data = {"templates": [{"id": "default", "name": "默认", "words": old}],
            "active": "default"}
    save_templates(data)
    return data


def save_templates(data):
    TEMPLATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                              encoding="utf-8")


GROUPS_FILE = DATA_DIR / ".groups.json"


def load_groups():
    """分组的顺序、折叠态、以及每组的标签颜色(macOS 风格)。组成员关系不存这里 ——
    在每个项目的 session.json group 字段里, 这样单个项目文件夹拷走也带着自己的组名。"""
    try:
        d = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
        raw = d.get("colors")
        colors = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        return {"order": [str(x) for x in (d.get("order") or [])],
                "collapsed": [str(x) for x in (d.get("collapsed") or [])],
                "colors": colors}
    except Exception:
        return {"order": [], "collapsed": [], "colors": {}}


def save_groups(data):
    GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GROUPS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                           encoding="utf-8")


def load_hotwords():
    """当前激活模板的热词(复核时注入 Whisper)"""
    data = load_templates()
    for t in data["templates"]:
        if t.get("id") == data.get("active"):
            return t.get("words") or []
    return []


# ---------------- 转写引擎 ----------------
def whisper_model():
    """Whisper 模型目录必须用户在 设置→本地模型 里配置(分发口径: 不内置默认)。
    未配置返回 None, 各入口见到 None 明确报错 —— 绝不兜底到某台机器的私人路径。
    保存前有 /api/model_check 把关: 指错目录会被 mlx 当成 HF repo id 联网下载大模型。"""
    v = (load_setting("whisper_model") or "").strip()
    return Path(v).expanduser() if v else None


class Engine:
    """双引擎: SenseVoice(默认,快而准) / Whisper(疑难音频兜底)。
    VAD 断句两引擎共用; recognize 按当前引擎分发。"""

    def __init__(self):
        self.engine_name = "sensevoice"
        self._sv = None
        self._wh = None
        self._wh_lock = threading.Lock()
        self.vad = None
        self._load_sensevoice()

    def _load_sensevoice(self):
        d = sv_model_dir()
        if d is None:
            return          # 未配置: 启动不炸, 到 start() 再明确报错
        self._sv = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(d / "model.int8.onnx"),
            tokens=str(d / "tokens.txt"),
            num_threads=4, language="zh", use_itn=True)

    def switch(self, name):
        """切换引擎(仅 idle 时调用); 惰性加载 whisper"""
        if name not in ("sensevoice", "whisper"):
            raise RuntimeError("未知引擎")
        wm = whisper_model()
        if name == "whisper" and (wm is None or not wm.exists()):
            raise RuntimeError("未配置 Whisper 模型：设置 → 本地模型")
        if name == "whisper" and self._wh is None:
            import mlx_whisper  # 惰性导入, 避免拖慢启动
            self._wh = True
        self.engine_name = name
        return name

    def new_vad(self):
        # 低延迟参数: 更短的静音即切句, 长句超过 max_speech 强制吐字, 更接近实时
        vp = vad_model_path()
        if vp is None:
            raise RuntimeError("未配置 VAD 模型：设置 → 本地模型（指向 silero_vad.onnx）")
        sv = sherpa_onnx.SileroVadModelConfig(model=str(vp))
        sv.threshold = 0.4
        sv.min_silence_duration = 0.25
        sv.min_speech_duration = 0.2
        sv.max_speech_duration = 6
        self.vad = sherpa_onnx.VoiceActivityDetector(
            config=sherpa_onnx.VadModelConfig(
                silero_vad=sv,
                sample_rate=SR, debug=False),
            buffer_size_in_seconds=120)

    def recognize(self, samples, lang):
        if self.engine_name == "whisper":
            return self._recognize_whisper(samples, lang)
        return self._recognize_sensevoice(samples, lang)

    def _recognize_sensevoice(self, samples, lang):
        self._sv.set_language(LANG_MAP.get(lang, "")) if hasattr(self._sv, "set_language") else None
        stream = self._sv.create_stream()
        stream.accept_waveform(SR, samples)
        self._sv.decode_stream(stream)
        return (stream.result.text or "").strip()

    def _recognize_whisper(self, samples, lang):
        import contextlib, io
        import mlx_whisper
        kw = dict(path_or_hf_repo=str(whisper_model()), verbose=False,
                  condition_on_previous_text=False)
        if lang and lang != "auto":
            kw["language"] = lang
        with contextlib.redirect_stderr(io.StringIO()):
            r = mlx_whisper.transcribe(samples, **kw)
        return (r.get("text") or "").strip()


ENGINE = Engine()

# ---------------- 应用状态 ----------------
class WinRec:
    """Windows 系统级录音: WASAPI loopback 采系统声 + WASAPI 采麦克风,
    线程内 numpy 混成 SR 单声道, 匿名管道吐 s16le —— 与 ffmpeg 的 stdout 协议一致。
    不需要任何虚拟声卡: loopback 是 Windows 自带的音频环回(对标 mac 的 SCK)。

    接口刻意做成 subprocess.Popen 同形(stdout/stderr/poll/send_signal/wait/kill),
    所以 _read_loop / _ffmpeg_err_loop / _kill_ffmpeg_sync 那套一行不改就能共用。
    设备打不开/缺依赖在 __init__ 里同步抛中文 RuntimeError → start() 返回 400 弹错,
    不会留下半死会话。"""

    TICK = 0.02    # 混音泵一拍的秒数

    def __init__(self, mode, mic_name=""):
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            raise RuntimeError("Windows 缺少 pyaudiowpatch：请在听道的 venv 里 pip install pyaudiowpatch")
        self.mode = mode
        self.returncode = None
        self._lk = threading.Lock()
        self._q = {"sys": deque(), "mic": deque()}
        self._res = {"sys": None, "mic": None}   # 一拍多出来的零头, 留到下拍
        self._stop = threading.Event()
        self._streams = []
        r, w = os.pipe()
        self.stdout = os.fdopen(r, "rb")
        self._w = os.fdopen(w, "wb")
        er, ew = os.pipe()
        self.stderr = os.fdopen(er, "rb")
        self._ew = os.fdopen(ew, "w", encoding="utf-8", errors="replace")
        self._pa = pyaudio.PyAudio()
        try:
            self._open_streams(pyaudio, mic_name)
        except Exception:
            self._close_pipes()
            try:
                self._pa.terminate()
            except Exception:
                pass
            raise
        self._pth = threading.Thread(target=self._pump_loop, daemon=True)
        self._pth.start()

    def log(self, s):
        try:
            self._ew.write(f"[winrec] {s}\n")
            self._ew.flush()
        except Exception:
            pass

    def _wasapi_range(self, pyaudio):
        try:
            w = self._pa.get_host_api_info_by_type(pyaudio.const.WASAPI)
            return int(w["deviceIndex"]), int(w["deviceIndex"] + w["deviceCount"])
        except Exception:
            return 0, self._pa.get_device_count()

    def _open_streams(self, pyaudio, mic_name):
        lo, hi = self._wasapi_range(pyaudio)
        try:
            out_name = self._pa.get_default_output_device_info()["name"]
        except Exception:
            out_name = ""
        try:
            mic_dflt = self._pa.get_default_input_device_info()["name"]
        except Exception:
            mic_dflt = ""
        loop, mics = None, []
        for i in range(lo, hi):
            try:
                info = self._pa.get_device_info_by_index(i)
            except Exception:
                continue
            if int(info.get("maxInputChannels", 0) or 0) <= 0:
                continue
            nm = (info.get("name") or "").strip()
            if info.get("isLoopbackDevice"):
                # 环回设备名 = "<渲染设备名> [Loopback]"; 优先默认输出那台的
                if loop is None or (out_name and nm.startswith(out_name)):
                    loop = info
            else:
                mics.append(info)
        mic = None
        if mics:
            if mic_name:
                mic = next((m for m in mics
                            if mic_name.lower() in (m.get("name") or "").lower()), None)
            mic = mic or next((m for m in mics
                               if (m.get("name") or "").strip() == mic_dflt.strip()), mics[0])
        want_sys = self.mode in ("mix", "system")
        want_mic = self.mode in ("mix", "mic")
        if want_sys and loop is None:
            raise RuntimeError("未找到 WASAPI 环回设备，系统声音内录不可用（检查 Windows 音频服务/声卡驱动）")
        if want_mic and mic is None:
            raise RuntimeError("找不到任何麦克风输入设备")
        for key, info in (("sys", loop if want_sys else None),
                          ("mic", mic if want_mic else None)):
            if info is None:
                continue
            rate = int(info.get("defaultSampleRate") or 48000)
            chans = min(int(info["maxInputChannels"]), 2)

            def cb(in_data, frame_count, time_info, status, key=key, rate=rate, chans=chans):
                try:
                    arr = _pcm_to_sr_mono(in_data, rate, chans)
                    if arr.size:
                        with self._lk:
                            self._q[key].append(arr)
                except Exception as e:
                    self.log(f"{key} 回调异常: {e}")
                return (None, pyaudio.paContinue)

            st = self._pa.open(format=pyaudio.paInt16, channels=chans, rate=rate,
                               input=True, frames_per_buffer=1024,
                               input_device_index=int(info["index"]),
                               stream_callback=cb)
            self._streams.append(st)
            self.log(f"{key} device → {info.get('name')} ({chans}ch {rate}Hz)")
        self.log("ready")

    def _take(self, key, n):
        """取一拍需要的 n 个样本; 零头回库存着, 不足补静音(设备时钟抖动的兜底)"""
        parts, got = [], 0
        r = self._res[key]
        if r is not None and r.size:
            parts.append(r)
            got += r.size
            self._res[key] = None
        while got < n:
            with self._lk:
                q = self._q[key]
                arr = q.popleft() if q else None
            if arr is None:
                break
            parts.append(arr)
            got += arr.size
        if not parts:
            return np.zeros(n, dtype=np.float32)
        cat = np.concatenate(parts) if len(parts) > 1 else parts[0]
        if cat.size >= n:
            self._res[key] = cat[n:] if cat.size > n else None
            return cat[:n]
        out = np.zeros(n, dtype=np.float32)
        out[:cat.size] = cat
        return out

    def _pump_loop(self):
        n = int(SR * self.TICK)
        want_sys = self.mode in ("mix", "system")
        want_mic = self.mode in ("mix", "mic")
        try:
            while not self._stop.wait(self.TICK):
                acc = self._take("sys", n) if want_sys else None
                if want_mic:
                    m = self._take("mic", n)
                    acc = m if acc is None else acc + m
                if acc is None:
                    continue
                np.clip(acc, -1.0, 1.0, out=acc)
                self._w.write((acc * 32767.0).astype(np.int16).tobytes())
        except Exception as e:
            self.log(f"泵线程退出: {e}")
        finally:
            self._shutdown()

    def _shutdown(self):
        for s in self._streams:
            try:
                s.stop_stream()
                s.close()
            except Exception:
                pass
        try:
            self._pa.terminate()
        except Exception:
            pass
        self._close_pipes()
        self.returncode = 0

    def _close_pipes(self):
        for f in (getattr(self, "_w", None), getattr(self, "_ew", None)):
            try:
                if f:
                    f.close()
            except Exception:
                pass

    # ---- Popen 同形接口: 停止收尾逻辑(_kill_ffmpeg_sync 等)零改动共用 ----
    def poll(self):
        return self.returncode

    def send_signal(self, sig):
        self._stop.set()

    def terminate(self):
        self._stop.set()

    def kill(self):
        self._stop.set()

    def wait(self, timeout=None):
        self._stop.set()
        self._pth.join(timeout if timeout else 5)
        return self.returncode


class App:
    def __init__(self):
        self.lock = threading.RLock()
        self._procs = {}        # sid -> Whisper 子进程 Popen(停止时 SIGTERM 它)
        self._cancel = set()    # 用户按过停止的 sid(云端链路在检查点自查)
        # 任务表: sid -> {kind,state,stage,pct}。批量导入后 refining 只是
        # "当前本地任务"的兼容指针, 前端一律以 jobs 为准(云端可多路并行)。
        self.progs = {}
        self._q_local = []      # 本地队列: GPU 一块, 严格串行
        self._q_cloud = []      # 云端队列: 网络 bound, 2 路并行
        self._cond = threading.Condition(self.lock)
        self._tls = threading.local()      # worker 线程当前处理的 sid
        threading.Thread(target=self._worker_loop, args=(False,), daemon=True).start()
        threading.Thread(target=self._worker_loop, args=(True,), daemon=True).start()
        threading.Thread(target=self._worker_loop, args=(True,), daemon=True).start()
        self.state = "idle"           # idle/recording/paused/stopping
        self.session = None
        self.events = []              # 事件总线 [{seq,type,...}]
        self.seq = 0
        # 录音过程态
        self.ffmpeg = None
        self.reader_thread = None
        self.raw_f = None
        self._pending_ff = None
        self.total_samples = 0        # 已喂入 VAD 的总样本(=时间轴)
        self.vad_lang = "zh"
        self.gen = 0                  # 会话代际号: stop/pause 递增, 迟到的 reader 数据作废
        # 流式小块状态
        self.chunk_buf = []
        self._chunk_t0 = 0            # 当前小块的起始时间(样本)
        # Whisper 精修状态: 正在后台处理的会话 id(目录名), None=无
        self.refining = None
        self.refine_stage = ""      # 精修走到哪一步, 供前端旋转斜杠下方那行小字
        self.refine_pct = None      # 精修百分比; None=还没有可信数字, 界面就不显示数
        self.refining_kind = "refine"     # refine=停录精修, import=导入转写
        # 输入电平(0~1 RMS, 带峰值保持), 供前端电平条
        self.level = 0.0

    @property
    def refining(self):
        return self._refining

    @refining.setter
    def refining(self, v):
        """开始/结束一轮后台处理时, 上一轮的阶段文字和百分比立刻作废。
        六处开始、多处结束都要清, 逐个补容易漏 —— 漏了就表现为"新任务刚起来
        先闪一下上一条的 48%"。放到 setter 里统一掉。
        注意 _refining 必须无条件写: 第一次赋值是 None->None, 若只在"变了"时写,
        属性就永远不存在, getter 直接 AttributeError 把 /api/status 打挂。"""
        changed = v != getattr(self, "_refining", None)
        self._refining = v
        if changed:
            self.refine_stage = ""
            self.refine_pct = None

    # ---------- 事件 ----------
    def emit(self, **obj):
        with self.lock:
            self.seq += 1
            obj["seq"] = self.seq
            self.events.append(obj)
            if len(self.events) > 800:
                self.events = self.events[-400:]

    def stage(self, text=None, pct=None):
        """记录并广播当前任务的阶段与百分比。批量任务后按 worker 线程路由到
        各自的任务表条目(云端并行时进度互不串台); 非 worker 上下文退回旧全局字段。
        完成前绝不显示 100。"""
        sid = self._jsid()
        j = self.progs.get(sid) if sid else None
        if j is None:
            if text is not None:
                self.refine_stage = text or ""
            if pct is not None:
                self.refine_pct = max(0, min(99, int(pct)))
            if self.refining:
                self.emit(type="refine_stage", id=self.refining,
                          stage=self.refine_stage, pct=self.refine_pct)
            return
        if text is not None:
            j["stage"] = text or ""
        if pct is not None:
            j["pct"] = max(0, min(99, int(pct)))
        self.emit(type="refine_stage", id=sid, stage=j["stage"], pct=j["pct"])

    def pct(self, n):
        """给进度拦截器当回调: 只动百分比, 不改阶段文字。"""
        self.stage(pct=n)

    def cloud_prog(self, text=None, frac=None):
        """云端路径的进度回调: 收 0~1 的总体分数, 换算成百分比转给 stage()。
        上传/等待/下载三个阶段共用一条进度轴, 免得各自算各自的。"""
        self.stage(text, None if frac is None else int(round(max(0.0, min(0.99, frac)) * 100)))

    def _jsid(self):
        """worker 线程里的当前任务 sid; 非 worker 线程退回 refining(兼容旧调用点)。"""
        return getattr(self._tls, "sid", None) or self.refining

    def _enqueue(self, sid, queue, fn):
        with self.lock:
            (self._q_cloud if queue == "cloud" else self._q_local).append((sid, fn))
            # 必须 notify_all: 一个 Condition 被 3 个 worker 共用(1 本地 + 2 云端),
            # notify() 只随机叫醒一个 —— 叫到"不对口"的那个(本地 worker 发现本地队列空
            # 又睡回去), 唤醒就被消耗掉, 对口的线程永远睡死 → 任务卡在 state="wait",
            # 界面表现为"排队中"不动了。各线程醒来都会自己 re-check 队列, 多叫无副作用。
            self._cond.notify_all()

    def _job_begin(self, sid, kind, state="run"):
        with self.lock:
            self.progs[sid] = {"kind": kind, "state": state, "stage": "", "pct": None}
        # refining 只表示"这份稿子正在被改写, 页面要锁"。云端转写和课后笔记都不改稿子
        # (笔记另存 note.md), 所以这两类不参与 locking, 否则生成笔记会把整个页面锁死。
        if state == "run" and kind not in ("cloud", "note"):
            self.refining, self.refining_kind = sid, ("refine" if kind == "refine" else "import")
        self.emit(type="refinish_start", id=sid, kind=kind, state=state)

    def _job_end(self, sid):
        with self.lock:
            self.progs.pop(sid, None)
            if self.refining == sid:
                self.refining = None
        self.emit(type="job_end", id=sid)

    def _worker_loop(self, cloud):
        while True:
            started = None
            with self.lock:
                q = self._q_cloud if cloud else self._q_local
                while not q:
                    self._cond.wait()
                sid, fn = q.pop(0)
                self._tls.sid = sid
                j = self.progs.get(sid)
                if j:
                    if j.get("state") != "run":
                        j["state"] = "run"
                        started = (sid, j.get("kind") or "refine")   # 广播留到锁外
                    if not cloud:
                        self.refining = sid
                        self.refining_kind = "refine" if j["kind"] == "refine" else "import"
            if started:
                # wait→run 必须广播出去: 前端只在"非 idle 且未查看项目"时才轮询 /api/status,
                # 停录后 state 已回 idle、人又常停在项目页, 没人再去拉状态 —— 不发事件的话
                # 界面会永远停在"排队中", 只有切走再切回(loadSession 会拉一次 status)才恢复。
                # emit 内部拿的是同一把非重入锁, 只能在锁外调用, 否则自锁死。
                self.emit(type="refinish_start", id=started[0], kind=started[1], state="run")
            try:
                fn()
            except Cancelled:
                # 抽轨/预处理阶段被停: runner 没机会自己收尾, 这里补终态(空壳标 stopped)
                print(f"[job] {sid} 已停止", flush=True)
                self._mark_stopped(SESSIONS_DIR / sid)
                self.emit(type="refinish", id=sid, ok=False, cancelled=True)
            except Exception as e:
                print(f"[job] {sid} 执行异常: {e}", flush=True)
            finally:
                self._tls.sid = None
                self._job_end(sid)

    def cancel_job(self, sid):
        """停止后台任务: 本地=直接 SIGTERM 子进程; 云端=打标记, 链路检查点见到就抛。
        排队/无任务也接受(幂等), 前端按完不再转圈。"""
        if not sid:
            return {"ok": False, "error": "缺 id"}
        with self.lock:
            self._cancel.add(sid)
            pr = self._procs.get(sid)
            j = self.progs.get(sid)
            was_wait = bool(j) and j.get("state") == "wait"
            if was_wait:
                for q in (self._q_local, self._q_cloud):
                    for k, it in enumerate(q):
                        if it[0] == sid:
                            q.pop(k)
                            break
                self.progs.pop(sid, None)
                self._cancel.discard(sid)     # 还没开跑就撤, 不留脏标记
        if was_wait:
            self._mark_stopped(SESSIONS_DIR / sid)
            self.emit(type="refinish", id=sid, ok=False, cancelled=True)
            self.emit(type="job_end", id=sid)
            print(f"[cancel] 排队中已出队: {sid}", flush=True)
            return {"ok": True, "id": sid, "queued": False}
        if pr:
            try:
                pr.terminate()
            except Exception:
                pass
        print(f"[cancel] 用户停止: {sid}", flush=True)
        return {"ok": True, "id": sid}

    def is_cancelled(self, sid):
        return sid in self._cancel

    def _uncancel(self, sid):
        with self.lock:
            self._cancel.discard(sid)

    def _ck(self, sid):
        """给云端链路当检查点回调: 见到取消标记就抛 Cancelled。"""
        def ck():
            if self.is_cancelled(sid):
                raise Cancelled("已停止")
        return ck

    def _mark_stopped(self, d):
        """停止落盘: 只有「一个字都还没有」的项目才标 stopped(前端出空壳+黄横幅);
        有稿的子进程停精修/停云转 → 原稿保持不动, 不标。"""
        try:
            sj = d / "session.json"
            meta = json.loads(sj.read_text(encoding="utf-8"))
            if not any(x.get("text") for x in (meta.get("segments") or [])):
                meta["stopped"] = True
                sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        except Exception:
            pass

    def events_after(self, n):
        with self.lock:
            return [e for e in self.events if e["seq"] > n]

    def status(self):
        with self.lock:
            s = self.session
            return {
                "state": self.state,
                "elapsed": round(self.total_samples / SR, 1) if s else 0,
                "session": s["name"] if s else "",
                "dir": str(s["dir"]) if s else "",
                "mode": s["mode"] if s else "",
                "lang": s["lang"] if s else "",
                "lines": len(s["segments"]) if s else 0,
                "seq": self.seq,
                "engine": ENGINE.engine_name,
                "refining": self.refining,
                "jobs": [dict(j, id=k) for k, j in self.progs.items()],
                "refiningKind": self.refining_kind,
                "refineStage": self.refine_stage,
                "refinePct": self.refine_pct,
                "localModel": (whisper_model().name
                               if whisper_model() and whisper_model().exists() else ""),
                "talkMode": talk_mode(),
                "cloudFlow": cloud_flow(),
                "cloudAsr": (cloud_cfg()["asr_model"] or cloud_cfg()["model"]),
                "cloudProvider": cloud_cfg()["provider"],
                "level": round(self.level if self.state == "recording" else 0.0, 4),
            }

    # ---------- 会话 ----------
    def _new_session(self, name, mode, lang):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = (name or "新录音").strip() or "新录音"
        name = name.replace("/", "-").replace(":", "-")
        d = SESSIONS_DIR / f"{name}-{stamp}"
        i = 1
        while d.exists():
            d = SESSIONS_DIR / f"{name}-{stamp}-{i}"; i += 1
        d.mkdir(parents=True)
        return {
            "name": name, "stamp": stamp, "dir": d, "mode": mode, "lang": lang,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "segments": [],   # [{t, d, text}]
            "notes": [],      # [{t, text}]
        }

    def start(self, mode, lang, name):
        with self.lock:
            if self.state != "idle":
                raise RuntimeError("已有进行中的会话，请先停止")
            if ENGINE.engine_name == "sensevoice" and ENGINE._sv is None:
                raise RuntimeError("未配置 SenseVoice 模型：设置 → 本地模型")
            self.session = self._new_session(name, mode, lang)
            self.total_samples = 0
            self.chunk_buf = []
            self._chunk_t0 = 0
            self.vad_lang = lang
            ENGINE.new_vad()
            self._start_recorder(mode)
            self.state = "recording"
            self.emit(type="status", **self.status())
        return {"ok": True, "device": mode}

    def _device_for_mode(self, mode):
        if mode == "mix":
            return find_device(["聚合", "Aggregate"])
        if mode == "system":
            return find_device(["BlackHole 2ch"])
        # 麦克风: 设置里手动指定的优先, 没配才按内置名单猜
        if mic_device():
            d = find_device([mic_device()])
            if d is not None:
                return d
        return find_device(["MacBook Pro麦克风", "麦克风"])

    def _spawn_ffmpeg(self, idx):
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "avfoundation", "-i", f":{idx}",
               "-ac", "1", "-ar", str(SR),
               "-f", "s16le", "-"]
        self.raw_f = open(self.session["dir"] / "raw.s16", "ab")
        self.ffmpeg = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()
        # ffmpeg 的 stderr 不能丢 DEVNULL: 设备打不开(如缺麦克风权限)时是唯一线索。
        # 单独起线程按行读入 sys.stderr(_Tee 会自动加时间戳落日志), 不能并进 stdout(那是 PCM)。
        threading.Thread(target=self._ffmpeg_err_loop, daemon=True).start()

    def _spawn_sck(self, mode):
        """SCK 系统级采集(mix=系统声+麦克风, system=仅系统声)。
        tingdao-mix 助手在进程内实时混成单轨, stdout 输出 s16le/SR/mono,
        与 ffmpeg 的输出协议一致 → _read_loop 原样工作。进程句柄沿用 self.ffmpeg:
        停止/收尾(SIGINT、等退出、关 raw_f)逻辑完全共用, 零改动。
        起动失败(最常见=缺屏幕录制权限)时助手秒退: 这里等不到 ready 信号,
        把 stderr 里的中文原因如实抛出去, 不静默卡死。"""
        if not SCK_HELPER.exists():
            raise RuntimeError("找不到音频助手 tingdao-mix（应与 app.py 同目录）")
        self.raw_f = open(self.session["dir"] / "raw.s16", "ab")
        self._sck_ready = threading.Event()
        self._sck_errbuf = []
        cmd = [str(SCK_HELPER), "--mode", mode, "--rate", str(SR)]
        if mic_device():
            cmd += ["--mic", mic_device()]   # 设置里指定的麦克风输入源
        self.ffmpeg = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()
        threading.Thread(target=self._ffmpeg_err_loop, daemon=True).start()
        if not self._sck_ready.wait(timeout=8):
            ff = self.ffmpeg
            try:
                ff.send_signal(signal.SIGTERM)
                ff.wait(timeout=2)
            except Exception:
                try:
                    ff.kill()
                except Exception:
                    pass
            err = self._sck_errbuf[-1] if self._sck_errbuf else ""
            self.ffmpeg = None
            try:
                self.raw_f.close()
            except Exception:
                pass
            self.raw_f = None
            try:
                self.session["dir"].rmdir()   # 清掉刚建的空会话目录(非空则rmdir不动)
            except Exception:
                pass
            raise RuntimeError(err or "音频助手起动超时（检查屏幕录制/麦克风权限）")

    def _start_recorder(self, mode):
        """录音源按平台分流(锁内调用; 起动失败抛 RuntimeError → 界面弹错):
        Windows        全部模式走 WinRec(WASAPI loopback + 麦, 免虚拟声卡)
        macOS mix/system 走 tingdao-mix(SCK, 免 BlackHole)
        macOS mic        沿用 ffmpeg avfoundation(麦克风直采)"""
        if platform.system() == "Windows":
            self._spawn_winrec(mode)
        elif mode in ("mix", "system"):
            self._spawn_sck(mode)
        else:
            dev = self._device_for_mode(mode)
            if dev is None:
                raise RuntimeError("找不到录音设备，请检查音频 MIDI 设置")
            self._spawn_ffmpeg(dev)

    def _spawn_winrec(self, mode):
        """Windows: WinRec 的接口与 Popen 同形 → 读流/日志/停止收尾全部共用既有
        self.ffmpeg 那套。设备打不开/缺 pyaudiowpatch 在 WinRec.__init__ 同步抛错,
        不需要像 mac 助手那样等 ready 信号。"""
        self.raw_f = open(self.session["dir"] / "raw.s16", "ab")
        self.ffmpeg = WinRec(mode, mic_device())
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()
        threading.Thread(target=self._ffmpeg_err_loop, daemon=True).start()

    def _ffmpeg_err_loop(self):
        """把录音 ffmpeg 的 stderr 逐行写进日志; 进程退出(EOF)后自然结束。"""
        ff = self.ffmpeg
        try:
            for line in iter(ff.stderr.readline, b""):
                msg = line.decode("utf-8", "replace").rstrip()
                if msg:
                    print(f"[ffmpeg] {msg}", flush=True)
                    # SCK 助手的就绪信号 / 报错行(起动失败要如实抛给界面)
                    if "[sckmix] ready" in msg:
                        rd = getattr(self, "_sck_ready", None)
                        if rd:
                            rd.set()
                    eb = getattr(self, "_sck_errbuf", None)
                    if eb is not None:
                        eb.append(msg)
        except Exception:
            pass
        finally:
            try:
                ff.stderr.close()
            except Exception:
                pass

    def _read_loop(self):
        """持续读取 ffmpeg PCM → VAD → 断句识别"""
        ff = self.ffmpeg
        try:
            while True:
                data = ff.stdout.read(2048)  # 1024 样本
                if not data:
                    break
                with self.lock:
                    if self.ffmpeg is not ff or self.raw_f is None:
                        break  # 已被 pause/stop 换掉
                    self.raw_f.write(data)
                    self._feed(np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0)
        except Exception as e:
            print(f"[reader] 异常(录音线程退出): {e}", flush=True)
        finally:
            # reader 自己退出时(如 ffmpeg 意外死亡)同步状态
            pass

    def _feed(self, samples):
        """喂 VAD(锁内调用); 断句即识别并广播; 同时按小块流式吐字"""
        if self.state != "recording":
            return  # 已停/暂停: 迟到数据作废, 防止重复识别
        self.total_samples += len(samples)
        # ---- 电平采样: 供前端底部电平条(峰值保持 + 缓 decay) ----
        try:
            rms = float(np.sqrt(np.mean(samples * samples)))
            self.level = max(rms, self.level * 0.80)
        except Exception:
            pass
        # ---- 流式小块: 每 CHUNK 秒立即识别广播(前端即时显示) ----
        n = int(CHUNK * SR)
        self.chunk_buf.extend(samples)
        if len(self.chunk_buf) >= n:
            blk = np.array(self.chunk_buf[:n], dtype=np.float32)
            del self.chunk_buf[:n]
            self._emit_chunk(blk)
        # ---- VAD 断句(正式句边界, 时间戳以此为准) ----
        for i in range(0, len(samples), VAD_WINDOW):
            c = samples[i:i + VAD_WINDOW]
            if len(c) < VAD_WINDOW:
                c = np.pad(c, (0, VAD_WINDOW - len(c)))
            ENGINE.vad.accept_waveform(c)
            while not ENGINE.vad.empty():
                self._decode_seg(ENGINE.vad.front)
                ENGINE.vad.pop()

    def _emit_chunk(self, blk):
        """小块流式识别: 仅广播给前端即时显示, 不入正式 segments"""
        # 静音小块跳过(能量门限), 避免空白字幕刷屏
        if float(np.sqrt(np.mean(blk * blk))) < 0.004:
            return
        try:
            text = ENGINE.recognize(blk, self.session["lang"])
        except Exception:
            return
        if text:
            self.emit(type="chunk", t=round(self._chunk_t0 / SR, 2), text=text)
            self._chunk_t0 += CHUNK
        else:
            self._chunk_t0 += CHUNK   # 无文字也推进时间轴

    def _decode_seg(self, seg):
        s = self.session
        text = ENGINE.recognize(seg.samples, s["lang"])
        item = {"t": round(seg.start / SR, 2),
                "d": round(len(seg.samples) / SR, 2),
                "text": text}
        # 去重: 与上一段时间戳和时长完全一致时跳过(竞态下同段会被识别两次)
        if s["segments"] and s["segments"][-1]["t"] == item["t"] \
                and s["segments"][-1]["d"] == item["d"]:
            return
        s["segments"].append(item)
        if text:
            self.emit(type="line", **item)

    def _drain_vad(self):
        """flush 出口: 停止后把 VAD 里残余的语音段识别掉"""
        if ENGINE.vad is None:
            return
        try:
            ENGINE.vad.flush()
        except Exception:
            pass
        while not ENGINE.vad.empty():
            self._decode_seg(ENGINE.vad.front)
            ENGINE.vad.pop()

    def _kill_ffmpeg(self):
        ff = self.ffmpeg
        if ff:
            try:
                ff.stdout.close()
            except Exception:
                pass
            ff.send_signal(signal.SIGINT)
            try:
                ff.wait(timeout=4)
            except subprocess.TimeoutExpired:
                ff.kill()
        self.ffmpeg = None
        if self.raw_f:
            try:
                self.raw_f.close()
            except Exception:
                pass
        if self.reader_thread:
            self.reader_thread.join(timeout=5)
            self.reader_thread = None

    def pause(self):
        with self.lock:
            if self.state != "recording":
                raise RuntimeError("当前不在录音")
            self._stop_ffmpeg_noblock()
        # 无锁等待退出(与 reader 无死锁风险)
        self._kill_ffmpeg_sync()
        with self.lock:
            self._drain_vad()
            ENGINE.new_vad()  # 重置, 恢复时继续(时间轴按样本数冻结)
            self.chunk_buf = []
            self._chunk_t0 = self.total_samples  # 流式块时间轴与暂停点对齐
            self.state = "paused"
            self.emit(type="status", **self.status())
        if platform.system() != "Windows" and self.session["mode"] not in ("mix", "system"):
            switch_output(output_restore())   # SCK 方案不切系统输出, 无需恢复
        return {"ok": True}

    def resume(self):
        with self.lock:
            if self.state != "paused":
                raise RuntimeError("当前不在暂停")
            mode = self.session["mode"]
            self._start_recorder(mode)
            self.state = "recording"
            self.emit(type="status", **self.status())
        return {"ok": True}

    def stop(self):
        with self.lock:
            if self.state == "idle":
                raise RuntimeError("没有进行中的会话")
            if self.state == "stopping":
                return {"ok": True, "id": self.session["dir"].name}
            if self.state == "recording":
                self._stop_ffmpeg_noblock()
            self.state = "stopping"
            self.emit(type="status", **self.status())
            sid = self.session["dir"].name
        # 收尾(杀线程/识别残余/编码音频)放后台, 不阻塞 HTTP 响应
        threading.Thread(target=self._stop_bg, daemon=True).start()
        return {"ok": True, "id": sid}

    def _stop_ffmpeg_noblock(self):
        """快速停录: 置空引用让 reader 退出, 记住进程对象供后台收尾"""
        ff = self.ffmpeg
        if ff:
            self._pending_ff = ff      # 后台线程接手等待
            self.ffmpeg = None
            try:
                ff.send_signal(signal.SIGINT)
            except Exception:
                pass

    def _stop_bg(self):
        try:
            self._kill_ffmpeg_sync()
        finally:
            if platform.system() != "Windows" and self.session["mode"] not in ("mix", "system"):
                switch_output(output_restore())   # SCK 方案不切系统输出, 无需恢复
        with self.lock:
            self._finish()
            self.state = "idle"
            self.emit(type="status", **self.status())
        # 停录后的处理严格按模式走一条, 绝不双跑:
        # single→本地 Whisper | cloud→只发事件让前端弹窗问,
        # 用户点确认才会上传(POST /api/cloud_transcribe), 不点就停在实时字幕稿。
        d = self.session["dir"] if self.session else None
        lang = self.session["lang"] if self.session else "zh"
        if d and (d / "audio.m4a").exists():
            mode = talk_mode()
            if mode == "cloud" and cloud_flow() == "local_post":
                # 流程②: 音频不出本机, 本地转完后只把文字送去做后制作
                print("[refine] 云端模式·本地转写+云端后处理（不上传音频）", flush=True)
                self._job_begin(d.name, "refine", state="wait")
                self._enqueue(d.name, "local",
                              lambda d=d, lang=lang: self._refinish_whisper(
                                  d, lang, post_flow=True))
            elif mode == "cloud":
                # 流程①: 不启动任何本地精修, 只广播"待确认"事件(带体积与时长)
                print("[refine] 对话模式=cloud → 等用户确认上传（不跑本地）", flush=True)
                up = d / "audio.m4a"
                self.emit(type="cloud_confirm", id=d.name,
                          mb=round(up.stat().st_size / 2**20, 1),
                          dur=round(float(self.session.get("total_samples", 0)) / SR, 1),
                          flow=cloud_flow())
                self.session["cloud_pending"] = True
            else:
                print(f"[refine] 对话模式={mode} → Whisper 本地精修", flush=True)
                self._job_begin(d.name, "refine", state="wait")
                self._enqueue(d.name, "local",
                              lambda d=d, lang=lang: self._refinish_whisper(d, lang))

    def _kill_ffmpeg_sync(self):
        """等待 ffmpeg/reader 真正退出并关文件(无锁调用, 允许较长时间)"""
        ff = getattr(self, "_pending_ff", None)
        rt = self.reader_thread
        if ff:
            try:
                ff.send_signal(signal.SIGINT)
            except Exception:
                pass
            try:
                ff.wait(timeout=6)
            except subprocess.TimeoutExpired:
                ff.kill()
        if rt:
            rt.join(timeout=6)
            self.reader_thread = None
        # raw_f 关闭放锁内, 与 reader 的写入互斥
        with self.lock:
            if self.raw_f:
                try:
                    self.raw_f.close()
                except Exception:
                    pass
        if ff and ff.stdout:
            try:
                ff.stdout.close()
            except Exception:
                pass
        self._pending_ff = None

    def _finish(self):
        s = self.session
        self._drain_vad()
        d = s["dir"]
        # 编码音频 m4a
        raw = d / "raw.s16"
        audio_rel = None
        listen_rel = None
        # 降噪在"源头"做: raw.s16 是整条录音唯一的全信息素材, 就在这一次编码里
        # 把处理档位的滤镜链一次成型进 audio.m4a。之后本地转写、上云转写、
        # 回放读到的都是同一份已经降噪的母本, 不再各走各的。
        # 旧做法是把滤镜链塞在 Whisper 之前、作用在已经压成 16k/AAC 的
        # audio.m4a 上 —— 那等于跟编码器失真打架, 噪声明显的录音也救不动,
        # 表现就是"结束录音的降噪形同没跑"(只有导入原始文件那条路看着有效)。
        chain = pretreat_chain()
        audio_proc = "off"
        listen_err = ""
        if raw.exists() and raw.stat().st_size > SR * 2:  # >1s
            m4a = d / "audio.m4a"

            def _enc(with_chain):
                cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                       "-f", "s16le", "-ar", str(SR), "-ac", "1",
                       "-i", str(raw)]
                if with_chain:
                    cmd += ["-af", with_chain]
                cmd += ["-c:a", "aac", "-b:a", "48k", str(m4a)]
                try:
                    return subprocess.run(cmd, capture_output=True, timeout=600)
                except Exception as e:
                    return type("_R", (), {"returncode": -1,
                                           "stderr": str(e).encode()})()

            r = _enc(chain) if chain else _enc(None)
            err = (getattr(r, "stderr", b"") or b"").decode(errors="ignore").strip()[:300]
            if chain and (r.returncode != 0 or not m4a.exists()
                          or m4a.stat().st_size < 1024):
                # 降噪翻车绝不能连音频一起丢掉: 摘掉滤镜链原样再编一次
                print("[finish] ⚠ 源头降噪失败, 回退未处理编码:", err, flush=True)
                r = _enc(None)
                audio_proc = "failed"
            else:
                audio_proc = chain or "off"
            if r.returncode == 0 and m4a.exists() and m4a.stat().st_size >= 1024:
                audio_rel = "audio.m4a"
            # 回放副本: 必须在删 raw 之前做（raw 是唯一的全信息源）
            # strong 档位与回放链完全同一条, 母本已经是它处理过的了 —— 这时再出
            # 一份副本纯属多余(两小时的课要多跑一整趟 ffmpeg), 回退还用母本。
            listen_err = ""
            if audio_rel and chain != LISTEN_FILTER:
                listen_rel, listen_err = encode_listen(
                    raw, d / LISTEN_FILE,
                    ["-f", "s16le", "-ar", str(SR), "-ac", "1"])
            elif audio_rel:
                listen_rel = audio_rel      # 母本即降噪后的那份
            try:
                raw.unlink()
            except Exception:
                pass
            save_setting("last_pretreat", {
                "chain": audio_proc, "at": time.strftime("%m-%d %H:%M"),
                "error": err if audio_proc == "failed" else "",
                "src": "raw.s16"})
            if chain:
                if audio_proc == chain:
                    print(f"[finish] 源头降噪已应用: {chain}", flush=True)
                else:
                    print("[finish] 源头降噪未生效, 已回退未处理编码", flush=True)
        # session.json (新格式, 供回放/搜索)
        (d / "session.json").write_text(json.dumps({
            "name": s["name"], "started": s["started"], "stamp": s["stamp"],
            "mode": s["mode"], "lang": s["lang"],
            "duration": round(self.total_samples / SR, 1),
            "audio": audio_rel, "audioListen": listen_rel,
            "audioListenError": listen_err if listen_rel is None else "",
            # 这份 audio.m4a 编码时吃了哪条滤镜链 —— 后续重跑精修据此决定
            # 要不要跳过预处理, 防止在已降噪的母本上二次处理。
            "audio_pretreat": audio_proc,
            "pretreat": audio_proc,
            "segments": s["segments"], "notes": s["notes"],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        # transcript.md
        lines = [f"# {s['name']}", "",
                 f"- 开始: {s['started']} | {MODE_LABELS.get(s['mode'], s['mode'])}"
                 f" | 时长: {fmt_ts(self.total_samples / SR)}", ""]
        for seg in s["segments"]:
            if seg["text"]:
                lines.append(f"[{fmt_ts(seg['t'])}] {seg['text']}")
        if s["notes"]:
            lines += ["", "## 时间线笔记", ""]
            lines += [f"- [{fmt_ts(n['t'])}] {n['text']}" for n in s["notes"]]
        (d / "transcript.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _is_hallucination(text, dur):
        """重复环/幻觉段判定(从严): 语速超生理极限(>15字/秒)或长文本字符多样性极低。
        曾发生尾部 0.1 秒吐 223 个「想」的事故。"""
        if len(text) < 12:
            return False
        if len(text) / max(dur, 0.1) > 15:
            return True
        if len(text) >= 30 and len(set(text)) < 6:
            return True
        return False

    @staticmethod
    def _pick_orig(old, start, end):
        """从原 VAD 句中挑与 [start,end] 时间重叠最多的一句文本(幻觉段回退用)。
        原句自身也是幻觉段(重跑精修时旧数据已含环)则跳过。"""
        best, best_ov = None, 0.0
        for seg in old:
            s0, s1 = seg.get("t", 0), seg.get("t", 0) + seg.get("d", 0)
            ov = min(end, s1) - max(start, s0)
            if ov > best_ov and seg.get("text"):
                if App._is_hallucination(seg["text"], seg.get("d", 0)):
                    continue
                best, best_ov = seg["text"], ov
        return best

    @staticmethod
    def _clean_tail(text):
        """去掉 Whisper 常甩在句尾的破折号(—— / — / –)及其后空白; 只清结尾、不动句中。
        整段只有破折号时清成空串, 由调用方按空段跳过。"""
        return re.sub(r'[—–\s]+$', '', text or '').strip()

    @staticmethod
    def _merge_segs(segs, min_s=10.0, max_s=15.0):
        """合并 Whisper 碎片段: 只在句末标点处且累计 >= min_s 秒才允许断段,
        超过 max_s 秒强制断。时间戳取段首, d 覆盖整段, 回放对齐不受影响。"""
        merged = []
        for s in segs:
            if merged:
                last = merged[-1]
                span = (s["t"] + s["d"]) - last["t"]
                ends_sent = last["text"].rstrip()[-1:] in "。！？!?…"
                diff_spk = bool(s.get("spk")) and s.get("spk") != last.get("spk")
                if (not diff_spk and span <= max_s
                        and not (ends_sent and span >= min_s)):
                    joiner = " " if (last["text"][-1:].isascii()
                                     and s["text"][:1].isascii()) else ""
                    last["text"] = last["text"] + joiner + s["text"]
                    last["d"] = round(span, 2)
                    continue
            merged.append(dict(s))
        return merged

    @staticmethod
    def _drop_repeat_loops(segs, min_len=6, max_gap=2.0, ring=3):
        """跨段复读过滤: 紧邻段文本完全相同(长度≥min_len, 间隔≤max_gap 秒)算一串,
        连串 ≥ring 判为复读环 → 整串丢弃; 连串 <ring 判为自然重复 → 原样保留。
        返回 (保留段, 丢弃文本列表)。

        为什么必须靠跨段结构判死: 实测那 170 秒的「请不吝点赞 订阅 转发 打赏支持…」幻觉块,
        avg_logprob=-0.04(模型极其自信)、no_speech_prob=0.00(不认为静音)、
        compression_ratio=0.85(不高)——三个官方阈值全部正常, 段内规则一律抓不到。
        为什么连串要丢光而不是留第一条: 环里的每一条都是编的, 留一条等于逐字稿里
        仍躺着一句假话(实测问题录音该串长 8)。
        为什么门槛定 3 而不是 2: 两份干净录音实测最长串只有 2(如「老师几次能够效果」
        连说两遍), 门槛 2 会误删真声; 门槛 3 在干净录音上零丢弃。
        为什么不设全局静音跳过: 库内置 hallucination_silence_threshold 实测会吃掉
        单人清晰录音 9% 的真实语音, 故改为会话级手动重跑(见 refine_silence), 不进默认路径。"""
        runs = []                              # [[seg, seg, ...], ...] 相邻同文成串
        for s in segs:
            t = s["text"].strip()
            if (runs and len(t) >= min_len and t == runs[-1][0]["text"].strip()
                    and s["t"] - (runs[-1][-1]["t"] + runs[-1][-1]["d"]) <= max_gap):
                runs[-1].append(s)
            else:
                runs.append([s])
        kept, dropped = [], []
        for r in runs:
            if len(r) >= ring:
                dropped += [x["text"].strip() for x in r]
            else:
                kept += r
        return kept, dropped

    def _whisper_segs(self, audio, old, fallback_dur, lang, silence_skip=False, sid=None,
                      pretreat=None):
        """用 Whisper 转写整条音频, 返回带真实时间戳的段落(精修与导入共用)。
        - 直接采用 result.segments 的 start/end(曾因按输出标点切句被整条无标点击穿)
        - 幻觉段(重复环)回退到时间重叠最多的原句, 无原句则丢弃
        - 碎片段按「句末标点 + 10~15 秒窗口」聚成饱满段
        - 可选预处理: 高通+频域降噪+响度归一, 改善差录音
        - pretreat=False: 跳过预处理。停录路径喂的是已经在源头降噪过的 audio.m4a,
          再套一遍滤镜就是对同一份噪声做两次处理。
        - 转写本体跑在子进程(whisper_worker.py): mlx_whisper 没有回调参数,
          在主进程里跑就是一块拆不开的整砖, 停止按钮按不动; 子进程 SIGTERM 即死。"""
        audio_path = Path(audio)
        tmp_wav = audio_path.parent / ".pretreat.wav"
        chain = None if pretreat is False else pretreat_chain()
        info = {"pretreat": "off", "error": "", "repeat_dropped": 0}
        if chain:
            # 长音频预处理要几十秒~分钟级, 这段也必须可停: 登记进 _procs 让
            # cancel_job 掐得到; 掐完先查标记走 Cancelled, 别掉进"预处理失败→
            # 回退原音继续转写"的分支(那是给真失败准备的, 不是给停止准备的)。
            ff = subprocess.Popen(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-i", str(audio_path), "-af", chain,
                 "-ar", "48000", "-ac", "1", str(tmp_wav)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if sid:
                with self.lock:
                    self._procs[sid] = ff
            try:
                errb = ff.stderr.read()
                rc = ff.wait(timeout=1800)
            finally:
                if sid:
                    with self.lock:
                        self._procs.pop(sid, None)
            if sid and self.is_cancelled(sid):
                raise Cancelled("已停止")
            r = type("_R", (), {"returncode": rc,
                                "stderr": errb or b""})()
            if r.returncode == 0 and tmp_wav.exists():
                audio_path = tmp_wav
                info["pretreat"] = chain
                self.stage("正在调整音频效果")
                print("[whisper] 预处理已应用:", chain, flush=True)
            else:
                info["pretreat"] = "failed"
                info["error"] = (r.stderr or b"").decode(errors="ignore").strip()[:300]
                print("[whisper] ⚠ 预处理失败, 已回退原始音频:", info["error"], flush=True)
            save_setting("last_pretreat", {
                "chain": info["pretreat"], "at": time.strftime("%m-%d %H:%M"),
                "error": info["error"], "src": Path(audio).name})
        try:
            dur = float(fallback_dur or 0)
            # 知道总时长才开 verbose: worker 每解出一句就往 stdout 打 `[起 --> 止] 文本`，
            # 父进程逐行喂 WhisperStdout 算进度——与旧 stdout 劫持完全同一格式。
            # 时长都不知道时宁可不出数字, 也不给假的。
            self.stage("本地模型转录中", 0 if dur else None)
            result = self._whisper_proc(audio_path, lang, dur, silence_skip, sid)
        finally:
            try:
                tmp_wav.unlink()
            except Exception:
                pass
        new_segs = []
        total = float(fallback_dur or 0)
        for s in (result.get("segments") or []):
            text = self._clean_tail((s.get("text") or "").strip())
            if not text:
                continue
            start = float(s.get("start", 0))
            end = float(s.get("end", start))
            # 尾段静音幻觉: 起点已落在音频之外(实测 62s 音频冒出 62.00+15.14s 的
            # 「欢迎订阅」)。这类段语速字符数都"合规", 只能靠时间边界判死。
            if total and start >= total - 0.35:
                print(f"[whisper] 丢弃越界幻觉段: t={start:.2f} (音频仅 {total:.1f}s) "
                      f"{text[:20]}…", flush=True)
                continue
            if total:
                end = min(end, total)
            dur = max(0.1, end - start)
            if self._is_hallucination(text, dur):
                orig = self._pick_orig(old, start, start + dur) if old else None
                if orig:
                    print(f"[whisper] 疑似幻觉段丢弃(回退原句): {text[:24]}…", flush=True)
                    new_segs.append({"t": round(start, 2), "d": round(dur, 2),
                                     "text": self._clean_tail(orig)})
                continue
            new_segs.append({"t": round(start, 2), "d": round(dur, 2), "text": text})
        if not new_segs:                      # 兜底: 拿不到分段时用全文, 不叠加旧稿
            full_text = self._clean_tail((result.get("text") or "").strip())
            if not full_text:
                return [], info
            new_segs = [{"t": 0, "d": round(fallback_dur or 1, 2), "text": full_text}]
        new_segs, dropped = self._drop_repeat_loops(new_segs)
        if dropped:
            info["repeat_dropped"] = len(dropped)
            print(f"[whisper] 跨段复读过滤: 丢弃 {len(dropped)} 段重复, "
                  f"样例「{dropped[0][:24]}…」", flush=True)
        return self._merge_segs(new_segs), info

    def _whisper_proc(self, audio_path, lang, total, silence_skip, sid):
        """跑 whisper_worker 子进程并收结果。
        进度: stdout 段行喂 WhisperStdout(非段行原样转回真 stdout, 日志不吞)。
        结果: 读 --out 落盘的 JSON —— 不靠解析 stdout, 段行格式变了也不伤正确性。
        取消: sid 登记进 _procs, cancel_job 直接 terminate; 醒来先查取消名单,
        被停 = 抛 Cancelled(不是失败, 别走红横幅)。"""
        wm = whisper_model()
        if wm is None:
            raise RuntimeError("未配置 Whisper 模型：设置 → 本地模型")
        out = Path(audio_path).parent / ".whout.json"
        cmd = [sys.executable, WORKER_PY, "--audio", str(audio_path),
               "--model", str(wm), "--total", str(total or 0),
               "--out", str(out)]
        if lang and lang != "auto":
            cmd += ["--lang", lang]
        hw = load_hotwords()
        if hw:
            cmd += ["--prompt", "以下是常用人名与术语：" + "、".join(hw)]
        if silence_skip:
            cmd += ["--silence-skip"]
        try:
            if out.exists():
                out.unlink()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    env=dict(os.environ, PYTHONUNBUFFERED="1"))
            if sid:
                with self.lock:
                    self._procs[sid] = proc
            parser = WhisperStdout(self.pct, total) if total else None
            for line in proc.stdout:
                if parser:
                    parser.write(line)
                else:
                    print(line, end="", flush=True)   # 无总时长: 段行进日志, 不出数字
            err = (proc.stderr.read() or "").strip()
            rc = proc.wait()
            if sid and self.is_cancelled(sid):
                raise Cancelled("已停止")
            if rc != 0 or not out.exists():
                raise RuntimeError(f"Whisper 子进程异常退出({rc}): "
                                   f"{err[-200:] or '无结果文件'}")
            return json.loads(out.read_text(encoding="utf-8"))
        finally:
            if sid:
                with self.lock:
                    self._procs.pop(sid, None)
            try:
                out.unlink()
            except Exception:
                pass

    def _md_tag(self, d, meta):
        """取稿子原本的来源标注（Whisper 转写 / 云端精修 xxx）。
        手改一句不该把出处悄悄改成"本地" —— 先读 meta，再回读 md 头部那一行，都没有才算本地。"""
        tag = (meta.get("refinished") or "").strip()
        if tag:
            return tag
        try:
            for line in (d / "transcript.md").read_text(encoding="utf-8").splitlines()[:4]:
                m = re.search(r"\(([^()]{1,60})\)\s*$", line.strip())
                if m:
                    return m.group(1)
        except Exception:
            pass
        return "本地"

    def _write_md(self, d, meta, tag):
        """按 session meta 重写 transcript.md"""
        lines = [f"# {meta.get('name', '')}", "",
                 f"- 开始: {meta.get('started', '')}"
                 f" | 时长: {fmt_ts(meta.get('duration', 0))} ({tag})", ""]
        labels = meta.get("spk_labels") or {}
        for seg in meta.get("segments") or []:
            if seg.get("text"):
                raw = seg.get("spk")
                spk = f"〔{labels.get(raw) or raw}〕" if raw else ""
                lines.append(f"[{fmt_ts(seg['t'])}] {spk}{seg['text']}")
        summary = (meta.get("summary") or "").strip()
        if summary:
            lines += ["", "## 摘要（云端生成）", ""]
            lines += summary.splitlines()
        notes = meta.get("notes") or []
        if notes:
            lines += ["", "## 时间线笔记", ""]
            lines += [f"- [{fmt_ts(n['t'])}] {n['text']}" for n in notes]
        (d / "transcript.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------- 导入音频/视频文件 ----------
    def pick_file(self):
        """唤起 macOS 原生文件选择器(支持多选); 取消返回 []。
        路径按行返回 —— 逗号做分隔会被文件名里的逗号背刺, 换行才是安全的。"""
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'set theFiles to choose file with prompt "选择音频或视频文件" '
                 'of type {"public.audio", "public.movie", "public.avi"} '
                 'with multiple selections allowed\n'
                 'set s to ""\n'
                 'repeat with f in theFiles\n'
                 '  set s to s & (POSIX path of f) & linefeed\n'
                 'end repeat\n'
                 'return s'],
                capture_output=True, text=True, timeout=900)
            return [p.strip() for p in (r.stdout or "").splitlines() if p.strip()]
        except Exception:
            return []

    def import_audio(self, path, talk="single"):
        """导入音视频: 秒建项目并排队, 抽轨+转写都在 worker 里跑(批量不堵口)。
        talk: single=本地 Whisper | cloud=云端转写。本地队列串行, 云端 2 路并行。"""
        src = Path(path or "")
        if not src.is_file():
            raise RuntimeError("文件不存在")
        talk = talk if talk in ("single", "cloud") else "single"
        if talk == "cloud" and not cloud_cfg()["enable"]:
            raise RuntimeError("云端未配置：请填 API 地址、Key 与转写模型名")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        stem = (src.stem.replace("/", "-").replace(":", "-").strip() or "导入")[:52]
        # 导入时间可见地写进标题, 同一文件反复导入也能一眼分辨
        name = f"{stem} · {time.strftime('%m-%d %H:%M')}"[:60]
        d = SESSIONS_DIR / f"{stem}-{stamp}"
        i = 1
        while d.exists():
            d = SESSIONS_DIR / f"{stem}-{stamp}-{i}"; i += 1
        d.mkdir(parents=True)
        lang = (self.session or {}).get("lang", "zh") if self.session else "zh"
        (d / "session.json").write_text(json.dumps({
            "name": name, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stamp": stamp, "mode": "import", "lang": lang, "talk": talk,
            "duration": 0, "audio": None, "source": str(src),
            "segments": [], "notes": [],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        queue = "cloud" if (talk == "cloud" and cloud_flow() == "asr_post") else "local"
        self._job_begin(d.name, "import", state="wait")
        self._enqueue(d.name, queue,
                      lambda d=d, src=src, talk=talk: self._import_run(d, src, talk))
        return {"ok": True, "id": d.name, "name": name}

    def _import_run(self, d, src, talk):
        """队列 worker 本体: 抽音轨 → 回填 meta → 按 talk 分派转写。
        抽轨 ffmpeg 登记进 _procs —— 停止按钮在抽轨阶段也掐得动。"""
        import shutil
        self.stage("抽取音轨中", 0)
        m4a = d / "audio.m4a"
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR),
             "-c:a", "aac", "-b:a", "64k", str(m4a)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with self.lock:
            self._procs[d.name] = ff
        try:
            errb = ff.stderr.read()
            rc = ff.wait(timeout=1800)
        finally:
            with self.lock:
                self._procs.pop(d.name, None)
        if self.is_cancelled(d.name):
            raise Cancelled("已停止")
        if rc != 0 or not m4a.exists() or m4a.stat().st_size < 1024:
            shutil.rmtree(d, ignore_errors=True)
            tail = (errb or b"").decode(errors="ignore").strip().splitlines()
            raise RuntimeError("无法从该文件提取音频" + (f"：{tail[-1]}" if tail else ""))
        dur = probe_dur(m4a)
        # 回放副本从已转好的 16k m4a 派生: 不保留原始全频
        listen_rel, listen_err = encode_listen(m4a, d / LISTEN_FILE)
        sj = d / "session.json"
        meta = json.loads(sj.read_text(encoding="utf-8"))
        meta.update({"duration": round(dur, 1), "audio": "audio.m4a",
                     "audioListen": listen_rel,
                     "audioListenError": listen_err if not listen_rel else ""})
        sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        lang = meta.get("lang") or "zh"
        src_keep = src if src.is_file() else m4a
        if talk == "cloud" and cloud_flow() == "local_post":
            # 流程②: 音频不出本机, 本地转完后只把文字给云端做后制作
            self._import_whisper(d, lang, src_keep, post_flow=True)
            return
        if talk == "cloud":
            # 流程①: 云端导入不跑本地; 失败只报错(前端给手动入口), 绝不自动转本地
            try:
                self._import_cloud(d, m4a)
            except Cancelled:
                self._mark_stopped(d)
                self.emit(type="refinish", id=d.name, kind="cloud",
                          ok=False, cancelled=True)
            except Exception as e:
                print(f"[import] 云端转写失败: {e}", flush=True)
                self.emit(type="refinish", id=d.name, kind="cloud",
                          ok=False, err=str(e)[:160])
            return
        self._import_whisper(d, lang, src_keep)

    def _import_whisper(self, d, lang, src, post_flow=False):
        self._uncancel(d.name)
        try:
            # 转写优先用原始文件: 我们自己压的 audio.m4a 是 16k/mono/AAC64k,
            # 在它上面做降噪等于跟编码器失真打架(原文件才有可救的信息)
            new_segs, info = self._whisper_segs(src, [],
                probe_dur(d / "audio.m4a") or 0, lang, sid=d.name)
            if not new_segs:
                raise RuntimeError("未识别到语音内容")
            sj = d / "session.json"
            meta = json.loads(sj.read_text(encoding="utf-8"))
            meta["segments"] = new_segs
            meta["pretreat"] = info["pretreat"]
            meta["transcribe_src"] = str(src.name)
            meta["refinished"] = "whisper"
            sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                          encoding="utf-8")
            self._write_md(d, meta, "Whisper 转写")
            if post_flow and self.cloud_cfg_full()["enable"]:
                self._cloud_refine_bg(d, self.cloud_cfg_full())   # 终态由后处理广播
                return
            self.emit(type="refinish", id=d.name, kind="import")
            print(f"[import] 转写完成: {d.name}（{len(new_segs)} 段）", flush=True)
        except Cancelled:
            print(f"[import] 转写已被用户停止: {d.name}", flush=True)
            self._mark_stopped(d)
            self.emit(type="refinish", id=d.name, kind="import",
                      ok=False, cancelled=True)
        except Exception as e:
            print(f"[import] 转写失败: {e}", flush=True)
            self.emit(type="refinish", id=d.name, kind="import", ok=False)
        # jobs/refining 清理由队列 worker 的 finally 统一兜底

    def cloud_cfg_full(self):
        """转写用模型名没填时退回后处理模型名(两个框用户可能只填一个)。"""
        cfg = cloud_cfg()
        if not cfg["asr_model"]:
            cfg["asr_model"] = cfg["model"]
        return cfg

    # ---------- 云端重转: 上传录音, 拿云端 ASR 的新稿 ----------
    def cloud_transcribe(self, sid):
        """把 audio.m4a 上传到 标准兼容接口重新转写并替换稿子。
        这是唯一会把录音送出本机的功能: 仅按钮显式触发, 弹窗已写明。
        原稿备份 segments_pre_cloud, 可还原。失败只广播不自动跑本地
        —— 前端会给「跑本地转写」按钮, 由用户决定(规矩: 绝不双跑)。"""
        if not sid or ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        if self.state in ("recording", "paused", "stopping"):
            raise RuntimeError("录制中不能云端转写")
        if sid in self.progs:
            raise RuntimeError("该项目已在任务队列中")
        cfg = cloud_cfg()
        if not cfg["enable"]:
            raise RuntimeError("云端未配置：请填 API 地址与 Key（设置 → 对话模式 → 云端）")
        d = SESSIONS_DIR / sid
        if not (d / "session.json").is_file():
            raise RuntimeError("项目不存在")
        if not (d / "audio.m4a").is_file():
            raise RuntimeError("该项目没有音频")
        self._uncancel(sid)
        self._job_begin(sid, "cloud", state="wait")
        # 流程①转写完还要接后制作; 流程②不会走到这里(那条是本地转写+云端后制作)
        target = self._cloud_asr_then_post if cloud_flow() == "asr_post" else self._cloud_asr_bg
        self._enqueue(sid, "cloud",
                      lambda: target(d, self.cloud_cfg_full()))
        return {"ok": True, "id": sid}

    def _cloud_asr_then_post(self, d, cfg):
        """云端流程①: 音频上云转写 → 结果再上云做后制作(一次终态广播)"""
        if self._cloud_asr_bg(d, cfg, emit_end=False):
            self._cloud_refine_bg(d, cfg)

    def _cloud_asr_bg(self, d, cfg, emit_end=True):
        """返回 True=已出稿。emit_end=False 时把终态广播让给后续后处理步骤。"""
        sj = d / "session.json"
        try:
            t0 = time.time()
            # 上云用转写母本 audio.m4a —— 停录时它就是从 raw.s16(唯一的全信息源)
            # 带着降噪滤镜链一次编出来的, 所以云端拿到的也是降噪后的音频,
            # 和本地 Whisper / 回放用的是同一份, 出稿差异可直接归因。
            # 仍绝不选 audio_listen.m4a: 那份是专门给人耳回放的副本, 与转写用的
            # 不是同一条时间轴基准, 换上去会让字幕对不上。
            up = d / "audio.m4a"
            meta = json.loads(sj.read_text(encoding="utf-8"))
            cfg["lang"] = meta.get("lang")
            cfg["hotwords"] = load_hotwords()
            # 时长给等待阶段估算用; 拿不到就只显示阶段文字, 不给编造的数字
            cfg["dur"] = float(meta.get("duration") or 0)
            print(f"[cloud-asr] 源文件 {up.name} → {cfg['base_url']} "
                  f"({up.stat().st_size/2**20:.1f} MB)，上传格式 {cfg.get('fmt') or asr_fmt()}",
                  flush=True)
            res = cloud_asr(cfg, up, prog=self.cloud_prog,
                            cancel=self._ck(d.name), sid=d.name)
            self._ck(d.name)()
            segs = []
            for s in res["segments"]:
                txt = (s.get("text") or "").strip()
                if not txt:
                    continue
                segs.append({"t": round(float(s.get("start", 0)), 2),
                             "d": round(max(0.1, float(s.get("end", 0))
                                            - float(s.get("start", 0))), 2),
                             "text": txt, "spk": s.get("spk") or ""})
            if not segs and res["text"]:
                segs = [{"t": 0, "d": round(float(meta.get("duration") or 1), 2),
                         "text": res["text"], "spk": ""}]
            if not segs:
                raise RuntimeError("云端未识别到语音内容")
            segs, dropped = self._drop_repeat_loops(segs)
            if dropped:
                print(f"[cloud-asr] 跨段复读过滤: 丢弃 {len(dropped)} 段", flush=True)
            # 备份只在第一次写: 云端转写后再叠加文字后处理, 不能把最早的本地稿备份顶掉
            if not meta.get("segments_pre_cloud"):
                meta["segments_pre_cloud"] = [s for s in (meta.get("segments") or [])
                                              if s.get("text")]
            meta["segments"] = self._merge_segs(segs)
            spks = sorted({x.get("spk") for x in segs if x.get("spk")})
            if spks:
                meta["speakers"] = spks
            # 「已上云」确认标记只在整段流程走完的那一步落盘。作为云端流程①的中间步
            # (emit_end=False, 后面还要接 _cloud_refine_bg 润色)时先不打标: 否则一旦
            # 润色失败, 稿件却已停在「已上云」态 → 前端 fromCloud 把云朵/静音按钮整排
            # 藏掉, 用户既没法重试、也点不到「文字后处理」单独补跑润色。转写正文照旧落盘。
            if emit_end:
                meta["refinished"] = f"cloud-asr:{cfg.get('asr_model') or cfg['model']}"
                meta["cloud_used"] = True        # 侧栏「已上云」标记的依据
            sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                          encoding="utf-8")
            self._write_md(d, meta, f"云端转写 {time.time()-t0:.0f}s")
            if emit_end:
                self.emit(type="refinish", id=d.name, kind="cloud")
            print(f"[cloud-asr] 完成: {d.name}（{len(meta['segments'])} 段）", flush=True)
            return True
        except Cancelled:
            print(f"[cloud-asr] 已被用户停止: {d.name}", flush=True)
            self._mark_stopped(d)
            if emit_end:
                self.emit(type="refinish", id=d.name, kind="cloud",
                          ok=False, cancelled=True)
            return False
        except Exception as e:
            print(f"[cloud-asr] 失败: {e}", flush=True)
            if emit_end:
                # 分类 + 人话: 原始堆栈只留在日志里, 界面上给能行动的原因
                kind = cloud_err_kind(e)
                self.emit(type="refinish", id=d.name, kind="cloud", ok=False,
                          err=cloud_err_text(kind, e), err_kind=kind)
            return False
        # jobs/refining 清理由队列 worker 的 finally 统一兜底

    # ---------- 云端增强: 文字后处理(录音不上传) ----------
    def cloud_refine(self, sid):
        """把本地稿的纯文本交给云端大模型: 修错字/顺标点/理分段 + 全篇摘要。
        音频永远不出本机; 原稿备份进 segments_pre_cloud, 可随时手动还原。"""
        if not sid or ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        if self.state in ("recording", "paused", "stopping"):
            raise RuntimeError("录制中不能云端精修")
        if sid in self.progs:
            raise RuntimeError("该项目已在任务队列中")
        cfg = cloud_cfg()
        if not cfg["enable"]:
            raise RuntimeError("云端未配置：请填 API 地址与 Key（设置 → 对话模式 → 云端）")
        d = SESSIONS_DIR / sid
        sj = d / "session.json"
        if sj.is_file():
            meta = json.loads(sj.read_text(encoding="utf-8"))
        else:
            # 早期项目只有 transcript.md 没有 session.json: 用同一条 md 兜底解析,
            # 并就地补一份 session.json, 让纯文本稿也能走云端后处理
            try:
                meta = self.load(sid)
            except Exception:
                raise RuntimeError("项目不存在或没有可读文稿")
            meta.pop("legacy", None)
            meta["audio"] = None
            meta.setdefault("notes", [])
            sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        segs = [s for s in (meta.get("segments") or []) if s.get("text")]
        if len(segs) < 3:
            raise RuntimeError("该项目文稿太少，无需云端精修")
        self._job_begin(sid, "cloud", state="wait")
        self._enqueue(sid, "cloud", lambda: self._cloud_refine_bg(d, cfg))
        return {"ok": True, "id": sid}

    # ---------- 课后笔记 ----------
    def study_note(self, sid, tpl_id):
        """按选定模板生成课后笔记, 结果写项目内 note.md。
        笔记是新增物: 不动 segments、不锁页面、不进 refining, 所以 kind='note' 只走任务表。"""
        if not sid or ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        if self.state in ("recording", "paused", "stopping"):
            raise RuntimeError("录制中不能生成笔记")
        if sid in self.progs:
            raise RuntimeError("该项目已在任务队列中")
        tpl = note_tpl_get(tpl_id)
        if not tpl:
            raise RuntimeError("请先选一个笔记模板")
        cfg = cloud_cfg()
        if not cfg["enable"]:
            raise RuntimeError("云端未配置：请填 API 地址与 Key（设置 → 对话模式 → 云端）")
        d = SESSIONS_DIR / sid
        if not (d / "session.json").is_file():
            raise RuntimeError("项目不存在或没有可读文稿")
        segs = [s for s in (json.loads((d / "session.json").read_text(encoding="utf-8"))
                            .get("segments") or []) if s.get("text")]
        if len(segs) < 3:
            raise RuntimeError("该项目文稿太少，不必生成笔记")
        self._job_begin(sid, "note", state="wait")
        self._enqueue(sid, "cloud", lambda: self._study_note_bg(d, cfg, tpl, segs))
        return {"ok": True, "id": sid}


    def _study_note_bg(self, d, cfg, tpl, segs):
        sid = d.name
        try:
            self._ck(sid)()
            # 上传瘦身: 剥掉每行的时间戳与说话人前缀 —— 那是旧分片对位机制的遗留格式,
            # 全文直出用不上(笔记输出也不含时间戳)。纯字符串处理零成本, 每行省约十个 token。
            body = "\n".join(t for t in (s.get("text", "").strip() for s in segs if s.get("text")) if t)
            # 笔记走单独配的「生成笔记模型」(cloud_cfg 里已让它在留空时回退到后处理模型),
            # 好让用户给这类机械活挑一个更便宜、且不需要思考的模型, 而把贵模型留给别的用途。
            ncfg = dict(cfg)
            ncfg["model"] = cfg.get("note_model") or cfg.get("model")
            ncfg_think_off = cloud_think_off_for(ncfg["provider"], ncfg["model"],
                                                 cfg.get("note_think", True))
            self.stage("通读全稿生成笔记", 10)
            print(f"[note] {tpl['name']} 通读 {len(segs)} 行 / {len(body)} 字"
                  f"（模型 {ncfg['model'] or '未填'} · 全文直出不分片 · 关思考={'on' if ncfg_think_off else 'off'}）", flush=True)
            # 全文一次直出: 模型真正通读上下文, 不再分片提要点 —— 分片压缩丢掉的细节,
            # 汇总阶段永远补不回来(笔记里出现"(待逐字稿补充)"就是这个原因)。
            # 稿子长到模型上下文装不下时, 让 API 直接报错: 大声失败好过悄悄丢内容。
            note = cloud_chat(ncfg, [
                {"role": "system", "content": tpl["prompt"] + MD_RULES},
                {"role": "user", "content": body}],
                temperature=0.3, retries=1, think_off=ncfg_think_off)   # 输出上限不写死: 交 cloud_chat 按正文量折算
            note = (note or "").strip()
            if not note:
                raise RuntimeError("模型没返回笔记内容")
            head = f"# {d.name.split('-2026')[0]}\n\n"
            (d / NOTE_FILE).write_text(
                head + f"> 由模板「{tpl['name']}」生成 · "
                       f"{time.strftime('%m-%d %H:%M', time.localtime())}\n\n{note}\n",
                encoding="utf-8")
            self.emit(type="refinish", id=sid, kind="note", ok=True)
            print(f"[note] 完成: {sid}（{len(note)} 字）", flush=True)
        except Cancelled:
            print(f"[note] 已停止: {sid}", flush=True)
            self.emit(type="refinish", id=sid, kind="note", ok=False, cancelled=True)
        except Exception as e:
            kind = cloud_err_kind(e)
            print(f"[note] 失败: {e}", flush=True)
            self.emit(type="refinish", id=sid, kind="note", ok=False,
                      err=cloud_err_text(kind, e), err_kind=kind)

    @staticmethod
    def _cloud_lines(segs):
        out = []
        for s in segs:
            spk = f"{s['spk']}｜" if s.get("spk") else ""
            out.append(f"[{fmt_ts(s['t'])}] {spk}{s['text']}")
        return out

    @staticmethod
    def _cloud_parse(reply, orig_by_ts):
        """解析模型回稿的一行 → 段。时间戳/说话人必须能在原稿找到归属(±2s),
        找不到的行丢弃; 同一段原稿只许被命中一次(防模型重复吐行);
        整体对上不足 85% 视为这次回复不可信, 由调用方保留原稿。"""
        new, used = [], set()
        for line in reply.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "```")):
                continue
            m = re.match(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?:(S\d{1,2})｜)?(.+)$", line)
            if not m:
                continue
            ts, spk, text = m.group(1), m.group(2), m.group(3).strip()
            parts = [int(x) for x in ts.split(":")]
            # fmt_ts 一小时以内输出 分:秒 两段, 以上才是 时:分:秒 三段
            sec = (parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3
                   else parts[0] * 60 + parts[1])
            hit = orig_by_ts.get(round(sec / 2) * 2) or orig_by_ts.get(
                round((sec + 1) / 2) * 2) or orig_by_ts.get(round((sec - 1) / 2) * 2)
            if not hit or id(hit) in used:
                continue
            used.add(id(hit))
            new.append({"t": hit["t"], "d": hit["d"], "text": text,
                        "spk": hit.get("spk", "")})
        return new

    def _cloud_refine_bg(self, d, cfg):
        sj = d / "session.json"
        try:
            meta = json.loads(sj.read_text(encoding="utf-8"))
            orig = [s for s in (meta.get("segments") or []) if s.get("text")]
            hw_note = "、".join(load_hotwords()[:80])
            _L = {"zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文", "yue": "粤语"}
            lang_note = _L.get(meta.get("lang") or "", "")
            lines = self._cloud_lines(orig)
            # 长稿分片(按行, ~6000 字/片), 每片独立精修后原序拼回
            chunks, cur, size = [], [], 0
            for ln in lines:
                cur.append(ln); size += len(ln)
                if size > 6000:
                    chunks.append(cur); cur, size = [], 0
            if cur:
                chunks.append(cur)
            self.stage("云端润色中")
            print(f"[cloud] {cfg['model']} 精修 {len(lines)} 行, 分 {len(chunks)} 片", flush=True)

            # 润色要求可由用户在设置里自定义(cloud_prompt); 但"逐行同格式、不得增删"
            # 这句是端上解析的硬契约, 必须固定追加, 否则对位闸门全线失效。
            CONTRACT = ("逐行改写正文，不得增删句子、不得改写时间戳与说话人标签、不得翻译；"
                        "输出与输入行数一致，每行保持原格式 [分:秒] S01｜正文；"
                        "不要输出任何解释或额外标记。")
            DEFAULT_SYS = ("你是逐字稿校对器，处理语音识别输出中的同音错字、标点缺失与"
                         "无意义口语重复（如「那个那个那个」保留一次）。")
            SYS = (cfg.get("prompt") or DEFAULT_SYS) + "\n" + CONTRACT
            if hw_note:
                SYS += ("\n本场涉及的专有名词，按这些写法校正：" + hw_note)
            if lang_note:
                SYS += ("\n仅使用" + lang_note + "输出。")
            # 分片之间互不依赖 → 4 路并行。串行时总耗时 = 片数 × 单片耗时(实测
            # 该转写模型单片约 110 秒, 4 片 7.3 分钟); 并行后 ≈ 最慢的一片。
            from concurrent.futures import ThreadPoolExecutor, as_completed
            orig_by_ts = {}
            for s in orig:
                orig_by_ts.setdefault(round(s["t"] / 2) * 2, s)
            bail = threading.Event()      # 取消时让还没开跑的片直接放弃

            def keep(ch):
                """把这几行原样回退成段(宁可这段没被精修, 也不崩、不丢)。"""
                joined = "\n".join(ch)
                return [{"t": s["t"], "d": s["d"], "text": s["text"],
                         "spk": s.get("spk", "")}
                        for s in orig if f"[{fmt_ts(s['t'])}]" in joined]

            def _refine_lines(ch):
                if bail.is_set():
                    raise Cancelled("已停止")
                try:
                    reply = cloud_chat(cfg, [
                        {"role": "system", "content": SYS},
                        {"role": "user", "content": "\n".join(ch)}],
                        retries=1, backoff=3.0)   # 单片撞限流/超时只补打一次,
                                                  # 不让整条任务白等几分钟重跑
                except Truncated:
                    # 模型单次输出装不下这么长的改写 → 按位置把「这一片」拆两半各自重试;
                    # 拆到只剩一行还截断(几乎不可能)就保留原文, 绝不整条判死。
                    if len(ch) <= 1:
                        print("[cloud] 单片仍被截断，保留原文", flush=True)
                        return keep(ch)
                    mid = len(ch) // 2
                    print(f"[cloud] 片被截断，就地拆成 {mid}+{len(ch)-mid} 行重试", flush=True)
                    return _refine_lines(ch[:mid]) + _refine_lines(ch[mid:])
                got = self._cloud_parse(reply, orig_by_ts)
                # 对不上 >15% 就这片作废, 保原文(宁可不变糟)
                if len(got) < int(len(ch) * 0.85):
                    print(f"[cloud] 片回稿对位率低({len(got)}/{len(ch)})，保留原文", flush=True)
                    return keep(ch)
                return got

            def one(i, ch):
                # 错峰起跳: 4 路同一瞬间打出去最容易撞该服务商的并发/QPS 限制
                time.sleep(i * 0.2)
                return _refine_lines(ch)

            results, futs, done = {}, {}, 0
            workers = max(1, min(4, len(chunks)))
            ex = ThreadPoolExecutor(max_workers=workers)
            try:
                futs = {ex.submit(one, i, ch): i for i, ch in enumerate(chunks)}
                for f in as_completed(futs):
                    results[futs[f]] = f.result()
                    done += 1
                    # 进度只在本(任务)线程里更新: stage() 靠线程局部 sid 路由,
                    # 放进片线程会串到别的任务上去。留 5% 给摘要阶段。
                    self.cloud_prog(frac=done / max(1, len(chunks)) * 0.95)
                    self._ck(d.name)()      # 每收一片检查一次取消
            except BaseException:
                # 取消/出错: 未开跑的片直接撤, 在途的片不陪等(否则停止要点好几分钟)
                bail.set()
                for f in futs:
                    f.cancel()
                ex.shutdown(wait=False, cancel_futures=True)
                raise
            ex.shutdown(wait=True)
            # 按片号原序拼回, 并行完成顺序不能影响稿子顺序
            refined = [x for i in sorted(results) for x in results[i]]
            self.stage("生成摘要中")
            # 摘要(用修正后的全文, 一次调用)。「深度思考」是用户开关、默认开(提精度);
            # 只有用户把它关了、且这个后处理模型确实支持关, 才发关思考参数省 token。
            full = " ".join(s["text"] for s in refined)[:15000]
            summary = ""
            summary_err = ""
            SUM_INSTR = ("用中文为这段逐字稿写摘要。第一行固定输出一个概括全篇的大标题，"
                         "用 Markdown 一级标题语法（以「# 」开头），不超过 20 字，"
                         "不加书名号、引号或句号；标题单独占一行，其后空一行再写一句话主题，"
                         "然后列 3-6 条要点（保留说话人区分与关键结论）。只输出摘要本身。" + MD_RULES)
            sum_msgs = [{"role": "system", "content": SUM_INSTR},
                        {"role": "user", "content": full}]
            think_off = cloud_think_off_for(cfg["provider"], cfg["model"],
                                            cfg.get("chat_think", True))
            try:
                summary = cloud_chat(cfg, sum_msgs, temperature=0.2, think_off=think_off)
            except Exception as e:
                summary_err = str(e)[:180]
                print(f"[cloud] 摘要失败(正文已完成): {e}", flush=True)

            if not meta.get("segments_pre_cloud"):
                meta["segments_pre_cloud"] = orig      # 一级备份, 可还原
            meta["segments"] = self._merge_segs(refined) if not any(
                s.get("spk") for s in refined) else refined
            meta["summary"] = summary
            # 摘要失败以前只进日志，界面上只表现为"摘要凭空少了"；
            # 现在留一条回执，前端据此挂横幅并给重试入口。成功则清掉旧回执。
            if summary_err:
                meta["summary_error"] = summary_err
            else:
                meta.pop("summary_error", None)
            meta["refinished"] = f"cloud:{cfg['model']}"
            meta["cloud_used"] = True        # 整段流程(转写+润色)跑完, 此刻才打「已上云」标
            sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                          encoding="utf-8")
            self._write_md(d, meta, f"云端精修 {cfg['model']}")
            self.emit(type="refinish", id=d.name, kind="cloud")
            print(f"[cloud] 完成: {d.name}（{len(refined)} 段）", flush=True)
        except Cancelled:
            print(f"[cloud] 后处理已被用户停止: {d.name}", flush=True)
            self.emit(type="refinish", id=d.name, kind="cloud",
                      ok=False, cancelled=True)
        except Exception as e:
            print(f"[cloud] 失败: {e}", flush=True)
            self.emit(type="refinish", id=d.name, kind="cloud", ok=False,
                      err=str(e)[:160])
        # jobs/refining 清理由队列 worker 的 finally 统一兜底

    def _import_cloud(self, d, src):
        """导入文件的云端转写: 直接上传原始文件(音质全信息), 换稿带时间戳。"""
        sj = d / "session.json"
        self._uncancel(d.name)
        try:
            t0 = time.time()
            cfg = self.cloud_cfg_full()
            cfg["lang"] = json.loads(sj.read_text(encoding="utf-8")).get("lang")
            cfg["hotwords"] = load_hotwords()
            print(f"[import] 云端转写 源文件 {src.name} "
                  f"({src.stat().st_size/2**20:.1f} MB) → {cfg['base_url']}，"
                  f"上传格式 {cfg.get('fmt') or asr_fmt()}", flush=True)
            res = cloud_asr(cfg, src, cancel=self._ck(d.name), sid=d.name)
            self._ck(d.name)()          # 单次请求回来越早取消也要作废结果
            segs = []
            for s in res["segments"]:
                txt = (s.get("text") or "").strip()
                if not txt:
                    continue
                segs.append({"t": round(float(s.get("start", 0)), 2),
                             "d": round(max(0.1, float(s.get("end", 0))
                                            - float(s.get("start", 0))), 2),
                             "text": txt, "spk": s.get("spk") or ""})
            meta = json.loads(sj.read_text(encoding="utf-8"))
            if not segs and res["text"]:
                segs = [{"t": 0, "d": round(float(meta.get("duration") or 1), 2),
                         "text": res["text"], "spk": ""}]
            if not segs:
                raise RuntimeError("云端未识别到语音内容")
            segs, dropped = self._drop_repeat_loops(segs)
            meta["segments"] = self._merge_segs(segs)
            spks = sorted({x.get("spk") for x in segs if x.get("spk")})
            if spks:
                meta["speakers"] = spks
            meta["transcribe_src"] = str(src.name)
            # 云端流程①(转写后再润色): 「已上云」标记交给润色成功后统一落盘, 此处先不打,
            # 免得润色失败却把导入稿钉死在「已上云」态、云朵按钮消失、无法重试/补跑润色。
            will_post = cloud_flow() == "asr_post" and cfg["enable"]
            if not will_post:
                meta["refinished"] = f"cloud-asr:{cfg.get('asr_model') or cfg['model']}"
                meta["cloud_used"] = True          # 侧栏「已上云」标记的依据
            sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                          encoding="utf-8")
            self._write_md(d, meta, f"云端转写·导入 {time.time()-t0:.0f}s")
            if will_post:
                cfg2 = dict(cfg, lang=meta.get("lang"), hotwords=load_hotwords())
                self._cloud_refine_bg(d, cfg2)     # 终态 + 「已上云」标记由润色成功后落盘
                return
            self.emit(type="refinish", id=d.name, kind="import")
            print(f"[import] 云端转写完成: {d.name}（{len(meta['segments'])} 段）", flush=True)
        except Cancelled:
            raise                    # 取消/异常终态由 _import_run 分派处统一收尾

    def rerun(self, sid):
        """已停止的空壳项目重跑转写: 用抽好的 audio.m4a(原始文件路径没存,
        且导入时已按最高可用音质抽过轨)。清 stopped 标记后走本地链路。"""
        if not sid or ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        d = SESSIONS_DIR / sid
        sj = d / "session.json"
        if not sj.is_file():
            raise RuntimeError("项目不存在")
        if sid in self.progs:
            raise RuntimeError("该项目已在任务队列中")
        if not (d / "audio.m4a").is_file():
            raise RuntimeError("该项目没有音频，无法重跑")
        meta = json.loads(sj.read_text(encoding="utf-8"))
        meta.pop("stopped", None)
        sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        self._uncancel(sid)
        lang = meta.get("lang") or "zh"
        self._job_begin(sid, "import", state="wait")
        self._enqueue(sid, "local",
                      lambda: self._import_whisper(d, lang, d / "audio.m4a"))
        return {"ok": True, "id": sid}

    def refine_silence(self, sid):
        """手动「跳过静音重跑」: 整份稿子被复读幻觉污染时的救急入口。
        默认精修路径不碰任何 Whisper 参数, 只有用户点这个按钮才会打开
        hallucination_silence_threshold —— 因为它实测会连真实语音一起删。"""
        if not sid or ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        if self.state in ("recording", "paused", "stopping"):
            raise RuntimeError("录制中不能重跑")
        if sid in self.progs:
            raise RuntimeError("该项目已在任务队列中")
        d = SESSIONS_DIR / sid
        sj = d / "session.json"
        if not sj.is_file():
            raise RuntimeError("项目不存在")
        if not (d / "audio.m4a").is_file():
            raise RuntimeError("该项目没有音频，无法重跑")
        lang = (json.loads(sj.read_text(encoding="utf-8")) or {}).get("lang", "zh")
        self._uncancel(sid)
        self._job_begin(sid, "refine", state="wait")
        self._enqueue(sid, "local",
                      lambda: self._refinish_whisper(d, lang, True))
        return {"ok": True, "id": sid}

    def _refinish_whisper(self, d, lang, silence_skip=False, post_flow=False):
        """停录后用 Whisper 重识别整条音频(长上下文, 质量高于流式块)。
        直接采用 Whisper 返回的分段起止时间戳, 不再按输出标点切句——
        曾发生整条输出无标点 → 时长比例切分击穿 → 515 字全堆进第一句的事故。
        重复环/幻觉段回退到该时间段的 SenseVoice 原句。失败静默保留原稿。
        silence_skip=True: 用户手动点「跳过静音重跑」的救急路径, 见 refine_silence。"""
        tag = "Whisper 复核·跳过静音" if silence_skip else "Whisper 复核"
        self._uncancel(d.name)
        try:
            sj_path = d / "session.json"
            meta = json.loads(sj_path.read_text(encoding="utf-8"))
            old = [] if silence_skip else (meta.get("segments") or [])
            if not old and not silence_skip:
                return
            new_segs, info = self._whisper_segs(
                d / "audio.m4a", old, float(meta.get("duration") or 0) or 1, lang,
                silence_skip=silence_skip, sid=d.name,
                # 停录时 audio.m4a 已在源头吃过滤镜链(raw.s16 全信息源),
                # 这里再套一遍就是对同一份噪声处理两次; 老项目没这个字段,
                # 沿用旧逻辑照设置走。
                pretreat=False if (meta.get("audio_pretreat") or "off") != "off" else None)
            if not new_segs:
                return
            meta["segments"] = new_segs
            meta["pretreat"] = (info["pretreat"] if info["pretreat"] != "off"
                                else (meta.get("audio_pretreat") or "off"))
            meta["refinished"] = "whisper+silence" if silence_skip else "whisper"
            sj_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                               encoding="utf-8")
            # 重写 transcript.md
            lines = [f"# {meta.get('name', '')}", "",
                     f"- 开始: {meta.get('started', '')}"
                     f" | 时长: {fmt_ts(meta.get('duration', 0))} ({tag})", ""]
            for seg in new_segs:
                if seg["text"]:
                    lines.append(f"[{fmt_ts(seg['t'])}] {seg['text']}")
            notes = meta.get("notes") or []
            if notes:
                lines += ["", "## 时间线笔记", ""]
                lines += [f"- [{fmt_ts(n['t'])}] {n['text']}" for n in notes]
            (d / "transcript.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            if post_flow:
                # 本地转完只把文字送云端润色: 终态由后处理那一步统一广播
                cfgp = self.cloud_cfg_full()
                if cfgp["enable"]:
                    self._cloud_refine_bg(d, cfgp)
                    return
                self.emit(type="refinish", id=d.name)
                return
            self.emit(type="refinish", id=d.name)
            print(f"[refinish] Whisper 复核完成: {d.name}", flush=True)
        except Cancelled:
            print(f"[refinish] 精修已被用户停止(原稿保持): {d.name}", flush=True)
            self.emit(type="refinish", id=d.name, ok=False, cancelled=True)
        except Exception as e:
            print(f"[refinish] Whisper 复核失败(保留原稿): {e}", flush=True)
            # 失败也要广播终态, 否则前端精修指示永远卡住
            self.emit(type="refinish", id=d.name, ok=False)
        # refining/jobs 清理由队列 worker 的 finally 统一兜底

    # ---------- 笔记 / 重命名 ----------
    def note(self, text):
        with self.lock:
            if self.state not in ("recording", "paused"):
                raise RuntimeError("只能在录制过程中记笔记")
            item = {"t": round(self.total_samples / SR, 1), "text": text.strip()}
            self.session["notes"].append(item)
            self.emit(type="note", **item)
            return item

    def set_spk_labels(self, sid, labels):
        """保存该项目的说话人显示名(键是模型给的 S01/S02, 只在本项目内有效)"""
        if not sid or ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        sj = SESSIONS_DIR / sid / "session.json"
        if not sj.is_file():
            raise RuntimeError("项目不存在")
        meta = json.loads(sj.read_text(encoding="utf-8"))
        clean = {}
        for k, v in (labels or {}).items():
            if re.fullmatch(r"S\d{1,3}", str(k)) and str(v).strip():
                clean[k] = str(v).strip()[:12]
        meta["spk_labels"] = clean
        sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        # 改名要连带重写导出稿, 否则界面上是"客户"、md 里还是 S01
        self._write_md(SESSIONS_DIR / sid, meta,
                       meta.get("refinished", "") or "本地")
        return {"ok": True, "labels": clean}

    def edit_segment(self, sid, t, text, undo=False):
        """就地改一句：按时间点定位，改 session.json 里那句的 text，并连带重写 transcript.md。
        撤销不需要后端存副本 —— 前端留着旧文字，再打一次这个接口回填即可。"""
        if ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        if self.state in ("recording", "paused", "stopping"):
            raise RuntimeError("录制中不能改稿")
        if sid in self.progs:
            raise RuntimeError("该项目正在跑后台任务，等它结束再改")
        new = (text or "").strip()
        if not new:
            raise RuntimeError("改完是空的 —— 要删这句请到文稿里删，或重跑转写")
        if len(new) > 5000:
            raise RuntimeError("这一句太长了（上限 5000 字）")
        d = SESSIONS_DIR / sid
        sj = d / "session.json"
        if not sj.is_file():
            raise RuntimeError("项目不存在")
        meta = json.loads(sj.read_text(encoding="utf-8"))
        segs = meta.get("segments") or []
        try:
            want = float(t)
        except (TypeError, ValueError):
            raise RuntimeError("时间点不对")
        hit = None
        for s in segs:
            if abs(float(s.get("t", -1e9)) - want) < 0.01:
                hit = s
                break
        if hit is None:
            raise RuntimeError("没找到这一句（稿子可能刚被重写过，刷新一下）")
        old = hit.get("text") or ""
        if old == new and not undo:
            return {"ok": True, "t": hit["t"], "old": old, "text": new,
                    "ed": hit.get("ed"), "same": True}
        hit["text"] = new
        # 修订标记：界面上留一个小点，一眼看出哪句被手改过；撤销回填时把点抹掉
        if undo:
            hit.pop("ed", None)
        else:
            hit["ed"] = int(time.time())
        sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        self._write_md(d, meta, self._md_tag(d, meta))
        return {"ok": True, "t": hit["t"], "old": old, "text": new, "ed": hit.get("ed")}

    def rename(self, name, sid=None):
        import os as _os
        name = (name or "").strip().replace("/", "-").replace(":", "-")
        if not name:
            raise RuntimeError("标题不能为空")
        cur_dir = self.session["dir"] if self.session else None
        target = (SESSIONS_DIR / sid) if sid else cur_dir
        if target is None or not target.is_dir():
            raise RuntimeError("会话不存在")
        is_live = (cur_dir is not None) and (target == cur_dir) and (self.state != "idle")
        if not is_live:
            # 查看旧项目改名: 只改磁盘, 不动录音
            return self._rename_on_disk(target, name)
        # ---- 录音中改名(原逻辑) ----
        with self.lock:
            if name == self.session["name"]:
                return {"ok": True, "name": name}
            s = self.session
            was_rec = self.state == "recording"
            if was_rec:
                self._stop_ffmpeg_noblock()
        if was_rec:
            self._kill_ffmpeg_sync()
        with self.lock:
            if was_rec:
                self._drain_vad()
                ENGINE.new_vad()
            s = self.session
            new_dir = s["dir"].parent / f"{name}-{s['stamp']}"
            if new_dir.exists():
                raise RuntimeError("同名会话已存在")
            _os.rename(s["dir"], new_dir)
            s["name"], s["dir"] = name, new_dir
            self.emit(type="status", **self.status())
            if was_rec:
                self._start_recorder(s["mode"])
                self.state = "recording"
        return {"ok": True, "name": name}

    def _rename_on_disk(self, d, name):
        import os as _os
        parts = d.name.split("-")
        stamp = "-".join(parts[-2:]) if len(parts) >= 2 else ""
        new_dir = d.parent / (f"{name}-{stamp}" if stamp else name)
        if new_dir.exists() and new_dir != d:
            raise RuntimeError("同名会话已存在")
        if new_dir != d:
            _os.rename(d, new_dir)
            d = new_dir
        # 同步 session.json 与 transcript.md 标题
        sj = d / "session.json"
        if sj.exists():
            try:
                meta = json.loads(sj.read_text(encoding="utf-8"))
                meta["name"] = name
                sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:
                pass
        md = d / "transcript.md"
        if md.exists():
            lines = md.read_text(encoding="utf-8").splitlines(keepends=True)
            if lines and lines[0].startswith("#"):
                lines[0] = f"# {name}\n"
                md.write_text("".join(lines), encoding="utf-8")
        return {"ok": True, "name": name, "id": d.name}

    # ---------- 历史 ----------
    @staticmethod
    def _clean_title(t):
        """去掉旧版标题里的「逐字稿：」等前缀"""
        return re.sub(r"^(逐字稿|转录稿|文稿)[:：]\s*", "", (t or "").strip())

    def history(self):
        items = []
        if not SESSIONS_DIR.exists():
            return items
        for d in sorted(SESSIONS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            sj = d / "session.json"
            if sj.exists():
                try:
                    meta = json.loads(sj.read_text(encoding="utf-8"))
                except Exception:
                    continue
                items.append({"id": d.name, "name": self._clean_title(meta.get("name", d.name)),
                              "date": meta.get("started", ""),
                              "duration": meta.get("duration", 0),
                              "lines": sum(1 for s in meta.get("segments", []) if s.get("text")),
                              "hasAudio": bool(meta.get("audio")),
                              "cloud": bool(meta.get("cloud_used")),
                              "stopped": bool(meta.get("stopped")),
                              "group": str(meta.get("group") or ""),
                              "notes": len(meta.get("notes", []))})
            elif (d / "transcript.md").exists():
                # 旧版 whisper 会话
                md = (d / "transcript.md").read_text(encoding="utf-8")
                lines = re.findall(r"^\[(\d{2}:\d{2}(?::\d{2})?)\] (.+)$", md, re.M)
                name = re.match(r"^# (.+)$", md, re.M)
                items.append({"id": d.name, "name": self._clean_title(name.group(1) if name else d.name),
                              "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime)),
                              "duration": 0, "lines": len(lines),
                              "hasAudio": False, "notes": 0, "group": "", "legacy": True})
        return items

    # ---- 分组: 成员写各项目 session.json 的 group 字段, 顺序/折叠在 groups.json ----
    def _each_meta(self):
        """遍历所有项目的 (session.json 路径, meta), 读失败的跳过"""
        if not SESSIONS_DIR.is_dir():
            return
        for d in sorted(SESSIONS_DIR.iterdir()):
            sj = d / "session.json"
            if not d.is_dir() or not sj.is_file():
                continue
            try:
                yield sj, json.loads(sj.read_text(encoding="utf-8"))
            except Exception:
                continue

    def group_set(self, ids, group):
        n = 0
        want = set(ids)
        for sj, meta in self._each_meta():
            if sj.parent.name in want:          # 目录名就是项目 id(history 同款口径)
                meta["group"] = group
                sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                              encoding="utf-8")
                n += 1
        return n

    def group_rename(self, frm, to):
        n = 0
        for sj, meta in self._each_meta():
            if str(meta.get("group") or "") == frm:
                meta["group"] = to
                sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                              encoding="utf-8")
                n += 1
        g = load_groups()
        g["order"] = [to if x == frm else x for x in g["order"]]
        g["collapsed"] = [to if x == frm else x for x in g["collapsed"]]
        if frm in g["colors"]:
            g["colors"][to] = g["colors"].pop(frm)
        save_groups(g)
        return n

    def group_delete(self, name):
        """删组 = 成员回到未分组; 文稿与录音一律不动"""
        n = 0
        for sj, meta in self._each_meta():
            if str(meta.get("group") or "") == name:
                meta["group"] = ""
                sj.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                              encoding="utf-8")
                n += 1
        g = load_groups()
        g["order"] = [x for x in g["order"] if x != name]
        g["collapsed"] = [x for x in g["collapsed"] if x != name]
        g["colors"].pop(name, None)
        save_groups(g)
        return n

    def load(self, sid):
        d = SESSIONS_DIR / sid
        if not d.is_dir() or ".." in sid:
            raise RuntimeError("会话不存在")
        sj = d / "session.json"
        if sj.exists():
            meta = json.loads(sj.read_text(encoding="utf-8"))
            meta["name"] = self._clean_title(meta.get("name", sid))
            # 回放优先给降噪副本, 没有则退回原始转写用音频
            play = meta.get("audioListen") if (meta.get("audioListen")
                                               and (d / meta["audioListen"]).exists()) \
                else meta.get("audio")
            meta["audioUrl"] = f"/audio/{sid}/{play}" if play else None
            meta["id"] = sid
            meta["spkLabels"] = meta.get("spk_labels") or {}
            # 课后笔记: 文件在不在就是"有没有笔记", 不需要额外状态字段。
            # 顶层再给一份 noteText, 让"只读 transcript.md 的老项目"也能被前端统一处理。
            nf = d / NOTE_FILE
            meta["hasNote"] = nf.is_file()
            meta["noteText"] = nf.read_text(encoding="utf-8") if nf.is_file() else ""
            pref = self._read_pref(d)
            meta["play_rate"] = pref.get("play_rate")
            meta["last_pos"] = pref.get("last_pos", 0)
            return meta
        # 旧版兼容: 解析 md
        md = (d / "transcript.md").read_text(encoding="utf-8")
        segs = []
        for ts, text in re.findall(r"^\[(\d{2}:\d{2}(?::\d{2})?)\] (.+)$", md, re.M):
            p = [int(x) for x in ts.split(":")]
            t = p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]
            segs.append({"t": t, "d": 0, "text": text.strip()})
        name = re.match(r"^# (.+)$", md, re.M)
        nf = d / NOTE_FILE
        pref = self._read_pref(d)
        return {"id": sid, "name": self._clean_title(name.group(1) if name else sid),
                "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime)),
                "segments": segs, "notes": [], "audioUrl": None, "duration": 0,
                "hasNote": nf.is_file(),
                "noteText": nf.read_text(encoding="utf-8") if nf.is_file() else "",
                "play_rate": pref.get("play_rate"), "last_pos": pref.get("last_pos", 0),
                "lang": "", "mode": "", "legacy": True}

    @staticmethod
    def _read_pref(d):
        """读项目播放偏好侧车 .pref.json；不存在或损坏都回退成空 dict，绝不抛。"""
        pf = d / PREF_FILE
        if pf.is_file():
            try:
                v = json.loads(pf.read_text(encoding="utf-8"))
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
        return {}

    def session_pref(self, sid, play_rate=None, last_pos=None):
        """按项目写播放偏好（倍速 / 上次位置）。只写小巧的 .pref.json，
        绝不重写 session.json 或 transcript.md —— 位置每几秒存一次，必须便宜且无副作用。"""
        if ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        d = SESSIONS_DIR / sid
        if not d.is_dir():
            raise RuntimeError("项目不存在")
        pf = d / PREF_FILE
        pref = self._read_pref(d)
        if play_rate is not None:
            pr = str(play_rate)
            if pr in ("1x", "1.5x", "2x", "0.75x"):
                pref["play_rate"] = pr
        if last_pos is not None:
            try:
                lp = float(last_pos)
                if lp >= 0:
                    pref["last_pos"] = round(lp, 1)
            except (TypeError, ValueError):
                pass
        pf.write_text(json.dumps(pref, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}

    def delete_audio(self, sid):
        """旧入口：只删录音、保留文稿。现在统一走 delete_session(full=False)，
        免得留第二条硬删路径 —— 同一件事只该有一种删法（进废纸篓）。"""
        return self.delete_session(sid, False)

    def delete_session(self, sid, full):
        """删除项目: full=False 仅把录音移进废纸篓(文稿留下); full=True 整个项目进废纸篓。
        一律走系统回收站，不硬删 —— 移不进去就报错，让用户自己决定下一步。"""
        if ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        d = SESSIONS_DIR / sid
        if not d.is_dir():
            raise RuntimeError("项目不存在")
        if full:
            where = to_trash(d)
            return {"ok": True, "full": True, "gone": not d.exists(), "trash": where}
        moved = []
        sj = d / "session.json"
        if sj.exists():
            meta = json.loads(sj.read_text(encoding="utf-8"))
            names = [meta.get("audio"), LISTEN_FILE]
            meta["audio"] = None
        else:
            names = [f.name for f in d.glob("*.m4a")]
        for n in [x for x in names if x]:
            f = d / n
            if not f.exists():
                continue
            moved.append(to_trash(f))          # 移不进废纸篓就直接抛错，不留下"半删"状态
        if sj.exists():
            sj.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "full": False, "moved": len(moved),
                "trash": moved[0] if moved else ""}

    def reveal(self, sid):
        """在 Finder 中显示项目文件夹"""
        if ".." in sid or "/" in sid:
            raise RuntimeError("非法路径")
        d = SESSIONS_DIR / sid
        if not d.is_dir():
            raise RuntimeError("项目不存在")
        subprocess.Popen(["open", "-R", str(d)])
        return {"ok": True}


APP = App()

# ---------------- HTTP (内部回环, 供窗口加载与音频流) ----------------
INDEX = Path(__file__).parent / "index.html"

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            body = INDEX.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/status":
            self._json(APP.status())
        elif u.path == "/api/events":
            q = parse_qs(u.query)
            after = int(q.get("after", ["0"])[0])
            self._json({"events": APP.events_after(after), "seq": APP.seq})
        elif u.path == "/api/history":
            self._json({"items": APP.history()})
        elif u.path == "/api/hotwords":
            self._json({"words": load_hotwords()})
        elif u.path == "/api/hotword_templates":
            self._json(load_templates())
        elif u.path == "/api/note_templates":
            # 只给清单, 不给"当前选中" —— 没有默认模板这回事, 每次生成都要自己选
            self._json({"templates": note_templates()})
        elif u.path == "/api/groups":
            # 分组顺序与折叠态; 成员关系在各项目 session.json 的 group 字段里
            self._json(load_groups())
        elif u.path == "/api/settings":
            s = load_settings()
            s["last_pretreat"] = load_setting("last_pretreat")
            k = cloud_key()
            # 真实 key 和密文都不下发, 只给缩短形态; 解不开时给个 stale 标记
            s["cloud_api_key"] = key_hint(k)
            s["cloud_key_stale"] = cloud_key_stale()
            s.pop("cloud_api_key_enc", None)
            s.setdefault("talk_mode", talk_mode())
            s.setdefault("cloud_flow", cloud_flow())
            s["whisper_model"] = str(whisper_model() or "")
            s["sv_model_dir"] = str(sv_model_dir() or "")
            s["vad_model"] = str(load_setting("vad_model") or "")
            self._json(s)
        elif u.path == "/api/volume":
            self._json(volume_state())
        elif u.path == "/api/pick_file":
            # 原生文件选择器(多选): 阻塞到用户选完或取消
            # 顺带报每个文件的体积/时长: 云端导入的确认弹窗要在建项目前给真实数字
            paths = APP.pick_file()
            out = []
            for p in paths:
                mb = dur = None
                try:
                    mb = round(Path(p).stat().st_size / 2**20, 1)
                except Exception:
                    pass
                dd = probe_dur(p)
                dur = round(dd, 1) if dd else None
                out.append({"path": p, "mb": mb, "dur": dur})
            self._json({"paths": out,
                        "path": out[0]["path"] if out else None,
                        "mb": out[0]["mb"] if out else None,
                        "dur": out[0]["dur"] if out else None})
        elif u.path == "/api/audio_devices":
            # 输出设备清单 + 当前生效值(auto=是否来自自动探测)
            devs = list_output_devices()
            r_set = (load_setting("output_restore") or "").strip()
            m_set = (load_setting("output_monitor") or "").strip()
            if platform.system() == "Windows":
                inputs, dflt = _win_mic_names()
            else:
                inputs, dflt = list(ca_input_devices().keys()), ca_default_input()
            self._json({"outputs": devs,
                        "restore": output_restore(), "restoreAuto": not bool(r_set),
                        "monitor": output_monitor(), "monitorAuto": not bool(m_set),
                        # SCK 内录不碰输出设备, 麦克风输入源是唯一需要确认的
                        "inputs": inputs,
                        "defaultInput": dflt,
                        "mic": mic_device()})
        elif u.path.startswith("/api/session/"):
            try:
                sid = unquote(u.path[len("/api/session/"):])
                self._json(APP.load(sid))
            except Exception as e:
                self._json({"error": str(e)}, 404)
        elif u.path.startswith("/audio/"):
            # /audio/<sid>/audio.m4a
            parts = unquote(u.path[len("/audio/"):]).split("/")
            f = SESSIONS_DIR / parts[0] / parts[1]
            if f.exists() and f.suffix == ".m4a":
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mp4")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "参数错误"}, 400)
        try:
            if u.path == "/api/start":
                return self._json(APP.start(body.get("mode", "system"),
                                            body.get("lang", "zh"), body.get("name", "")))
            if u.path == "/api/pause":
                return self._json(APP.pause())
            if u.path == "/api/resume":
                return self._json(APP.resume())
            if u.path == "/api/stop":
                return self._json(APP.stop())
            if u.path == "/api/import":
                paths = body.get("paths") or ([body.get("path")] if body.get("path") else [])
                talk = body.get("talk", "single")
                ids, errs = [], []
                for p in paths:
                    try:
                        r = APP.import_audio(p, talk)
                        ids.append({"id": r["id"], "name": r["name"]})
                    except Exception as e:
                        errs.append({"path": p, "error": str(e)[:120]})
                return self._json({"ok": bool(ids), "ids": ids, "errors": errs})
            if u.path == "/api/model_check":
                # 保存前把关: 指错的目录会被引擎当成 HF repo id 联网下载大模型,
                # 或让识别器启动即崩 —— 必须当场拒绝, 不能等出事。
                p = (body.get("path") or "").strip()
                kind = body.get("kind") or "whisper"
                if not p:
                    # 分发口径: 本地模型必须用户配置, 留空不是"回默认"而是没配
                    return self._json({"ok": False,
                                       "msg": "模型路径不能留空 —— 必须自己配置"})
                d = Path(p).expanduser()
                if kind == "sensevoice":
                    ok = (d.is_dir() and (d / "tokens.txt").is_file()
                          and ((d / "model.int8.onnx").is_file()
                               or (d / "model.onnx").is_file()))
                elif kind == "vad":
                    ok = d.is_file() and d.suffix.lower() == ".onnx"
                else:
                    ok = (d.is_dir() and (d / "config.json").is_file()
                          and (d / "weights.safetensors").is_file())
                return self._json({"ok": ok, "path": str(d), "name": d.name})
            if u.path == "/api/cancel":
                return self._json(APP.cancel_job(body.get("id", "")))
            if u.path == "/api/rerun":
                return self._json(APP.rerun(body.get("id", "")))
            if u.path == "/api/refine_silence":
                return self._json(APP.refine_silence(body.get("id", "")))
            if u.path == "/api/cloud_key_save":
                # key 只有这一条写入路径: 加密落盘, 配置里不留明文。
                v = (body.get("api_key") or "").strip()
                if looks_like_hint(v):
                    # 传回来的是显示用的缩短形态/密文本身 —— 那不是新 key, 别拿它覆盖真 key
                    return self._json({"ok": True, "kept": True, "hint": key_hint(cloud_key())})
                bad = key_problem(v) if v else ""
                if bad:
                    return self._json({"ok": False, "error": bad})
                cloud_key_set(v)                 # 空值 = 用户主动清除
                now = cloud_key()
                return self._json({"ok": True, "saved": bool(now), "hint": key_hint(now)})
            if u.path == "/api/cloud_refine":
                return self._json(APP.cloud_refine(body.get("id", "")))
            if u.path == "/api/study_note":
                return self._json(APP.study_note(body.get("id", ""), body.get("template", "")))
            if u.path == "/api/note_template":
                # 一个路由管增/改/删: action=save(带 id 则改, 不带则新建) | delete
                act = (body.get("action") or "save").strip()
                if act == "delete":
                    return self._json(note_tpl_del(body.get("id", "")))
                return self._json(note_tpl_save(body))
            if u.path == "/api/groups":
                raw = body.get("colors")
                colors = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
                save_groups({"order": [str(x) for x in (body.get("order") or [])],
                             "collapsed": [str(x) for x in (body.get("collapsed") or [])],
                             "colors": colors})
                return self._json({"ok": True})
            if u.path == "/api/group_set":
                grp = str(body.get("group") or "").strip()
                return self._json({"ok": True,
                                   "n": APP.group_set(body.get("ids") or [], grp)})
            if u.path == "/api/group_rename":
                frm, to = str(body.get("from") or "").strip(), str(body.get("to") or "").strip()
                if not frm or not to:
                    return self._json({"error": "组名不能为空"})
                return self._json({"ok": True, "n": APP.group_rename(frm, to)})
            if u.path == "/api/group_delete":
                name = str(body.get("name") or "").strip()
                if not name:
                    return self._json({"error": "组名不能为空"})
                return self._json({"ok": True, "n": APP.group_delete(name)})
            if u.path == "/api/cloud_transcribe":
                return self._json(APP.cloud_transcribe(body.get("id", "")))
            if u.path == "/api/cloud_test":
                # 连接测试: 只测「文字接口能不能通」+「音频协议存不存在」, 绝不上传任何音频
                prov = (body.get("provider") or "openai").strip()
                base = (body.get("base_url") or "").strip().rstrip("/")
                key = (body.get("api_key") or "").strip()
                # 输入框留空 = 用后台已存的那把; 传回来的是缩短形态/密文也一律退回已存的
                # (原来这里直接把掩码当 key 发出去, 认证必然失败 —— 就是这个 bug)
                if not key or looks_like_hint(key):
                    key = cloud_key()
                model = (body.get("model") or "").strip()
                if not base or not key:
                    return self._json({"ok": False, "error": "地址和 Key 都要填"})
                bad = key_problem(key)
                if bad:
                    # 不拦的话这把 key 会进到 HTTP 头里炸成 UnicodeEncodeError,
                    # 看起来就像"服务器无缘无故认证失败"
                    return self._json({"ok": False, "error": bad})
                cfg = {"provider": prov if prov in ("openai", "dashscope") else "openai",
                       "base_url": base, "api_key": key, "model": model,
                       "asr_model": (body.get("asr_model") or "").strip()}
                out = {}
                try:
                    out["chat"] = cloud_chat(cfg, [{"role": "user", "content": "回复两个字：正常"}],
                                             max_tokens=256, timeout=30,
                                             ignore_length=True)   # 探针: 只验通不通
                except Exception as e:
                    out["chat_error"] = str(e)
                # 首次遇到某模型时探一次它的「深度思考」能力(会思考可关/只会思考/不思考)并
                # 缓存进 cloud_think_cap; 已测过的模型直接复用缓存, 不重复探测(省 token)。
                note_model = (body.get("note_model") or "").strip()
                out["note_model"] = note_model
                if "chat" in out:
                    out["think_chat"] = cloud_think_probe(cfg, model)
                    out["think_note"] = (
                        None if not note_model or note_model == model
                        else cloud_think_probe(cfg, note_model))
                import requests as _rq
                try:
                    if cfg["provider"] == "dashscope":
                        # 只看上传凭证接口在不在(不传文件、不建任务)
                        rr = _rq.get(_ds_base(cfg) + "/api/v1/uploads",
                                     params={"action": "getPolicy",
                                             "model": cfg["asr_model"] or "paraformer-v2"},
                                     headers={"Authorization": f"Bearer {key}"}, timeout=20)
                        jj = rr.json() if rr.content else {}
                        if rr.status_code == 200 and (jj.get("data") or {}).get("upload_host"):
                            out["asr"] = "异步任务音频协议可用（已取到上传凭证）"
                        else:
                            out["asr"] = f"异步任务上传凭证接口异常 {rr.status_code}"
                    else:
                        rr = _rq.post(base + "/audio/transcriptions",
                                      headers={"Authorization": f"Bearer {key}"},
                                      timeout=20)
                        out["asr"] = ("音频转写接口存在（缺参数被拒, 属正常）"
                                      if rr.status_code in (400, 401, 415, 422)
                                      else f"该地址没有 /audio/transcriptions（{rr.status_code}）")
                except Exception as e:
                    out["asr"] = f"音频接口探测失败: {type(e).__name__}"
                return self._json({"ok": "chat" in out, **out})
            if u.path == "/api/volume":
                return self._json(volume_set(body.get("pct", 0)))
            if u.path == "/api/note":
                return self._json({"ok": True, "note": APP.note(body.get("text", ""))})
            if u.path == "/api/spk_labels":
                return self._json(APP.set_spk_labels(body.get("id", ""),
                                                     body.get("labels") or {}))
            if u.path == "/api/edit_segment":
                return self._json(APP.edit_segment(body.get("id", ""),
                                                   body.get("t"), body.get("text", ""),
                                                   bool(body.get("undo"))))
            if u.path == "/api/session_pref":
                return self._json(APP.session_pref(body.get("id", ""),
                                                   body.get("play_rate"),
                                                   body.get("last_pos")))
            if u.path == "/api/rename":
                return self._json(APP.rename(body.get("name", ""), body.get("id") or None))
            if u.path == "/api/delete_audio":
                return self._json(APP.delete_audio(body.get("id", "")))
            if u.path == "/api/delete_session":
                return self._json(APP.delete_session(body.get("id", ""), bool(body.get("full"))))
            if u.path == "/api/reveal":
                return self._json(APP.reveal(body.get("id", "")))
            if u.path == "/api/engine":
                if APP.state != "idle":
                    return self._json({"ok": False, "error": "请在空闲时切换引擎"}, 400)
                return self._json({"ok": True,
                                    "engine": ENGINE.switch(body.get("engine", ""))})
            if u.path == "/api/hotwords":
                try:
                    txt = (body.get("text") or "")[:2000]
                    HOTWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    HOTWORDS_FILE.write_text(txt, encoding="utf-8")
                    # 同步写入当前激活模板(单一数据源, 旧 txt 仅作兼容备份)
                    data = load_templates()
                    for t in data["templates"]:
                        if t["id"] == data.get("active"):
                            t["words"] = parse_wordlist(txt)
                    save_templates(data)
                    return self._json({"ok": True, "words": load_hotwords()})
                except Exception as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            if u.path == "/api/setting":
                kk = body.get("key")
                if kk in ("cloud_api_key", "cloud_api_key_enc"):
                    # 密钥只能走 /api/cloud_key_save(加密落盘)。这个通用口子写 key
                    # 正是上一个 bug 的成因: 失焦时把显示用的掩码当 key 存了进去。
                    return self._json({"ok": False, "error": "密钥请走专用保存接口"}, 400)
                save_setting(kk, body.get("value"))
                return self._json({"ok": True})
            if u.path == "/api/hotword_templates/save":
                data = load_templates()
                tid = body.get("id") or ""
                name = (body.get("name") or "").strip()[:30] or "未命名"
                words = parse_wordlist(body.get("words") or "")[:500]
                if tid:
                    for t in data["templates"]:
                        if t["id"] == tid:
                            t["name"], t["words"] = name, words
                            break
                    else:
                        return self._json({"ok": False, "error": "模板不存在"}, 404)
                else:
                    tid = f"t{int(time.time() * 1000)}"
                    data["templates"].append({"id": tid, "name": name, "words": words})
                save_templates(data)
                return self._json({"ok": True, "id": tid})
            if u.path == "/api/hotword_templates/select":
                data = load_templates()
                tid = body.get("id") or ""
                if any(t["id"] == tid for t in data["templates"]):
                    data["active"] = tid
                    save_templates(data)
                    return self._json({"ok": True, "active": tid})
                return self._json({"ok": False, "error": "模板不存在"}, 404)
            if u.path == "/api/hotword_templates/delete":
                data = load_templates()
                tid = body.get("id") or ""
                if len(data["templates"]) <= 1:
                    return self._json({"ok": False, "error": "至少保留一个模板"}, 400)
                data["templates"] = [t for t in data["templates"] if t["id"] != tid]
                if data.get("active") == tid:
                    data["active"] = data["templates"][0]["id"]
                save_templates(data)
                return self._json({"ok": True})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        self.send_error(404)


def _report_port_to_shell(port):
    """被 tauri 壳拉起时, 壳在 TINGDAO_PORTFILE 约定一个临时文件路径: 把后端真正绑到的
    空闲端口写进去, 壳读到端口号才开窗口。单独运行(无该环境变量)时静默跳过。"""
    pf = (os.environ.get("TINGDAO_PORTFILE") or "").strip()
    if not pf:
        return
    try:
        with open(pf, "w", encoding="utf-8") as f:
            f.write(str(port))
    except Exception as e:
        print(f"[port] 写端口文件失败 {pf}: {e}", flush=True)


def main():
    global PORT
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    setup_log()
    # 端口交给 OS 现挑(bind 端口 0 = 一个真正空闲的回环端口, 没有「探测到空闲→再占用」之间的抢端口竞态);
    # 绑好后从 socket 读回真实端口, 全进程(含回报给壳、喂给 pywebview)都用这一个值。
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    PORT = server.server_address[1]
    _report_port_to_shell(PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"内部服务 http://127.0.0.1:{PORT}")

    def finish_up(reason):
        """退出前的统一收尾: 录音/暂停中必须先停录落盘, 否则音频和半截稿子留在原地。"""
        if APP.state in ("recording", "paused"):
            try:
                APP.stop()
                print(f"已自动收尾保存({reason})")
            except Exception as e:
                print(f"收尾失败: {e}")
        server.shutdown()

    # headless: 窗口交给外部壳(tauri), 本进程只跑 HTTP 常驻。
    # 收到 SIGTERM/SIGINT 走与关窗同一套收尾 —— 壳 kill 我们的时候不能丢稿子。
    if "--no-window" in sys.argv[1:] or os.environ.get("TINGDAO_HEADLESS") == "1":
        print("headless: 只提供 HTTP 服务, 窗口由外部壳负责")
        gone = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: gone.set())
        signal.signal(signal.SIGINT, lambda *_: gone.set())
        # 第二道闸: 壳被强杀(SIGKILL)时不会走到它的 Exit, 也就没人 kill 我们。
        # 父进程一消失, 我们会被 launchd 收养 —— getppid 变了就是信号, 自行收摊。
        # 绝不能留一个看不见的后端在后台占着麦克风和本地回环端口。
        parent = os.getppid()

        def watch_parent():
            while not gone.wait(1.0):
                if os.getppid() != parent:
                    print("父进程(壳)已消失, 后端自行退出")
                    gone.set()
                    return
        threading.Thread(target=watch_parent, daemon=True).start()
        gone.wait()
        finish_up("收到退出信号")
        return

    import webview
    # 标题栏方案: 保持"标题栏在原位"，只把它的不透明底色擦掉 + 去掉分隔线。
    #
    # 为什么不用 NSWindowStyleMaskFullSizeContentView(全尺寸内容视图):
    # 实测一开那个位, AppKit 就把标题栏改成"点击穿透" —— 顶部命中测试落到 WKWebView,
    # 结果窗口拖不动, 而且窗口会自己缩掉 32pt 高。所以内容不铺到顶, 只换个"皮":
    # 标题栏容器 + 它里面那几层背景擦成 clear, 白色窗口底色透出来, 视觉上跟 App 的
    # 白色顶栏连成一片; 顶部拖拽、红绿灯位置/悬停行为全部还是系统原生。
    # (pywebview 在创建窗口时会主动给标题栏容器刷一层不透明 windowBackgroundColor,
    #  所以只设 titlebarAppearsTransparent 是不够的, 必须把那层底色擦掉 —— 上一版就栽在这)
    win = webview.create_window(
        "听道", f"http://127.0.0.1:{PORT}",
        width=1020, height=740, min_size=(860, 620),
        background_color="#ffffff",
        frameless=False, easy_drag=False)

    def apply_native_chrome():
        """把标题栏刷成透明(露出白色窗口底色)、去掉分隔线，红绿灯保持原生可用。"""
        def _do():
            try:
                import re
                import AppKit
                nw = win.native
                if nw is None:
                    print("原生标题栏设置跳过: 拿不到 NSWindow")
                    return
                # 注意: 这里绝不碰 styleMask —— 加 FullSizeContentView 会让顶部失去拖拽
                nw.setTitlebarAppearsTransparent_(True)
                nw.setTitleVisibility_(AppKit.NSWindowTitleHidden)
                try:
                    nw.setTitleSeparatorStyle_(0)     # macOS 11+: 0 = 不画分隔线
                except Exception:
                    pass                              # 老系统没有这个 API, 忽略
                nw.setBackgroundColor_(AppKit.NSColor.whiteColor())
                nw.setMovableByWindowBackground_(False)   # 只有标题栏能拖, 正文不误拖

                # 擦掉标题栏那几层的不透明底色(只碰 Titlebar/Backdrop/Decoration,
                # 不碰红绿灯按钮和标题文字控件, 免得把系统按钮画花)
                KEEP = re.compile(r"Titlebar|Backdrop|Separator|Decoration")
                wiped = []

                def _wipe(v):
                    if v.respondsToSelector_("setOpaque:"):
                        v.setOpaque_(False)
                    if v.respondsToSelector_("setBackgroundColor:"):
                        v.setBackgroundColor_(AppKit.NSColor.clearColor())
                        wiped.append(str(v.className()))
                    for sub in v.subviews():
                        if KEEP.search(str(sub.className())):
                            _wipe(sub)

                fv = nw.contentView().superview()
                if fv is not None:
                    for v in fv.subviews():
                        if KEEP.search(str(v.className())):
                            _wipe(v)
                for tag in (AppKit.NSWindowCloseButton, AppKit.NSWindowMiniaturizeButton,
                            AppKit.NSWindowZoomButton):
                    b = nw.standardWindowButton_(tag)
                    if b:
                        b.setHidden_(False)
                print("透明标题栏已启用(顶部原生可拖): 已擦除", sorted(set(wiped)))
            except Exception as e:
                print("原生标题栏设置失败(退回普通标题栏):", e)
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(_do)      # 必须回主线程碰 AppKit
        except Exception as e:
            print("调度失败(忽略):", e)

    # before_show 先应用一次(窗口还没上屏, 不会闪灰), loaded 再兜一次(幂等)
    win.events.before_show += apply_native_chrome
    win.events.loaded += apply_native_chrome
    webview.start()
    finish_up("窗口关闭")     # 与 headless 分支同一套收尾, 不再各写一份


if __name__ == "__main__":
    main()
