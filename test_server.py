import base64
import hashlib
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

from starlette.testclient import TestClient

from server import create_app


class ServerTest(unittest.TestCase):
    def test_oauth_preview_and_browser_confirmation(self):
        origin = "https://test.example"
        resource = origin + "/mcp"
        password = "test-owner-secret-" * 3
        deliver = Mock()
        callback = "https://chatgpt.com/connector/oauth/test_callback"
        verifier = "v" * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        accept = {"Accept": "application/json, text/event-stream"}
        preview = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "preview_email", "arguments": {
                "to": "owner@example.com", "subject": "测试", "body": "<script>测试</script>",
            }},
        }
        with TestClient(create_app(origin, password, deliver), base_url=origin) as client:
            self.assertEqual(client.post("/mcp", json=preview, headers=accept).status_code, 401)
            registration = client.post("/register", json={
                "redirect_uris": [callback], "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            })
            self.assertEqual(registration.status_code, 201, registration.text)
            client_id = registration.json()["client_id"]
            authorization = client.get("/authorize", params={
                "client_id": client_id, "response_type": "code", "redirect_uri": callback,
                "code_challenge": challenge, "code_challenge_method": "S256",
                "scope": "mail:preview", "state": "test", "resource": resource,
            }, follow_redirects=False)
            self.assertEqual(authorization.status_code, 302, authorization.text)
            key = parse_qs(urlsplit(authorization.headers["location"]).query)["key"][0]
            login = client.post("/owner/connect", data={"key": key, "passphrase": password}, follow_redirects=False)
            self.assertEqual(login.status_code, 303)
            code = parse_qs(urlsplit(login.headers["location"]).query)["code"][0]
            token = client.post("/token", data={
                "grant_type": "authorization_code", "client_id": client_id, "code": code,
                "redirect_uri": callback, "code_verifier": verifier, "resource": resource,
            })
            self.assertEqual(token.status_code, 200, token.text)
            headers = {**accept, "Authorization": f"Bearer {token.json()['access_token']}"}
            result = client.post("/mcp", json=preview, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            tool_result = result.json()["result"]
            self.assertFalse(tool_result.get("isError"), tool_result)
            contents = tool_result.get("structuredContent") or json.loads(tool_result["content"][0]["text"])
            confirmation = contents["confirmation_url"]
            self.assertIn("&lt;script&gt;", client.get(confirmation).text)
            key = parse_qs(urlsplit(confirmation).query)["key"][0]
            denied = client.post("/owner/send", data={"key": key, "passphrase": "wrong"})
            self.assertEqual(denied.status_code, 403)
            deliver.assert_not_called()
            self.assertEqual(client.post("/owner/send", data={"key": key, "passphrase": password}).status_code, 200)
            self.assertEqual(client.post("/owner/send", data={"key": key, "passphrase": password}).status_code, 410)
            deliver.assert_called_once()
            self.assertEqual(deliver.call_args.args[0].body, "<script>测试</script>")
