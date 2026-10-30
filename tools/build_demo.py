"""生成首次启动时放进数据目录的「听道使用说明」演示项目。

产物写到 assets/demo/：
  demo-session.json  项目元数据（文稿、章节、摘要、笔记），首启时改写为 session.json
  demo-note.md       课后笔记，首启时改写为 note.md
  demo-audio.m4a     用 macOS 系统朗读生成的录音，让回放、跳句、目录刻度都能试
  note-images/       文稿和笔记里用到的插图（由人工截图放入，这里只读取尺寸）

只能在 macOS 上运行（要用 say 和 ffmpeg）：python3 tools/build_demo.py
"""
import json
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "demo"
IMAGES = OUT / "note-images"
VOICE = "Tingting"
SPK_VOICES = {"S01": "Tingting", "S02": "Flo (中文（中国大陆）)"}
RATE = 200
GAP = 0.45            # 段与段之间留的空白秒数

# 每一项: ("h1"/"h2", 标题) 或 ("p", 正文, 选项)
# 选项: spk 说话人 / bold、underline、color、background 要标出的原文片段 /
#      ed 标成手改过 / note 时间线笔记文字 / quote 引用 / images [(文件, 排版, 显示宽度)]
DOC = [
    ("h1", "写在前面"),
    ("p", "这份文稿是听道自带的使用说明。它和你以后录出来的稿子是同一种东西：每段前面有时间，点一下就能从那里开始听。",
     {"images": [("overview.png", "inline", 680)]}),
    ("p", "配套的录音是用系统朗读做的，声音有点生硬，凑合着听。"),
    ("p", "这里可以随便动手：改字、划重点、插图、记笔记都行，改乱了也不要紧。看完用不上了，归档或者删掉都可以，不影响别的项目。"),

    ("h1", "录一段音"),
    ("h2", "开始和结束"),
    ("p", "点右下角的 ＋ 新建录音。录完点计时条右边的小方块结束，听道会问你一句，确认以后，录音和文稿一起存在本地。"),
    ("p", "空闲的时候按 ⌘⇧R 也能直接开录。这组快捷键可以在「设置 → 声音与快捷键」里换掉。Windows 上，这份说明里所有的 ⌘ 都换成 Ctrl，⌥ 换成 Alt。"),
    ("p", "开录前可以先在顶上给这次录音起个名字。不起也行，会按日期自动命名，以后随时能改。"),
    ("h2", "录什么声音"),
    ("p", "录音来源有三种：仅系统声音、系统声音加麦克风、仅麦克风。听网课、开线上会议用前两种，当面谈话用最后一种。",
     {"images": [("record-dock.png", "inline", 620)]}),
    ("p", "录到一半也能换来源，录音不会断。底栏上画着喇叭和话筒的那个按钮，点开就能在三种来源之间切换。"),
    ("p", "旁边写着百分比的是输出音量，录音时想把电脑声音调小一点，直接在这里调，不用去找系统菜单。再旁边是暂停，暂停期间不录，继续以后接着往下写。"),
    ("h2", "实时字幕和精修"),
    ("p", "录的时候字幕一句句往外冒，这是本地模型跑的快稿。结束以后，Whisper 会把整段重新听一遍，换上一份更准的精修稿。所以录音中看到错字，不用急着改。"),
    ("p", "人名、术语这类词，提前放进热词库，精修时认得更准。录音中也能换词库，入口是顶上那块小吊牌右边的小齿轮。"),

    ("h1", "录音时记笔记和插图"),
    ("h2", "随手记一句"),
    ("p", "录音时按 ⌘N，或者点底栏的笔记按钮，会弹出一个小输入框。写完按回车就记下了，时间点算在按回车的那一刻。要换行按 Shift 加回车，Esc 收起。",
     {"note": "像这样。这是一条录音时随手记的笔记，回看的时候它就插在当时那句话的后面。"}),
    ("h2", "拖进来，粘进来"),
    ("p", "录音时，可以直接把图片从访达或者桌面拖进听道窗口。看到「松开以记下图片」再松手，这张图就挂在当下这个时间点上。",
     {"bold": ["松开以记下图片"]}),
    ("p", "截图也一样，在录音界面按 ⌘V 就粘进来了。课件、白板、聊天记录，都可以这么存。记下的图会在窗口一角叠成一小摞，数字是这次录音一共记了几张。"),
    ("h2", "用 iPhone 拍照"),
    ("p", "在 Mac 版里，如果 iPhone 和电脑登录的是同一个 Apple ID，录音底栏会多一个相机按钮。点它，iPhone 上会直接打开相机，拍完的照片自动回到这次录音里。"),
    ("p", "嫌点按钮慢，就按 ⌘⇧P，跳过菜单直接拍。这一项只在录音或暂停时有效。"),

    ("h1", "回头看稿"),
    ("p", "打开一个项目，右上角有一条收着的工具条，点向下的小箭头展开。说话人、查找、复制、归档、打开文件夹、跳过静音重跑、云端处理，都在这一排。",
     {"images": [("toolbar.png", "inline", 440)]}),
    ("h2", "跟着听"),
    ("p", "点任意一段，录音就从这一段开始放。正在放的句子会亮起来，文稿跟着往下走。你自己滚动去看别处的时候，它不会把你拽回去。"),
    ("p", "空格是播放和暂停，↑ 和 ↓ 跳到上一句、下一句。"),
    ("p", "想快进一小段又不想改倍速，就在播放时按住 → 键。按住的时候是两倍速，一松手就回到原来的速度。",
     {"bold": ["按住 → 键"]}),
    ("p", "播放条上的倍速按钮在 1x、1.5x、2x、0.75x 之间轮换，每个项目单独记。下次再打开同一个项目，会提示「继续上次」，点一下回到上回听到的地方。"),
    ("h2", "章节和目录"),
    ("p", "做过 AI 摘要的稿子会带上章节标题，就像这份。文稿右边有一列细细的刻度，鼠标移上去会展开成目录，点标题直接跳过去。",
     {"images": [("outline-rail.png", "inline", 400)]}),
    ("p", "有笔记的项目会多一个圆形的「全部笔记」按钮，点开能看到这个项目里所有的笔记，按时间排好，还标着各自属于哪一章。"),
    ("h2", "改错字"),
    ("p", "双击一段就能直接改。改完按回车保存，Esc 放弃。刚改完的那一下，旁边会出现「撤销这一处」，连着改了好几处也能一处一处退回去。"),
    ("p", "这一段就是改过的，所以句尾多了一个小圆点。鼠标放到圆点上，能看到是什么时候改的。", {"ed": True}),
    ("h2", "划重点"),
    ("p", "用鼠标选中一段字，旁边会浮出一条小工具栏，可以加粗、加下划线，也可以点调色板换文字颜色和背景颜色。最近用过的颜色排在最前面，连着标好几处很顺手。",
     {"images": [("format-bar.png", "inline", 580)]}),
    ("p", "选中以后直接按 ⌘B 加粗、⌘U 加下划线，不必去点按钮。这一句里的几处就是这样标出来的。",
     {"bold": ["⌘B 加粗"], "underline": ["⌘U 加下划线"], "background": [("这样标出来的", "#fff2a8")]}),
    ("h2", "查找和替换"),
    ("p", "⌘F 在当前文稿里查找，回车或者 ↑ ↓ 在结果之间跳。Aa 按钮决定区不区分大小写。"),
    ("p", "展开替换，可以把一个叫错的名字一次全改对。也可以只替换选中的那一处。替换完后悔了，同样有「撤销这一处」。"),
    ("h2", "说话人"),
    ("p", "云端转写多人录音时，会给每段标上说话人，就是时间后面那个小数字。下面两句是示范。"),
    ("p", "这周睡得怎么样？", {"spk": "S01"}),
    ("p", "比上周好一点，不过夜里还是会醒两三次。", {"spk": "S02"}),
    ("p", "点工具栏上的说话人按钮，可以把 1 和 2 改成「咨询师」「来访者」这样的名字。改名只在这个项目里算数，导出的文稿也会跟着改。"),

    ("h1", "在文稿里放图片"),
    ("h2", "拖进来和粘进来"),
    ("p", "不录音的时候，文稿里一样能放图。把图片拖到某一段上就行；或者先滚到那附近，按 ⌘V 粘贴，图会放在屏幕正中那段的后面。"),
    ("p", "粘贴前别让光标停在输入框里，不然图会粘进输入框。"),
    ("h2", "落点决定排版"),
    ("p", "拖的时候看好落点。落在一段的上沿或下沿，图片插在这段的前面或后面，单独占一行。落在这段的左侧或右侧，图片就靠边放，文字绕着它排。",
     {"images": [("drop-zones.png", "inline", 700)]}),
    ("p", "旁边这张就是放在右侧的。已经放好的图也能拖去别处，排法按新的落点重新算。",
     {"images": [("drop-zones-small.png", "aside-right", 340)]}),
    ("p", "图片右下角有一个小手柄，拖它等比缩放。双击图片，会用系统的看图软件打开原图。右键可以把它从文稿里删掉，删的只是这里这一张，你电脑上的原文件不受影响。"),
    ("p", "如果图太宽，靠边放不下，会自动改成单独占一行，免得把文字挤成一条。"),
    ("h2", "带图的笔记"),
    ("p", "在任意一段上点右键，选「添加时间线笔记」，这段下面会展开一张笔记卡片。卡片里可以写字，也可以把图拖进去、粘进去。"),
    ("p", "写笔记的时候，卡片里的图片右键有五种排法：嵌入型、四周型环绕、上下型环绕、衬于文字下方、浮于文字上方，意思和 Word 里一样，可以边写边排。后两种还能在卡片里拖到任意位置。",
     {"images": [("note-image-menu.png", "inline", 560)]}),
    ("p", "保存以后，图片跟着这条笔记落进文稿，之后就按文稿里的规则来：拖动换位置，拖手柄缩放，拖到段落两侧靠边。"),
    ("p", "想引用原文，先在文稿里选中那句话，点浮动工具栏最右边的引用按钮，选中的话会作为引用带进笔记。",
     {"quote": "想引用原文，先在文稿里选中那句话", "note": "引用会带着原话进笔记，回头看就知道这条笔记在说哪句。"}),
    ("p", "写完按回车保存。已经记下的笔记，右键可以修改或删除。"),

    ("h1", "摘要和课后笔记"),
    ("h2", "AI 摘要"),
    ("p", "文稿最上面那一块是 AI 摘要，生成的时候会顺手把章节目录也做出来。这一项要先在设置里配好云端服务。"),
    ("p", "摘要生成过以后，生成按钮就收起来了。想重新生成，把鼠标停在摘要标题那一行，等一两秒，右边会浮出重新生成的按钮。现在就可以去最上面试试。",
     {"bold": ["等一两秒"], "images": [("summary-regen.png", "inline", 580)]}),
    ("p", "摘要怎么写也能自己定。设置里摘要模型的旁边有一支笔，点开改提示词。"),
    ("h2", "课后笔记"),
    ("p", "⌘⇧B 打开右侧的课后笔记。它是从整份文稿整理出来的一篇复习笔记，和上面说的时间线笔记是两回事。"),
    ("p", "生成前要挑一个模板：全面版适合复习，精简版适合考前背，表格版适合做对照。模板可以在设置里自己添。对结果不满意，就用「换个模板重生成」。"),
    ("p", "这份说明附带的课后笔记是一张快捷键速查表，现在按 ⌘⇧B 就能看到。"),

    ("h1", "管理项目"),
    ("h2", "项目栏"),
    ("p", "⌘B 收起或展开左边的项目栏。收起以后，鼠标移到左上角那个开关按钮上，项目栏会临时浮出来，移开就收回去。"),
    ("p", "鼠标停在一个项目上，右边会出现三个点。点它，或者直接在项目上右键，可以改名、复制文稿、移到分组、收藏、归档。",
     {"images": [("sidebar-menu.png", "inline", 420)]}),
    ("p", "项目栏顶上的「收藏」只列出你收藏过的项目。"),
    ("h2", "分组"),
    ("p", "把项目拖到分组上就放进去了，先多选几个再拖，可以一次搬一批。不想拖，就用右键菜单里的「移到项目」。"),
    ("p", "每个分组可以挑一种颜色标签。排序方式选「按组标签」，同色的组会排在一起。分组之间的先后顺序也能拖动调整。"),
    ("h2", "搜索"),
    ("p", "⌘K 打开命令面板，输入名字找项目或分组，↑ ↓ 选择，回车打开。"),
    ("h2", "归档和删除"),
    ("p", "工具栏里的归档按钮把项目收进「归档」，并没有删掉。到归档里可以批量勾选再删除，删掉的文件进系统废纸篓，后悔了还能拖回来。删除时也可以只删录音，留下文稿。"),

    ("h1", "导入、云端和导出"),
    ("h2", "导入音视频"),
    ("p", "右上角「更多」里的「导入音频 / 视频」能把已有的文件转成文稿。一次选好几个文件，会问你是合并成一份，还是每个文件各建一个项目。合并时按列表里的顺序接起来。"),
    ("h2", "云端处理"),
    ("p", "云端处理有两条路。一条是把录音传上去，用云端模型重新转写；另一条只把本地转好的文字发出去，修错字和标点，录音留在你的电脑上。上传之前都会再问你一次。"),
    ("p", "本地转写偶尔会出现同一句话反复出现的情况。用工具栏的「跳过静音重跑」再转一遍，一般就好了。代价是可能漏掉少量很轻的说话声，耗时也长一些。"),
    ("h2", "复制和导出"),
    ("p", "工具栏的复制按钮，默认复制不带时间戳的纯文本。按住 ⌥ 再点，可以临时换成带时间戳的 Markdown，或者按说话人分行的剧本格式。默认用哪种，在「设置 → 外观与阅读」里改。⌘E 直接复制纯文本。"),
    ("p", "每个项目就是一个普通文件夹，里面有录音、一份 session.json 和一份 Markdown 文稿。工具栏的文件夹按钮能直接打开它，要备份就把整个文件夹拷走。"),

    ("h1", "设置里值得一看的"),
    ("p", "外观可以选浅色、深色或者跟随系统，主题色能自己调。「材质效果」里可以调界面玻璃的模糊程度和透明度。"),
    ("p", "逐字稿的字号和行距在「外观与阅读」，改了立刻生效。任务完成时会响一声，声音和音量能换，也能关掉。"),
    ("p", "缓存每满一个月自动清一次，录音、文稿、图片和模型都不会动。"),
    ("p", "⌘, 打开设置。快捷键记不住的时候按 ⌘/，所有快捷键都列在一张卡片上。"),
    ("p", "说明就到这里。准备好了，点右下角的 ＋，录下你的第一段。"),
]

