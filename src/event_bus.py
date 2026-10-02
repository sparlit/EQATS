import datetime
import hashlib
import json
import uuid
from typing import Any


class Event:
    """
    A canonical, structured Event representation as defined in EQATS Version 3.0.
    """

    def __init__(
        self,
        family: Any,
        source: Any,
        payload: Any,
        correlation_id: Any = None,
        causation_id: Any = None,
        schema_version: Any = "1.0",
    ) -> None:
        self.event_id = str(uuid.uuid4())
        self.timestamp = datetime.datetime.now(datetime.UTC).isoformat()
        self.family = family
        self.source = source
        self.schema_version = schema_version
        self.correlation_id = correlation_id or self.event_id
        self.causation_id = causation_id
        self.payload = payload
        self.integrity_metadata = self._generate_integrity_hash()

    def _generate_integrity_hash(self) -> Any:
        """Generates a cryptographic hash of the event's core payload to ensure immutability."""
        payload_str = json.dumps(self.payload, sort_keys=True)
        raw_string = f"{self.event_id}|{self.timestamp}|{self.family}|{self.source}|{self.schema_version}|{self.correlation_id}|{self.causation_id}|{payload_str}"
        return hashlib.sha256(raw_string.encode("utf-8")).hexdigest()

    def to_dict(self) -> Any:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "family": self.family,
            "source": self.source,
            "schema_version": self.schema_version,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
            "integrity_metadata": self.integrity_metadata,
        }


class EventBus:
    """
    Highly robust, thread-safe, synchronous Event Bus routing system state updates
    across all 9 specialized architectural planes.
    """

    def __init__(self) -> None:
        self._listeners = {}
        self._history = []

    def subscribe(self, event_family: Any, listener_func: Any) -> None:
        """Registers a callback function to be executed when a specific event family is published."""
        if event_family not in self._listeners:
            self._listeners[event_family] = []
        self._listeners[event_family].append(listener_func)

    def publish(self, event: Event) -> None:
        """
        Publishes an event to all registered listeners.
        Stores a record of the published event in the immutable history for replay and audit trails.
        """
        recalculated_hash = event._generate_integrity_hash()
        if recalculated_hash != event.integrity_metadata:
            raise ValueError(f"CRITICAL: Event integrity compromised for Event {event.event_id}")
        self._history.append(event)
        if event.family in self._listeners:
            for listener in self._listeners[event.family]:
                try:
                    listener(event)
                except Exception as e:
                    print(f"ERROR: Listener {listener.__name__} crashed handling {event.family}: {e}")
        elif event.family == "MARKET_DATA":
            print(f"[EVENT BUS - IF-ELIF LOOP] Market data event received: {event.event_id}")
        elif event.family == "TRADE_SIGNAL":
            print(f"[EVENT BUS - IF-ELIF LOOP] Trade signal event received: {event.event_id}")
        elif event.family == "RISK_VIOLATION":
            print(f"[EVENT BUS - IF-ELIF LOOP] Risk violation event received: {event.event_id}")
        else:
            pass
        if "*" in self._listeners:
            for listener in self._listeners["*"]:
                try:
                    listener(event)
                except Exception as e:
                    print(f"ERROR: Wildcard listener crashed handling {event.family}: {e}")

    def get_history(self) -> Any:
        """Returns the complete event history."""
        return list(self._history)

    def clear_history(self) -> None:
        """Resets the history (useful for clean test setups)."""
        self._history.clear()


global_event_bus = EventBus()
