import re
import secrets
from time import time
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizeError, RegistrationError, TokenError,
)
from mcp.shared.auth import OAuthToken


SCOPE = "mail:preview"
CALLBACK = re.compile(
    r"https://chatgpt\.com/(?:connector_platform_oauth_redirect|connector/oauth/[A-Za-z0-9_-]+)"
)


class OwnerAuth:
    def __init__(self, origin, passphrase):
        self.origin = origin
        self.resource = origin + "/mcp"
        self.passphrase = passphrase.encode()
        self.clients = {}
        self.pending = {}
        self.codes = {}
        self.tokens = {}

    def check_passphrase(self, value):
        return secrets.compare_digest(value.encode(), self.passphrase)

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def register_client(self, client_info):
        if not all(CALLBACK.fullmatch(str(uri)) for uri in client_info.redirect_uris):
            raise RegistrationError("invalid_redirect_uri", "Use a ChatGPT OAuth callback.")
        if len(self.clients) >= 50:
            raise RegistrationError("invalid_client_metadata", "Registration limit reached.")
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client, params):
        if params.resource not in (None, self.resource):
            raise AuthorizeError("invalid_request", "Incorrect MCP resource.")
        now = time()
        self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
        if len(self.pending) >= 50:
            raise AuthorizeError("temporarily_unavailable", "Try again later.")
        key = secrets.token_urlsafe(32)
        self.pending[key] = (now + 300, client.client_id, params)
        return f"{self.origin}/owner/connect?{urlencode({'key': key})}"

    def approve(self, key):
        expiry, client_id, params = self.pending.pop(key)
        if expiry <= time():
            raise KeyError(key)
        now = time()
        self.codes = {k: v for k, v in self.codes.items() if v.expires_at > now}
        code = AuthorizationCode(
            code=secrets.token_urlsafe(32), client_id=client_id, scopes=[SCOPE],
            expires_at=time() + 90, code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self.resource, subject="owner",
        )
        self.codes[code.code] = code
        return str(code.redirect_uri) + "?" + urlencode({"code": code.code, "state": params.state or ""})

    async def load_authorization_code(self, client, authorization_code):
        code = self.codes.get(authorization_code)
        if code and code.client_id == client.client_id:
            return code

    async def exchange_authorization_code(self, client, authorization_code):
        code = self.codes.pop(authorization_code.code, None)
        if not code or code.client_id != client.client_id or code.expires_at <= time():
            raise TokenError("invalid_grant")
        now = int(time())
        self.tokens = {k: v for k, v in self.tokens.items() if v.expires_at > now}
        token = secrets.token_urlsafe(32)
        self.tokens[token] = AccessToken(
            token=token, client_id=client.client_id, scopes=[SCOPE],
            expires_at=now + 8 * 3600, resource=self.resource, subject="owner",
        )
        return OAuthToken(access_token=token, expires_in=8 * 3600, scope=SCOPE)

    async def load_access_token(self, token):
        access = self.tokens.get(token)
        if access and access.expires_at > time():
            return access

    async def load_refresh_token(self, client, refresh_token):
        return None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        raise TokenError("invalid_grant")

    async def revoke_token(self, token):
        self.tokens.pop(token.token, None)
