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
        self.main_window = main_window
        self.subject = subject
        self.vertical = bool(vertical_screen)
        self.initUI()
        QTimer.singleShot(0, self.async_init)
        #self.script_location = os.path.dirname(os.path.abspath(__file__))

    @asyncSlot()
    async def async_init(self):

        for tel in ["wk06","zb08","jk15"]:
            await create_task(self.toi_message_reader(tel), "message_reader")


    def initUI(self,):
        self.layout = QHBoxLayout(self)
        self.info_e = QTextEdit()

        self.layout.addWidget(self.info_e)


    async def toi_message_reader(self,tel):
        try:
            r = get_reader(f'tic.status.{tel}.toi.message', deliver_policy='new')
            async for data, meta in r:
                txt = f"{time.strftime('%H:%M:%S', time.gmtime())}"
                print(os.getcwd())
                if "BELL" in data['info']:
                    txt = f"(UT {txt}) {data['info']} by {data['tel']}"
                    self.info_e.append(txt)
                    subprocess.run(["aplay",f"{os.getcwd()}/sounds/romulan_alarm.wav"])
                if "STOP" in data['info']:
                    txt = f"(UT {txt}) {data['info']} reached by {data['tel']}"
                    self.info_e.append(txt)
                    subprocess.run(["aplay",f"{os.getcwd()}/sounds/alert06.wav"])


        except Exception as e:
            logger.warning(f'{e}')


widget_class = MessageWidget