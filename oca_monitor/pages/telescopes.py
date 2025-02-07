import copy
import logging
import os
import subprocess
import time
import asyncio

from PyQt6.QtWidgets import QWidget, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6 import QtCore, QtGui

from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import get_reader


logger = logging.getLogger(__name__.rsplit('.')[-1])

class TelecopeWindow(QWidget):
    def __init__(self, main_window, subject='telemetry.weather.davis', vertical_screen = False, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.subject = subject
        self.vertical = bool(vertical_screen)
        self.mkUI()
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

        QtCore.QTimer.singleShot(0, self.async_init)

    @asyncSlot()
    async def async_init(self):
        for tel in self.main_window.telescope_names:
            await create_task(self.oca_telemetry_program_reader(tel),"message_reader")
            await create_task(self.oca_az_reader(tel), "message_reader")
            await create_task(self.oca_alt_reader(tel), "message_reader")
            for k in self.oca_tel_state[tel].keys():
                await create_task(self.oca_telemetry_reader(tel,k),"message_reader")


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
                self.update_table()
        except Exception as e:
            logger.warning(f'ERROR: {e}')

    async def oca_telemetry_program_reader(self,tel):
        try:
            reader = get_reader(f'tic.status.{tel}.toi.ob', deliver_policy='last')
            async for status, meta in reader:
                self.ob_prog_status[tel] = status
                self.update_table()
        except Exception as e:
                logger.warning(f'ERROR: {e}')

    def update_table(self):

        i = -1
        for t in self.main_window.telescope_names:
            i = i + 1

            # TELESKOPY
            txt = t

            item = QTableWidgetItem(txt)
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.obs_t.setItem(i, 0, item)

            # DOME
            state, rgb = "--", (0, 0, 0)
            shutter = self.oca_tel_state[t]["dome_shutterstatus"]["val"]
            moving = self.oca_tel_state[t]["dome_slewing"]["val"]

            if shutter != None or moving != None:
                if shutter == None and moving == None : state,rgb = "SHUTTER and STATUS ERROR",(150, 0, 0)
                elif shutter == None: state,rgb = "SHUTTER ERROR",(150, 0, 0)
                elif moving == None : state,rgb = "DOME STATUS ERROR",(150, 0, 0)
                else:
                    if moving: state,rgb = "MOVING",(255, 160, 0)
                    elif shutter==0: state,rgb = "OPEN",(0, 150, 0)
                    elif shutter==1: state,rgb = "CLOSED",(150, 150, 150)
                    elif shutter==2: state,rgb = "OPENING",(255, 160, 0)
                    elif shutter==3: state,rgb = "CLOSING",(255, 160, 0)
                    else: state,rgb = "SHUTTER ERROR",(150, 0, 0)

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
                if status == 3: state,rgb = "OPEN",(0, 150, 0)
                elif status == 1: state, rgb = "CLOSED", (150, 150, 150)
                elif status == 2: state, rgb = "MOVING", (255, 160, 0)
                else: state,rgb = "ERROR",(150, 0, 0)

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
                if motors == "false": state,rgb = "MOTORS OFF", (150, 150, 150)
                elif slewing: state,rgb = "SLEWING", (255, 160, 0)
                elif tracking: state,rgb = "TRACKING",(0, 150, 0)
                else: state,rgb = "IDLE",(150, 150, 150)

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
                filtr = str(pos)
            except:
                pass
            #if pos != None:
            #    filtr = self.nats_cfg[t]["filter_list_names"][pos]

            if ccd != None :
                if ccd == 2:
                    state,rgb = f"EXP [{filtr}]", (0, 150, 0)
                elif ccd == 0:
                    state,rgb = f"IDLE [{filtr}]", (150, 150, 150)
                else:
                   state, rgb = f"NO IDEA [{filtr}]", (100, 100, 100)

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
                    state,rgb = f"{program.split()[1]}", (0, 150, 0)
                else:
                    if len(program.split())>1:
                        state, rgb = f"{program.split()[0]} {program.split()[1]}", (0, 150, 0)
                    else:
                        state, rgb = f"{program.split()[0]}", (0, 150, 0)
                if dt == None or t0 == None:
                    state = f"{state} (??)"
                else:
                    t = time.time() - t0
                    p = t / dt
                    if p > 1.2:
                        rgb = (150, 0, 0)
                        state = f"{state} (??)"
                    state = f"{state} ({int(p*100)}%)"
            else:
                rgb = (150, 150, 150)
                state = f"IDLE"


            item = QTableWidgetItem(state)
            item.setForeground(QtGui.QBrush(QtGui.QColor(*rgb)))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.obs_t.setItem(i, 5, item)

            self.obs_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

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