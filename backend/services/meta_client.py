"""Thin wrappers over the Meta Model API's OpenAI-compatible endpoints."""

import base64
import json
from functools import lru_cache
from pathlib import Path

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import config

_RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
_retry = retry(retry=retry_if_exception_type(_RETRYABLE), wait=wait_exponential(min=2, max=20),
               stop=stop_after_attempt(4), reraise=True)


@lru_cache(maxsize=1)
def client() -> OpenAI:
    if not config.META_API_KEY:
        raise RuntimeError("META_API_KEY is not set in .env")
    return OpenAI(base_url=config.META_BASE_URL, api_key=config.META_API_KEY, timeout=180, max_retries=0)


def image_part(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


@_retry
def spark_json(system: str, content: list[dict] | str, schema_name: str, schema: dict) -> dict:
    """Call Muse Spark with a JSON schema response format and return the parsed object."""
    resp = client().chat.completions.create(
        model=config.SPARK_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
    )
    text = resp.choices[0].message.content or ""
    # Tolerate a fenced reply even though the schema should prevent one.
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


@_retry
def muse_image(prompt: str, out_path: Path) -> Path:
    resp = client().images.generate(model=config.IMAGE_MODEL, prompt=prompt, n=1)
    data = base64.b64decode(resp.data[0].b64_json)
    ext = ".webp" if data[8:12] == b"WEBP" else ".jpg" if data[:2] == b"\xff\xd8" else ".png"
    out_path = out_path.with_suffix(ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path
