"""Run the simulated week against a real model on an OpenAI-compatible endpoint.

Local Ollama (default, no key, no proxy):
    ollama pull qwen3:8b
    python scripts/simulate_week_live.py --model qwen3:8b

Free cloud tiers (key from the provider, mind their rate limits):
    python scripts/simulate_week_live.py --base-url https://openrouter.ai/api/v1 \\
        --model <free-model-id> --api-key-env OPENROUTER_API_KEY --rpm 15

Uses the project's own LLM class (provider "openai"), so bio-throttling and
JSON parsing are exactly what Aura runs with. Only the simulated owner is fake.
The owner is synthetic, so no personal data leaves the machine.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class _Settings:
    """Stand-in for settings_manager: never touches outputs/settings.json."""

    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


def _is_local(base_url: str) -> bool:
    from urllib.parse import urlparse

    return (urlparse(base_url).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}


def probe(base_url: str, api_key: str, timeout: float = 10.0):
    """Return (ok, detail): can the endpoint list its models?"""
    import requests

    session = requests.Session()
    session.trust_env = not _is_local(base_url)
    headers = {"Authorization": f"Bearer {api_key or 'local'}"}
    try:
        response = session.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout)
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"
    finally:
        session.close()
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: {response.text[:200]}"
    try:
        models = [m.get("id") for m in response.json().get("data", [])]
    except ValueError:
        models = []
    return True, models


class _Progress:
    """One stderr line per model call (the harness silences print/logging)."""

    _KINDS = (("open_loops", "trích xuất"), ("CHỦ ĐỘNG nhắn tin", "ping"),
              ("BẢN SẮC HIỆN TẠI", "bản ngã"), ("Aura vừa đọc xong", "đọc sách"))

    def __init__(self, inner):
        self.inner = inner
        self.count = 0

    def _call(self, method, prompt, args, kwargs):
        import time

        self.count += 1
        kind = next((label for marker, label in self._KINDS if marker in str(prompt)), method)
        started = time.monotonic()
        try:
            result = getattr(self.inner, method)(prompt, *args, **kwargs)
            status = "ok"
            return result
        except Exception as error:
            cause = error.__cause__ or error.__context__
            status = f"LỖI {type(error).__name__}" + (f" <- {type(cause).__name__}: {str(cause)[:120]}" if cause else "")
            raise
        finally:
            sys.stderr.write(f"  [{self.count:>3}] {kind:<11} {time.monotonic() - started:6.1f}s {status}\n")
            sys.stderr.flush()

    def generate_json(self, prompt, *args, **kwargs):
        return self._call("generate_json", prompt, args, kwargs)

    def generate_text(self, prompt, *args, **kwargs):
        return self._call("generate_text", prompt, args, kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def make_llm_factory(base_url: str, model: str, api_key: str, rpm: float, retries: int = 1):
    def factory(engine):
        from config import Config
        from components.llm import LLM
        from core.sim_week import RateLimitedLLM

        # The offline Unsloth backend would start loading torch in the background.
        Config.LOCAL_LLM_ENABLED = False
        llm = LLM(ego=engine.ego)
        llm.settings = _Settings({
            "provider": "openai",
            "openai_base_url": base_url,
            "openai_model": model,
            "openai_api_key": api_key,
        })
        # Progress sits inside the limiter so every attempt (retries too) shows.
        # LLM already retries each call 3x; one extra round here is enough.
        return RateLimitedLLM(_Progress(llm), rpm=rpm, retries=retries, backoff_seconds=10.0)

    return factory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.getenv("AURA_OPENAI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="", help="name of the env var holding the key")
    parser.add_argument("--rpm", type=float, default=0.0, help="max calls per minute (0 = unlimited)")
    parser.add_argument("--retries", type=int, default=1, help="extra retries after a 429/timeout")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", help="also write the full report as JSON")
    parser.add_argument("--messages", action="store_true", help="list what Aura said")
    args = parser.parse_args(argv)

    import config  # noqa: F401  (loads the project's .env, which holds the key)

    api_key = os.getenv(args.api_key_env, "") if args.api_key_env else ""
    if not api_key and not _is_local(args.base_url):
        print(f"Thiếu API key: đặt biến môi trường {args.api_key_env or '<--api-key-env>'}.")
        return 2

    ok, detail = probe(args.base_url, api_key)
    if not ok:
        print(f"Không kết nối được tới {args.base_url}: {detail}")
        if _is_local(args.base_url):
            print("Ollama chưa chạy? Cài Ollama, rồi chạy: ollama serve  và  ollama pull " + args.model)
        return 3
    if detail and args.model not in detail:
        print(f"Cảnh báo: endpoint không liệt kê model '{args.model}'. Có: {', '.join(detail[:15])}")

    from core.sim_week import format_report, run_week

    print(f"Chạy {args.days} ngày với {args.model} @ {args.base_url} (rpm={args.rpm or 'không giới hạn'})...")
    report = run_week(
        seed=args.seed,
        days=args.days,
        llm_factory=make_llm_factory(args.base_url, args.model, api_key, args.rpm, args.retries),
    )
    out = sys.stdout
    out.write(format_report(report) + "\n")
    if args.messages:
        out.write("\n")
        for _, stamp, kind, text in report.aura_messages:
            out.write(f"{stamp} [{kind}] {text}\n")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
