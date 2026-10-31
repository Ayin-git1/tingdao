# 发布听道前端补丁

从 3.1.9 起支持：启动后后台检查 GitHub，静默下载，下次启动生效。旧版用户必须先安装支持补丁的基础版。补丁只替换 `index.html`，后端、助手、依赖与原生壳仍使用完整安装包更新。

## 密钥

当前公钥在 `frontend-patch-public-key.hex`，编译进原生壳。私钥生成于本机 `releases/patch-signing/private.pem`，权限为 0600，整个 releases/ 已被 Git 忽略。

**请单独备份私钥。不要提交到 Git、上传到 Release、复制进 App，或在对话中粘贴。** 私钥丢失后，已安装客户端无法接受新密钥签名；需要发布新的基础安装版。私钥泄露时同样需要更换密钥并发布基础版。

只在建立全新补丁信任体系时生成密钥，正常发补丁不重新生成：

```sh
node tools/frontend-patch.cjs keygen releases/patch-signing/private.pem frontend-patch-public-key.hex
```

工具会拒绝覆盖已有密钥。运行依赖 Node 18+，客户端不依赖 Node，也不新增 Python 签名库。

## 生成补丁

先验证新的页面兼容目标基础版的 Python API 和资源。每个基础版本单独维护递增整数序号，已经发布的序号不要复用。

```sh
node tools/frontend-patch.cjs build \
  --key releases/patch-signing/private.pem \
  --base-version 3.1.9 --revision 1 \
  --html index.html --out releases/3.1.9/frontend-patch-p1
```

从 3.1.9.1 起可加 `--notes 更新说明.md`（Markdown，≤8000 字）：说明写进签名标签，客户端下载后在右上角显示「更新」，点开展示这段说明并可「立即重启」。3.1.9 客户端忽略该字段。基础版本号支持四段增量版，如 `--base-version 3.1.9.1`。

输出三个公开文件：`index-3.1.9-p1.html`、`tingdao-patch.sig` 和 `tingdao-patch.json`。JSON 是补丁标签文件，签名绑定其完整原始字节（不要手动修改）：

```json
{
  "schema": 1,
  "base_version": "3.1.9",
  "revision": 1,
  "action": "apply",
  "asset": "index-3.1.9-p1.html",
  "size": 123456,
  "sha256": "由工具计算的64位十六进制SHA256"
}
```

## GitHub 配置

在 `Ayin-git1/tingdao` 创建固定 tag 为 `frontend-patches` 的 Release，勾选 **pre-release**。不要放安装包，此频道仅供补丁使用。客户端按 tag 查询 GitHub Release，再按资产名获取补丁标记和前端文件；普通安装包更新逻辑继续跳过预发布。

每次发布先上传新的 HTML，再替换签名与 JSON（可先更新签名，最后更新 JSON）。更新期间签名与标签不一致时，客户端会静默跳过，下次启动重试。保留当前 JSON 引用的 HTML 资产。发布工具只构建文件，不自动上传。

补丁必须精确匹配基础版，例如 3.1.9 补丁不会被 3.1.8 或 3.1.10 应用。本版一个标签文件只指向一个基础版；将频道切到新基础版后，旧基础版继续使用自己已验证的本地补丁。

## 完整安装版升级时同步补丁标签

每次改变基础安装版版本号（不限于语义版本中的“大版本”），都必须把补丁通道纳入发布检查，不能只更新 App 和安装包元数据。

1. 确认新安装版内置前端已包含需要保留的旧修复；新版本不会继承旧基础版本的补丁目录。
2. 基于最终交付源码，为新基础版本生成 `tingdao-patch.json` 和签名。沿用原密钥，不能手改 JSON 后保留旧签名。
3. 查询远端记录，确定新基础版本的序号。从未发布过时才使用 1；已有记录则递增，不能拿旧基础版本的序号直接判断。
4. 发布完整安装版时，同步发布新的补丁标签。需要 HTML 时先上传资产，再更新签名与 JSON；只授权本地制作时，准备配套资产并明确记录远端尚未同步。
5. 回读远端标签，验证 `base_version` 等于新安装版的 `APP_VERSION`、签名有效、所引用的 HTML 资产及哈希正确，并分别验收普通安装包更新与补丁检查。

如果新基础版本没有额外补丁，用签名的 `action: "builtin"` 标签初始化频道，表示使用该基础版本自带前端。例如首次发布 3.1.10，且确认该基础版本从未发布过补丁时：

```sh
node tools/frontend-patch.cjs build \
  --key releases/patch-signing/private.pem \
  --base-version 3.1.10 --revision 1 --rollback \
  --out releases/3.1.10/frontend-baseline-p1
```

现有命令的 `--rollback` 生成“使用本基础版本内置前端”动作，在这里用于初始化基线，不会降级安装包版本。以后发布真正前端补丁，从更高序号继续。

漏同步不会阻止完整安装包检测和安装，但新版本会忽略旧基础版本的补丁标签。当前单标签频道切换后，旧基础版本继续使用已验证的本地补丁或内置页面，不再获得该频道的新下载。

## 生效与恢复

- 补丁在用户数据目录 `.frontend-patches/<基础版本>/` 下，App 包保持不变。
- 当前进程固定使用启动时的页面快照，下载不会中途切换页面、刷新或弹提示。
- 新补丁第一次启动后由页面回报就绪；未收到回报，则下次启动回退内置页面，且不重试该序号。该检测覆盖页面启动，不检测所有功能错误。
- 同时启动多个实例时，只有获得补丁目录锁的实例管理补丁；其他实例使用内置页面。
- 下载、校验或落盘失败时继续使用已有页面。GitHub 限流、断网或不存在补丁 Release 均不影响正常使用。
- 直接运行源码且没有原生验证器时不启用补丁下载，不接受未签名页面。

发布远程回退指令（序号必须高于之前所有已发布序号）：

```sh
node tools/frontend-patch.cjs build \
  --key releases/patch-signing/private.pem \
  --base-version 3.1.9 --revision 2 --rollback \
  --out releases/3.1.9/rollback-p2
```

回退输出只有 JSON 和签名。上传替换频道的这两个文件，用户下一次检查下载、再下一次启动使用内置页面。恢复补丁时继续使用更高序号。

## 本地验证

```sh
python3 -m unittest discover -s tests -p test_frontend_patch.py
node --test tests/frontend-patch-publisher.test.js tests/frontend-patch-ui.test.js
cargo test --manifest-path tauri-shell/Cargo.toml --locked --offline
TINGDAO_TEST_PATCH_VERIFIER="绝对路径/听道.app/Contents/MacOS/tingdao-shell" \
  ~/tingdao-venv/bin/python -m unittest discover -s tests -p test_frontend_patch_integration.py
```

集成测试只使用临时数据目录和本地 HTTP 服务，并调用真实原生验证器。Windows 代码与资源 staging 可在本机测试；Windows 安装包仍需 Windows 构建与运行验证。
