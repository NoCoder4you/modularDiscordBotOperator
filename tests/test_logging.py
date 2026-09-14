import logging
import time

from shared.bot_core.logging import configure_logging


def test_log_timestamp_marked_z_uses_utc():
    logger = configure_logging("timestamp-test")
    handler = logger.handlers[0]
    formatter = handler.formatter
    assert formatter is not None
    assert formatter.converter is time.gmtime

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "ready", (), None)
    record.created = 0
    handler.filters[0].filter(record)

    assert formatter.format(record).startswith("1970-01-01T00:00:00Z")
