重新梳理后，建议不要按原报告里的“性能问题严重程度”直接排序开发顺序，而要同时看两件事：

- **问题风险**：现在不改，会造成多大性能/稳定性问题。
- **修改风险**：改这块代码，本身有多大概率引入录音丢失、字幕错乱、定位失效等回归。

这两者并不相同。例如「PCM 无界队列」问题风险高，但直接改成有界队列的修改风险也很高，因此不应该直接动队列结构。

## 一、最终优先级

| 顺序 | 改动 | 问题风险 | 修改风险 | 建议 |
|---|---|---:|---:|---|
| P0-1 | Whisper stdout/stderr 管道堵塞 | 高 | **低** | **最先做** |
| P0-2 | 音频 Range / 206 分段读取 | 高 | **低~中** | **最先做** |
| P0-3 | 全局锁内执行推理/编码/IO | 高 | **高** | 分阶段做 |
| P1-1 | 图片阻塞正文打开 | 高 | **中** | 尽快做 |
| P1-2 | 状态轮询请求重叠 | 中高 | **低** | 尽快做 |
| P1-3 | 长稿滚动/播放全量扫描 | 中高 | **中** | 尽快做 |
| P1-4 | history 元数据缓存 | 中 | **低** | 可以直接做 |
| P1-5 | 笔记定位重复搜索 | 中 | **低~中** | 可以做 |
| P1-6 | 全文查找/弹窗整页操作 | 中 | **低~中** | 可以做 |
| P2-1 | PCM 队列积压治理 | 高 | **高** | **先监控再改** |
| P2-2 | 正文分批渲染 | 中高 | **中** | 长稿优化第二阶段 |
| P2-3 | 启动流程后台预热模型 | 中 | **中高** | 稳定后再做 |
| P2-4 | 导入转码流水线 | 中 | **中高** | 测量后决定 |
| P3-1 | 常驻 Whisper worker | 不确定 | **高** | 暂缓 |
| P3-2 | GPU 加速 | 不确定 | **高** | 暂缓 |
| P3-3 | 云端并发重构 | 不确定 | **中高** | 暂缓 |
| P3-4 | 正文虚拟列表 | 潜在高收益 | **极高** | 最后考虑 |
| P3-5 | Swift FIFO / 音频回调重构 | 不确定 | **极高** | 没数据不动 |
| P3-6 | 模糊/玻璃材质降级 | 不确定 | 中 | GPU 采样后决定 |

所以整体策略应该变成：

> **先消除确定性的稳定性问题 → 再减少明显的无效工作 → 再处理架构型性能问题 → 最后才碰模型、虚拟化和音频底层。**

---

# 二、逐项风险评估

## 1. Whisper stdout / stderr 管道

### 当前问题

这是报告里**性价比最高的一项**。

父进程：

```text
读取 stdout
    ↓
等待 stdout EOF
    ↓
读取 stderr
```

如果 stderr 管道被写满：

```text
worker 等待 stderr 被读取
父进程等待 worker stdout 结束
→ 双方等待
```

属于经典 subprocess pipe deadlock。

### 推荐修改

优先考虑：

```text
stdout → 当前实时读取逻辑
stderr → 独立线程持续排空
```

或者：

```text
stderr → 日志文件
```

不建议简单：

```python
stderr=subprocess.DEVNULL
```

因为会失去模型加载、FFmpeg、Whisper 崩溃等重要错误信息。

### 修改风险：低

主要验证：

- 实时进度仍能返回；
- stop/cancel 正常；
- worker 出错仍能看到错误；
- worker 退出码正确处理。

**适合作为第一项修改。**

---

# 2. 音频 Range / 206

这也是非常适合优先处理的一项。

现在：

```text
浏览器请求 audio
        ↓
Python read_bytes()
        ↓
整个文件进内存
        ↓
返回浏览器
```

应该变成：

```text
浏览器
 ↓ Range: bytes=...
Python
 ↓ seek()
 ↓ 读取指定范围
206 Partial Content
```

### 收益

