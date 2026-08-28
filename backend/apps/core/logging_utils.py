import json
import logging

from apps.core.correlation import get_correlation_id


class CorrelationIdLogFilter(logging.Filter):
    """Stamps every log record with the current request's correlation id
    (or '-' outside a request/known transaction context) without any logger
    call needing to pass it explicitly."""

    def filter(self, record):
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    """Minimal structured-logging formatter - one JSON object per line, no
    extra dependency. Enable with DJANGO_LOG_FORMAT=json for log
    aggregators (e.g. hosted platforms, ELK) that expect JSON lines."""

    def format(self, record):
        payload = {
            'timestamp': self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
            'level': record.levelname,
            'logger': record.name,
            'correlation_id': getattr(record, 'correlation_id', '-'),
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload)
