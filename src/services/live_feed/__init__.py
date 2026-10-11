"""Live Feed Reliability V0.1 -- P0-1 Slice 1 foundation.

Types, boundaries, and a nonblocking single-writer controller skeleton
only. See docs/LIVE_FEED_RELIABILITY_CONTRACT_V0_1.md for the frozen
design and docs/LIVE_FEED_IMPLEMENTATION_SEQUENCE_V0_1.md for what is and
is not implemented yet. No real Futu behavior, no LIVE promotion, no
DecisionEligibility.
"""

from .commands import (
    FakeProviderCommandExecutor,
    ProviderCommand,
    ProviderCommandExecutor,
    ProviderCommandResult,
    ProviderCommandType,
    is_command_result_stale,
)
from .controller import (
    CommandQueueFull,
    EnqueueResult,
    LiveFeedController,
    LiveFeedControllerSnapshot,
    LivePromotionForbidden,
    WriterConcurrencyViolation,
    run_command_worker_once,
)
from .health import LiveFeedHealth, StreamFeedHealth, SymbolFeedHealth
from .identity import ControllerGeneration, new_command_id, new_runtime_instance_id
from .opend_subscription_manager import (
    HistoryWarmStartEvidence,
    HistoryWarmStartResult,
    OpenDSubscriptionManager,
    OpenDSubscriptionManagerSnapshot,
    OpenDSubscriptionQuota,
    SubscriptionMutationAdapter,
    SubscriptionMutationResult,
)
from .registry import DesiredRegistryEntry, DesiredRegistrySnapshot, DesiredSubscriptionRegistry

__all__ = [
    "CommandQueueFull",
    "ControllerGeneration",
    "DesiredRegistryEntry",
    "DesiredRegistrySnapshot",
    "DesiredSubscriptionRegistry",
    "EnqueueResult",
    "FakeProviderCommandExecutor",
    "HistoryWarmStartEvidence",
    "HistoryWarmStartResult",
    "LiveFeedController",
    "LiveFeedControllerSnapshot",
    "LiveFeedHealth",
    "LivePromotionForbidden",
    "OpenDSubscriptionManager",
    "OpenDSubscriptionManagerSnapshot",
    "OpenDSubscriptionQuota",
    "ProviderCommand",
    "ProviderCommandExecutor",
    "ProviderCommandResult",
    "ProviderCommandType",
    "StreamFeedHealth",
    "SubscriptionMutationAdapter",
    "SubscriptionMutationResult",
    "SymbolFeedHealth",
    "WriterConcurrencyViolation",
    "is_command_result_stale",
    "new_command_id",
    "new_runtime_instance_id",
    "run_command_worker_once",
]
