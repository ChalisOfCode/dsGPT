import json

import httpx

from .config import Model

# Local CPU inference can spend several minutes evaluating a long prompt before
# emitting its first streamed byte. Keep this bounded below the Work task limit,
# while avoiding a false runtime failure at the old three-minute HTTP default.
LOCAL_INFERENCE_READ_TIMEOUT = 900


def ollama_input_estimate(messages):
    """Conservative UTF-8 bound shared by context assembly and the inference guard."""
    return 512 + sum(
        len(message["content"].encode("utf-8")) + 64 + 4096 * len(message.get("images", []))
        for message in messages
    )


def runtime_error(payload, fallback="inference_failed"):
    """Classify only runtime error fields; never retain or expose the supplied text."""
    if isinstance(payload, dict):
        payload = payload.get("error", payload.get("message"))
        if isinstance(payload, dict):
            payload = payload.get("message")
    if not isinstance(payload, str):
        return fallback
    text = payload[:8192].lower()
    if any(value in text for value in ("out of memory", "out_of_memory", "insufficient memory")):
        return (
            "gpu_out_of_memory"
            if any(word in text for word in ("cuda", "gpu", "vram", "cublas"))
            else "runtime_out_of_memory"
        )
    if any(value in text for value in ("cuda error", "cuda_error", "cublas_status", "ggml_cuda")):
        return "cuda_error"
    if any(
        value in text
        for value in ("failed to load model", "unable to load model", "error loading model")
    ):
        return "model_load_failed"
    return fallback


async def response_error(response):
    raw = bytearray()
    async for part in response.aiter_bytes():
        raw.extend(part[: 8192 - len(raw)])
        if len(raw) >= 8192:
            break
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw.decode("utf-8", errors="replace")
    return runtime_error(value, "runtime_unavailable")


