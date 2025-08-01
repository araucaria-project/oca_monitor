import logging
import datetime

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QHBoxLayout, QLabel
from PyQt6.QtCore import QTimer
from PyQt6 import QtGui
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
import numpy as np

import oca_monitor.config as config


logger = logging.getLogger(__name__.rsplit('.')[-1])

class sensor():
    def __init__(self,name,name_to_display='',x=0,y=0):
        self.name = name
        self.name_to_display = name_to_display
        self.temp = "Undef"
        self.hum = "Undef"
        self.x = x
        self.y = y

class ConditionsScreensWidget(QWidget):
    def __init__(self, main_window, subject_conditions='telemetry.conditions', subject_water='telemetry.water.level', subject_energy='telemetry.power.data-manager', vertical_screen = True, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.subject_water = subject_water
        self.subject_energy = subject_energy
        self.subject_conditions = subject_conditions
        self.vertical = bool(vertical_screen)
        self.sensors = {}
        self.htsensors = config.ht_subjects
        self.initUI()
        QTimer.singleShot(0, self.async_init)
        # async init
        

    @asyncSlot()
    async def async_init(self):
        #obs_config = await self.main_window.observatory_config()
        await create_task(self.reader_loop_water(), "reader_water")
        await create_task(self.reader_loop_energy(), "reader_energy")
        for sens,params in self.htsensors.items():
            if sens not in self.sensors.keys():
                self.sensors[sens]=sensor(sens,params[0],x=params[1],y=params[2])
                print(sens,params[1],params[2])
            subject = self.subject_conditions+'.'+sens
            await create_task(self.reader_loop_conditions(subject,sens), "reader_conditions")


    def initUI(self):
        # Layout
        self.layout = QVBoxLayout(self)
        self.label_water = QLabel()
        self.label_water.setStyleSheet("background-color : cyan; color: black")
        self.label_water.setFont(QtGui.QFont('Arial', 22))
        self.label_conditions = QLabel()
        self.label_conditions.setStyleSheet("background-color : white; color: black")
        self.label_energy = QLabel()
        self.label_energy.setStyleSheet("background-color : pink; color: black")
        self.label_energy.setFont(QtGui.QFont('Arial', 22))
        # Matplotlib setup
        self.figure = Figure(figsize=(24,16),facecolor='lightgrey')
        self.canvas = FigureCanvas(self.figure)
        self.layout.addWidget(self.canvas)
        self.draw_figure()
        self.layout.addWidget(self.label_water)
        self.layout.addWidget(self.label_energy)
        self.temp_layout = QHBoxLayout(self)
        self.temp_layout.addWidget(self.label_conditions)
        self.temp_layout.addWidget(self.canvas)
        self.layout.addLayout(self.temp_layout)


    async def reader_loop_conditions(self,subject,sens):
        msg = Messenger()
        
        try:

            rdr = msg.get_reader(
                subject,
                deliver_policy='last',
            )
            logger.info(f"Subscribed to {subject}")

                
            async for data, meta in rdr:
                
                if True:
                    # if we crossed the midnight, we want to copy today's data to yesterday's and start today from scratch
                        
                    self.ts = dt_ensure_datetime(data['ts'])
                    measurement = data['measurements']
                    self.sensors[sens].temp = measurement['temperature']
                    logger.debug(f"Measured temperature {self.sensors[sens].name+' '+str(self.sensors[sens].temp)}")
                        
                    self.sensors[sens].hum = measurement['humidity']
                    logger.debug(f"Measured humidity {self.sensors[sens].name+' '+str(self.sensors[sens].hum)}")
                        
                        
        except:
            pass

        

    def draw_figure(self):
        self.figure.clf()
        self.figure.gca().tick_params(axis='both', left=False, top=False, right=False, bottom=False, labelleft=False, labeltop=False, labelright=False, labelbottom=False)
        img = mpimg.imread('./oca_monitor/resources/gfx/oca_main_building.png')
        self.figure.gca().imshow(img)
        text = ''
        for s,sens in self.sensors.items():
            
            if int(sens.x)+int(sens.y)!=0:
                #print(s)
                if sens.temp != "Undef":
                    if sens.name_to_display != '':
                        self.figure.gca().text(int(sens.x),int(sens.y)-90,sens.name_to_display,backgroundcolor='lightgreen',color='red',fontsize='large')
                    self.figure.gca().text(int(sens.x),int(sens.y)-20,str(int(sens.temp))+'$^{\circ} C$',backgroundcolor='lightgreen',color='red',fontsize='large')
                if sens.hum != "Undef":
                    self.figure.gca().text(int(sens.x),int(sens.y)+50,str(int(sens.hum))+'%',backgroundcolor='lightgreen',color='red',fontsize='large')

            else:
                
                if sens.temp != "Undef":
                    text = text+'\n'+sens.name_to_display+'\t'
                    text = text+str(int(sens.temp))+'C\t'
                if sens.hum != "Undef":
                   text = text + str(int(sens.hum))+'%'

        self.label_conditions.setText(text)


        self.canvas.draw()
        QTimer.singleShot(10000, self.draw_figure)

        
        

    async def reader_loop_water(self):
        msg = Messenger()
        #try:
        if True:
            # We want the data from the midnight of yesterday

            rdr = msg.get_reader(
                self.subject_water,
                deliver_policy='last'
            )
            logger.info(f"Subscribed to {self.subject_water}")

            
            async for data, meta in rdr:
                
                if True:
                    # if we crossed the midnight, we want to copy today's data to yesterday's and start today from scratch
                    
                    self.ts = dt_ensure_datetime(data['ts'])
                    measurement = data['measurements']
                    self.water_level = measurement['water_level']
                    logger.debug(f"Measured water level {self.water_level}")
                    try:
            
                        self.label_water.setText('Water '+str(self.water_level)+ ' litres')
                    except:
                        self.label_water.setText('No data')
        #except:
        #    pass

    

    async def reader_loop_energy(self):
        msg = Messenger()

        # We want the data from the midnight of yesterday
        today_midnight = datetime.datetime.combine(datetime.date.today(), datetime.time(0))
        yesterday_midnight = today_midnight - datetime.timedelta(days=1)

        rdr = msg.get_reader(
            self.subject_energy,
            deliver_policy='by_start_time',
            opt_start_time=today_midnight,
        )
        logger.info(f"Subscribed to {self.subject_energy}")

        sample_measurement = {
                "state_of_charge": 100,
                "pv_power": 0,
                "battery charge": 0,
                "battery_discharge": 0,
        }
        async for data, meta in rdr:
            try:
            #if True:
                # if we crossed the midnight, we want to copy today's data to yesterday's and start today from scratch
                now = datetime.datetime.now()
                '''if now.date() > today_midnight.date():
                    logger.info("Crossed the midnight, resetting the data")
                    yesterday_midnight = today_midnight
                    today_midnight = datetime.datetime.combine(now.date(), datetime.time(0))
                    self.ln_yesterday_wind.set_data(
                        self.ln_today_wind.get_xdata(),
                        self.ln_today_wind.get_ydata()
                    )
                    self.ln_today_wind.set_data([], [])

                    self.ln_yesterday_temp.set_data(
                        self.ln_today_temp.get_xdata(),
                        self.ln_today_temp.get_ydata()
                    )
                    self.ln_today_temp.set_data([], [])

                    self.ln_yesterday_hum.set_data(
                        self.ln_today_hum.get_xdata(),
                        self.ln_today_hum.get_ydata()
                    )
                    self.ln_today_hum.set_data([], [])

                    self.ln_yesterday_pres.set_data(
                        self.ln_today_pres.get_xdata(),
                        self.ln_today_pres.get_ydata()
                    )
                    self.ln_today_pres.set_data([], [])'''

                # handle current datapoint. it has measurement timestamp in data.ts, and the measurement in data.measurement
                ts = dt_ensure_datetime(data['ts']).astimezone()
                measurement = data['measurements']
                soc = measurement['state_of_charge']
                pv = measurement['pv_power']
                if pv < 0:
                    pv = 0
                bc = measurement['battery_charge']
                bd = measurement['battery_discharge']
                ec = bd + pv - bc
                # depending on the date of the measurement, we want to add point to the yesterday or today data
                hour = ts.hour + ts.minute / 60 + ts.second / 3600
                '''if ts < today_midnight.astimezone():
                    #logger.info(f'Adding point to yesterday data {wind_speed10}')
                    self.ln_yesterday_wind.set_data(
                        list(self.ln_yesterday_wind.get_xdata()) + [hour],
                        list(self.ln_yesterday_wind.get_ydata()) + [wind_speed10]
                    )

                    self.ln_yesterday_temp.set_data(
                        list(self.ln_yesterday_temp.get_xdata()) + [hour],
                        list(self.ln_yesterday_temp.get_ydata()) + [temp]
                    )

                    self.ln_yesterday_hum.set_data(
                        list(self.ln_yesterday_hum.get_xdata()) + [hour],
                        list(self.ln_yesterday_hum.get_ydata()) + [hum]
                    )

                    self.ln_yesterday_pres.set_data(
                        list(self.ln_yesterday_pres.get_xdata()) + [hour],
                        list(self.ln_yesterday_pres.get_ydata()) + [pres]
                    )
                else:
                    #logger.info(f'Adding point to today data {wind_speed10}')
                    self.ln_today_wind.set_data(
                        list(self.ln_today_wind.get_xdata()) + [hour],
                        list(self.ln_today_wind.get_ydata()) + [wind_speed10]
                    )
                    self.ln_today_temp.set_data(
                        list(self.ln_today_temp.get_xdata()) + [hour],
                        list(self.ln_today_temp.get_ydata()) + [temp]
                    )

                    self.ln_today_hum.set_data(
                        list(self.ln_today_hum.get_xdata()) + [hour],
                        list(self.ln_today_hum.get_ydata()) + [hum]
                    )

                    self.ln_today_pres.set_data(
                        list(self.ln_today_pres.get_xdata()) + [hour],
                        list(self.ln_today_pres.get_ydata()) + [pres]
                    )
                # lazy redraw
                
                self.ax_wind.relim()
                self.ax_wind.autoscale_view()

                self.ax_temp.relim()
                self.ax_temp.autoscale_view()

                self.ax_hum.relim()
                self.ax_hum.autoscale_view()

                self.ax_pres.relim()
                self.ax_pres.autoscale_view()
                self.canvas.draw_idle()'''
            except:
                soc = 'NaN'
                pv = 'NaN'
                bc = 'NaN'
                bd = 'NaN'
                ec = 'NaN'

            #try:
            if True:
                text = 'ENERGY:\nClusters state of charge\t'+str(soc)+' %\n' + 'Solar Power\t\t'+str(pv)+' W\n'+ 'Power consumption\t'+str(ec)+' W'
                self.label_energy.setText(text)
        #except:
        #    self.label_energy.setText('No data')
        #    self.label_energy.setText(text)
                                       

widget_class = ConditionsScreensWidget