不仅降低内存。

更重要的是改善：

- 播放开始速度；
- 时间轴拖动；
- seek；
- 长录音重新定位；
- 浏览器缓存行为。

### 修改风险：低~中

真正容易出错的是 HTTP 边界条件：

```text
Range: bytes=100-200
Range: bytes=100-
Range: bytes=-500
```

以及：

```text
Content-Range
Content-Length
Accept-Ranges
416 Range Not Satisfiable
```

### 不要顺带修改

不要同时：

- 改 WAV 格式；
- 转低码率；
- 改 M4A；
- 改播放器。

**只修改传输方式。**

---

# 3. `self.lock` 锁粒度

这是整个报告里**最重要、同时修改风险最高的核心项之一**。

现在类似：

```python
with self.lock:
    ...
    model.transcribe()
    ...
    write_wav()
    ffmpeg()
```

问题不是“用了锁”。

而是：

> **锁保护的区域太大。**

正确结构应该是：

```text
锁内
│
├─读取当前 session 状态
├─复制所需数据
├─获取 generation id
└─退出锁
       ↓
推理 / FFmpeg / IO
       ↓
再次进入锁
│
├─确认 generation 没变化
├─确认 session 仍然有效
└─提交结果
```

### 最大风险

假设：

```text
录音 A
↓
后台开始识别
↓
用户停止 A
↓
开始录音 B
↓
A 的识别结果完成
```

如果只是“把锁移出去”，旧任务可能：

```text
A 的结果
    ↓
写进 B
```

所以报告里提到的**会话代际 generation/token**不是附加优化，而是这个改动的前置条件。

建议类似：

```python
session_generation += 1
```

每个后台任务带：

```python
generation_snapshot
```

提交前：

```python
if generation_snapshot != current_generation:
    discard()
```

### 修改风险：高

这里不要一次性重写。

建议拆成三步。

#### 3A

只增加：

```text
session generation / session token
```

但暂时不改变锁。

#### 3B

先把最安全的 IO 移出去：

```text
文件编码
文件写入
```

#### 3C

最后才把：

```text
模型推理
_finish()
```

拆出锁。

这样出了问题，可以知道是哪一步引入的。

---

# 4. PCM 无界队列

这一项我反而建议**暂时不要直接改**。

报告的判断是正确的：

> 不要简单 `Queue(maxsize=...)`。

因为音频采集链路最重要的是：

```text
绝对不能因为识别慢
↓
阻塞录音采集
↓
导致原始音频丢帧
```

性能优化不能破坏录音正确性。

## 第一阶段只增加观测

记录：

```text
queue 当前长度
queue 对应音频秒数
生产速度
消费速度
实时识别耗时
正式识别耗时
临时字幕 backlog
```

例如：

```text
PCM backlog: 0.8 s
PCM backlog: 4.2 s
PCM backlog: 18.7 s
```

这比记录：

```text
queue size = 123
```

更有意义。

### 真正优化策略

优先级应该是：

```text
原始录音             永远保留
正式 VAD 识别        高优先级
临时字幕识别         可降级
```

积压后：

```text
降低临时识别频率
↓
跳过部分临时窗口
↓
恢复正常后重新开启
```

而不是丢正式音频。

### 修改风险：高

因此：

**先 instrumentation，后 policy。**

---

# 5. 图片阻塞文稿打开

当前：

```javascript
await Promise.all(
    images.map(img => img.decode())
)

showTranscript()
```

只要一张图片：

- 很大；
- 损坏；
- 解码慢；

整个文稿都会延迟。

应该反过来：

```text
读取文稿
↓
马上显示文字
↓
首屏图片加载
↓
附近图片加载
↓
其余图片进入视口时加载
```

### 修改风险：中

主要风险不是加载，而是你现在图片系统还有：

- 行内图片；
- 两栏避让；
- 拖拽；
- 图片定位；
- 图片尺寸。

如果 lazy load 导致图片高度后变化：

```text
正文布局重新计算
→ 页面跳动
```

所以必须保存：

