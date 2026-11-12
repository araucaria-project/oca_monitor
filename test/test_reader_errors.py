import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from serverish.base.exceptions import (
    MessengerConnectionClosed, MessengerJetStreamError, MessengerReaderConfigError, MessengerTransportTimeout,
)

from oca_monitor.pages import tvs_controlroom, water


@pytest.fixture(params=['water', 'controlroom'])
def page(request, monkeypatch):
    reader = Mock()
    if request.param == 'water':
        monkeypatch.setattr(water, 'Messenger', lambda: SimpleNamespace(get_reader=reader))
        window = SimpleNamespace(telemetry_start_time=None, ts=[], water_level=[], update_window=Mock())
        return water.WaterWindow.water_loop, window, reader, window.update_window, 'water_loop'

    monkeypatch.setattr(tvs_controlroom, 'get_reader', reader)
    window = SimpleNamespace(tel='wk06', update_pictures=Mock())
    return tvs_controlroom.WidgetTvsControlroom.reader_nats_ofp, window, reader, window.update_pictures, 'reader_nats_ofp'


@pytest.mark.parametrize('error', [MessengerConnectionClosed, MessengerJetStreamError,
                                  MessengerReaderConfigError, MessengerTransportTimeout])
def test_reader_errors_are_logged(page, error, caplog):
    run, window, reader, _, name = page

    async def failing_reader():
        raise error('read failed')
        yield

    reader.return_value = failing_reader()
    with caplog.at_level(logging.WARNING):
        asyncio.run(run(window))
    assert [(record.levelno, record.getMessage()) for record in caplog.records] == [
        (logging.ERROR, f'{name} reader stopped, the widget will not update: read failed')
    ]
    reader.assert_called_once()


@pytest.mark.parametrize('error', [MessengerConnectionClosed, MessengerJetStreamError, MessengerTransportTimeout,
                                  ValueError, TypeError, LookupError, TimeoutError])
def test_processing_errors_are_logged_and_next_item_processed(page, error, caplog):
    run, window, reader, update, name = page

    async def items():
        for _ in range(2):
            yield {'ts': 1, 'measurements': {'water_level': 42}}, {}

    reader.return_value = items()
    update.side_effect = [error('processing failed'), None]
    with caplog.at_level(logging.WARNING):
        asyncio.run(run(window))
    assert f'{name} get error: processing failed' in caplog.text
    assert caplog.records[0].levelno == logging.WARNING
    assert update.call_count == 2


def test_water_history_stays_aligned_after_100_points(monkeypatch):
    async def items():
        for i in range(205):
            yield {'ts': i, 'measurements': {'water_level': i}}, {}

    reader = Mock(return_value=items())
    monkeypatch.setattr(water, 'Messenger', lambda: SimpleNamespace(get_reader=reader))
    window = SimpleNamespace(telemetry_start_time=None, ts=[], water_level=[])

    def update():
        assert len(window.ts) == len(window.water_level) <= 100
        assert window.ts == window.water_level

    window.update_window = Mock(side_effect=update)
    asyncio.run(water.WaterWindow.water_loop(window))
    assert window.update_window.call_count == 205
    assert window.ts == list(range(105, 205))
    assert window.water_level == list(range(105, 205))


@pytest.mark.parametrize('error', [asyncio.CancelledError, TimeoutError])
def test_controlroom_preserves_cancellation_and_builtin_timeout(monkeypatch, error):
    async def failing_reader():
        raise error()
        yield

    monkeypatch.setattr(tvs_controlroom, 'get_reader', lambda *args, **kwargs: failing_reader())
    window = SimpleNamespace(tel='wk06')
    with pytest.raises(error):
        asyncio.run(tvs_controlroom.WidgetTvsControlroom.reader_nats_ofp(window))
