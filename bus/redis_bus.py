"""
Redis pub/sub helper for Gary's message bus.

All events flow through one Redis channel called "events".
Pipelines, the agent, and tools all use this module to talk to the bus.
"""

import redis.asyncio as redis
from events.schema import Event


# The single channel everything publishes/subscribes to.
CHANNEL = "events"


class Bus:
    """
    A thin wrapper around Redis pub/sub.
    
    Usage:
        bus = Bus()
        await bus.connect()
        await bus.publish(some_event)
        async for event in bus.subscribe():
            print(event)
    """

    def __init__(self, host: str = "localhost", port: int = 6379):
        self.host = host
        self.port = port
        self.client: redis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self.client = redis.Redis(host=self.host, port=self.port, decode_responses=True)
        # Ping to verify connection works
        await self.client.ping()

    async def publish(self, event: Event) -> None:
        """Publish an event to the bus."""
        if self.client is None:
            raise RuntimeError("Bus not connected. Call connect() first.")
        await self.client.publish(CHANNEL, event.model_dump_json())

    async def subscribe(self):
        """
        Subscribe to all events on the bus.
        
        Yields Event objects as they arrive.
        Use with `async for event in bus.subscribe(): ...`
        """
        if self.client is None:
            raise RuntimeError("Bus not connected. Call connect() first.")
        
        pubsub = self.client.pubsub()
        await pubsub.subscribe(CHANNEL)
        
        async for message in pubsub.listen():
            # Redis sends a "subscribe" confirmation message first — skip it.
            if message["type"] != "message":
                continue
            
            # Parse the JSON back into an Event object.
            event = Event.model_validate_json(message["data"])
            yield event

    async def close(self) -> None:
        """Close the Redis connection cleanly."""
        if self.client is not None:
            await self.client.aclose()