SUMMARY = """# 听道使用说明

听道自带的功能说明，也是一个可以随便动手试的示范项目。

- 录音：三种录音来源，录到一半也能换；实时字幕先出快稿，结束后自动精修。
- 录音时：⌘N 记一句笔记，图片能拖进来、粘进来，Mac 上还能用 iPhone 直接拍。
- 看稿：点哪段听哪段，按住 → 两倍速，双击改字，选中文字可以加粗、上色、引用到笔记。
- 图片：文稿和笔记卡片里都能放图，拖到段落左右两侧就变成文字环绕。
- 摘要：鼠标在摘要标题上停一两秒，会浮出重新生成的按钮。
- 管理：分组、收藏、归档，⌘K 搜索，⌘/ 查看全部快捷键。"""

NOTE_MD = """# 快捷键速查

Windows 上把 ⌘ 换成 Ctrl，⌥ 换成 Alt。

## 录音

| 按键 | 作用 |
| --- | --- |
| ⌘⇧R | 空闲时开始录音（可在设置里改） |
| ⌘N | 记一句笔记，回车保存，Shift+回车换行 |
| ⌘V | 把剪贴板里的图片记到当前时间点 |
| ⌘⇧P | 用 iPhone 直接拍照插入（仅 Mac） |

## 看稿

| 按键 | 作用 |
| --- | --- |
| 空格 | 播放 / 暂停 |
| ↑ ↓ | 上一段 / 下一段 |
| 按住 → | 临时两倍速，松开恢复 |
| 双击 | 就地改这一段，回车保存，Esc 放弃 |
| ⌘B / ⌘U | 选中文字后加粗 / 下划线 |
| ⌘F | 查找和替换 |
| ⌘E | 复制不带时间戳的纯文本 |
| ⌥ 点复制 | 临时选择复制格式 |

## 窗口

| 按键 | 作用 |
| --- | --- |
| ⌘B | 收起 / 展开项目栏 |
| ⌘⇧B | 打开 / 收起课后笔记 |
| ⌘K | 搜索项目和分组 |
| ⌘, | 打开设置 |
| ⌘/ | 查看全部快捷键 |
| Esc | 关掉当前弹层 |

## 容易漏掉的

- 鼠标在摘要标题上停一两秒，会浮出「重新生成」。
- 图片拖到段落的左侧或右侧，会变成文字环绕；拖到上沿或下沿，单独占一行。
- 笔记卡片里的图片右键，有五种排版方式。
- 选中文稿里的话，点浮动工具栏最右边的按钮，可以引用到笔记。
- 项目栏收起时，鼠标移到左上角的开关按钮上，项目栏会临时浮出来。
"""

