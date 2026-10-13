# Policy Amadeus — 手动维护版

本版本不自动检查、下载、安装或重启，不注册计划任务，不启动法律 AI 审查，也不向 Codex 自动发送故障请求。

政策生成、执照提取和店铺配置保留。程序使用本地规则，并保留规则完整性、复核期限及已知待复核事项的安全检查；移除自动更新不表示旧政策已经通过新的法律复核。

需要更新政策或程序时，请在当前聊天明确提出请求。

测试：`python -m unittest discover -q`

手动打包：`python -m PyInstaller --noconfirm "Shopify Policy Studio.spec"`

被清理的自动更新代码和临时产物保存在工作目录外的 `manual_mode_backup`，不随程序打包。
