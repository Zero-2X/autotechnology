"""Distribution domain services."""

from .service import DeterministicFakePublisher, DistributionError, DistributionService, FakePublisherPort
from .ports import (
    ConnectionPort,
    DistributionPortError,
    DistributionPortSet,
    InboxPort,
    MetricsPort,
    PublisherCapabilityRegistry,
    PublisherPort,
    WebhookPort,
)
from .manual import ManualAdapter
from .package_storage import ExportPackageStorage, InMemoryPrivatePackageStore, PackageStoragePort
from .fake import FakeOfficialAdapter, FakeOfficialError
from .fake_workflow import FakeDeliveryWorkflowService, FakeWorkflowError
from .matrix import CapabilityMatrix, CapabilityMatrixError, CapabilityMatrixRegistry
from .retry import RetryDecision, RetryPolicyError, RetryPolicyService
from .idempotency import DeliveryIdempotencyError, DeliveryIdempotencyService
from .reconcile import PublicationReconciler, ReconciliationError
from .deadletter import DeadLetterError, DeadLetterService, DeliveryDeadLetterService, DeliveryUnknownService, UnknownDeliveryService
from .killswitch import DistributionKillSwitchService, KillSwitchError
from .vertical import ManualExportVerticalSliceService, VerticalSliceError
from .webhook import FakeWebhookPort, WebhookError, WebhookIngressService, WebhookReceipt, sign_fixture_payload

__all__ = [
    "ConnectionPort", "DeterministicFakePublisher", "DistributionError", "DistributionPortError", "DistributionPortSet",
    "CapabilityMatrix", "CapabilityMatrixError", "CapabilityMatrixRegistry", "DeliveryIdempotencyError", "DeliveryIdempotencyService", "DistributionService", "ExportPackageStorage",
    "FakeOfficialAdapter", "FakeOfficialError", "FakeDeliveryWorkflowService", "FakeWorkflowError", "FakePublisherPort", "InboxPort", "InMemoryPrivatePackageStore", "ManualAdapter",
    "MetricsPort", "PackageStoragePort", "PublicationReconciler", "PublisherCapabilityRegistry", "PublisherPort", "ReconciliationError", "RetryDecision", "RetryPolicyError", "RetryPolicyService",
    "DeadLetterError", "DeadLetterService", "DeliveryDeadLetterService", "DeliveryUnknownService", "UnknownDeliveryService",
    "DistributionKillSwitchService", "KillSwitchError",
    "ManualExportVerticalSliceService", "VerticalSliceError",
    "FakeWebhookPort", "WebhookError", "WebhookIngressService", "WebhookPort", "WebhookReceipt", "sign_fixture_payload",
]
