from .base import PaymentProvider, PaymentProviderConfigError
from .geniuspay import GeniusPayProvider
from .jeko import JekoProvider

PROVIDER_REGISTRY: dict[str, type[PaymentProvider]] = {
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