SPEECH = [("⌘⇧R", "Command Shift R"), ("⌘⇧P", "Command Shift P"), ("⌘⇧B", "Command Shift B"),
          ("⌘,", "Command 逗号"), ("⌘/", "Command 斜杠"), ("⌘", "Command "), ("⌥", "Option "),
          ("↑ 和 ↓", "上下方向键"), ("↑ ↓", "上下方向键"), ("→ 键", "右方向键"), ("→", "右方向键"),
          ("1x、1.5x、2x、0.75x", "一倍、一点五倍、两倍、零点七五倍"),
          ("session.json", "session 点 json"), ("Aa", "大小写"), ("「", ""), ("」", ""),
          ("设置 → ", "设置里的")]


def speech_text(text):
    for a, b in SPEECH:
        text = text.replace(a, b)
    return text


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def u16(text, part):
    """文稿格式按 UTF-16 下标存（与前端一致）。"""
    i = text.index(part)
    start = len(text[:i].encode("utf-16-le")) // 2
    return start, start + len(part.encode("utf-16-le")) // 2


def formats_for(text, opts):
    spans = []
    for key in ("bold", "underline"):
        for part in opts.get(key, []):
            spans.append((*u16(text, part), {key: True}))
    for key in ("color", "background"):
        for part, color in opts.get(key, []):
            spans.append((*u16(text, part), {key: color}))
    spans.sort()
    return [{"start": s, "end": e, "style": st} for s, e, st in spans]