```text
width
height
aspect-ratio
```

提前预留空间。

### 建议不要现在做

暂时不要上完整：

```javascript
IntersectionObserver + 图片虚拟化 + LRU + 内存估算
```

第一版只做到：

> **不要等待所有 decode 完成再显示正文。**

已经能解决大部分问题。

---

# 6. 滚动导航和播放高亮

这里其实是两个问题。

## A. 滚动

现在：

```text
scroll event
↓
遍历所有 paragraph
↓
getBoundingClientRect()
```

会出现：

```text
scroll
→ JS
→ layout
→ getBoundingClientRect
→ layout
```

应该先最低成本改成：

```javascript
scroll → requestAnimationFrame(update)
```

保证最多：

```text
一帧一次
```

之后再做位置缓存。

### 风险：低~中

---

## B. 播放高亮

如果每次：

```text
currentTime
↓
从第一段遍历
↓
找到当前段
```

那么：

```text
100 段还好
3000 段开始浪费
```

因为时间戳天然有序，可以二分：

```text
O(n)
↓
O(log n)
```

而 DOM 更新应该只：

```text
previous.classList.remove()
current.classList.add()
```

而不是重新处理所有段。

### 风险：低

这是很值得做的一项。

---

# 7. history 缓存

这个项目当前测试：

```text
30 项     6.53 ms
150 项   32.02 ms
500 项  110.31 ms
```

本身还没有严重到需要数据库。

所以原报告：

> 不要现在迁移 SQLite。

这个判断正确。

可以建立：

```python
cache[path] = {
    mtime,
    size,
    metadata
}
```

只有：

```text
mtime / size 改变
```

才重新读 JSON。

### 修改风险：低

注意：

不要只依赖目录 mtime。

最好针对：

```text
session.json
```

本身记录：

```text
mtime_ns
size
```

---

# 8. 轮询请求合并

这个问题和锁问题实际上是**互相放大的**。

现在：

```text
180 ms 状态轮询
+
900 ms event 轮询
```

如果后端某次被 lock 卡 1 秒：

```text
request 1 等待
request 2 又来了
request 3 又来了
...
```

会把偶发阻塞放大成请求堆积。

不要：

```javascript
setInterval(fetchStatus, 180)
```

应该：

```javascript
async function poll() {
    await fetchStatus()
    setTimeout(poll, 180)
}
```

也就是：

```text
response
↓
等待间隔
↓
下一请求
```

天然避免 overlap。

### 修改风险：低

建议甚至可以在锁重构之前完成。

---

# 9. 长稿整体渲染

这里要把：

**分批渲染**

和

**虚拟列表**

彻底区分。

### 分批渲染

例如：

```text
前 100 段
↓
页面出现
↓
requestIdleCallback
↓
后 200 段
↓
继续
```

DOM 最终仍然全部存在。

修改风险：

**中。**

---

### 虚拟列表

屏幕只有：

```text
20～50 行 DOM
```

滚走以后：

```text
节点直接销毁
```

这会影响：

- Cmd+F；
- 行内编辑；
- 图片位置；
- 拖放；
- 时间轴；
- anchor；
- scrollTo；
- selection；
- 高亮；
- DOM Range。

对于你的软件，这一项是**最后的武器**，不是常规优化。

修改风险：

**极高。**

所以：

> 先分批渲染，不要虚拟化。

---

# 10. 笔记定位

这里比较适合建立一个基础索引：

```javascript
lineById = new Map()
```

原来：

```text
笔记 1 → 搜全文
笔记 2 → 搜全文
笔记 3 → 搜全文
...
```

改为：

```text
line id → DOM node
```

如果根据时间定位：

```text
timestamp[]
```

天然适合二分。

### 修改风险：低~中

需要注意：

当：

```text
重新渲染文稿
编辑内容
插入图片
```

Map 必须重新建立或同步维护。

---

# 11. 全文查找

原来的：

```text
每次查找
↓
恢复所有段落 HTML
↓
重新标记
```

对于长稿显然太重。

