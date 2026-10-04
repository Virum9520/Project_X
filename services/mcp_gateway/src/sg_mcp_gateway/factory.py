"""Wire the gateway and assistant from `Settings` (no live provider is contacted here)."""

from sg_core.identity import AuditSink
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.providers.llm import llm_client_from_settings
from sg_core.settings import Settings
from sg_mcp_gateway.assistant import ChatModel, OwnerAssistant
from sg_mcp_gateway.budget import AssistantBudget, DbAssistantBudget
from sg_mcp_gateway.gateway import McpGateway
from sg_mcp_gateway.mcp_client import HttpMcpClient
from sg_mcp_gateway.policy import GatewayLimits


def limits_from_settings(settings: Settings) -> GatewayLimits:
    return GatewayLimits(
        max_rows=settings.owner_assistant_max_rows,
        max_tool_bytes=settings.owner_assistant_max_tool_bytes,
        tool_timeout_seconds=settings.owner_assistant_tool_timeout_seconds,
        max_concurrent_queries=settings.owner_assistant_max_concurrent_queries,
        max_tool_calls=settings.owner_assistant_max_tool_calls,
        max_steps=settings.owner_assistant_max_steps,
        max_output_tokens=settings.owner_assistant_max_output_tokens,
    )


def gateway_from_settings(settings: Settings, audit: AuditSink) -> McpGateway:
    limits = limits_from_settings(settings)
    timeout = limits.tool_timeout_seconds
    el = (
        HttpMcpClient(
            settings.elevenlabs_mcp_url, settings.elevenlabs_mcp_access_token, timeout=timeout
        )
        if settings.elevenlabs_mcp_url
        else None
    )
    tiger = (
        HttpMcpClient(settings.tiger_mcp_url, settings.tiger_mcp_token, timeout=timeout)
        if settings.tiger_mcp_url
        else None
    )
    return McpGateway(
        audit=audit,
        limits=limits,
        elevenlabs=el,
        tiger=tiger,
        tiger_service_id=settings.tiger_mcp_service_id or None,
    )


def build_assistant(
    settings: Settings,
    audit: AuditSink,
    *,
    llm: ChatModel | None = None,
    budget: AssistantBudget | None = None,
) -> OwnerAssistant:
    """Raises `ProviderNotConfiguredError` when no model key is set (and no `llm` is injected)."""
    if llm is None:
        if settings.openrouter_api_key is None:
            raise ProviderNotConfiguredError("OPENROUTER_API_KEY is not configured")
        llm = llm_client_from_settings()
    return OwnerAssistant(
        llm=llm,
        gateway=gateway_from_settings(settings, audit),
        budget=budget or DbAssistantBudget(settings),
        model=settings.owner_assistant_model or None,
        turn_hold_usd=settings.owner_assistant_turn_hold_usd,
    )
