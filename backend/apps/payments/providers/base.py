from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class PaymentProviderError(Exception):
    """Base class for all payment-provider errors. Callers outside apps.payments
    should only ever need to catch this, never a provider-specific subclass."""


class PaymentProviderConfigError(PaymentProviderError):
    pass


@dataclass
class PaymentInitResult:
    checkout_url: str | None
    provider_transaction_id: str
    raw: dict = field(default_factory=dict)


@dataclass
class PaymentStatusResult:
    status: str  # one of Payment.STATUS_CHOICES (pending/accepted/refused/cancelled/failed)
    raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    """Strategy interface implemented by each payment gateway integration.

    The rest of the project (views, services) depends only on this interface
    and on PaymentProviderError, never on a concrete provider's client or
    exception classes.
    """

    method: str

    @abstractmethod
    def create_payment(self, *, transaction_id, amount, description, customer, metadata=None) -> PaymentInitResult:
        ...

    @abstractmethod
    def verify_payment(self, reference) -> PaymentStatusResult:
        ...

    def refund(self, reference, amount=None):
        """Neither Jèko nor GeniusPay currently expose a merchant-triggered
        refund-creation endpoint (GeniusPay only emits a payment.refunded
        webhook event). Override this once a provider actually supports it."""
        raise NotImplementedError(f'{self.method} does not support refunds yet')
