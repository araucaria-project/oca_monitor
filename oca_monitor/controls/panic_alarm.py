import logging
from typing import Optional

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox
import json, requests
import oca_monitor.config as config
from qasync import asyncSlot


logger = logging.getLogger(__name__.rsplit('.')[-1])


class PanicAlarm:

    def __init__(self, name: str = 'raise_alarm') -> None:
        self.name = name
        self.timeout: float = 5
        self.button = QCheckBox()
        self.button.setStyleSheet("QCheckBox::indicator{width: 270px; height:270px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.button.setChecked(False)
        self.c: Optional[QDialog] = None
        self.d: Optional[QDialog] = None

    def alarm_window(self):
        print(self.button.isChecked())
        if self.button.isChecked():
            self.d = QDialog()
            layout = QVBoxLayout()
            l1 = QHBoxLayout()
            self.d.setWindowTitle("ALARM")
            self.d.button_silent_test = QPushButton()
            self.d.button_silent_test.setText('TEST')
            self.d.button_silent_test.clicked.connect(lambda: self.raise_alarm('OCM: TEST,' ,wyj=0))
            self.d.button_silent_test.setStyleSheet \
                ('QPushButton {background-color: white; border:  grey; font: bold;font-size: 32px; color: black;height: 160px;width: 220px}')

            self.d.button_siren = QPushButton()
            self.d.button_siren.setText('SIREN')
            self.d.button_siren.clicked.connect(lambda: self.raise_alarm('' ,wyj=1))
            self.d.button_siren.setStyleSheet \
                ('QPushButton {background-color: yellow; border:  grey; font: bold;font-size: 34px;color: black;height: 160px;width: 220px}')

            self.d.button_sirenstop = QPushButton()
            self.d.button_sirenstop.setText('SIREN STOP')
            self.d.button_sirenstop.clicked.connect(lambda: self.raise_alarm('' ,wyj=0))
            self.d.button_sirenstop.setStyleSheet \
                ('QPushButton {background-color: orange; border:  grey; font: bold;font-size: 34px;color: black;height: 160px;width: 220px}')

            self.d.button_alarm = QPushButton()
            self.d.button_alarm.setText('REAL ALARM')
            self.d.button_alarm.clicked.connect(lambda: self.raise_alarm('OCM: HELP US,' ,wyj=1))
            self.d.button_alarm.setStyleSheet \
                ('QPushButton {background-color: red; border:  grey; font: bold;font-size: 34px;color: black;height: 160px;width: 220px}')

            self.d.button_close = QPushButton()
            self.d.button_close.setText('EXIT')
            self.d.button_close.clicked.connect(self.d_close_clicked)
            self.d.button_close.setStyleSheet \
                ('QPushButton {background-color: grey; border:  grey; font: bold;font-size: 34px;color: black;height: 100px;width: 400px}')


            l1.addWidget(self.d.button_silent_test)
            l1.addWidget(self.d.button_siren)
            l1.addWidget(self.d.button_sirenstop)
            l1.addWidget(self.d.button_alarm)

            layout.addLayout(l1)
            layout.addWidget(self.d.button_close)


            self.d.setLayout(layout)
            self.d.exec()

            # self.d.setGeometry(500,300,1400,500)

        return 1

    def d_close_clicked(self):
        self.d.close()
        self.button.setChecked(False)
        print('status' ,self.button.isChecked())
        self.raise_alarm()

    @asyncSlot()
    async def raise_alarm(self ,mess ,wyj=0):
        if len(mess) > 0:
            for name ,po_data in config.pushover.items():

                user = po_data[0]
                token = po_data[1]
                await self.push(name ,user ,token ,mess)

            self.c = QDialog()
            label = QLabel()
            label.setText('ALARM SENT')
            label.setStyleSheet("QLabel{font-size: 40pt;background-color: white; color:red}")
            button = QPushButton('OK')
            button.clicked.connect(self.c_close_clicked)
            layout = QVBoxLayout()
            layout.addWidget(label)
            layout.addWidget(button)
            self.c.setLayout(layout)
            self.c.exec()

        await self.siren(wyj)
        self.d_close_clicked()

    async def push(self, name ,user ,token ,mess):
        pars = {'token' :token ,'user' :user ,'message' :mess +name +'!'}
        try:
            requests.post('https://api.pushover.net/1/messages.json' ,data=pars)
        except:
            pass

    def c_close_clicked(self):
        self.c.close()

    async def siren(self,wyj):
        for siren, ip in config.bbox_sirens.items():
            requests.post(f'http://{ip}/state',json={"relays":[{"relay":0,"state":wyj}]})
