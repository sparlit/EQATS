"""
Circuit Breaker Resilience Pattern Implementation.
Protects broker gateway routes and external execution channels from cascading failures
and endpoint hammering during sustained outages.
"""

import time
import threading
import logging
from event_bus import global_event_bus, Event

_log = logging.getLogger(__name__)


class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""
    pass


class CircuitBreaker:
    """
    Circuit Breaker state machine wrapping gateway order execution routes.

    States:
      - CLOSED: Normal operation; calls are allowed.
      - OPEN: Cooldown active; calls fail fast without hitting the remote service.
      - HALF_OPEN: Cooldown elapsed; allows probe call to test endpoint recovery.
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self, failure_threshold=5, cooldown_seconds=30.0, half_open_probe=True, excluded_exceptions=()):
        self.failure_threshold = int(failure_threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self.half_open_probe = bool(half_open_probe)
        self.excluded_exceptions = tuple(excluded_exceptions)

        self._state = self.CLOSED
        self._consecutive_failures = 0
        self._last_state_change = time.time()
        self._probe_in_flight = False
        self._lock = threading.Lock()

    def get_state(self):
        """Returns the current circuit breaker state string."""
        with self._lock:
            self._evaluate_state_transition_nolock()
            return self._state

    def _evaluate_state_transition_nolock(self):
        """Evaluates whether OPEN state cooldown has elapsed to transition to HALF_OPEN."""
        if self._state == self.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self.cooldown_seconds:
                if self.half_open_probe:
                    self._transition_to_nolock(self.HALF_OPEN, reason="cooldown_elapsed")
                else:
                    self._transition_to_nolock(self.CLOSED, reason="cooldown_elapsed_auto_close")

    def _transition_to_nolock(self, new_state, reason=""):
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        self._last_state_change = time.time()
        if new_state == self.HALF_OPEN:
            self._probe_in_flight = False
        elif new_state == self.CLOSED:
            self._consecutive_failures = 0
            self._probe_in_flight = False

        _log.warning(
            "CircuitBreaker state transition: %s -> %s (reason: %s, failures: %d)",
            old_state, new_state, reason, self._consecutive_failures
        )

        try:
            global_event_bus.publish(Event(
                family="circuit_breaker",
                source="CircuitBreaker",
                payload={
                    "old_state": old_state.lower(),
                    "new_state": new_state.lower(),
                    "state": new_state.lower(),
                    "reason": reason,
                    "consecutive_failures": self._consecutive_failures
                }
            ))
        except Exception as e:
            _log.debug("Event bus publish exception in CircuitBreaker: %s", e)

    def allow(self):
        """
        Determines if a call is permitted through the circuit breaker.
        Returns True if call should proceed, False if circuit is OPEN.
        """
        with self._lock:
            self._evaluate_state_transition_nolock()

            if self._state == self.CLOSED:
                return True

            if self._state == self.HALF_OPEN:
                if not self._probe_in_flight:
                    self._probe_in_flight = True
                    return True
                return False

            # OPEN state
            return False

    def record_failure(self, exception=None):
        """Records a failure event and trips the breaker to OPEN if threshold is exceeded."""
        if exception is not None and self.excluded_exceptions and isinstance(exception, self.excluded_exceptions):
            _log.debug("CircuitBreaker ignoring excluded exception: %s", type(exception).__name__)
            return

        with self._lock:
            self._consecutive_failures += 1
            _log.info(
                "CircuitBreaker recorded failure #%d/%d in state %s",
                self._consecutive_failures, self.failure_threshold, self._state
            )

            if self._state == self.HALF_OPEN:
                self._transition_to_nolock(self.OPEN, reason="probe_failed")
            elif self._state == self.CLOSED:
                if self._consecutive_failures >= self.failure_threshold:
                    self._transition_to_nolock(self.OPEN, reason="failure_threshold_exceeded")

    def record_success(self):
        """Records a successful call and closes the circuit breaker."""
        with self._lock:
            if self._state in (self.HALF_OPEN, self.OPEN):
                self._transition_to_nolock(self.CLOSED, reason="probe_succeeded")
            else:
                self._consecutive_failures = 0

    def reset(self):
        """Resets the circuit breaker to CLOSED state and clears failure counter."""
        with self._lock:
            self._transition_to_nolock(self.CLOSED, reason="manual_reset")
