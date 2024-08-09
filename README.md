# oca_monitor

Program with GUI to monitor different systems (telescopes, weather, environement, electricity, etc.) at Observatorio Cerro Murphy.

Requirements:
python 3
PyQt5
astropy
matplotlib

# Running
python oca_monit.py

# Adding/modifying tabs
Edit oca_monit_tabs.py and add new tab name to the "tabList" (the and of the file)

# Adding/modifying telescopes
Edit oca_monit_telescopes.py and add new telescope name to the "telescopesList" (the and of the file)

# Installing on Raspberry PI
Usually installing oca monitor on RPi is a nightmare (poetry install cannot install several python libraries and it has to be done manually, which is also problematic) then it is much better to make a copy of a SD card of working RPi with oca_monitor already installed. A copy is available on a pendrive. Everything you have to do is to insert pendrive to some PC (or your laptop) with SD card slot. Insert also a new (or used but not needed) SD card and check in /dev/ what is the name of pendrive and SD card (disconnect pendrive list content of `/dev/` directory, and then connect it and see what appeard, it should be something like `/dev/sd...`, repeat the procedure for SD card). Then use the command:

```
dd bs=4M if=/dev/pendrive_name of=/dev/sd_name status=progress
```

Wait about 10 minutes. When it is ready you can insert SD card to RPi and boot. Now  you just have to change the host name (in Raspberry Menu>Preferences>Raspberry Pi Configuration). Then make sure that the mac address of the new RPi is different from already existing in the network (it has to be different, but make sure :)). Now your RPi is configured and you can run oca monitor.