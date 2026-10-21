import hashlib
import hmac
import json

import httpx


class IntegrationError(RuntimeError):
    pass


def signed_body(secret, payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, signature


class Publisher:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def publish(self, key, channel, text, digest):
        secret = self.settings.publisher_secret.get_secret_value()
        if not secret:
            raise IntegrationError("PUBLISHER_NOT_CONFIGURED")
        body, signature = signed_body(
            secret, {"key": key, "channel": channel, "text": text, "digest": digest}
        )
        with httpx.Client(transport=self.transport, timeout=15) as client:
            response = client.post(
                f"{self.settings.publisher_url}/api/posts",
                content=body,
                headers={"Content-Type": "application/json", "X-Signature": signature},
            )
        if response.is_error:
            raise IntegrationError(f"PUBLISH_HTTP_{response.status_code}")
        result = response.json()
        if not isinstance(result.get("url"), str) or not result["url"].startswith(
            ("http://", "https://")
        ):
            raise IntegrationError("INVALID_PUBLISH_RESPONSE")
        return result["url"]
