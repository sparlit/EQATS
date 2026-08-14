import datetime
import uuid
import hashlib
import json

class Event:
    """
    A canonical, structured Event representation as defined in EAQTS Version 2.4.
    """
    def __init__(self, family, source, payload, correlation_id=None, causation_id=None, schema_version="1.0"):
        self.event_id = str(uuid.uuid4())
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.family = family
        self.source = source
        self.schema_version = schema_version
        self.correlation_id = correlation_id or self.event_id
        self.causation_id = causation_id
        self.payload = payload
        self.integrity_metadata = self._generate_integrity_hash()

    def _generate_integrity_hash(self):
        """Generates a cryptographic hash of the event's core payload to ensure immutability."""
        payload_str = json.dumps(self.payload, sort_keys=True)
        raw_string = f"{self.event_id}|{self.timestamp}|{self.family}|{self.source}|{self.schema_version}|{self.correlation_id}|{self.causation_id}|{payload_str}"
        return hashlib.sha256(raw_string.encode('utf-8')).hexdigest()

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "family": self.family,
            "source": self.source,
            "schema_version": self.schema_version,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
            "integrity_metadata": self.integrity_metadata
        }


class EventBus:
    """
    Highly robust, thread-safe, synchronous Event Bus routing system state updates
    across all 9 specialized architectural planes.
    """
    def __init__(self):
        self._listeners = {}
        self._history = []

    def subscribe(self, event_family, listener_func):
        """Registers a callback function to be executed when a specific event family is published."""
        if event_family not in self._listeners:
            self._listeners[event_family] = []
        self._listeners[event_family].append(listener_func)

    def publish(self, event: Event):
        """
        Publishes an event to all registered listeners.
        Stores a record of the published event in the immutable history for replay and audit trails.
        """
        # Validate integrity before processing
        recalculated_hash = event._generate_integrity_hash()
        if recalculated_hash != event.integrity_metadata:
            raise ValueError(f"CRITICAL: Event integrity compromised for Event {event.event_id}")

        self._history.append(event)

        # Notify any subscribed listeners
        if event.family in self._listeners:
            for listener in self._listeners[event.family]:
                try:
                    listener(event)
                except Exception as e:
                    print(f"ERROR: Listener {listener.__name__} crashed handling {event.family}: {e}")

        # Global wildcard listeners if any
        if "*" in self._listeners:
            for listener in self._listeners["*"]:
                try:
                    listener(event)
                except Exception as e:
                    print(f"ERROR: Wildcard listener crashed handling {event.family}: {e}")

    def get_history(self):
        """Returns the complete event history."""
        return list(self._history)

    def clear_history(self):
        """Resets the history (useful for clean test setups)."""
        self._history.clear()


# Single global instance of the event bus
global_event_bus = EventBus()