def image_node(name, layout, width, index):
    path = IMAGES / name
    w, h = png_size(path)
    return {"type": "image", "file": f"note-images/{name}", "name": name, "mime": "image/png",
            "bytes": path.stat().st_size, "width": w, "height": h, "displayWidth": width,
            "layout": layout, "anchorRowId": f"segment-{index}", "insertPosition": "after",
            "position": {"mode": "flow", "x": None, "y": None}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="tingdao-demo-"))
    segments, outline, notes, clips = [], [], [], []
    pending = []
    t = 0.6
    for item in DOC:
        if item[0] in ("h1", "h2"):
            pending.append({"level": 1 if item[0] == "h1" else 2, "title": item[1]})
            continue
        text, opts = item[1], (item[2] if len(item) > 2 else {})
        clip = tmp / f"{len(clips):03d}.aiff"
        voice = SPK_VOICES.get(opts.get("spk"), VOICE)
        subprocess.run(["say", "-v", voice, "-r", str(RATE), "-o", str(clip), speech_text(text)], check=True)
        dur = probe(clip)
        clips.append((clip, dur))
        # 标题时间排在本段之前且互不相同（真实摘要里每个标题各占一个时间点）
        for k, h in enumerate(pending):
            outline.append({"t": round(t - 0.1 * (len(pending) - k), 1), **h})
        pending = []
        seg = {"t": round(t, 1), "d": round(dur, 1), "text": text}
        if opts.get("spk"):
            seg["spk"] = opts["spk"]
        fm = formats_for(text, opts)
        if fm:
            seg["formats"] = fm
        if opts.get("ed"):
            seg["ed"] = int(time.time())
        index = len(segments)
        segments.append(seg)

        content = []
        if opts.get("quote"):
            content.append({"type": "quote", "text": opts["quote"]})
        if opts.get("note"):
            content.append({"type": "text", "text": opts["note"]})
        for name, layout, width in opts.get("note_images", []):
            content.append(image_node(name, layout, width, index))
        if content:
            notes.append({"t": round(t + min(dur, 2.0), 1),
                          "text": "\n".join(n["text"] for n in content if n["type"] == "text"),
                          "content": content})
        for name, layout, width in opts.get("images", []):
            path = IMAGES / name
            if not path.is_file():
                print(f"缺图，先跳过: {name}")
                continue
            notes.append({"t": round(t + 0.1, 1), "text": "",
                          "content": [image_node(name, layout, width, index)]})
        t += dur + GAP

    # 段落之间垫静音，拼成一条录音
    silence = tmp / "gap.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", str(GAP), str(silence)], check=True)
    lead = tmp / "lead.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", "0.6", str(lead)], check=True)
    listing = tmp / "list.txt"
    lines = [f"file '{lead}'"]
    for clip, _ in clips:
        lines += [f"file '{clip}'", f"file '{silence}'"]
    listing.write_text("\n".join(lines) + "\n")
    audio = OUT / "demo-audio.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-ac", "1", "-ar", "22050", "-c:a", "aac", "-b:a", "32k", str(audio)], check=True)
    duration = round(probe(audio), 1)

    notes.sort(key=lambda n: n["t"])
    meta = {
        "name": "听道使用说明", "mode": "system", "lang": "zh", "duration": duration,
        "audio": "audio.m4a", "audioMaster": None, "audioSampleRate": 16000,
        "audioListen": None, "audioListenError": "",
        "segments": segments, "notes": notes,
        "summary": SUMMARY, "outline": outline,
        "spk_labels": {"S01": "咨询师", "S02": "来访者"},
        "demo": True,
    }
    (OUT / "demo-session.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "demo-note.md").write_text(NOTE_MD, encoding="utf-8")
    shutil.rmtree(tmp)
    print(f"{len(segments)} 段，{len(outline)} 个标题，{len(notes)} 条笔记，录音 {duration} 秒")


if __name__ == "__main__":
    main()
