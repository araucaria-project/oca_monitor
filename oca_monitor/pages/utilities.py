"""Small site utilities panel (monitor2, 2026-11-12): power, water, internet at a glance.

* **POWER** — battery state of charge (colour: warn / danger thresholds as on the Battery chart), charging /
  discharging power, solar production and site load (``load = pv + discharge - charge``, as in ``weather.py``
  ``_PowerPanel``). Source ``telemetry.power.data-manager`` (SMA, ~5 s); ``pv_power`` -2147483648 = no value (night).
* **WATER** — tank level in m3 and % (``telemetry.water.level``), as in the Site panel.
* **NET** — internet uplink from wan-watchdog (``svc.publish.oca.wan.status``, published on change), as in Site.

A value older than its ``*_stale_min`` is shown grey with its age (time from the NATS message, not from ``ts``:
the water meter writes ``ts`` in Chile local time).
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Optional

from PyQt6 import QtCore, QtGui
from PyQt6.QtWidgets import QGridLayout, QLabel, QWidget
from qasync import asyncSlot

from oca_monitor.pages.site_status import SiteStatusWidget, _Group

logger = logging.getLogger(__name__.rsplit('.')[-1])

_SENTINEL_INT32_MIN = -2_147_483_648
_GRAY = '#808080'
_OK = '#6ed0a8'
_WARN = '#ffaa33'
_DANGER = '#ff4d4d'
_SOLAR = '#e0c050'


def _msg_time(meta) -> float:
    """Time of the NATS message (UTC), else now"""
    try:
        return datetime.datetime(*meta['nats']['timestamp'][:6], tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        return time.time()


def _age(sec: float) -> str:
    m = int(sec // 60)
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _kw(w: float) -> str:
    return f"{w / 1000:.1f} kW" if abs(w) >= 1000 else f"{w:.0f} W"


class UtilitiesWidget(QWidget):
    """Power / water / internet - see module docstring."""

    def __init__(self, main_window,
                 power_subject: str = 'telemetry.power.data-manager',
                 water_subject: str = 'telemetry.water.level',
                 net_subject: str = 'svc.publish.oca.wan.status',
                 soc_warn_pct: float = 30.0,
                 soc_danger_pct: float = 15.0,
                 water_capacity_m3: float = 15.0,
                 water_warn_pct: float = 20.0,
                 water_danger_pct: float = 10.0,
                 power_stale_min: float = 5.0,
                 water_stale_min: float = 60.0,
                 **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.power_subject, self.water_subject, self.net_subject = power_subject, water_subject, net_subject
        self.soc_warn_pct, self.soc_danger_pct = float(soc_warn_pct), float(soc_danger_pct)
        self.water_capacity_m3 = float(water_capacity_m3)
        self.water_warn_pct, self.water_danger_pct = float(water_warn_pct), float(water_danger_pct)
        self.power_stale_s, self.water_stale_s = 60 * float(power_stale_min), 60 * float(water_stale_min)
        self.power: Optional[dict] = None
        self.power_t: Optional[float] = None
        self.water_m3: Optional[float] = None
        self.water_t: Optional[float] = None
        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        self._timer = QtCore.QTimer(self)       # ages / staleness
        self._timer.timeout.connect(self._render)
        self._timer.start(30000)

    # ---- UI -----------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setStyleSheet("UtilitiesWidget { background-color: #181818; } QLabel { color: #e0e0e0; }")
        big = QtGui.QFont('Arial', 16, QtGui.QFont.Weight.Bold)
        small = QtGui.QFont('Arial', 12, QtGui.QFont.Weight.Bold)

        def label(font):
            lbl = QLabel("—")
            lbl.setFont(font)
            lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
            return lbl

        self.box_power = _Group('POWER')
        self.lbl_battery = label(big)
        self.lbl_flow = label(small)
        self.box_power.layout.addStretch(1)
        self.box_power.layout.addWidget(self.lbl_battery)
        self.box_power.layout.addStretch(1)
        self.box_power.layout.addWidget(self.lbl_flow)
        self.box_power.layout.addStretch(1)

        self.box_water = _Group('WATER')
        self.lbl_water = label(small)
        self.box_water.layout.addWidget(self.lbl_water)

        self.box_net = _Group('NET')
        self.lbl_net = label(small)
        self.lbl_net.setToolTip("Internet uplink (wan-watchdog): no message yet")
        self.box_net.layout.addWidget(self.lbl_net)

        grid = QGridLayout(self)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(4)
        grid.addWidget(self.box_power, 0, 0, 1, 2)
        grid.addWidget(self.box_water, 1, 0)
        grid.addWidget(self.box_net, 1, 1)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)

    # ---- NATS ---------------------------------------------------------------

    @asyncSlot()
    async def async_init(self):
        for clb, subject in ((self._power_callback, self.power_subject), (self._water_callback, self.water_subject),
                             (self._net_callback, self.net_subject)):
            try:
                await self.main_window.run_reader(clb=clb, subject=subject, deliver_policy='last')
            except Exception as e:
                logger.warning(f"reader {subject} subscription failed: {e}")

    async def _power_callback(self, data, meta) -> bool:
        try:
            self.power = dict(data['measurements'])
            self.power_t = _msg_time(meta)
            self._render()
        except Exception as e:
            logger.warning(f"power message skipped: {e!r}")
        return True

    async def _water_callback(self, data, meta) -> bool:
        try:
            self.water_m3 = float(data['measurements']['m3'])
            self.water_t = _msg_time(meta)
            self._render()
        except Exception as e:
            logger.warning(f"water message skipped: {e!r}")
        return True

    async def _net_callback(self, data, meta) -> bool:
        try:
            route = str(data['measurements']['route'])
        except (KeyError, TypeError):
            return True
        since = datetime.datetime.fromtimestamp(_msg_time(meta), datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
        self.lbl_net.setText(f"🌐 {route}")
        self.lbl_net.setStyleSheet(f"color: {SiteStatusWidget.NET_COLORS.get(route.lower(), '#e0e0e0')};")
        self.lbl_net.setToolTip(f"Internet uplink (wan-watchdog): {route} since {since} UT")
        return True

    # ---- drawing ------------------------------------------------------------

    @staticmethod
    def _value(d: dict, key: str) -> Optional[float]:
        try:
            v = float(d.get(key))
        except (TypeError, ValueError):
            return None
        return None if v == _SENTINEL_INT32_MIN or abs(v) > 1e6 else v

    def _render(self) -> None:
        try:
            self._render_power()
            self._render_water()
        except Exception as e:      # plain Qt slot (timer) - must not raise
            logger.warning(f"utilities render: {e!r}")

    def _render_power(self) -> None:
        if self.power is None:
            return
        age = time.time() - (self.power_t or time.time())
        stale = age > self.power_stale_s
        soc = self._value(self.power, 'state_of_charge')
        pv = self._value(self.power, 'pv_power')
        charge = self._value(self.power, 'battery_charge') or 0.0
        discharge = self._value(self.power, 'battery_discharge') or 0.0
        if soc is None:
            soc_txt, color = "—", _GRAY
        else:
            soc_txt = f"{soc:.0f} %"
            color = _DANGER if soc <= self.soc_danger_pct else _WARN if soc <= self.soc_warn_pct else _OK
        net = charge - discharge
        if abs(net) < 50:
            flow = ""
        elif net > 0:
            flow = f'  <span style="color:{_OK}">▲ charging {_kw(net)}</span>'
        else:
            flow = f'  <span style="color:{_WARN}">▼ {_kw(-net)}</span>'
        if stale:
            self.lbl_battery.setText(f'<span style="color:{_GRAY}">🔋 {soc_txt}  (no data {_age(age)})</span>')
        else:
            self.lbl_battery.setText(f'🔋 <span style="color:{color}">{soc_txt}</span>{flow}')
        load = (pv or 0.0) + discharge - charge
        solar = f'<span style="color:{_SOLAR}">☀ {_kw(pv)}</span>' if pv and pv > 0 else \
            f'<span style="color:{_GRAY}">☀ —</span>'
        self.lbl_flow.setText(f'{solar}   <span style="color:{_GRAY if stale else "#e0e0e0"}">⚡ load {_kw(load)}</span>')
        self.lbl_flow.setToolTip("☀ solar production, ⚡ site load (solar + battery discharge - charge)")

    def _render_water(self) -> None:
        if self.water_m3 is None:
            return
        age = time.time() - (self.water_t or time.time())
        pct = 100.0 * self.water_m3 / self.water_capacity_m3 if self.water_capacity_m3 > 0 else None
        if age > self.water_stale_s:
            self.lbl_water.setText(f'<span style="color:{_GRAY}">💧 {self.water_m3:.1f} m³ ({_age(age)} ago)</span>')
            return
        if pct is None:
            self.lbl_water.setText(f"💧 {self.water_m3:.1f} m³")
            return
        color = _DANGER if pct <= self.water_danger_pct else _WARN if pct <= self.water_warn_pct else _GRAY
        self.lbl_water.setText(f'💧 {self.water_m3:.1f} m³ <span style="color:{color}">{pct:.0f}%</span>')


widget_class = UtilitiesWidget
