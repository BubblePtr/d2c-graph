from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from d2c_graph.config import AppConfig, ModelConfig


def _create_model(config: ModelConfig):
    if config.provider == "openai_compatible":
        return ChatOpenAI(
            model=config.model,
            api_key=config.api_key(),
            base_url=config.base_url,
            temperature=0,
        )
    return ChatGoogleGenerativeAI(
        model=config.model,
        google_api_key=config.api_key(),
        temperature=0,
    )


def create_vision_model(config: AppConfig):
    return _create_model(config.models.vision)


def create_text_model(config: AppConfig):
    return _create_model(config.models.text)
