# 蜀漢发信助手

从 ChatGPT Work 生成单收件人的纯文本邮件预览，然后在 iPhone 浏览器中核对并发送。发件人固定为 `1@syokukan.co.jp`。

## Render 部署

可以使用仓库根目录的 `render.yaml` 创建 Blueprint。已有 New Web Service 页面时，也可以手动设置：

| 项目 | 设置 |
| --- | --- |
| Language | Python 3 |
| Branch | main |
| Root Directory | 留空 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn server:app_factory --factory --host 0.0.0.0 --port $PORT --no-access-log` |
| Health Check Path | `/health` |
| Instance Type | Starter 或其他允许 SMTP 587 出站的付费类型 |

在 Render 的 Environment 页面填写 `SMTP_USERNAME`（与 Outlook 的 IMAP 登录用户名相同）、`SMTP_PASSWORD` 和 `OWNER_PASSPHRASE`。用密码管理器生成至少 32 字符的独立随机密钥，用于插件登录和发送确认。只在 Render 和该服务自己的 HTTPS 确认页输入密钥。Render 自动提供 `RENDER_EXTERNAL_URL`；本地集成测试直接调用应用工厂。

## ChatGPT 接入

1. 部署成功后，将 `https://<服务名>.onrender.com/mcp` 添加为自定义 MCP 服务器，身份验证选 OAuth，使用动态客户端注册。
2. 在 iPhone 的 ChatGPT Work 使用插件，要求生成发给你自己的测试邮件。登录时在浏览器里填写插件确认密钥。
3. 核对 ChatGPT 给出的预览。打开确认链接，核对页面里的内容，输入插件确认密钥并点击「确认发送」。到收件箱检查是否收到。

预览链接 15 分钟内有效，仅能提交一次。仅运行一个服务实例。服务重启后，未提交的预览、OAuth 注册和登录都会失效；需要重新连接插件，必要时重新添加 MCP 服务器。遇到无法确认 SMTP 结果时，请先检查收件箱再决定是否重新生成邮件。

## 验证

安装依赖后运行 `python -m unittest -v`。测试使用模拟 SMTP。
