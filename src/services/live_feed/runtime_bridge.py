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
        self._adapter.start()
        try:
            for key in unique:
                accepted = self._controller.request_add_desired(key)
                if not accepted.accepted:
                    raise RuntimeError("desired registry ingress rejected")
            self._adapter.subscribe_streams(unique)
            self._subscribed.extend(unique)
            self._controller.process_pending()
        except Exception:
            self._cleanup()
            raise
        self._started = True
        return self.snapshot()

    def drain(self) -> LiveFeedRuntimeSnapshot:
        if not self._started:
            raise RuntimeError("live feed runtime is not started")
        self._controller.process_pending()
        return self.snapshot()

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
