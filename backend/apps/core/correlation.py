import uuid
from contextvars import ContextVar

_correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='-')

HEADER_NAME = 'X-Correlation-ID'


def new_id():
    return uuid.uuid4().hex


def set_correlation_id(value):
    _correlation_id_var.set(str(value))


def get_correlation_id():
    return _correlation_id_var.get()
