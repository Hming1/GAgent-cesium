from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, SerializeAsAny

from models.geodata import GeoDataObject
from models.settings_model import SettingsSnapshot

# class ChatMessage(BaseModel):
#    role: Literal["user", "assistant", "system"]
#    content: str


class OrchestratorRequest(BaseModel):
    messages: List[BaseMessage]


class OrchestratorResponse(BaseModel):
    messages: List[BaseMessage]


class ChatPayload(BaseModel):
    id: Optional[str] = None
    input: Optional[str] = None
    messages: Optional[List[BaseMessage]] = None
    query: Optional[str] = None


class ChatResponse(BaseModel):
    id: str
    messages: List[BaseMessage]


# GeoAgent Messages
class GeoAgentRequest(BaseModel):
    """
    Request of the Frontend to the GeoAgent, which contains the message history,
    a request and geodata related to the query
    """

    messages: Optional[List[BaseMessage]] = None
    query: Optional[str] = None
    geodata_last_results: Optional[List[GeoDataObject]] = None
    geodata_layers: Optional[List[GeoDataObject]] = None
    execution_plan: Optional[Dict[str, Any]] = None
    # global_geodata: Optional[List[GeoDataObject]] = None
    options: Optional[Union[Dict[str, Any], SettingsSnapshot]] = None


class GeoAgentResponse(BaseModel):
    """
    Response of the GeoAgent, which contains the message history,
    a response and geodata related to the query
    """

    # Pydantic otherwise serializes only BaseMessage fields and silently drops
    # subclass fields such as AIMessage.tool_calls and ToolMessage.tool_call_id.
    messages: Optional[List[SerializeAsAny[BaseMessage]]] = None
    results_title: Optional[str] = None
    geodata_results: Optional[List[GeoDataObject]] = None
    geodata_layers: Optional[List[GeoDataObject]] = None  # Uncommented for styling support
    execution_plan: Optional[Dict[str, Any]] = None
    global_geodata: Optional[List[GeoDataObject]] = None
    options: Optional[Union[Dict[str, Any], SettingsSnapshot]] = None
