# Policy Amadeus

## 免费无人值守维护（2026.09.29-2）

公开 GitHub 仓库运行 `.github/workflows/free-maintenance.yml`，每天北京时间 09:00 全量检查、每小时 17 分增量检查及失败重试。工作流仅允许公开仓库标准运行器，不调用付费 AI/API，不使用付费制品存储。定时任务可能延迟，不能保证实时运行。

`automation_state` 保存逐国覆盖、疑难审查队列、运行记录和官方正文快照。源码/状态上传前只使用明确白名单；执照、店铺配置和私钥不进入仓库。签名私钥只放 GitHub Actions 加密 Secret。未知法规变化不自动改写；只有 `reviewed_changes.json` 中已有官方证据、明确批准且已到生效日期的变更能自动激活，随后测试、签名和发布。首个云端基线不是法律审查完成证明。

本机安装版注册每小时和每日 09:00 的 Windows 检查任务，错过的运行自动补跑。程序文件更新等待旧版退出，失败恢复备份。规则包更新独立于 EXE。本机网络离线时保留最近核验规则，不删除缓存绕过审查。

一次性部署使用 `deploy_free_updates.py`；它验证指定仓库为公开仓库，使用已有登录，将已有签名密钥加密配置到 Secret，再复制明确白名单源码及更新文件。没有权限时明确失败，不自动购买、切换付费服务或泄露密钥。每周审查任务应在云端每日维护实际通过后切换，不提前撤销现有每日检查。

一个三步式 Windows 桌面应用：

1. 选择一个或多个已核验销售国家与输出语言
2. 输入店铺、域名、客服邮箱和客服电话
3. 导入公司执照 PDF

## 直接运行

双击 `run.cmd`。源码运行需要 Pillow、pypdf、deep-translator、translatepy 和 requests。

界面完整显示 `ui_background.jpg`，不会裁剪图片；窗口比例不一致时使用黑色留边。`app_icon.ico` 和 `app_icon.png` 用作窗口、任务栏、桌面 EXE 图标。

## 打包为 EXE

双击 `build_exe.cmd`。首次打包会自动安装 PyInstaller，完成后的程序位于：

`dist\Policy Amadeus.exe`

完成三步后，程序会在自身所在目录保存并在下次启动恢复 `policy_studio_config.json`。

## 规则库与安全检查

- 法定参数来自 `legal_rulepack.json`，规则包包含版本、核验日期、复核截止日和官方来源。
- 每次启动检查官方来源变化；检测到变化且没有已签名更新包时停止生成。
- 每个市场按官方来源逐一检查，并支持政府站点的备用 HTML、API 与 PDF 表示；若站点临时拒绝访问、要求 JavaScript 或发生 TLS/CDN 故障，会显示“部分来源不可达”，但继续使用最近一次已核验的本地规则，不把访问失败误判为法律变化。
- PDF 官方来源会先提取正文再做指纹；超大页面包装表单和内嵌法规数据不会被误删。
- 远程更新必须通过 HTTPS、SHA-256 和 Ed25519 数字签名验证。
- 更新通道内置于 `update_channel.json`；发布私钥仅保存在 `%LOCALAPPDATA%\\Policy Amadeus`，绝不打包进 EXE。
- 使用 `python publisher_tools.py <HTTPS Raw基础地址>` 生成待发布的 `rulepack_release/manifest.json` 与规则包。
- AI审阅默认关闭，只能报告问题，不能修改法定参数或政策正文。

## 本机自动更新

安装版首次打开时会登记当前用户的 Windows 计划任务 `Policy Amadeus Auto Update`，每天本地时间 09:00 运行 `Policy Amadeus.exe --auto-update`。任务会检查全部已配置官方来源、下载经过 Ed25519 签名与 SHA-256 校验的规则包，并检查单独签名的程序发布清单。新版 EXE 下载并校验后，安装助手会等正在运行的程序退出再替换文件；替换失败时保留旧版并记录原因。

检查状态保存在 `%LOCALAPPDATA%\Policy Amadeus\auto_update_status.json`，安装状态保存在同目录的 `app_install_status.json`。后台入口不加载桌面界面，同一时间只允许一个定时检查进程；异常写入 `auto_update_error.json`。来源指纹检查不等于完整逐国法律核验，覆盖报告明确记录检查方法。安装签名规则包不会自动清除尚未复核的网页变化。程序版本在 `app_version.json` 中，每次代码发布必须递增。尚未发布新的 `app_manifest.json` 时，程序会记录 `no_published_release` 并继续使用已安装版本。

发布端在完整测试和打包通过后运行 `python publisher_tools.py https://raw.githubusercontent.com/yeqi1469-create/policy-amadeus-rulepack/main --app-exe "dist\Policy Amadeus.exe"`，将签名规则包、EXE 和两份清单放入 `rulepack_release`。发布这些文件到配置的 GitHub 仓库后，已安装程序才会自动收到更新。官方网页变化需要逐国核验；暂时不可达不会自动改写法规参数。