class InferenceError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class LocalInference:
    """Local-only HTTP; optional ephemeral authentication for an owned runtime."""

    def __init__(self, transport=None, local_token=None, local_socket=None):
        self.transport = transport
        self.local_token = local_token
        self.local_socket = local_socket
        self.resident_ollama = None

    async def release_resident(self):
        previous = self.resident_ollama
        if previous is not None:
            async with self.client(previous) as client:
                await self._json(
                    client,
                    "POST",
                    "/api/generate",
                    json={"model": previous.runtime_model, "keep_alive": 0, "stream": False},
                )
            self.resident_ollama = None

    def client(self, model):
        return httpx.AsyncClient(
            base_url=model.endpoint.rstrip("/"),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=10, read=LOCAL_INFERENCE_READ_TIMEOUT, write=30, pool=10
            ),
            transport=(
                httpx.AsyncHTTPTransport(uds=str(self.local_socket))
                if self.local_socket
                else self.transport
            ),
            headers={"Authorization": "Bearer " + self.local_token} if self.local_token else {},
        )

    async def _json(self, client, method, path, **kwargs):
        response = await client.request(method, path, **kwargs)
        if response.status_code != 200:
            raise InferenceError(await response_error(response))
        return response.json()

    async def validate_local_model(self, client, model):
        if model.runtime == "ollama":
            tags = await self._json(client, "GET", "/api/tags")
            entry = next(
                (x for x in tags.get("models", []) if x.get("name") == model.runtime_model), None
            )
            if not entry or entry.get("size", 0) <= 0 or not entry.get("digest"):
                raise InferenceError("local_model_required")
            info = await self._json(
                client, "POST", "/api/show", json={"model": model.runtime_model}
            )
            if info.get("remote_host") or info.get("remote_model") or not info.get("model_info"):
                raise InferenceError("local_model_required")
            if (
                model.expected_digest
                and entry["digest"].removeprefix("sha256:") != model.expected_digest
            ):
                raise InferenceError("model_digest_changed")
            thinking = info.get("thinking")
            values = thinking.get("values") if isinstance(thinking, dict) else None
            from .generation import controls

            return {
                "thinking_choices": controls(info),
                "digest": entry["digest"].removeprefix("sha256:"),
                "bytes": entry["size"],
                "vision": "vision" in info.get("capabilities", []),
                # Match llama.cpp's answer-first policy. Older Ollama versions expose
                # no thinking metadata but accept the boolean control. Do not request
                # an unsupported off switch from models advertising mandatory thinking.
                "think": None
                if isinstance(values, list) and values and not any(v is False for v in values)
                else False,
            }
        else:
            models = await self._json(client, "GET", "/v1/models")
            if model.runtime_model not in {x["id"] for x in models.get("data", [])}:
                raise InferenceError("local_model_required")
            props = await self._json(client, "GET", "/props")
            context = props.get("default_generation_settings", {}).get("n_ctx")
            if not isinstance(context, int) or context < model.context:
                raise InferenceError("runtime_context_mismatch")
            return {"digest": None, "bytes": None}

    async def prepare(self, client, model, messages):
        local = await self.validate_local_model(client, model)
        image_count = sum(len(m.get("images", [])) for m in messages)
        if image_count and (model.runtime != "ollama" or not local.get("vision")):
            raise InferenceError("local_vision_model_required")
        if model.runtime == "llama.cpp":
            result = await self._json(
                client,
                "POST",
                "/apply-template",
                json={
                    "messages": messages,
                    "add_generation_prompt": True,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            prompt = result["prompt"]
            result = await self._json(
                client, "POST", "/tokenize", json={"content": prompt, "add_special": True}
            )
            tokens = len(result["tokens"])
            budget = {"input_tokens": tokens, "method": "runtime_tokenizer"}
        else:
            # Ollama has no supported tokenizer endpoint. This is deliberately conservative,
            # not advertised as an exact count. 512 tokens reserve the local template.
            tokens = ollama_input_estimate(messages)
            budget = {"input_tokens_upper_estimate": tokens, "method": "utf8_safety_estimate"}
        if tokens + model.output_tokens > model.context:
            raise InferenceError("context_exceeded")
        return budget, local

    async def stream(self, model: Model, messages, response_schema=None):
        try:
            previous = self.resident_ollama
            if previous and (
                model.runtime != "ollama"
                or (model.endpoint, model.runtime_model)
                != (previous.endpoint, previous.runtime_model)
            ):
                await self.release_resident()
            async with self.client(model) as client:
                budget, local = await self.prepare(client, model, messages)
                yield {"kind": "context", "data": budget}
                if model.runtime == "ollama":
                    from .generation import think_value

                    path = "/api/chat"
                    payload = {
                        "model": model.runtime_model,
                        "messages": messages,
                        "stream": True,
                        # Prompt text such as /no_think is not a runtime control.
                        "think": think_value(model.reasoning_effort, local),
                        # Keep repeated agent turns warm; explicitly release our previous
                        # model before switching so dsGPT does not accumulate GPU models.
                        "keep_alive": "5m",
                        "options": {
                            "num_ctx": model.context,
                            "num_predict": model.output_tokens,
                        },
                    }
                else:
                    if model.reasoning_effort not in (None, "auto", "off"):
                        raise InferenceError("thinking_control_unsupported")
                    path = "/v1/chat/completions"
                    payload = {
                        "model": model.runtime_model,
                        "messages": messages,
                        "stream": True,
                        "max_tokens": model.output_tokens,
                        "stream_options": {"include_usage": True},
                        "chat_template_kwargs": {"enable_thinking": False},
                    }
                ended, thinking_chunks = False, 0
                visible_output, output_limited = False, False
                if response_schema:
                    if model.runtime == "ollama":
                        payload["format"] = response_schema
                        payload["options"]["temperature"] = 0
                    else:
                        # Structured tool decisions should not inherit the server's
                        # creative-chat sampling default. Ordinary Chat is unchanged.
                        payload["temperature"] = 0
                        payload["response_format"] = {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "project_action",
                                "strict": True,
                                "schema": response_schema,
                            },
                        }
                async with client.stream("POST", path, json=payload) as response:
                    if response.status_code != 200:
                        raise InferenceError(await response_error(response))
                    if model.runtime == "ollama":
                        self.resident_ollama = model
                    async for line in response.aiter_lines():
                        if not line or line.startswith(":"):
                            continue
                        if model.runtime == "ollama":
                            obj = json.loads(line)
                            if "error" in obj:
                                raise InferenceError(runtime_error(obj))
                            if obj.get("message", {}).get("thinking"):
                                # Count only; never store or forward the reasoning text.
                                thinking_chunks += 1
                            content = obj.get("message", {}).get("content", "")
                            if content:
                                visible_output = visible_output or bool(content.strip())
                                yield {"kind": "delta", "data": {"text": content}}
                            if obj.get("done"):
                                ended = True
                                metrics = {
                                    k: obj[k]
                                    for k in (
                                        "total_duration",
                                        "load_duration",
                                        "eval_count",
                                        "eval_duration",
                                        "prompt_eval_count",
                                        "prompt_eval_duration",
                                    )
                                    if isinstance(obj.get(k), (int, float))
                                }
                                metrics["thinking_chunks"] = thinking_chunks
                                yield {"kind": "metrics", "data": metrics}
                                if obj.get("done_reason") == "length":
                                    output_limited = True
                                    yield {"kind": "warning", "data": {"code": "output_limit"}}
                                break
                        else:
                            if not line.startswith("data: "):
                                continue
                            if line[6:] == "[DONE]":
                                ended = True
                                break
                            obj = json.loads(line[6:])
                            if "error" in obj:
                                raise InferenceError(runtime_error(obj))
                            for choice in obj.get("choices", []):
                                content = choice.get("delta", {}).get("content")
                                if content:
                                    visible_output = visible_output or bool(content.strip())
                                    yield {"kind": "delta", "data": {"text": content}}
                                if choice.get("finish_reason") == "length":
                                    output_limited = True
                                    yield {"kind": "warning", "data": {"code": "output_limit"}}
                            if obj.get("usage"):
                                metrics = {
                                    k: obj["usage"][k]
                                    for k in (
                                        "prompt_tokens",
                                        "completion_tokens",
                                        "total_tokens",
                                    )
                                    if isinstance(obj["usage"].get(k), (int, float))
                                }
                                yield {"kind": "metrics", "data": metrics}
                    if not ended:
                        raise InferenceError("runtime_protocol_error")
                    if not visible_output:
                        raise InferenceError(
                            "output_limit" if output_limited else "empty_model_response"
                        )
        except httpx.HTTPError as exc:
            raise InferenceError("runtime_unavailable") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise InferenceError("runtime_protocol_error") from exc
