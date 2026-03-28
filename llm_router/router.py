from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from utils.text import extract_keywords, split_sentences


class ProviderError(RuntimeError):
    pass


class RateLimitError(ProviderError):
    pass


@dataclass
class ProviderState:
    name: str
    cooldown_until: float = 0.0
    failures: int = 0

    def available(self) -> bool:
        return time.time() >= self.cooldown_until


class BaseProvider:
    def __init__(self, config):
        self.config = config
        self.state = ProviderState(self.__class__.__name__)

    def available(self) -> bool:
        return self.state.available()

    def cooldown(self, seconds: int = 60) -> None:
        self.state.cooldown_until = time.time() + seconds

    def generate(self, prompt: str, task_type: str) -> str:
        raise NotImplementedError


class GeminiProvider(BaseProvider):
    def generate(self, prompt: str, task_type: str, timeout_seconds: int = 90) -> str:
        if not self.config.gemini_api_key:
            raise ProviderError("Gemini API key missing")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.gemini_model}:generateContent?key={self.config.gemini_api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 1400},
        }
        response = requests.post(url, json=payload, timeout=timeout_seconds)
        if response.status_code == 429:
            raise RateLimitError("Gemini rate limited")
        if response.status_code >= 400:
            raise ProviderError(f"Gemini error {response.status_code}: {response.text[:300]}")
        data = response.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise ProviderError("Gemini returned empty text")
        return text