建议保存：

```javascript
lastMatches
```

下一次搜索前只清理：

```text
上一轮匹配节点
```

### 修改风险：中

尤其要注意：

如果现在查找是通过修改 `innerHTML` 实现的，要防止：

- 破坏编辑状态；
- 破坏图片节点；
- 破坏事件绑定；
- selection 丢失。

长期最好改为：

```text
Range / text node 高亮
```

但不是本轮必须完成。

---

# 12. 弹窗打开遍历 `body *`

这个完全没有必要。

如果只是为了：

```text
禁止背景滚动
```

应直接控制：

```css
body.modal-open {
    overflow: hidden;
}
```

或者具体：

```text
.transcript-scroll
.sidebar-scroll
```

### 修改风险：低

属于很好清理掉的无效工作。

---

# 13. 启动模型预热

现在：

```text
启动 Python
↓
加载模型
↓
迁移
↓
清缓存
↓
HTTP ready
↓
Tauri 打开
```

优化后：

```text
HTTP ready
↓
Tauri UI 打开
↓
后台：
 ├模型加载
 ├缓存维护
 └其他初始化
```

体验会明显更好。

但是必须增加：

```text
model_state =
uninitialized
loading
ready
error
```

录音按钮需要根据状态：

```text
模型未 ready
→ 禁止开始实时识别
```

或者：

```text
允许录音
但暂时只录制
```

### 修改风险：中高

因为会改变应用初始化生命周期。

**不要和锁重构一起做。**

---

# 14. Whisper 常驻 worker

这不是一定会快。

如果一个文件：

```text
模型加载 2 秒
转写 40 秒
```

常驻意义有限。

如果：

```text
模型加载 4 秒
转写 3 秒
```

才值得。

而常驻进程需要额外解决：

```text
模型状态
任务协议
进程崩溃
自动重启
内存泄漏
取消
版本更新
模型切换
```

### 修改风险：高

所以必须先测：

```text
startup_ms
model_load_ms
transcribe_ms
```

没有数据之前：

**不改。**

---

# 15. 导入流水线

现在：

```text
源文件
↓
M4A
↓
回放文件
↓
识别
```

理论上可以：

```text
源文件
├→ 识别
└→ 回放生成
```

但是必须确认识别输入和：

- 降噪；
- 标准化；
- 声道转换；
- sample rate；

有没有依赖前面的处理。

### 修改风险：中高

所以先加阶段计时：

```text
decode
convert
playback copy
recognition
postprocess
```

再决定有没有价值。

---

# 16. 云端并发

现在实际上已经不是：

```text
只有 2 个请求
```

而可能是：

```text
2 worker
×
润色内部 4 chunk
```

潜在并发量更高。

因此现在继续：

```text
2 → 4 worker
```

不一定更快，可能只会带来：

```text
429
timeout
retry
```

推荐最终形成：

```text
global cloud semaphore
```

例如：

```text
所有云端任务共用一个总并发预算
```

但先记录：

```text
queue wait
request duration
429 count
retry count
timeout count
```

### 修改风险：中高

暂时不属于第一批。

---

# 三、建议修改计划

我建议整个优化拆成 **5 个阶段**，不要同时大面积修改。

## Phase 0：先建立性能基线

这一阶段**不改变行为**。

增加轻量日志：

```text
锁等待时间
模型推理耗时
_finish 耗时
PCM backlog 秒数

worker：
启动耗时
模型加载耗时
推理耗时

前端：
loadSession 总耗时
首次文字显示耗时
图片 decode 耗时
段落数量
图片数量

history：
扫描耗时
JSON 读取次数

云端：
queue / request / retry
```

### 修改风险

**极低。**

这是后面所有优化是否真的有效的判断依据。

---

# Phase 1：低风险、高收益

建议一次完成这些：

1. **修 Whisper stdout/stderr 管道。**
2. **实现音频 Range / 206。**
3. **状态轮询改为无重叠请求。**
4. **history 加 mtime/size 缓存。**
5. **播放高亮改二分查找，只更新前后节点。**
6. **删除弹窗 `body *` 全遍历。**
7. **建立正文 `lineId → DOM` Map。**

