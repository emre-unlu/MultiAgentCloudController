from __future__ import annotations

import os
from typing import Optional, Type, TypeVar

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMClientError(RuntimeError):
    """Raised when the LLM client cannot be created or invoked."""


class LLMClient:
    """Small wrapper around the chat model used by the agent system.

    Responsibilities:
    - initialize the configured LLM once
    - expose a structured-output helper for Pydantic schemas
    - keep model selection and API wiring out of runner code

    Current implementation assumes OpenAI-compatible usage through LangChain.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        temperature: float = 0.0,
    ) -> None:
        self.model_name = model or os.getenv("OPENAI_MODEL", "gpt-5-mini")
        self.temperature = temperature
        self._model = self._build_model()

    def _build_model(self):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise LLMClientError(
                "OPENAI_API_KEY is not set. Add it to your environment or .env file before using the LLM client."
            )

        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:  # pragma: no cover - dependency guard
            raise LLMClientError(
                "langchain_openai is not installed or could not be imported."
            ) from exc

        kwargs = {
            "model": self.model_name,
            "temperature": self.temperature,
            "api_key": api_key,
        }

        project_id = os.getenv("OPENAI_PROJECT_ID", "")
        if project_id:
            kwargs["project"] = project_id

        return ChatOpenAI(**kwargs)

    @property
    def model(self):
        return self._model

    def invoke_text(self, prompt: str) -> str:
        """Return plain text output from the configured model."""

        try:
            response = self._model.invoke(prompt)
        except Exception as exc:
            raise LLMClientError(f"LLM text invocation failed: {exc}") from exc

        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(item) for item in content)
        return str(content)

    def invoke_structured(self, prompt: str, schema: Type[SchemaT]) -> SchemaT:
        """Return structured output parsed into the requested Pydantic schema."""

        try:
            structured_model = self._model.with_structured_output(schema,method="function_calling",)
            result = structured_model.invoke(prompt)
        except Exception as exc:
            raise LLMClientError(
                f"LLM structured invocation failed for schema {schema.__name__}: {exc}"
            ) from exc

        if isinstance(result, schema):
            return result

        if isinstance(result, BaseModel):
            return schema.model_validate(result.model_dump())

        return schema.model_validate(result)


_default_client: Optional[LLMClient] = None



def get_llm_client() -> LLMClient:
    """Return a lazily created shared LLM client instance."""

    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