class OpenRouterProvider(BaseProvider):
    def __init__(self, config, api_key_attr: str = "openrouter_api_key", provider_name: str = "OpenRouter"):
        super().__init__(config)
        self.api_key_attr = api_key_attr
        self.provider_name = provider_name

    def _api_key(self) -> str:
        return getattr(self.config, self.api_key_attr, "")

    def generate(self, prompt: str, task_type: str, timeout_seconds: int = 90) -> str:
        api_key = self._api_key()
        if not api_key:
            raise ProviderError(f"{self.provider_name} API key missing")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.openrouter_model,
            "messages": [
                {"role": "system", "content": f"You are ViralForge AI for {task_type}."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.75,
        }
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
        if response.status_code == 429:
            raise RateLimitError(f"{self.provider_name} rate limited")
        if response.status_code >= 400:
            raise ProviderError(f"{self.provider_name} error {response.status_code}: {response.text[:300]}")
        data = response.json()
        text = data["choices"][0]["message"]["content"].strip()
        if not text:
            raise ProviderError(f"{self.provider_name} returned empty text")
        return text


class LocalProvider(BaseProvider):
    def generate(self, prompt: str, task_type: str, timeout_seconds: int = 90) -> str:
        keywords = ", ".join(extract_keywords(prompt, limit=6))
        sentences = split_sentences(prompt)
        hook = sentences[0] if sentences else prompt[:160]
        templates = {
            "research": (
                f"Trend brief:\n"
                f"- Hook: {hook}\n"
                f"- Signals: {keywords}\n"
                f"- Angle: use a curious, practical, human tone.\n"
                f"- Next action: turn the strongest trend into a short-form story."
            ),
            "script": (
                f"Hey, you won't believe this...\n\n"
                f"{hook}\n\n"
                f"Why it works: {keywords}.\n"
                f"Call to action: ask the audience a sharp question.\n"
                f"Close with a punchy one-line takeaway."
            ),
            "video": "Build a vertical 9:16 montage with fast pacing, bold captions, and a clear voiceover.",
            "optimize": "Try 3 hooks, use emotional language, and lead with the strongest benefit in the first 2 seconds.",
            "post": "Write a caption that sounds conversational, includes 3-5 hashtags, and ends with a question.",
            "analytics": "Summarize performance, compare against prior winners, and list one specific improvement.",
            "monetization": "Use the strongest audience intent to suggest an affiliate offer and a sponsorship angle.",
        }
        return templates.get(task_type, f"Local draft for {task_type}:\n{prompt}")


class LLMRouter:
    def __init__(self, config, memory=None, logger=None):
        self.config = config
        self.memory = memory
        self.logger = logger
        providers = [
            GeminiProvider(config),
            OpenRouterProvider(config, "openrouter_api_key", "OpenRouter Primary"),
            LocalProvider(config),
        ]
        if getattr(config, "openrouter_api_key_2", ""):
            providers.insert(2, OpenRouterProvider(config, "openrouter_api_key_2", "OpenRouter Backup"))
        self.providers = providers

    def generate_text(self, prompt: str, task_type: str = "general") -> str:
        context = ""
        if self.memory:
            try:
                context_items = self.memory.retrieve_relevant_context(prompt, limit=3)
                if context_items:
                    context = "\n".join(f"- {item['document']}" for item in context_items)
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Memory lookup failed: %s", exc)
        merged_prompt = prompt if not context else f"{prompt}\n\nRelevant memory:\n{context}"

        errors: list[str] = []
        for provider in self.providers:
            if not provider.available():
                continue
            try:
                text = provider.generate(merged_prompt, task_type)
                if self.memory:
                    self.memory.save_memory(
                        kind="llm_output",
                        content=text,
                        metadata={"task_type": task_type, "provider": provider.__class__.__name__},
                    )
                return text
            except RateLimitError as exc:
                provider.cooldown(90)
                errors.append(str(exc))
                continue
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            except Exception as exc:
                errors.append(f"Unexpected: {exc}")
                continue
        fallback = LocalProvider(self.config).generate(merged_prompt, task_type)
        if self.logger:
            self.logger.info("LLMRouter fallback used. Errors: %s", "; ".join(errors))
        return fallback

    def recommended_provider(self) -> dict[str, str]:
        for provider in self.providers:
            provider_name = getattr(provider, "provider_name", provider.__class__.__name__)
            if isinstance(provider, LocalProvider):
                continue
            if not provider.available():
                continue
            try:
                connected = provider.generate("Reply with ping.", "general", timeout_seconds=10)
                if connected:
                    return {
                        "provider": provider_name,
                        "model": getattr(self.config, "gemini_model", "") if provider_name == "GeminiProvider" else getattr(self.config, "openrouter_model", ""),
                        "status": "connected",
                        "message": "Healthy and responding.",
                    }
            except Exception as exc:
                if self.logger:
                    self.logger.debug("Provider recommendation probe failed for %s: %s", provider_name, exc)
                continue
        return {
            "provider": "LocalProvider",
            "model": "local",
            "status": "fallback",
            "message": "No cloud provider responded, using local fallback.",
        }

    def health_report(self, probe_prompt: str = "Reply with ping.", task_type: str = "general", timeout_seconds: int = 20) -> list[dict[str, str | bool]]:
        report: list[dict[str, str | bool]] = []
        for provider in self.providers:
            provider_name = getattr(provider, "provider_name", provider.__class__.__name__)
            model = getattr(self.config, "gemini_model", "") if provider_name == "GeminiProvider" else getattr(self.config, "openrouter_model", "") if "OpenRouter" in provider_name else "local"
            item = {
                "provider": provider_name,
                "model": model,
                "available": provider.available(),
                "connected": False,
                "status": "unknown",
                "message": "",
            }
            if isinstance(provider, LocalProvider):
                item["connected"] = True
                item["status"] = "local"
                item["message"] = "Local fallback is always available."
                report.append(item)
                continue
            if not provider.available():
                item["status"] = "cooldown"
                item["message"] = "Provider is in cooldown."
                report.append(item)
                continue
            try:
                provider.generate(probe_prompt, task_type, timeout_seconds=timeout_seconds)
                item["connected"] = True
                item["status"] = "ok"
                item["message"] = "Connected."
            except RateLimitError as exc:
                provider.cooldown(90)
                item["status"] = "rate_limited"
                item["message"] = str(exc)
            except ProviderError as exc:
                item["status"] = "error"
                item["message"] = str(exc)
            except Exception as exc:
                item["status"] = "error"
                item["message"] = f"Unexpected: {exc}"
            report.append(item)
        return report
