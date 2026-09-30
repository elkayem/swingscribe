"""The GUI console's asyncio filter: a browser's dropped connection must not
print a traceback, and nothing else asyncio reports may be hidden with it.

Each case runs CPython's own proactor teardown as a loop callback, so the
record under test is the one asyncio really writes, not a reconstruction.
Nothing here needs the gui group or Windows: the teardown is plain Python.
"""

import asyncio
import errno
import logging
import types
from asyncio.proactor_events import _ProactorBasePipeTransport

import pytest

from swingscribe.gui import server


class _ResetSocket:
    """A socket whose peer has gone: shutting it down raises `error`."""

    def __init__(self, error: BaseException):
        self.error = error

    def fileno(self) -> int:
        return 3

    def shutdown(self, how: int) -> None:
        raise self.error

    def close(self) -> None:
        pass


def _run_callback(callback, *args) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.call_soon(callback, *args)
        loop.call_soon(loop.stop)
        loop.run_forever()
    finally:
        loop.close()


def _tear_down(error: BaseException) -> None:
    """What the proactor loop runs when a browser drops a connection."""
    transport = types.SimpleNamespace(
        _called_connection_lost=False,
        _protocol=types.SimpleNamespace(connection_lost=lambda exc: None),
        _sock=_ResetSocket(error),
        _server=None,
    )
    teardown = types.MethodType(_ProactorBasePipeTransport._call_connection_lost, transport)
    _run_callback(teardown, None)


def _asyncio_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "asyncio"]


def _reset() -> ConnectionResetError:
    return ConnectionResetError(
        10054, "An existing connection was forcibly closed by the remote host"
    )


@pytest.fixture
def filtered():
    logger = logging.getLogger("asyncio")
    logger.addFilter(server.not_a_dropped_connection)
    yield
    logger.removeFilter(server.not_a_dropped_connection)


def test_unfiltered_the_teardown_prints_the_console_traceback(caplog):
    """The control: without the filter this is the report in the console, so
    the test below is not passing because nothing was logged at all."""
    _tear_down(_reset())

    [record] = _asyncio_records(caplog)
    assert "_ProactorBasePipeTransport._call_connection_lost" in record.getMessage()
    assert isinstance(record.exc_info[1], ConnectionResetError)


def test_the_filter_swallows_a_dropped_connection(caplog, filtered):
    _tear_down(_reset())

    assert _asyncio_records(caplog) == []


def test_another_error_in_the_same_teardown_still_prints(caplog, filtered):
    """Only the reset is the browser's doing; a bad descriptor is a bug."""
    _tear_down(OSError(errno.EBADF, "Bad file descriptor"))

    [record] = _asyncio_records(caplog)
    assert type(record.exc_info[1]) is OSError


def test_a_reset_raised_anywhere_else_still_prints(caplog, filtered):
    def elsewhere() -> None:
        raise _reset()

    _run_callback(elsewhere)

    [record] = _asyncio_records(caplog)
    assert isinstance(record.exc_info[1], ConnectionResetError)


def test_a_record_without_an_exception_still_prints(caplog, filtered):
    logging.getLogger("asyncio").warning("Executing <Task> took 0.500 seconds")

    [record] = _asyncio_records(caplog)
    assert record.exc_info is None
