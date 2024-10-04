import logging
import os
import subprocess
import time

from PyQt6.QtWidgets import  QWidget, QHBoxLayout, QTextEdit
from PyQt6.QtCore import QTimer

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

    @asyncSlot()
    async def async_init(self):

        for tel in self.parent.telescope_names:
            await create_task(self.toi_message_reader(tel), "message_reader")


    def initUI(self,):
        self.layout = QHBoxLayout(self)
        self.info_e = QTextEdit()

        self.layout.addWidget(self.info_e)

    def play_sun_alt(self, go):
        if go and self.one_sun_sound:
            txt = f"{time.strftime('%H:%M:%S', time.gmtime())}"
            txt = f"(UT {txt}) Sun altitude caution!"
            self.info_e.append(txt)
            subprocess.run(["aplay", f"{os.getcwd()}/sounds/alert23.wav"])
            self.one_sun_sound = False
        elif not go:
            self.one_sun_sound = True

    def play_weather_warning(self,go):
        if go and self.one_weather_warning:
            txt = f"{time.strftime('%H:%M:%S', time.gmtime())}"
            txt = f"(UT {txt}) Weather warning!"
            self.info_e.append(txt)
            subprocess.run(["aplay", f"{os.getcwd()}/sounds/alert09.wav"])
            self.one_weather_warning = False
        elif not go:
            self.one_weather_warning = True

    def play_weather_stop(self, go):

        if go and self.one_weather_stop:
            txt = f"{time.strftime('%H:%M:%S', time.gmtime())}"
            txt = f"(UT {txt}) Weather STOP!"
            self.info_e.append(txt)
            subprocess.run(["aplay", f"{os.getcwd()}/sounds/klingon_alert.wav"])
            self.one_weather_stop = False
        elif not go:
            self.one_weather_stop = True

    async def toi_message_reader(self,tel):
        try:
            r = get_reader(f'tic.status.{tel}.toi.message', deliver_policy='new')
            async for data, meta in r:
                txt = f"{time.strftime('%H:%M:%S', time.gmtime())}"
                if "info" in data.keys() and "tel" in data.keys():
                    if "BELL" in data['info']:
                        txt = f"(UT {txt}) {data['info']} by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/romulan_alarm.wav"])
                    elif "STOP" in data['info']:
                        txt = f"(UT {txt}) {data['info']} reached by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/alert06.wav"])
                    elif "PING" in data['info']:
                        txt = f"(UT {txt}) {data['info']} reached by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/tos_alien_sound_4.wav"])
                    else:
                        txt = f"(UT {txt}) {data['info']} by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/computerbeep_12.wav"])


        except Exception as e:
            logger.warning(f'{e}')


widget_class = MessageWidget