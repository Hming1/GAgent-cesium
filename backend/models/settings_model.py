from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class GeoServerBackend(BaseModel):
    url: str = Field(..., description="GeoServer 服务端点 URL")
    name: Optional[str] = Field(None, description="该后端的可读名称")
    description: Optional[str] = Field(None, description="可选说明 / 用途备注")
    username: Optional[str] = Field(None, description="Basic 认证用户名")
    password: Optional[str] = Field(None, description="Basic 认证密码")
    enabled: bool = Field(True, description="是否启用该后端")
    allow_insecure: bool = Field(
        False,
        description=(
            "允许不安全连接（例如过期或自签名 SSL 证书）。"
            "警告：仅应在受信任的开发环境服务器上启用。"
        ),
    )


class MCPServer(BaseModel):
    url: str = Field(..., description="MCP 服务端点 URL")
    name: Optional[str] = Field(None, description="该 MCP 服务的可读名称")
    description: Optional[str] = Field(
        None, description="可选的工具/能力说明"
    )
    enabled: bool = Field(True, description="是否启用该 MCP 服务")
    api_key: Optional[str] = Field(
        None,
        description="认证用 API Key（如 Bearer Token、API Key）",
    )
    headers: Optional[Dict[str, str]] = Field(
        None,
        description="额外的 HTTP 认证请求头（例如 {'X-API-Key': 'xxx'}）",
    )


class SearchPortal(BaseModel):
    url: str = Field(..., description="地理数据门户 URL")
    enabled: bool = Field(True, description="是否启用该门户")


class ModelSettings(BaseModel):
    model_provider: str = Field(..., description="模型提供商名称，例如 openai、google")
    model_name: str = Field(..., description="模型标识，例如 gpt-4")
    max_tokens: int = Field(..., ge=1, description="最大生成 token 数")
    system_prompt: str = Field("", description="系统提示词覆盖")
    message_window_size: Optional[int] = Field(
        None,
        ge=0,
        description=(
            "上下文中保留的最近消息条数上限。"
            "为 None 时使用环境变量 MESSAGE_WINDOW_SIZE（默认 20）。"
            "设为 0 可禁用裁剪。"
        ),
    )
    enable_parallel_tools: bool = Field(
        False,
        description=(
            "启用并行工具执行以加快多工具查询。"
            "实验性：并发更新可能导致状态损坏。"
            "仅在模型支持并行工具调用时生效。"
        ),
    )
    enable_performance_metrics: bool = Field(
        True,
        description=(
            "启用性能指标采集与存储。"
            "开启后会跟踪耗时、token 用量与工具性能。"
            "可通过 /metrics 端点查看。"
        ),
    )
    enable_agent_audit: bool = Field(
        True,
        description=(
            "持久化智能体运行的输入、输出、工具事件、最终状态与指标，"
            "用于流程评估与运维审计。"
        ),
    )
    agent_audit_level: str = Field(
        "tool",
        description=(
            "智能体审计明细级别：'summary' 仅保存请求/最终结果，"
            "'tool' 额外保存工具事件，'full' 包含 LLM 回调细节。"
        ),
    )
    enable_dynamic_tools: bool = Field(
        True,
        description=(
            "基于查询分析启用动态工具选择。"
            "开启后仅按查询加载相关工具，从而减小上下文并提升性能。"
            "通过语义相似度支持多语言。"
            "默认开启，以便多轮地理空间工作流更容易落在模型上下文限制内。"
        ),
    )
    tool_selection_strategy: str = Field(
        "conservative",
        description=(
            "动态工具选择策略。可选："
            "'all'（加载全部工具，关闭动态选择）、"
            "'semantic'（语义相似度）、"
            "'conservative'（语义 + 核心工具）、"
            "'minimal'（仅最相关工具）。"
        ),
    )
    tool_similarity_threshold: float = Field(
        0.3,
        ge=0.0,
        le=1.0,
        description=(
            "语义选择中纳入工具的最低相似度分数（0.0–1.0）。"
            "越低则纳入的工具越多。"
        ),
    )
    max_tools_per_query: Optional[int] = Field(
        None,
        ge=1,
        description=(
            "每次查询最多加载的工具数量。"
            "None 表示不限制。用于严格控制上下文。"
        ),
    )
    message_management_mode: Optional[str] = Field(
        None,
        description=(
            "长对话的消息管理策略。"
            "可选：'summarize'（基于 LLM 的智能摘要，默认）、"
            "'prune'（简单窗口截断）。"
            "为 None 时使用环境变量 MESSAGE_MANAGEMENT_MODE（默认 'summarize'）。"
            "设置后可按用户/组织控制对话记忆。"
        ),
    )
    use_summarization: bool = Field(
        False,
        description=(
            "已废弃的布尔开关，仅为向后兼容保留。"
            "请改用 message_management_mode 字段或环境变量 MESSAGE_MANAGEMENT_MODE，"
            "二者接受字符串值 'summarize'（默认）或 'prune'。"
        ),
    )
    enable_smart_crs: bool = Field(
        True,
        description=(
            "为地理处理启用智能 CRS（坐标参考系）选择。"
            "开启后，运算会按地理范围与操作类型自动选择几何上更合适的投影，"
            "从而降低几何误差（例如缓冲区误差从约 20% 降到 <1%，"
            "极区面积计算误差从约 50% 降到 <1%）。"
            "关闭后恢复全部运算使用旧版 EPSG:4326 的行为。"
        ),
    )
    enable_memory: bool = Field(
        True,
        description="为聊天请求启用记忆上下文注入与记忆更新。",
    )
    plan_mode: bool = Field(
        False,
        description=(
            "方案 B：强制智能体在执行任何工具前，先为所有请求生成执行计划。"
        ),
    )
    enable_short_term_memory: bool = Field(
        True,
        description="启用会话级短期记忆（以压缩 Markdown 形式存储）。",
    )
    enable_long_term_memory: bool = Field(
        False,
        description=(
            "启用用户级长期记忆的检索与存储。"
            "需要基于数据库的记忆记录。"
        ),
    )


class ToolConfig(BaseModel):
    name: str = Field(..., description="设置中引用的工具名称")
    enabled: bool = Field(True, description="是否启用该工具")
    prompt_override: str = Field("", description="覆盖默认工具行为的自定义提示词")


class SettingsSnapshot(BaseModel):
    search_portals: List[SearchPortal] = Field(
        default_factory=list,
        description="[已废弃] 已配置的数据门户端点。应用中已不再使用。",
    )
    geoserver_backends: List[GeoServerBackend] = Field(
        ..., description="已配置的 GeoServer 后端"
    )
    mcp_servers: List[MCPServer] = Field(
        default_factory=list, description="已配置的 MCP（Model Context Protocol）服务"
    )
    model_settings: ModelSettings = Field(..., description="大语言模型使用配置")
    tools: List[ToolConfig] = Field(..., description="按工具覆盖的配置项")
    session_id: Optional[str] = Field(
        None,
        description=(
            "服务端下发的标识，用于限定缓存资源范围"
            "（例如预取的 GeoServer 图层）。"
        ),
    )
    conversation_id: Optional[str] = Field(
        None,
        description=(
            "客户端为当前聊天会话下发的标识。"
            "短期记忆按该 id 隔离，新会话开始时应重置。"
        ),
    )
