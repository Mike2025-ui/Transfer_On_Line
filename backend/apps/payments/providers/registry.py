from .base import PaymentProvider, PaymentProviderConfigError
from .cinetpay import CinetPayProvider
from .feexpay import FeexPayProvider
from .geniuspay import GeniusPayProvider
from .jeko import JekoProvider

PROVIDER_REGISTRY: dict[str, type[PaymentProvider]] = {
    CinetPayProvider.method: CinetPayProvider,
    FeexPayProvider.method: FeexPayProvider,
    GeniusPayProvider.method: GeniusPayProvider,
    JekoProvider.method: JekoProvider,
}

AUTO_METHOD = 'auto'
SUPPORTED_METHODS = [AUTO_METHOD, *PROVIDER_REGISTRY]


def get_provider(method: str) -> PaymentProvider:
    try:
        provider_class = PROVIDER_REGISTRY[method]
    except KeyError:
        raise PaymentProviderConfigError(f'Unsupported payment method: {method}') from None
    return provider_class()
