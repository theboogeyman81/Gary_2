"""
Event schema for Gary's message bus.

Every message that flows through Redis follows this shape.
This file is the single source of truth for what an event looks like.
"""

from pydantic import BaseModel, Field
from typing import Literal, Any
import time


class Event(BaseModel):
    """
    The base shape of every event on the bus.
    
    Fields:
        type: what kind of event this is (e.g. "speech", "gesture", "speak")
        timestamp: when it happened (Unix time, seconds)
        source: which part of Gary published it (e.g. "voice_pipeline", "agent")
        payload: the actual content, varies by type
    """
    type: str
    timestamp: float = Field(default_factory=time.time)
    source: str
    payload: dict[str, Any]