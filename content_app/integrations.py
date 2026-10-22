import hashlib
import hmac
import json

import httpx


class IntegrationError(RuntimeError):
    pass


class PublishResult:
    def __init__(self, *, external_id, url, destination="local_test"):
        self.external_id = external_id
        self.url = url
        self.destination = destination


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
        try:
            with httpx.Client(transport=self.transport, timeout=15) as client:
                response = client.post(
                    f"{self.settings.publisher_url}/api/posts",
                    content=body,
                    headers={"Content-Type": "application/json", "X-Signature": signature},
                )
        except httpx.TimeoutException as exc:
            # The remote service may have committed the post before the response was lost.
            # Callers must reconcile this outcome instead of blindly reposting it.
            raise IntegrationError("PUBLISH_UNCERTAIN") from exc
        except httpx.HTTPError as exc:
            raise IntegrationError("PUBLISH_NETWORK_FAILED") from exc
        if response.is_error:
            raise IntegrationError(f"PUBLISH_HTTP_{response.status_code}")
        result = response.json()
        if not isinstance(result.get("url"), str) or not result["url"].startswith(
            ("http://", "https://")
        ):
            raise IntegrationError("INVALID_PUBLISH_RESPONSE")
        # Legacy test destinations may only return a URL; the idempotency key is
        # still a stable external reference for those adapters. The bundled
        # publisher returns an explicit external_id.
        external_id = result.get("external_id") or key
        return PublishResult(
            external_id=external_id,
            url=result["url"],
            destination=result.get("destination", "local_test"),
        )

    def reconcile(self, key, digest):
        """Look up an idempotency key after a lost response; never republishes."""
        with httpx.Client(transport=self.transport, timeout=15) as client:
            response = client.get(f"{self.settings.publisher_url}/api/posts/{key}")
        if response.status_code == 404:
            return None
        if response.is_error:
            raise IntegrationError(f"RECONCILE_HTTP_{response.status_code}")
        result = response.json()
        if result.get("digest") != digest:
            raise IntegrationError("RECONCILE_DIGEST_MISMATCH")
        return PublishResult(
            external_id=result["external_id"],
            url=result["url"],
            destination=result.get("destination", "local_test"),
        )
