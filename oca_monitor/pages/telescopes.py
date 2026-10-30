import copy
import datetime
import logging
import os
import subprocess
import time
import asyncio

from PyQt6.QtWidgets import QWidget, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QLabel
from PyQt6 import QtCore, QtGui
from PyQt6.QtSvg import QSvgRenderer

from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import get_reader, single_read

from oca_monitor.paths import icon_path
from oca_monitor.widgets import chart_kit as ck


logger = logging.getLogger(__name__.rsplit('.')[-1])

CLOUDS_MAX_AGE = 600        # s; an older allsky_overwatch message does not count (day, service down)
MIRROR_FANS_STALE = 15 * 60  # s; an older focuser.fansstatus does not count


def icon(name, color, size=14):
    """An icon of resources/icons (svg, as in TOI) painted in one colour."""
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    QSvgRenderer(str(icon_path(f'{name}.svg'))).render(painter)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QtGui.QColor(color))
    painter.end()
    return pixmap

class TelecopeWindow(QWidget):

    # COLORS in (R, G, B) format
    COLORS = {
        'yellow': (255, 255, 0),
        'red': (255, 0, 0),
        'light_gray': (150, 150, 150),
        'green': (0, 255, 0),
        'gray': (100, 100, 100),
        'lime': (0, 255, 0)
    }

    def __init__(self, main_window, subject='telemetry.weather.davis', vertical_screen = False,
                 clouds_subject='tic.status.ocm.allsky_overwatch.clouds', humidity_limit=70., temperature_limit=0., **kwargs):
        super().__init__()
        self.main_window = main_window
        self.subject = subject
        self.clouds_subject = clouds_subject
        self.humidity_limit = float(humidity_limit)        # % - icon as in TOI
        self.temperature_limit = float(temperature_limit)  # C
        self.weather = {}           # last telemetry.weather.davis measurements
        self.safety_cutoff = {t: None for t in self.main_window.telescope_names}
        self.mirror_fans = {}       # tel -> (fans on, time.time() of the message)
        self.clouds = None          # last allsky_overwatch clouds message
        self.vertical = bool(vertical_screen)
        self.mkUI()
        self.lock = asyncio.Lock()
        templeate = {
            "mount_motor":{"val":None, "pms_topic":".mount.motorstatus"},
            "mirror_status": {"val": None, "pms_topic": ".covercalibrator.coverstate"},
            "mount_tracking": {"val": None, "pms_topic": ".mount.tracking"},
            "mount_slewing": {"val": None, "pms_topic": ".mount.slewing"},
            "dome_shutterstatus": {"val": None, "pms_topic": ".dome.shutterstatus"},
            "dome_slewing": {"val": None, "pms_topic": ".dome.slewing"},
            "fw_position": {"val": None, "pms_topic": ".filterwheel.position"},
            "ccd_state": {"val": None, "pms_topic": ".camera.camerastate"},

        }
        self.oca_tel_state = {k:copy.deepcopy(templeate) for k in self.main_window.telescope_names}

        templeate = {"ob_started":False,"ob_done":False,"ob_expected_time":None,"ob_start_time":None,"ob_program":None}
        self.ob_prog_status = {t:copy.deepcopy(templeate) for t in self.main_window.telescope_names}
        self.az = {t:None for t in self.main_window.telescope_names}
        self.alt = {t:None for t in self.main_window.telescope_names}
        self.toi_op_status = {t:None for t in self.main_window.telescope_names}

        QtCore.QTimer.singleShot(0, self.async_init)
        logger.info(f"TelecopeWindow init setup done")

    @asyncSlot()
    async def async_init(self):

        # try:
        #     nats_cfg = await single_read(f'tic.config.observatory')
        #     self.nats_cfg = nats_cfg[0]
        # except AttributeError:
        #     logger.error(f'Can not get observatory config.')
        #     self.nats_cfg = None

        self.filters = {t:None for t in self.main_window.telescope_names}

        for tel in self.main_window.telescope_names:
            try:
                tmp = self.main_window.nats_cfg["config"]["telescopes"][tel]["observatory"]["components"]["filterwheel"]["filters"]
                tmp_n = [item["name"] for item in sorted(tmp, key=lambda x: x["position"])]
            except (KeyError, TypeError):
                tmp_n = None
            self.filters[tel] = tmp_n

        await create_task(self.weather_reader(), "nats_tel_weather_reader")
        await create_task(self.clouds_reader(), "nats_tel_clouds_reader")
        for tel in self.main_window.telescope_names:
            await create_task(self.safety_cutoff_reader(tel), "nats_tel_safety_cutoff_reader")
            await create_task(self.mirror_fans_reader(tel), "nats_tel_mirror_fans_reader")
            await create_task(self.oca_telemetry_program_reader(tel),"nats_oca_telemetry_program_reader")
            await create_task(self.oca_az_reader(tel), "nats_oca_az_reader")
            await create_task(self.oca_alt_reader(tel), "nats_oca_alt_reader")
            await create_task(self.oca_toi_status_reader(tel), "nats_oca_toi_status_reader")
            for k in self.oca_tel_state[tel].keys():
                await create_task(self.oca_telemetry_reader(tel,k),"nats_oca_telemetry_reader")

    # the icons of the Telescope column, as in TOI's obs window (weather, safety cutoff, mirror fans, clouds)
    async def weather_reader(self):
        try:
            reader = get_reader(self.subject, deliver_policy='last')
            async for data, meta in reader:
                self.weather = data.get('measurements') or {}
                async with self.lock:
                    self.update_table()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'EXCEPTION weather_reader: {e}')

    async def clouds_reader(self):
        try:
            reader = get_reader(self.clouds_subject, deliver_policy='last')
            async for data, meta in reader:
                self.clouds = data
                async with self.lock:
                    self.update_table()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'EXCEPTION clouds_reader: {e}')

    async def safety_cutoff_reader(self, tel):
        try:
            reader = get_reader(f'tic.status.{tel}.access_grantor.safety_cutoff_state', deliver_policy='last')
            async for data, meta in reader:
                state = (data.get('measurements') or {}).get(f'{tel}.access_grantor.safety_cutoff_state')
                self.safety_cutoff[tel] = None if state is None else bool(state)
                async with self.lock:
                    self.update_table()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'EXCEPTION safety_cutoff_reader: {e}')

    async def mirror_fans_reader(self, tel):
        try:
            reader = get_reader(f'tic.status.{tel}.focuser.fansstatus', deliver_policy='last')
            async for data, meta in reader:
                values = list((data.get('measurements') or {}).values())
                self.mirror_fans[tel] = (None if not values or values[0] is None else str(values[0]) == 'True', time.time())
                async with self.lock:
                    self.update_table()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'EXCEPTION mirror_fans_reader: {e}')

    def clouds_at(self, tel):
        """"red" / "yellow" when the telescope observes where allsky_overwatch marks clouds on its last frame."""
        d = self.clouds
        if not d or not d.get('time'):
            return None
        try:
            age = time.time() - datetime.datetime.fromisoformat(d['time']).timestamp()
        except (TypeError, ValueError):
            return None
        return (d.get('telescopes') or {}).get(tel) if age <= CLOUDS_MAX_AGE else None

    def telescope_icons(self, t):
        """(icon, colour, tooltip) of the Telescope column, as in TOI (without its joystick: TOI's own access)."""
        out = []
        if self.safety_cutoff.get(t):
            out.append(('icon_hat', 'red', 'safety cutoff ON'))
        op = self.toi_op_status[t] or {}
        if (self.ob_prog_status[t] or {}).get('error'):
            out.append(('icon_bug', 'red', 'program error'))
        changed = lambda k: (op.get(k) or {}).get('state') != (op.get(k) or {}).get('defoult')
        fans, fans_t = self.mirror_fans.get(t, (None, 0))
        if fans is None or time.time() - fans_t > MIRROR_FANS_STALE:
            fans = changed('mirror_fans') if op else None
        if (op and changed('dome_ventilators')) or fans:
            out.append(('icon_fan', 'orange', 'ventilators / mirror fans on'))
        if op and (changed('flat_lamps') or changed('dome_lights')):
            out.append(('icon_bulb', 'orange', 'flat lamps / dome lights on'))
        def _f(key):
            try:
                return float(self.weather.get(key))
            except (TypeError, ValueError):
                return None
        wind, rain, humidity, temperature = _f('wind_10min_ms'), _f('rain_mm'), _f('humidity'), _f('temperature_C')
        stop, pointing = ck.telescope_wind_limits(getattr(self.main_window, 'nats_cfg', None), t)
        if wind is not None and stop is not None and wind > stop:
            out.append(('icon_wind', 'red', f'wind {wind:.1f} m/s above the observation stop {stop:g}'))
        elif wind is not None and pointing is not None and wind > pointing:
            out.append(('icon_wind', 'orange', f'wind {wind:.1f} m/s above the pointing limit {pointing:g}'))
        if rain is not None and rain > 0:
            out.append(('icon_rain', 'red', 'rain'))
        if humidity is not None and humidity > self.humidity_limit:
            out.append(('icon_water', 'red', f'humidity {humidity:.0f} % above {self.humidity_limit:g} %'))
        if temperature is not None and temperature < self.temperature_limit:
            out.append(('icon_cold', 'red', f'temperature {temperature:.1f} C below {self.temperature_limit:g} C'))
        clouds = self.clouds_at(t)
        if clouds:
            out.append(('icon_cloud', 'red' if clouds == 'red' else 'orange',
                        'pointing into thick clouds' if clouds == 'red' else 'pointing into clouds'))
        return out

    async def oca_toi_status_reader(self,tel):
        try:
            reader = get_reader(f'tic.status.{tel}.toi.status', deliver_policy='last')
            async for data, meta in reader:
                self.toi_op_status[tel] = data
                async with self.lock:
                    self.update_table()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'EXCEPTION oca_toi_status_reader: {e}')

    async def oca_az_reader(self,tel):
        try:
            r = get_reader(f'tic.telemetry.{tel}.mount.azimuth', deliver_policy='last')
            async for data, meta in r:
                for k in data["measurements"].keys():
                    self.az[tel] = data["measurements"][k]
                    self.main_window.telescopes_az = self.az
        except Exception as e:
            logger.warning(f'ERROR: {e}')

    async def oca_alt_reader(self,tel):
        try:
            r = get_reader(f'tic.telemetry.{tel}.mount.altitude', deliver_policy='last')
            async for data, meta in r:
                for k in data["measurements"].keys():
                    self.alt[tel] = data["measurements"][k]
                    self.main_window.telescopes_alt = self.alt
        except Exception as e:
            logger.warning(f'ERROR: {e}')

    async def oca_telemetry_reader(self,tel,key):
        try:
            r = get_reader(f'tic.status.{tel}{self.oca_tel_state[tel][key]["pms_topic"]}', deliver_policy='last')
            async for data, meta in r:
                txt = data["measurements"][f"{tel}{self.oca_tel_state[tel][key]['pms_topic']}"]
                self.oca_tel_state[tel][key]["val"] = txt
                async with self.lock:
                    self.update_table()
        except Exception as e:
            logger.warning(f'ERROR: {e}')

    async def oca_telemetry_program_reader(self,tel):
        try:
            reader = get_reader(f'tic.status.{tel}.toi.ob', deliver_policy='last')
            async for status, meta in reader:
                self.ob_prog_status[tel] = status
                async with self.lock:
                    self.update_table()
        except Exception as e:
                logger.warning(f'ERROR: {e}')


    def update_table(self):
        i = -1
        for t in self.main_window.telescope_names:
            i = i + 1

            # TELESKOPY: name and the icons of TOI's obs window
            cell = QWidget()
            lay = QHBoxLayout(cell)
            lay.setContentsMargins(1, 0, 1, 0)
            lay.setSpacing(3)
            lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            name = QLabel(t)
            name.setStyleSheet("color: rgb(%d, %d, %d);" % self.COLORS['light_gray'])
            lay.addWidget(name)
            try:
                for icon_name, color, tip in self.telescope_icons(t):
                    label = QLabel()
                    label.setPixmap(icon(icon_name, color))
                    label.setToolTip(tip)
                    lay.addWidget(label)
            except Exception as e:
                logger.warning(f'EXCEPTION telescope icons {t}: {e}')
            self.obs_t.setCellWidget(i, 0, cell)

            # DOME
            state, rgb = "--", (0, 0, 0)
            shutter = self.oca_tel_state[t]["dome_shutterstatus"]["val"]
            moving = self.oca_tel_state[t]["dome_slewing"]["val"]

            if shutter != None or moving != None:
                if shutter == None and moving == None : state,rgb = "SHUTTER and STATUS ERROR", self.COLORS['red']
                elif shutter == None: state,rgb = "SHUTTER ERROR", self.COLORS['red']
                elif moving == None : state,rgb = "DOME STATUS ERROR", self.COLORS['red']
                else:
                    if moving: state,rgb = "MOVING", self.COLORS['yellow']
                    elif shutter==0: state,rgb = "OPEN", self.COLORS['green']
                    elif shutter==1: state,rgb = "CLOSED", self.COLORS['light_gray']
                    elif shutter==2: state,rgb = "OPENING", self.COLORS['yellow']
                    elif shutter==3: state,rgb = "CLOSING", self.COLORS['yellow']
                    else: state,rgb = "SHUTTER ERROR", self.COLORS['red']

            item = QTableWidgetItem(state)
            item.setForeground(QtGui.QBrush(QtGui.QColor(*rgb)))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.obs_t.setItem(i, 1, item)


            # MIRROR
            state, rgb = "--", (0, 0, 0)
            status = self.oca_tel_state[t]["mirror_status"]["val"]
            if status == None:
                state, rgb = "NO IDEA", (0, 0, 0)
            else:
                if status == 3: state,rgb = "OPEN", self.COLORS['green']
                elif status == 1: state, rgb = "CLOSED", self.COLORS['light_gray']
                elif status == 2: state, rgb = "MOVING", self.COLORS['yellow']
                else: state,rgb = "ERROR", self.COLORS['red']

            item = QTableWidgetItem(state)
            item.setForeground(QtGui.QBrush(QtGui.QColor(*rgb)))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.obs_t.setItem(i, 2, item)



            # MOUNT
            state, rgb = "--", (0, 0, 0)
            slewing = self.oca_tel_state[t]["mount_slewing"]["val"]
            tracking = self.oca_tel_state[t]["mount_tracking"]["val"]
            motors = self.oca_tel_state[t]["mount_motor"]["val"]

            if slewing != None or tracking != None:
                if motors == "false": state,rgb = "MOTORS OFF", self.COLORS['light_gray']
                elif slewing: state,rgb = "SLEWING", self.COLORS['yellow']
                elif tracking: state,rgb = "TRACKING", self.COLORS['green']
                else: state,rgb = "IDLE", self.COLORS['light_gray']

            item = QTableWidgetItem(state)
            item.setForeground(QtGui.QBrush(QtGui.QColor(*rgb)))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.obs_t.setItem(i, 3, item)

            # CCD
            state, rgb = "--", (0, 0, 0)
            filtr = "--"
            pos = self.oca_tel_state[t]["fw_position"]["val"]
            ccd =  self.oca_tel_state[t]["ccd_state"]["val"]


            try:
                if pos != None:
                    if pos >= 0:
                        filtr = self.filters[t][pos]
            except Exception as e:
                pass

            if ccd != None :
                if ccd == 2:
                    state,rgb = f"EXP [{filtr}]", self.COLORS['green']
                elif ccd == 0:
                    state,rgb = f"IDLE [{filtr}]", self.COLORS['light_gray']
                else:
                   state, rgb = f"NO IDEA [{filtr}]", self.COLORS['gray']

            item = QTableWidgetItem(state)
            item.setForeground(QtGui.QBrush(QtGui.QColor(*rgb)))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.obs_t.setItem(i, 4, item)

            # PROGRAM
            state, rgb = "--", (0, 0, 0)
            started = self.ob_prog_status[t]["ob_started"]
            done = self.ob_prog_status[t]["ob_done"]
            program = self.ob_prog_status[t]["ob_program"]
            t0 = self.ob_prog_status[t]["ob_start_time"]
            dt = self.ob_prog_status[t]["ob_expected_time"]
            if started and not done:
                if "OBJECT" in program:
                    state,rgb = f"{program.split()[1]}", self.COLORS['green']
                else:
                    if len(program.split())>1:
                        state, rgb = f"{program.split()[0]} {program.split()[1]}", self.COLORS['green']
                    else:
                        state, rgb = f"{program.split()[0]}", self.COLORS['green']
                if dt == None or dt == 0 or t0 == None:
                    state = f"{state} (??)"
                else:
                    t = time.time() - t0
                    p = t / dt
                    if p > 1.2:
                        rgb = self.COLORS['yellow']
                    state = f"{state} ({int(p*100)}%)"
            else:
                rgb = self.COLORS['light_gray']
                state = f"IDLE"


            item = QTableWidgetItem(state)
            item.setForeground(QtGui.QBrush(QtGui.QColor(*rgb)))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.obs_t.setItem(i, 5, item)

            self.obs_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # QtCore.QTimer.singleShot(1000, self.update_table)

    def mkUI(self):

        grid = QGridLayout()

        w = 0
        self.obs_t = QTableWidget(3, 6)
        self.obs_t.setHorizontalHeaderLabels(["Telescope", "Dome","Mirror", "Mount", "Instrument", "Program"])
        self.obs_t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.obs_t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.obs_t.verticalHeader().hide()
        self.obs_t.setShowGrid(False)
        self.obs_t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        #self.obs_t.setFixedWidth(550)  # Size
        self.obs_t.setStyleSheet("font-size: 9pt; selection-background-color: rgb(138,176,219);")
        grid.addWidget(self.obs_t, w, 0, 1, 1)

        self.setLayout(grid)


widget_class = TelecopeWindow