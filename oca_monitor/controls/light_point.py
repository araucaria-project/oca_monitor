import logging
from qasync import asyncSlot
from oca_monitor.utils import send_http, get_http


logger = logging.getLogger(__name__.rsplit('.')[-1])


class LightPoint:

    def __init__(self ,name ,ip ,slider):
        self.name = name
        self.ip = ip

        self.slider= slider
        self.slider.setGeometry(100, 100, 100, 100)
        self.slider.setNotchesVisible(True)
        self.slider.valueChanged.connect(self.changeLight)

    async def changeLight(self):
        try:
            if self.is_active:
                new_value = int(self.slider.value( ) *255 /100)
                print(new_value)
                if new_value > 255:
                    new_value = 255

                val = str(hex(int(new_value))).replace('0x' ,'' ,1)
                if len(val) == 1:
                    val = '0 ' +val

                await self.req(val)
        except:
            pass

    @asyncSlot()
    async def req(self ,val):
        # try:
        #
        #     requests.post('http://'+self.ip+'/api/rgbw/set',json={"rgbw":{"desiredColor":val}})
        # except:
        #     pass
        await send_http(url='http:// ' +self.ip +'/api/rgbw/set', json={"rgbw" :{"desiredColor" :val}})

    async def status(self):
        try:
            # if True:
            # req = requests.get('http://'+self.ip+'/api/rgbw/state',timeout=0.5)
            req = await get_http(url='http:// ' +self.ip +'/api/rgbw/state', timeout=1)
            if int(req.status_code) != 200:
                self.is_active = False
            else:
                self.is_active = True
                self.curr_value = int(req.json()["rgbw"]["desiredColor"] ,16)
                self.slider.setValue(int(self.curr_value *100 /255))
        except:
            self.is_active = False
