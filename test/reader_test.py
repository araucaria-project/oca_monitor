import asyncio
import datetime

import serverish
from serverish.messenger import Messenger


async def start():
    msg = Messenger()
    await msg.open("nats.oca.lan", 4222, wait=3)
    print(f"Connected")
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    print(f"Passsed")
    rdr = msg.get_reader(
        "",
        deliver_policy='by_start_time',
        opt_start_time=ts
    )
    async for data, meta in rdr:
        print(data)
        print(meta)

asyncio.run(start())
