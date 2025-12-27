import asyncio
import logging

from PyQt6.QtWidgets import QCheckBox
import aiohttp
from qasync import asyncSlot


logger = logging.getLogger(__name__.rsplit('.')[-1])


class WaterPump:
    def __init__(self, ip: str, name: str = 'hot_water'):
        self.name = name
        self.timeout: float = 5
        self.ip = ip
        self.button = QCheckBox()
        self.button.setStyleSheet("QCheckBox::indicator{width: 170px; height:170px;} QCheckBox::indicator:checked {image: url(./Icons/hot_water_on.png)} QCheckBox::indicator:unchecked {image: url(./Icons/hot_water_off.png)}")
        self.button.setChecked(False)

    @property
    def url(self) -> str:
        return f'http://{self.ip}/state'

    @asyncSlot()
    async def button_pressed(self) -> None:
        # Water pump signal need to be pressed for 2 seconds to get effect
        await self.change_state()
        await asyncio.sleep(2)
        self.button.setChecked(False)

    @asyncSlot()
    async def change_state(self):

        if self.button.isChecked():
            value = 1
        else:
            value = 0
        logger.info(f'Water pomp sent {value} to {self.url}')
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                await session.post(
                    self.url,
                    json={"relays": [{"relay": 0, "state": value}]}
                )
                logger.info(f'Water pomp sent to state {value}')
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.error(f'Hot water pump can not be connected')
