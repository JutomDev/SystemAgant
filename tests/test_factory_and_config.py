"""Unit tests for configuration and simulation LLM factory."""

from core import __version__
from core.config import AppConfig, get_config
from core.llm_factory import get_architect_llms, get_coder_llm
from core.models import ArchitectOutput


def test_package_version():
    assert __version__ == "0.2.1"


def test_app_config_defaults():
    config = get_config()
    assert config.mode in ["simulation", "gemini-free", "vertex"]
    assert config.web_port > 0


def test_simulation_architect_wbs_generation():
    config = AppConfig(mode="simulation")
    models = get_architect_llms(config)
    planner = models["planner"]

    structured_planner = planner.with_structured_output(ArchitectOutput)
    result = structured_planner.invoke([])

    assert isinstance(result, ArchitectOutput)
    assert len(result.response) > 0
    assert result.wbs is not None
    assert len(result.wbs) > 0
    assert len(result.wbs[0].tasks) > 0


def test_simulation_coder_tool_calls():
    config = AppConfig(mode="simulation")
    coder = get_coder_llm(config)

    # Bind dummy tool list
    tools = []
    runnable = coder.bind_tools(tools)
    response = runnable.invoke([])

    assert hasattr(response, "tool_calls")
    assert len(response.tool_calls) > 0
    assert "name" in response.tool_calls[0]
