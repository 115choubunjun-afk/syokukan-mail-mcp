from functools import partial
from html import escape
import os
from urllib.parse import urlsplit

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from mailer import Drafts, SENDER, deliver_smtp
from owner_auth import OwnerAuth, SCOPE


def page(title, content, status=200):
    return HTMLResponse(
        '<!doctype html><html lang="zh"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title}</title><h1>{title}</h1>{content}</html>',
        status_code=status,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )


def form(key, action, label):
    return (
        f'<form method="post" action="{action}">'
        f'<input type="hidden" name="key" value="{escape(key, quote=True)}">'
        '<p><label>插件确认密钥 <input type="password" name="passphrase" required></label></p>'
        f'<button type="submit">{label}</button></form>'
    )


def create_app(origin, passphrase, deliver):
    url = urlsplit(origin)
    if url.scheme != "https" or not url.hostname or url.path or url.query or url.fragment or url.username:
        raise ValueError("PUBLIC_ORIGIN must be an HTTPS origin without a trailing slash.")
    if len(passphrase) < 32:
        raise ValueError("OWNER_PASSPHRASE must be at least 32 characters.")
    auth = OwnerAuth(origin, passphrase)
    drafts = Drafts(deliver)
    mcp = FastMCP(
        "蜀漢发信助手",
        instructions="为用户准备邮件预览。展示全部字段和确认链接。用户必须亲自在网页核对并提交发送。",
        auth_server_provider=auth,
        auth=AuthSettings(
            issuer_url=origin, resource_server_url=auth.resource, validate_token_resource=True,
            required_scopes=[SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[url.netloc], allowed_origins=[origin],
        ),
    )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False))
    def preview_email(to: str, subject: str, body: str) -> dict:
        """Prepare a single-recipient plain-text email. Returns a private browser confirmation link valid for 15 minutes."""
        key, draft = drafts.create(to, subject, body)
        return {
            "from": SENDER, "to": draft.to, "subject": draft.subject, "body": draft.body,
            "confirmation_url": f"{origin}/owner/send?key={key}",
            "status": "awaiting_confirmation",
        }

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request):
        return PlainTextResponse("ok")

    @mcp.custom_route("/owner/connect", methods=["GET", "POST"])
    async def connect(request):
        if request.method == "GET":
            key = request.query_params.get("key", "")
            return page("连接蜀漢发信助手", form(key, "/owner/connect", "允许连接"))
        async with request.form(max_fields=2, max_files=0, max_part_size=2048) as fields:
            if not auth.check_passphrase(str(fields.get("passphrase", ""))):
                return page("密钥不正确", "<p>返回上一页后重试。</p>", 403)
            try:
                target = auth.approve(str(fields.get("key", "")))
            except KeyError:
                return page("连接已过期", "<p>请从 ChatGPT 重新连接。</p>", 410)
        return RedirectResponse(target, status_code=303, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/owner/send", methods=["GET", "POST"])
    async def send(request):
        if request.method == "GET":
            key = request.query_params.get("key", "")
            try:
                draft = drafts.view(key)
            except KeyError:
                return page("预览不可用", "<p>请在 ChatGPT 重新生成预览。</p>", 410)
            content = (
                f'<p>发件人：{SENDER}</p><p>收件人：{escape(draft.to)}</p>'
                f'<p>主题：{escape(draft.subject)}</p>'
                f'<pre wrap>{escape(draft.body)}</pre>'
                + form(key, "/owner/send", "确认发送")
            )
            return page("核对邮件并发送", content)
        async with request.form(max_fields=2, max_files=0, max_part_size=2048) as fields:
            if not auth.check_passphrase(str(fields.get("passphrase", ""))):
                return page("密钥不正确", "<p>返回上一页后重试。</p>", 403)
            key = str(fields.get("key", ""))
        try:
            await run_in_threadpool(drafts.confirm, key)
        except KeyError:
            return page("预览不可用", "<p>这份预览可能已提交或过期。</p>", 410)
        except Exception:
            return page("无法确认发送结果", "<p>请先检查收件箱，再决定是否重新发送。</p>", 502)
        return page("已提交给邮件服务器", "<p>请在收件箱确认是否收到。</p>")

    return mcp.streamable_http_app()


def app_factory():
    origin = os.getenv("PUBLIC_ORIGIN") or os.environ["RENDER_EXTERNAL_URL"]
    return create_app(
        origin,
        os.environ["OWNER_PASSPHRASE"],
        partial(deliver_smtp, username=os.environ["SMTP_USERNAME"], password=os.environ["SMTP_PASSWORD"]),
    )
