"""Read the user's one local configuration file without exposing its contents."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    provider: str
    protocol: str
    base_url: str
    api_key: str = field(repr=False)
    model: str
    figma_token: str = field(repr=False)
    figma_mode: str
    figma_bridge_client: Path
    runtime_dir: Path
    model_request_limit: int
    repair_limit: int
    auto_retry_limit: int
    provider_timeout: int
    token_limit: Optional[int]
    cost_limit_micro_usd: Optional[int]
    web_host: str
    web_port: int
    backend_host: str
    backend_port: int
    preview_host: str
    preview_port_start: int
    preview_port_end: int
    build_timeout: int
    issues: tuple[str, ...]

    @property
    def model_ready(self) -> bool:
        return not self.issues


def _integer(values: dict[str, Optional[str]], key: str, default: int,
             issues: list[str], minimum: int = 1) -> int:
    raw = values.get(key)
    try:
        number = default if raw in (None, "") else int(raw)
        if number < minimum:
            raise ValueError
        return number
    except (TypeError, ValueError):
        issues.append(f"{key} 必须是不小于 {minimum} 的整数")
        return default


def _optional_integer(values: dict[str, Optional[str]], key: str,
                      issues: list[str]) -> Optional[int]:
    if not values.get(key):
        return None
    return _integer(values, key, 1, issues)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    values = dict(dotenv_values(ENV_FILE, interpolate=False)) if ENV_FILE.is_file() else {}
    issues: list[str] = []
    if not ENV_FILE.is_file():
        issues.append("根目录 .env 不存在")
    provider = (values.get("D2C_PROVIDER") or "openai").strip()
    protocol = (values.get("D2C_API_PROTOCOL") or "openai_responses").strip()
    base_url = (values.get("OPENAI_BASE_URL") or "").strip().rstrip("/")
    api_key = (values.get("OPENAI_API_KEY") or "").strip()
    model = (values.get("D2C_MODEL") or "").strip()
    if provider != "openai":
        issues.append("D2C_PROVIDER 必须为 openai")
    if protocol not in {"openai_responses", "openai_chat_completions"}:
        issues.append("D2C_API_PROTOCOL 不受支持")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc or parsed_url.query or parsed_url.fragment:
        issues.append("OPENAI_BASE_URL 必须是有效的 API 基础地址")
    if not api_key:
        issues.append("OPENAI_API_KEY 未填写")
    if model != "openai/gpt-6-luna":
        issues.append("D2C_MODEL 必须为 openai/gpt-6-luna")
    requests = _integer(values, "D2C_MODEL_REQUEST_LIMIT", 2, issues)
    repairs = _integer(values, "D2C_REPAIR_LIMIT", 1, issues, 0)
    retries = _integer(values, "D2C_AUTO_RETRY_LIMIT", 0, issues, 0)
    if requests > 2 or repairs > 1 or retries != 0:
        issues.append("请求上限不得超过 2 次，修复不得超过 1 次，自动重试必须为 0")
    runtime_path = Path(values.get("D2C_RUNTIME_DIR") or "./runtime").expanduser()
    runtime_dir = (runtime_path if runtime_path.is_absolute() else PROJECT_ROOT / runtime_path).resolve()
    figma_mode = (values.get("D2C_FIGMA_MODE") or "rest").strip().lower()
    if figma_mode not in {"rest", "mcp"}:
        issues.append("D2C_FIGMA_MODE 必须为 rest 或 mcp")
    return Settings(
        provider=provider, protocol=protocol, base_url=base_url, api_key=api_key,
        model=model, figma_token=(values.get("FIGMA_ACCESS_TOKEN") or "").strip(),
        figma_mode=figma_mode,
        figma_bridge_client=(PROJECT_ROOT / "figma-mcp-bridge" / "server" / "bridge-client.mjs").resolve(),
        runtime_dir=runtime_dir, model_request_limit=requests, repair_limit=repairs,
        auto_retry_limit=retries,
        provider_timeout=_integer(values, "D2C_PROVIDER_TIMEOUT_SECONDS", 180, issues),
        token_limit=_optional_integer(values, "D2C_TOKEN_LIMIT", issues),
        cost_limit_micro_usd=_optional_integer(values, "D2C_COST_LIMIT_MICRO_USD", issues),
        web_host=(values.get("D2C_WEB_HOST") or "127.0.0.1").strip(),
        web_port=_integer(values, "D2C_WEB_PORT", 5173, issues),
        backend_host=(values.get("D2C_BACKEND_HOST") or "127.0.0.1").strip(),
        backend_port=_integer(values, "D2C_BACKEND_PORT", 7001, issues),
        preview_host=(values.get("D2C_PREVIEW_HOST") or "127.0.0.1").strip(),
        preview_port_start=_integer(values, "D2C_PREVIEW_PORT_START", 7100, issues),
        preview_port_end=_integer(values, "D2C_PREVIEW_PORT_END", 7199, issues),
        build_timeout=_integer(values, "D2C_BUILD_TIMEOUT_SECONDS", 120, issues),
        issues=tuple(issues),
    )
