"""
Centralized LLM configuration and model factory.
Supports multiple providers (Google, OpenAI, Anthropic) with easy switching.
"""

import os
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Type, Optional, Literal
from dataclasses import dataclass

load_dotenv()


# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    name: str                    # Model name (e.g., "gemini-2.0-flash", "gpt-4o")
    provider: Literal["google", "openai", "anthropic"]
    api_key_env: str             # Environment variable for API key
    

# Available model presets
MODELS = {
    # Google models
    "gemini-flash": ModelConfig(
        name="gemini-2.0-flash",
        provider="google",
        api_key_env="GOOGLE_API_KEY"
    ),
    "gemini-pro": ModelConfig(
        name="gemini-2.5-pro",
        provider="google",
        api_key_env="GOOGLE_API_KEY"
    ),
    
    
    # OpenAI models (uncomment when needed)
    # "gpt-4o": ModelConfig(
    #     name="gpt-4o",
    #     provider="openai",
    #     api_key_env="OPENAI_API_KEY"
    # ),
    # "gpt-4o-mini": ModelConfig(
    #     name="gpt-4o-mini",
    #     provider="openai",
    #     api_key_env="OPENAI_API_KEY"
    # ),
    
    # Anthropic models (uncomment when needed)
    # "claude-sonnet": ModelConfig(
    #     name="claude-3-5-sonnet-20241022",
    #     provider="anthropic",
    #     api_key_env="ANTHROPIC_API_KEY"
    # ),
}


# =============================================================================
# AGENT MODEL ASSIGNMENTS
# =============================================================================

# Assign specific models to each agent based on their needs
AGENT_MODELS = {
    "planner": "gemini-flash", # Smart reasoning for plan creation (1 call)
    "decision": "gemini-flash", # Routing decisions (N calls) - could use cheaper
    "executor": "gemini-flash", # Translating tasks to actions
    "verifier": "gemini-flash", # Checking results - could use cheaper
    "fallback": "gemini-flash", # Creative recovery strategies
    "interaction": "gemini-flash", # User-facing polish
}

# Temperature presets for different agent behaviors
TEMPERATURES = {
    "planner": 0.3,
    "decision": 0.2,
    "executor": 0.2,
    "verifier": 0.3,
    "fallback": 0.4,
    "interaction": 0.5,
}


# To get the appropriate LLM class for the provider
def _get_llm_class(provider: str):
    """Get the appropriate LLM class for the provider."""
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic
    else:
        raise ValueError(f"Unknown provider: {provider}")


def get_llm(
    schema: Optional[Type[BaseModel]] = None,
    temperature: float = 0.3,
    model_key: str = "gemini-flash",
):
    """
    Factory function to create configured LLM instances.
    
    Args:
        schema: Pydantic model for structured output (optional)
        temperature: Creativity level (0.0 = deterministic, 1.0 = creative)
        model_key: Key from MODELS dict (e.g., "gemini-flash", "gpt-4o")
    
    Returns:
        Configured LLM instance
    """
    config = MODELS[model_key]
    api_key = os.getenv(config.api_key_env)
    
    if not api_key:
        raise ValueError(f"API key not found. Set {config.api_key_env} in your .env file.")
    
    LLMClass = _get_llm_class(config.provider)
    
    llm = LLMClass(
        model=config.name,
        temperature=temperature,
        api_key=api_key,
    )
    
    if schema:
        return llm.with_structured_output(schema)
    return llm


# For each of the models

class Models:
    """
    Model instances for each agent type.
    Each agent can use a different model based on AGENT_MODELS config.
    """
    
    @staticmethod
    def planner(schema: Type[BaseModel]):
        """Model for creating multi-step plans."""
        return get_llm(
            schema=schema, 
            temperature=TEMPERATURES["planner"],
            model_key=AGENT_MODELS["planner"]
        )
    
    @staticmethod
    def decision_maker(schema: Type[BaseModel]):
        """Model for deciding next actions."""
        return get_llm(
            schema=schema, 
            temperature=TEMPERATURES["decision"],
            model_key=AGENT_MODELS["decision"]
        )
    
    @staticmethod
    def executor(schema: Type[BaseModel]):
        """Model for translating tasks to browser actions."""
        return get_llm(
            schema=schema, 
            temperature=TEMPERATURES["executor"],
            model_key=AGENT_MODELS["executor"]
        )
    
    @staticmethod
    def verifier(schema: Type[BaseModel]):
        """Model for checking if actions succeeded."""
        return get_llm(
            schema=schema, 
            temperature=TEMPERATURES["verifier"],
            model_key=AGENT_MODELS["verifier"]
        )
    
    @staticmethod
    def fallback(schema: Type[BaseModel]):
        """Model for generating recovery strategies."""
        return get_llm(
            schema=schema, 
            temperature=TEMPERATURES["fallback"],
            model_key=AGENT_MODELS["fallback"]
        )
    
    @staticmethod
    def interaction(schema: Type[BaseModel]):
        """Model for user-facing responses."""
        return get_llm(
            schema=schema, 
            temperature=TEMPERATURES["interaction"],
            model_key=AGENT_MODELS["interaction"]
        )


# Utils

def list_available_models():
    """Print all available model configurations."""
    print("Available Models:")
    print("-" * 50)
    for key, config in MODELS.items():
        print(f"  {key}")
        print(f"    Provider: {config.provider}")
        print(f"    Model: {config.name}")
        print(f"    API Key: {config.api_key_env}")
        print()


def show_agent_assignments():
    """Print current model assignments per agent."""
    print("Agent Model Assignments:")
    print("-" * 50)
    for agent, model_key in AGENT_MODELS.items():
        config = MODELS[model_key]
        temp = TEMPERATURES[agent]
        print(f"  {agent}:")
        print(f"    Model: {config.name} ({model_key})")
        print(f"    Temperature: {temp}")
        print()
