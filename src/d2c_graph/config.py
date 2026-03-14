from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator


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


class McpTransportConfig(BaseModel):
    transport: str | None = Field(default=None, validation_alias=AliasChoices("transport", "type"))
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    protocol_version: str = "2024-11-05"
    startup_timeout_seconds: int = 20
    request_timeout_seconds: int = 180

    @model_validator(mode="after")
    def validate_transport(self) -> "McpTransportConfig":
        if self.transport is None:
            if self.command and self.url:
                raise ValueError("MCP config is ambiguous: set transport when both command and url are provided")
            if self.url:
                self.transport = "http"
            elif self.command:
                self.transport = "stdio"
            else:
                raise ValueError("MCP config requires either command or url")
        return self

    def require_command_for_stdio(self) -> None:
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP transport requires command")

    def require_url_for_remote(self) -> None:
        if self.transport in {"sse", "http"} and not self.url:
            raise ValueError(f"{self.transport} MCP transport requires url")


class D2CMcpConfig(McpTransportConfig):
    tool_name: str
    figma_arg_name: str = "figma_url"
    extra_tool_args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_d2c_transport(self) -> "D2CMcpConfig":
        self.require_command_for_stdio()
        self.require_url_for_remote()
        if self.transport not in {"stdio", "sse"}:
            raise ValueError("d2c_mcp transport must be stdio or sse")
        return self


class FigmaMcpConfig(McpTransportConfig):
    tool_name: str = "get_screenshot"
    file_key_arg_name: str = "fileKey"
    node_id_arg_name: str = "nodeId"

    @model_validator(mode="after")
    def validate_figma_transport(self) -> "FigmaMcpConfig":
        self.require_command_for_stdio()
        self.require_url_for_remote()
        if self.transport not in {"stdio", "sse", "http"}:
            raise ValueError("figma_mcp transport must be stdio, sse, or http")
        return self


class BuildCommandConfig(BaseModel):
    command: str


class BuildConfig(BaseModel):
    react: BuildCommandConfig
    kmp: BuildCommandConfig


class ReactScaffoldConfig(BaseModel):
    command: str

    @model_validator(mode="after")
    def validate_target_placeholder(self) -> "ReactScaffoldConfig":
        if "{target}" not in self.command:
            raise ValueError("scaffold.react.command must include {target}")
        return self


class KmpScaffoldConfig(BaseModel):
    git_url: str
    branch: str | None = None


class ScaffoldConfig(BaseModel):
    react: ReactScaffoldConfig
    kmp: KmpScaffoldConfig


class AppConfig(BaseModel):
    models: ModelGroup
    figma_mcp: FigmaMcpConfig
    d2c_mcp: D2CMcpConfig
    scaffold: ScaffoldConfig
    build: BuildConfig

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(payload)
