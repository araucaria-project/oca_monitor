import logging
import os
import subprocess
import time

from PyQt6.QtWidgets import  QWidget, QHBoxLayout, QTextEdit
from PyQt6.QtCore import QTimer, Qt

from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import get_reader


logger = logging.getLogger(__name__.rsplit('.')[-1])

class MessageWidget(QWidget):
    def __init__(self, main_window, subject='telemetry.weather.davis', vertical_screen = False, **kwargs):
        super().__init__()
        self.parent = main_window
        self.subject = subject
        self.vertical = bool(vertical_screen)
        self.initUI()
        self.parent.sound_page = self
        self.one_sun_sound = True
        self.one_weather_warning = True
        self.one_weather_stop = True
        QTimer.singleShot(0, self.async_init)
        #self.script_location = os.path.dirname(os.path.abspath(__file__))
        logger.info(f"MessageWidget init setup done")

    @asyncSlot()
    async def async_init(self):
        await create_task(self.reader_ocm_messages(), "message_reader")

    def initUI(self,):
        self.layout = QHBoxLayout(self)
        self.info_e = QTextEdit()

        self.layout.addWidget(self.info_e)
        # logger.info(f"MessageWidget UI setup done")


    async def reader_ocm_messages(self):
            r = get_reader(f'tic.status.ocm.messages', deliver_policy='new')
            async for data, meta in r:
                try:
                    label = data["label"]
                    c = Qt.GlobalColor.gray
                    if label == "INFO":
                        c = Qt.GlobalColor.gray
                    elif label == "PING":
                        c = Qt.GlobalColor.darkYellow
                        subprocess.run(["aplay", f"{os.getcwd()}/sounds/tos_alien_sound_4.wav"])
                    elif label == "PROGRAM STOP":
                        c = Qt.GlobalColor.gray
                        subprocess.run(["aplay", f"{os.getcwd()}/sounds/alert07.wav"])
                    elif label == "PROGRAM BELL":
                        c = Qt.GlobalColor.gray
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/romulan_alarm.wav"])
                    elif label == "PROGRAM ERROR":
                        c = Qt.GlobalColor.red
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/alert06.wav"])
                    elif label == "WEATHER ALERT":
                        c = Qt.GlobalColor.red
                        subprocess.run(["aplay", f"{os.getcwd()}/sounds/klingon_alert.wav"])
                    elif label == "WEATHER WARNING":
                        c = Qt.GlobalColor.darkYellow
                        subprocess.run(["aplay", f"{os.getcwd()}/sounds/alert09.wav"])
                    elif label == "SUN WARNING":
                        c = Qt.GlobalColor.darkYellow
                        subprocess.run(["aplay", f"{os.getcwd()}/sounds/alert23.wav"])
                    elif label == "FWHM WARNING":
                        c = Qt.GlobalColor.darkYellow
                        subprocess.run(["aplay", f"{os.getcwd()}/sounds/computerbeep_12.wav"])
                    else:
                        c = Qt.GlobalColor.gray
                        subprocess.run(["aplay", f"{os.getcwd()}/sounds/computerbeep_12.wav"])


                    # if label == "TOI RESPONDER":
                    #     c = QtCore.Qt.darkGreen
                    # if label == "PLANRUNNER":
                    #     c = QtCore.Qt.darkGray

                    txt = f'{data["ut"]} [{data["user"]}] {data["info"]}'
                    self.info_e.setTextColor(c)
                    self.info_e.append(txt)
                    self.info_e.repaint()


                except Exception as e:
                    logger.warning(f'{e} {data}')


widget_class = MessageWidget