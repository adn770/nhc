"""LLM backend abstraction.

Provides a uniform interface for multiple LLM providers: Ollama, MLX,
Anthropic, or none (narrative disabled). Follows the same pattern as MDT.
"""

import abc
from typing import Any, Generator


class LLMBackend(abc.ABC):
    """Abstract base class for LLM providers."""

    @abc.abstractmethod
    def generate_stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[str, None, None]:
        """Generate a streaming response from the model.

        Yields chunks of text.
        """

    def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """Non-streaming convenience wrapper."""
        return "".join(self.generate_stream(messages, tools))


class OllamaBackend(LLMBackend):
    """Ollama API backend."""

    def __init__(self, url: str, model: str, options: dict[str, Any]) -> None:
        import ollama
        self.client = ollama.Client(host=url)
        self.model = model
        self.options = options

    def generate_stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[str, None, None]:
        response = self.client.chat(
            model=self.model,
            messages=messages,
            stream=True,
            options=self.options,
            tools=tools,
        )
        for chunk in response:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content


class MLXBackend(LLMBackend):
    """MLX (Apple Silicon local models) backend."""

    def __init__(self, model_path: str, options: dict[str, Any]) -> None:
        from mlx_lm import load
        self.model, self.tokenizer = load(model_path)
        self.model_path = model_path
        self.options = options

    def generate_stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[str, None, None]:
        from mlx_lm import stream_generate

        if hasattr(self.tokenizer, "apply_chat_template"):
            prompt = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
        else:
            prompt = "\n".join(
                f"{m['role']}: {m['content']}" for m in messages
            )

        for token in stream_generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=self.options.get("num_predict", 2048),
            temp=self.options.get("temperature", 0.1),
        ):
            yield token


class AnthropicBackend(LLMBackend):
    """Anthropic Claude API backend."""

    def __init__(self, api_key: str, model: str, options: dict[str, Any]) -> None:
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.options = options

    def generate_stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[str, None, None]:
        # Separate system message from conversation
        system = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                chat_messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": self.options.get("num_predict", 2048),
            "temperature": self.options.get("temperature", 0.1),
        }
        if system:
            kwargs["system"] = system

        with self.client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text


def create_backend(config: dict[str, Any]) -> LLMBackend | None:
    """Factory: create an LLM backend from merged config.

    Returns None if provider is 'none' (narrative disabled).
    """
    provider = config.get("provider", "none")
    model = config.get("model", "")
    temp = float(config.get("temp", 0.1))
    ctx = int(config.get("ctx", 16384))

    if provider == "none":
        return None

    if provider == "ollama":
        url = config.get("url", "http://localhost:11434")
        options = {
            "temperature": temp,
            "num_ctx": ctx,
            "num_predict": 2048,
        }
        return OllamaBackend(url=url, model=model, options=options)

    if provider == "mlx":
        options = {
            "temperature": temp,
            "num_predict": 2048,
        }
        return MLXBackend(model_path=model, options=options)

    if provider == "anthropic":
        api_key = config.get("api_key", "")
        if not api_key:
            raise ValueError("Anthropic provider requires --api-key")
        options = {
            "temperature": temp,
            "num_predict": 2048,
        }
        return AnthropicBackend(api_key=api_key, model=model, options=options)

    raise ValueError(f"Unknown LLM provider: {provider}")
