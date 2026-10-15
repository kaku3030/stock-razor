"""Thin lifecycle bridge between a streaming provider adapter and LiveFeedController.

This runtime owns orchestration only. It does not qualify delivery mode, infer
bar closure, create strategy signals, or expose any trading path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from data_provider.live_feed_types import ProviderEvent, SemanticStreamKey
from .controller import EnqueueResult, LiveFeedController, LiveFeedControllerSnapshot


class StreamingAdapter(Protocol):
    def register_event_sink(self, sink) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def subscribe_stream(self, key: SemanticStreamKey) -> None: ...
    def subscribe_streams(self, keys: Sequence[SemanticStreamKey]) -> None: ...
    def unsubscribe_stream(self, key: SemanticStreamKey) -> None: ...


@dataclass(frozen=True)
class LiveFeedRuntimeSnapshot:
    controller: LiveFeedControllerSnapshot
    subscribed: tuple[SemanticStreamKey, ...]


class LiveFeedRuntimeBridge:
    """Bind one provider adapter to the existing single-writer controller."""

    def __init__(
        self,
        controller: LiveFeedController,
        adapter: StreamingAdapter,
        *,
        on_event_accepted: Callable[[ProviderEvent], None] | None = None,
    ) -> None:
        self._controller = controller
        self._adapter = adapter
        self._on_event_accepted = on_event_accepted
        self._subscribed: list[SemanticStreamKey] = []
        self._started = False

    def start(self, streams: Sequence[SemanticStreamKey]) -> LiveFeedRuntimeSnapshot:
        if self._started:
            raise RuntimeError("live feed runtime already started")
        unique = tuple(dict.fromkeys(streams))
        if not unique:
            raise ValueError("at least one stream is required")
        self._adapter.register_event_sink(self._submit_event)
        registered: list[SemanticStreamKey] = []
        adapter_start_attempted = False
        try:
            for key in unique:
                accepted = self._controller.request_add_desired(key)
                if not accepted.accepted:
                    raise RuntimeError("desired registry ingress rejected")
                registered.append(key)
            # Desired keys must be committed before start(), because the
            # provider may emit data synchronously from its start callback.
            self._controller.process_pending()
            adapter_start_attempted = True
            self._adapter.start()
            # A failed subscribe batch can be partially applied. Own all
            # attempted keys for bounded cleanup before invoking the adapter.
            self._subscribed.extend(unique)
            self._adapter.subscribe_streams(unique)
            # Drain immediate provider callbacks as on the original startup
            # path; each event follows the already committed desired keys.
            self._controller.process_pending()
        except Exception:
            try:
                if adapter_start_attempted:
                    self._cleanup()
            finally:
                # A failed start must not leave ghost desired streams that
                # could accept delayed provider pushes on the next attempt.
                self._controller.process_pending()
                for key in registered:
                    removed = self._controller.request_remove_desired(key)
                    if not removed.accepted:
                        raise RuntimeError("startup desired registry rollback rejected")
                self._controller.process_pending()
            raise
        self._started = True
        return self.snapshot()

    def drain(self) -> LiveFeedRuntimeSnapshot:
        if not self._started:
            raise RuntimeError("live feed runtime is not started")
        self._controller.process_pending()
        return self.snapshot()

    def subscribe_streams(self, streams: Sequence[SemanticStreamKey]) -> None:
        """Add streams through the existing controller and provider owner.

        This is the mutation seam used by the instance-scoped subscription
        manager. Desired keys are registered before provider subscription so
        an immediate push is not rejected as undesired. If provider mutation
        fails, the desired registry is rolled back and the exception remains
        visible to the manager as an unknown transport outcome.
        """
        if not self._started:
            raise RuntimeError("live feed runtime is not started")
        unique = tuple(key for key in dict.fromkeys(streams) if key not in self._subscribed)
        if not unique:
            return
        queued: list[SemanticStreamKey] = []
        for key in unique:
            accepted = self._controller.request_add_desired(key)
            if not accepted.accepted:
                for prior in queued:
                    self._controller.request_remove_desired(prior)
                self._controller.process_pending()
                raise RuntimeError("desired registry ingress rejected")
            queued.append(key)
        self._controller.process_pending()
        try:
            self._adapter.subscribe_streams(unique)
        except Exception:
            # A batch exception is ambiguous: the provider may have
            # accepted some streams. Request bounded per-key compensation;
            # the manager still marks transport UNKNOWN if any step failed.
            for key in reversed(unique):
                try:
                    self._adapter.unsubscribe_stream(key)
                except Exception:
                    pass
            for key in unique:
                self._controller.request_remove_desired(key)
            self._controller.process_pending()
            raise
        self._subscribed.extend(unique)

    def subscribe_stream(self, key: SemanticStreamKey) -> None:
        self.subscribe_streams((key,))

    def unsubscribe_stream(self, key: SemanticStreamKey) -> None:
        """Remove one stream after provider ACK; baseline policy stays external."""
        if not self._started:
            raise RuntimeError("live feed runtime is not started")
        if key not in self._subscribed:
            return
        self._adapter.unsubscribe_stream(key)
        accepted = self._controller.request_remove_desired(key)
        if not accepted.accepted:
            # Keep local ownership so stop() still attempts cleanup. The
            # provider may have unsubscribed, but controller state is unknown.
            raise RuntimeError("desired registry ingress rejected after provider unsubscribe")
        self._controller.process_pending()
        self._subscribed.remove(key)

    def stop(self) -> LiveFeedRuntimeSnapshot:
        if not self._started:
            return self.snapshot()
        stop = self._controller.request_stop()
        if not stop.accepted:
            raise RuntimeError("stop ingress rejected")
        self._cleanup()
        self._controller.process_pending()
        self._started = False
        return self.snapshot()

    def snapshot(self) -> LiveFeedRuntimeSnapshot:
        return LiveFeedRuntimeSnapshot(
            controller=self._controller.snapshot(),
            subscribed=tuple(self._subscribed),
        )

    def _cleanup(self) -> None:
        for key in reversed(self._subscribed):
            try:
                self._adapter.unsubscribe_stream(key)
            except Exception:
                pass
        self._subscribed.clear()
        self._adapter.stop()

    def _submit_event(self, event: ProviderEvent) -> EnqueueResult:
        result = self._controller.submit_event(event)
        if result.accepted and self._on_event_accepted is not None:
            self._on_event_accepted(event)
        return result
