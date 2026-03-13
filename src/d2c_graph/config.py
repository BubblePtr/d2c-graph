from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


Provider = Literal["openai_compatible", "gemini"]


class ModelConfig(BaseModel):
    provider: Provider
    model: str
    api_key_env: str
    base_url: str | None = None

    @model_validator(mode="after")
    def validate_provider_fields(self) -> "ModelConfig":
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("openai_compatible provider requires base_url")
        if self.provider == "gemini" and self.base_url:
            raise ValueError("gemini provider does not use base_url")
        return self

    def api_key(self) -> str:
        value = os.getenv(self.api_key_env)
        if not value:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return value


class ModelGroup(BaseModel):
    vision: ModelConfig
    text: ModelConfig


class D2CMcpConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    tool_name: str
    figma_arg_name: str = "figma_url"
    extra_tool_args: dict[str, Any] = Field(default_factory=dict)
    protocol_version: str = "2024-11-05"
    startup_timeout_seconds: int = 20
    request_timeout_seconds: int = 180


class BuildCommandConfig(BaseModel):
    command: str


class BuildConfig(BaseModel):
    react: BuildCommandConfig
    kmp: BuildCommandConfig


class AppConfig(BaseModel):
    models: ModelGroup
    d2c_mcp: D2CMcpConfig
    build: BuildConfig

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(payload)