这一阶段最大的特点：

> **基本不改变核心数据流。**

所以非常适合作为第一轮性能优化。

---

# Phase 2：前端长稿性能

顺序建议：

```text
图片不再阻塞正文
↓
scroll → rAF
↓
缓存段落位置
↓
笔记定位索引
↓
全文查找局部清理
↓
正文分批渲染
```

### 暂时明确禁止

不要在这一阶段引入：

```text
虚拟列表
```

先看这些措施是否已经足够。

---

# Phase 3：录音并发模型

这是最需要测试的一阶段。

先：

```text
加入 session generation
```

测试没有行为变化。

然后：

```text
IO 出锁
```

再：

```text
FFmpeg 出锁
```

最后：

```text
模型推理出锁
```

每完成一步都进行：

```text
录音
暂停
继续
停止
立即开始新录音
快速连续停止/开始
退出项目
切换项目
关闭程序
```

特别测试：

> **上一录音的异步任务绝对不能污染下一录音。**

---

# Phase 4：PCM 自适应降级

只有 Phase 0 的数据证实：

```text
PCM backlog 持续增长
```

才执行。

不要限制录音队列。

改的是：

```text
临时字幕任务生产速度
```

类似：

```text
backlog < 2 s
实时字幕正常

2–5 s
降低临时识别频率

>5 s
暂停临时识别

backlog 恢复
恢复临时字幕
```

正式录音和正式识别数据始终保留。

---

# Phase 5：实验性优化

最后才判断：

```text
模型后台加载
Whisper 常驻 worker
GPU
导入流水线
云端总并发
虚拟列表
Swift 音频结构
玻璃材质性能
```

这些全部要求：

> **先证明存在瓶颈，再改。**

---

# 四、每阶段的回归测试重点

尤其建议以后让 Codex 每个性能改动都遵守：

```text
修改一个性能问题
→ 增加对应回归测试
→ 再修改下一个
```

核心测试矩阵可以固定下来：

| 功能 | 必测 |
|---|---|
| 实时录音 | 连续录制 30min+ |
| 快速操作 | 开始→停止→开始 |
| 暂停 | 暂停→继续 |
| 停止 | 正在识别时停止 |
| 会话 | A 停止后立即打开 B |
| 音频 | 播放、暂停、拖动、跳到末尾 |
| 长录音 | 1h+ 音频 seek |
| 长稿 | 1000/3000/5000 段 |
| 图片稿 | 10/50/100 张图片 |
| 查找 | 长稿连续搜索 |
| 笔记 | 图片、行内、侧栏笔记定位 |
| Whisper | 正常、失败、取消、强制结束 |
| App | 启动、关闭、异常 worker 恢复 |

---

# 五、我会把原报告压缩成这张路线图

```text
第一轮：确定性问题
────────────────────
subprocess 死锁
Range 音频
轮询重叠
history 缓存
播放高亮
DOM 全遍历

          ↓

第二轮：长稿
────────────────────
正文先显示
图片延迟加载
scroll rAF
位置缓存
笔记索引
全文查找
分批渲染

          ↓

第三轮：录音核心
────────────────────
session generation
↓
IO 出锁
↓
FFmpeg 出锁
↓
推理出锁

          ↓

第四轮：实时识别
────────────────────
测 backlog
↓
临时字幕自适应降级
↓
正式录音绝不阻塞

          ↓

第五轮：有数据再决定
────────────────────
模型预热
常驻 worker
GPU
导入流水线
云端并发
虚拟列表
Swift FIFO
材质降级
```

其中最需要防止的一件事是：**为了性能优化，把一个目前“有点慢但正确”的录音系统改成一个“更快但偶发丢数据/串会话”的系统。** 因此 `self.lock` 和 PCM 两项虽然问题等级最高，却不适合最先大改；第一轮应该先吃掉那些**收益明确、回归面小**的问题。