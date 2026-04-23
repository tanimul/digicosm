"""
AI Proxy Service — Digital Consumption Ecosystem Platform.

Handles the full lifecycle of an AI request:
  1. Validate & deduct credits from wallet
  2. Route to best provider + key
  3. Forward the request (OpenAI, Claude, DeepSeek, …)
  4. Stream or buffer the response
  5. Log usage, update conversation, refund on failure

Caching uses Django's cache backend (Redis).
"""

import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Any, Generator, Optional

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.wallet.models import Wallet
from .models import (
    AIConversation,
    AIMessage,
    AIService,
    AIUsageLog,
    MessageRole,
    ProviderAPIKey,
    ServiceType,
    UsageStatus,
)
from .routing import AIRoutingEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS    = 120
STREAMING_TIMEOUT_SECONDS  = 300
CACHE_DEFAULT_TTL          = 3600   # 1 hour for identical prompt cache hits
CACHE_KEY_PREFIX           = "ai:response:"

# Credits-to-BDT rate (keep in sync with wallet)
BDT_TO_CREDITS_RATE        = Decimal("10.0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_cache_key(service_id, messages: list[dict]) -> str:
    """Deterministic cache key from service + message history."""
    import hashlib, json
    payload = json.dumps({"sid": str(service_id), "msgs": messages}, sort_keys=True)
    digest  = hashlib.sha256(payload.encode()).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


def _extract_openai_usage(response: dict) -> dict:
    usage = response.get("usage", {})
    return {
        "prompt_tokens":     usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens":      usage.get("total_tokens", 0),
    }


def _extract_claude_usage(response: dict) -> dict:
    usage = response.get("usage", {})
    return {
        "prompt_tokens":     usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens":      usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
    }


def _extract_assistant_text(response: dict, provider_name: str) -> str:
    """Pull the assistant's text from a raw provider response."""
    if provider_name == "claude":
        contents = response.get("content", [])
        texts    = [c.get("text", "") for c in contents if c.get("type") == "text"]
        return "".join(texts)
    # OpenAI / DeepSeek / Gemini / Cohere all use choices[0].message.content
    choices = response.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


# ---------------------------------------------------------------------------
# AIProxyService
# ---------------------------------------------------------------------------

class AIProxyService:
    """
    Main gateway service.  Instantiate once per request (or use as a singleton).
    """

    def __init__(self) -> None:
        self.router = AIRoutingEngine()

    # ------------------------------------------------------------------
    # Public: non-streaming request
    # ------------------------------------------------------------------

    def process_request(
        self,
        user,
        service_id: str,
        messages: list[dict],
        params: Optional[dict] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """
        Process a complete (non-streaming) AI chat request.

        Returns a dict with keys: ``content``, ``usage``, ``credits_charged``,
        ``request_id``, ``session_id``, ``cached``, ``response_time_ms``.

        Raises:
            ``ValueError``  — service not found / inactive
            ``ValidationError`` — insufficient credits
        """
        params     = params or {}
        request_id = uuid.uuid4()
        start_ts   = time.perf_counter()

        # 1. Resolve service
        service = self._get_service(service_id)

        # 2. Cache lookup (skip for sessions with existing history)
        cache_key     = _build_cache_key(service_id, messages)
        cached_result = self._check_cache(cache_key)
        if cached_result and not session_id:
            cached_result["request_id"]  = str(request_id)
            cached_result["cached"]      = True
            cached_result["response_time_ms"] = 0
            self._log_usage(
                user=user,
                service=service,
                key=None,
                usage_data={
                    **_extract_openai_usage(cached_result.get("_raw", {})),
                    "credits_charged": Decimal(str(cached_result.get("credits_charged", 0))),
                    "bdt_cost":        Decimal("0"),
                    "profit_bdt":      Decimal(str(cached_result.get("credits_charged", 0))) / BDT_TO_CREDITS_RATE,
                    "response_time_ms": 0,
                    "status":          UsageStatus.SUCCESS,
                    "request_id":      request_id,
                    "session_id":      uuid.UUID(session_id) if session_id else None,
                    "cached":          True,
                },
            )
            return cached_result

        # 3. Route
        provider, key = self.router.select_provider_and_key(
            service_type=service.service_type,
            requirements={"service_name": service.service_name},
        )
        record_start = self.router.record_request_start(provider, key)

        # 4. Deduct credits upfront (refunded on failure)
        estimated_credits = service.sell_price_credits
        wallet            = self._get_wallet(user)
        with transaction.atomic():
            wallet.debit_credits(
                amount=estimated_credits,
                description=f"AI request: {service.display_name}",
                metadata={"request_id": str(request_id), "service_id": str(service_id)},
            )

        # 5. Call provider
        raw_response  = {}
        error_message = ""
        status        = UsageStatus.SUCCESS
        try:
            raw_response = self._dispatch(
                provider_name=provider.name,
                key=key,
                messages=messages,
                model=service.model_id,
                params=params,
            )
            key.increment_usage()
            provider.total_requests_served += 1
            provider.save(update_fields=["total_requests_served", "updated_at"])
        except httpx.TimeoutException as exc:
            status        = UsageStatus.TIMEOUT
            error_message = f"Request timed out: {exc}"
            logger.error("AI timeout for service=%s: %s", service.service_name, exc)
            self._refund_credits(wallet, estimated_credits, request_id)
            provider.mark_unhealthy()
        except Exception as exc:
            status        = UsageStatus.FAILED
            error_message = str(exc)[:2048]
            logger.exception("AI request failed for service=%s", service.service_name)
            self._refund_credits(wallet, estimated_credits, request_id)
            try:
                provider2, key2 = self.router.failover(key, service)
                raw_response    = self._dispatch(
                    provider_name=provider2.name,
                    key=key2,
                    messages=messages,
                    model=service.model_id,
                    params=params,
                )
                status        = UsageStatus.SUCCESS
                error_message = ""
                key           = key2
                provider      = provider2
                wallet.debit_credits(
                    amount=estimated_credits,
                    description=f"AI request (failover): {service.display_name}",
                    metadata={"request_id": str(request_id)},
                )
            except Exception as failover_exc:
                logger.error("Failover also failed: %s", failover_exc)

        elapsed_ms = self.router.record_request_end(provider, record_start, success=(status == UsageStatus.SUCCESS))

        # 6. Extract usage
        if provider.name == "claude":
            token_data = _extract_claude_usage(raw_response)
        else:
            token_data = _extract_openai_usage(raw_response)

        total_tokens    = token_data["total_tokens"]
        credits_charged = self._calculate_credits(service, total_tokens) if total_tokens else estimated_credits
        bdt_cost        = (credits_charged / BDT_TO_CREDITS_RATE * service.cost_per_request_bdt).quantize(Decimal("0.000001"))
        sell_bdt        = (credits_charged / BDT_TO_CREDITS_RATE).quantize(Decimal("0.000001"))
        profit_bdt      = sell_bdt - bdt_cost

        # Adjust credit charge if actual differs from estimate
        if status == UsageStatus.SUCCESS and credits_charged != estimated_credits:
            diff = credits_charged - estimated_credits
            if diff > Decimal("0"):
                try:
                    wallet.debit_credits(amount=diff, description="AI usage adjustment")
                except Exception:
                    pass
            elif diff < Decimal("0"):
                self._refund_credits(wallet, abs(diff), request_id)

        # 7. Log usage
        usage_log = self._log_usage(
            user=user,
            service=service,
            key=key,
            usage_data={
                **token_data,
                "credits_charged":  credits_charged,
                "bdt_cost":         bdt_cost,
                "profit_bdt":       profit_bdt,
                "response_time_ms": elapsed_ms,
                "status":           status,
                "error_message":    error_message,
                "request_id":       request_id,
                "session_id":       uuid.UUID(session_id) if session_id else None,
                "cached":           False,
            },
        )

        # 8. Persist conversation
        assistant_text = _extract_assistant_text(raw_response, provider.name)
        if session_id and status == UsageStatus.SUCCESS:
            self._update_conversation(
                user=user,
                session_id=session_id,
                service=service,
                messages=messages,
                assistant_text=assistant_text,
                tokens=total_tokens,
                credits=credits_charged,
            )

        # 9. Cache successful response
        result = {
            "content":          assistant_text,
            "usage":            token_data,
            "credits_charged":  str(credits_charged),
            "request_id":       str(request_id),
            "session_id":       session_id or str(usage_log.session_id),
            "cached":           False,
            "response_time_ms": elapsed_ms,
            "status":           status,
            "error_message":    error_message,
            "_raw":             raw_response,
        }
        if status == UsageStatus.SUCCESS:
            self._cache_response(cache_key, result)

        return result

    # ------------------------------------------------------------------
    # Public: SSE streaming
    # ------------------------------------------------------------------

    def stream_response(
        self,
        user,
        service_id: str,
        messages: list[dict],
        params: Optional[dict] = None,
        session_id: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Yield Server-Sent Events for a streaming AI response.

        Each yielded string is a complete SSE line (``data: {...}\\n\\n``).
        A final ``data: [DONE]\\n\\n`` terminates the stream.
        """
        params     = params or {}
        request_id = uuid.uuid4()

        service  = self._get_service(service_id)
        provider, key = self.router.select_provider_and_key(
            service_type=service.service_type,
            requirements={"service_name": service.service_name},
        )
        record_start = self.router.record_request_start(provider, key)

        # Pre-deduct estimated credits
        estimated_credits = service.sell_price_credits
        wallet            = self._get_wallet(user)
        wallet.debit_credits(
            amount=estimated_credits,
            description=f"AI stream: {service.display_name}",
            metadata={"request_id": str(request_id)},
        )

        decrypted_key = key.get_decrypted_key()
        full_content  = []
        total_tokens  = 0
        status        = UsageStatus.SUCCESS
        error_msg     = ""

        try:
            stream_fn = self._get_stream_function(provider.name)
            for chunk in stream_fn(
                api_key=decrypted_key,
                messages=messages,
                model=service.model_id,
                params=params,
                base_url=provider.base_url,
            ):
                if chunk.get("type") == "token":
                    token_text = chunk.get("text", "")
                    full_content.append(token_text)
                    yield f"data: {json.dumps({'token': token_text, 'request_id': str(request_id)})}\n\n"
                elif chunk.get("type") == "usage":
                    total_tokens = chunk.get("total_tokens", 0)

            key.increment_usage()

        except httpx.TimeoutException as exc:
            status    = UsageStatus.TIMEOUT
            error_msg = str(exc)
            self._refund_credits(wallet, estimated_credits, request_id)
            yield f"data: {json.dumps({'error': 'timeout', 'message': error_msg})}\n\n"

        except Exception as exc:
            status    = UsageStatus.FAILED
            error_msg = str(exc)[:2048]
            self._refund_credits(wallet, estimated_credits, request_id)
            yield f"data: {json.dumps({'error': 'failed', 'message': error_msg})}\n\n"

        finally:
            elapsed_ms      = self.router.record_request_end(provider, record_start, success=(status == UsageStatus.SUCCESS))
            assistant_text  = "".join(full_content)
            credits_charged = self._calculate_credits(service, total_tokens) if total_tokens else estimated_credits
            bdt_cost        = (credits_charged / BDT_TO_CREDITS_RATE * service.cost_per_request_bdt).quantize(Decimal("0.000001"))
            sell_bdt        = (credits_charged / BDT_TO_CREDITS_RATE).quantize(Decimal("0.000001"))

            self._log_usage(
                user=user,
                service=service,
                key=key,
                usage_data={
                    "prompt_tokens":     0,
                    "completion_tokens": total_tokens,
                    "total_tokens":      total_tokens,
                    "credits_charged":   credits_charged,
                    "bdt_cost":          bdt_cost,
                    "profit_bdt":        sell_bdt - bdt_cost,
                    "response_time_ms":  elapsed_ms,
                    "status":            status,
                    "error_message":     error_msg,
                    "request_id":        request_id,
                    "session_id":        uuid.UUID(session_id) if session_id else None,
                    "cached":            False,
                },
            )

            if session_id and status == UsageStatus.SUCCESS:
                self._update_conversation(
                    user=user,
                    session_id=session_id,
                    service=service,
                    messages=messages,
                    assistant_text=assistant_text,
                    tokens=total_tokens,
                    credits=credits_charged,
                )

        yield "data: [DONE]\n\n"

    # ------------------------------------------------------------------
    # Provider dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        provider_name: str,
        key: ProviderAPIKey,
        messages: list[dict],
        model: str,
        params: dict,
    ) -> dict:
        decrypted = key.get_decrypted_key()
        base_url  = key.provider.base_url

        dispatch_map = {
            "openai":   self.call_openai,
            "deepseek": self.call_deepseek,
            "claude":   self.call_claude,
            "gemini":   self.call_openai,   # Gemini uses OpenAI-compatible endpoint
            "cohere":   self.call_openai,   # Cohere v2 is also OpenAI-compatible
            "custom":   self.call_openai,
        }
        fn = dispatch_map.get(provider_name, self.call_openai)
        return fn(api_key=decrypted, messages=messages, model=model, params=params, base_url=base_url)

    def call_openai(
        self,
        api_key: str,
        messages: list[dict],
        model: str,
        params: dict,
        base_url: str = "https://api.openai.com/v1",
    ) -> dict:
        """Call the OpenAI (or compatible) chat completions endpoint."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       model,
            "messages":    messages,
            "max_tokens":  params.get("max_tokens", 2048),
            "temperature": params.get("temperature", 0.7),
            "stream":      False,
        }
        if params.get("response_format"):
            payload["response_format"] = params["response_format"]

        with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def call_claude(
        self,
        api_key: str,
        messages: list[dict],
        model: str,
        params: dict,
        base_url: str = "https://api.anthropic.com",
    ) -> dict:
        """Call the Anthropic Messages API."""
        # Separate system message from the conversation
        system_content = ""
        chat_messages  = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        headers = {
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json",
        }
        payload: dict[str, Any] = {
            "model":       model,
            "messages":    chat_messages,
            "max_tokens":  params.get("max_tokens", 2048),
        }
        if system_content:
            payload["system"] = system_content
        if params.get("temperature") is not None:
            payload["temperature"] = params["temperature"]

        with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = client.post(
                f"{base_url.rstrip('/')}/v1/messages",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def call_deepseek(
        self,
        api_key: str,
        messages: list[dict],
        model: str,
        params: dict,
        base_url: str = "https://api.deepseek.com/v1",
    ) -> dict:
        """Call the DeepSeek API (OpenAI-compatible protocol)."""
        return self.call_openai(
            api_key=api_key,
            messages=messages,
            model=model,
            params=params,
            base_url=base_url,
        )

    # ------------------------------------------------------------------
    # Streaming generators
    # ------------------------------------------------------------------

    def _get_stream_function(self, provider_name: str):
        stream_map = {
            "openai":   self._stream_openai,
            "deepseek": self._stream_openai,
            "claude":   self._stream_claude,
            "gemini":   self._stream_openai,
            "cohere":   self._stream_openai,
            "custom":   self._stream_openai,
        }
        return stream_map.get(provider_name, self._stream_openai)

    def _stream_openai(
        self,
        api_key: str,
        messages: list[dict],
        model: str,
        params: dict,
        base_url: str,
    ) -> Generator[dict, None, None]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       model,
            "messages":    messages,
            "max_tokens":  params.get("max_tokens", 2048),
            "temperature": params.get("temperature", 0.7),
            "stream":      True,
        }
        total_tokens = 0
        with httpx.Client(timeout=STREAMING_TIMEOUT_SECONDS) as client:
            with client.stream("POST", f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        try:
                            data  = json.loads(line[6:])
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            text  = delta.get("content", "")
                            if text:
                                yield {"type": "token", "text": text}
                            if data.get("usage"):
                                total_tokens = data["usage"].get("total_tokens", 0)
                        except json.JSONDecodeError:
                            continue
        yield {"type": "usage", "total_tokens": total_tokens}

    def _stream_claude(
        self,
        api_key: str,
        messages: list[dict],
        model: str,
        params: dict,
        base_url: str,
    ) -> Generator[dict, None, None]:
        system_content = ""
        chat_messages  = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        headers = {
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json",
        }
        payload: dict[str, Any] = {
            "model":       model,
            "messages":    chat_messages,
            "max_tokens":  params.get("max_tokens", 2048),
            "stream":      True,
        }
        if system_content:
            payload["system"] = system_content

        input_tokens  = 0
        output_tokens = 0
        with httpx.Client(timeout=STREAMING_TIMEOUT_SECONDS) as client:
            with client.stream("POST", f"{base_url.rstrip('/')}/v1/messages", headers=headers, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or line.startswith("event:"):
                        continue
                    if line.startswith("data: "):
                        try:
                            data       = json.loads(line[6:])
                            event_type = data.get("type", "")
                            if event_type == "content_block_delta":
                                text = data.get("delta", {}).get("text", "")
                                if text:
                                    yield {"type": "token", "text": text}
                            elif event_type == "message_start":
                                usage         = data.get("message", {}).get("usage", {})
                                input_tokens  = usage.get("input_tokens", 0)
                            elif event_type == "message_delta":
                                usage         = data.get("usage", {})
                                output_tokens = usage.get("output_tokens", 0)
                        except json.JSONDecodeError:
                            continue
        yield {"type": "usage", "total_tokens": input_tokens + output_tokens}

    # ------------------------------------------------------------------
    # Credits & billing
    # ------------------------------------------------------------------

    def _calculate_credits(self, service: AIService, total_tokens: int) -> Decimal:
        """
        Calculate credits to charge based on token usage and service pricing.

        Uses a per-token rate derived from the service's ``sell_price_credits``
        and a reference token cost (credits per 1K tokens).
        """
        # sell_price_credits is the base cost for a "standard" 1K-token request.
        # Scale proportionally for the actual token count.
        base_tokens = Decimal("1000")
        tokens      = Decimal(str(max(total_tokens, 1)))
        charged     = (service.sell_price_credits * tokens / base_tokens).quantize(Decimal("0.0001"))
        # Minimum charge = 1 credit
        return max(charged, Decimal("1"))

    def _log_usage(
        self,
        user,
        service: AIService,
        key: Optional[ProviderAPIKey],
        usage_data: dict,
    ) -> AIUsageLog:
        return AIUsageLog.objects.create(
            user=user,
            service=service,
            provider_key=key,
            request_id=usage_data.get("request_id", uuid.uuid4()),
            session_id=usage_data.get("session_id"),
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            credits_charged=usage_data.get("credits_charged", Decimal("0")),
            bdt_cost=usage_data.get("bdt_cost", Decimal("0")),
            profit_bdt=usage_data.get("profit_bdt", Decimal("0")),
            response_time_ms=usage_data.get("response_time_ms", 0),
            status=usage_data.get("status", UsageStatus.SUCCESS),
            error_message=usage_data.get("error_message", ""),
            cached=usage_data.get("cached", False),
            metadata=usage_data.get("metadata", {}),
        )

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _check_cache(self, cache_key: str) -> Optional[dict]:
        """Return a cached response dict, or None on miss."""
        try:
            return cache.get(cache_key)
        except Exception:
            return None

    def _cache_response(self, cache_key: str, response: dict, ttl: int = CACHE_DEFAULT_TTL) -> None:
        """Store a response in cache, stripping the raw provider payload."""
        cacheable = {k: v for k, v in response.items() if k != "_raw"}
        try:
            cache.set(cache_key, cacheable, timeout=ttl)
        except Exception as exc:
            logger.warning("Failed to cache AI response: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_service(self, service_id: str) -> AIService:
        try:
            service = AIService.objects.select_related("provider").get(pk=service_id, is_active=True)
        except AIService.DoesNotExist:
            raise ValueError(f"AI service '{service_id}' not found or inactive.")
        if not service.provider.is_active:
            raise ValueError(f"Provider '{service.provider.display_name}' is currently inactive.")
        return service

    def _get_wallet(self, user) -> Wallet:
        try:
            return Wallet.objects.select_for_update().get(user=user)
        except Wallet.DoesNotExist:
            raise ValueError(f"No wallet found for user {user.id}.")

    def _refund_credits(self, wallet: Wallet, amount: Decimal, request_id: uuid.UUID) -> None:
        """Silently refund credits; log any failure."""
        try:
            from apps.wallet.models import LedgerEntry, EntryType, AccountType, CurrencyType
            from django.db import transaction as _t
            with _t.atomic():
                before = wallet.credit_balance
                after  = before + amount
                LedgerEntry.objects.create(
                    entry_type=EntryType.CREDIT,
                    account_type=AccountType.USER_WALLET,
                    wallet=wallet,
                    amount=amount,
                    currency=CurrencyType.CREDITS,
                    balance_before=before,
                    balance_after=after,
                    description=f"AI refund for request {request_id}",
                    metadata={"request_id": str(request_id)},
                )
                wallet.credit_balance = after
                wallet.save(update_fields=["credit_balance", "updated_at"])
        except Exception as exc:
            logger.error("Credit refund failed for request %s: %s", request_id, exc)

    def _update_conversation(
        self,
        user,
        session_id: str,
        service: AIService,
        messages: list[dict],
        assistant_text: str,
        tokens: int,
        credits: Decimal,
    ) -> None:
        """Persist conversation messages and update aggregate stats."""
        try:
            convo, created = AIConversation.objects.get_or_create(
                session_id=session_id,
                defaults={"user": user, "service": service},
            )
            if created:
                # Auto-title from first user message
                first_user = next((m["content"] for m in messages if m.get("role") == "user"), "")
                convo.auto_set_title(first_user)

            # Persist each new user message
            for msg in messages:
                if msg.get("role") in (MessageRole.USER, MessageRole.SYSTEM):
                    AIMessage.objects.get_or_create(
                        conversation=convo,
                        role=msg["role"],
                        content=msg["content"],
                        defaults={"tokens": 0},
                    )

            # Persist assistant response
            if assistant_text:
                AIMessage.objects.create(
                    conversation=convo,
                    role=MessageRole.ASSISTANT,
                    content=assistant_text,
                    tokens=tokens,
                )

            convo.record_usage(tokens=tokens, credits=credits)

        except Exception as exc:
            logger.error("Failed to update conversation %s: %s", session_id, exc)
