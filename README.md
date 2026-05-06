# oca_monitor

Program with GUI to monitor different systems (telescopes, weather, environement, electricity, etc.) at Observatorio
Cerro Murphy.

Requirements:
* python 3
* PyQt6
* astropy
* matplotlib

# Running

```bash
poetry run ocam --env <envname>
```

where `<envname>` is the name of the settings section (e.g. `kitchen`)

# Chart overlays — FWHM and Photometric Zero

The weather/conditions page (`pages/weather.py`) renders a stack of squeezed
charts. Two of them carry a large in-chart overlay value with non-obvious
semantics:

**FWHM (`fwhm` chart) — round-robin overlay.** The overlay does not show
"the most recent FWHM regardless of telescope". Instead it cycles through
telescopes every 3 s (`OVERLAY_ROTATE_SEC`), showing each telescope's last
FWHM in turn, coloured by that telescope. A telescope is included in the
rotation only while its last sample arrived within 15 minutes
(`OVERLAY_FRESH_WINDOW_SEC`) of the most recent sample on *any*
telescope — the gate is inter-telescope arrival skew, not wall-clock,
so when all telescopes stop together at the end of the night they all
keep cycling (showing the seeing at end-of-night), while a single
telescope that stalls or is taken offline mid-night drops out about
15 minutes later so observers aren't misled by stale seeing.

**Photometric Zero (`phot_zero` chart) — site-wide trend overlay.** The
overlay tracks the *trend line's* tip (the bright white smoothed mean
across all telescopes), not any single telescope's last frame, so it
conveys current site-wide photometric quality. Its colour follows the
alert zones: green when the site is photometric, amber when degraded,
red when poor. The white trend line itself sits above the per-telescope
scatter at high opacity so it reads as the headline signal of the panel
without being thick enough to obscure individual points.

# Adding/modifying tabs

Edit oca_monit_tabs.py and add new tab name to the "tabList" (the and of the file)

# Adding/modifying telescopes

Edit oca_monit_telescopes.py and add new telescope name to the "telescopesList" (the and of the file)

# Installing on Raspberry PI

Usually installing oca monitor on RPi is a nightmare (poetry install cannot install several python libraries and it has
to be done manually, which is also problematic) then it is much better to make a copy of a SD card of working RPi with
oca_monitor already installed. A copy is available on a pendrive. Everything you have to do is to insert pendrive to
some PC (or your laptop) with SD card slot. Insert also a new (or used but not needed) SD card and check in /dev/ what
is the name of pendrive and SD card (disconnect pendrive list content of `/dev/` directory, and then connect it and see
what appeard, it should be something like `/dev/sd...`, repeat the procedure for SD card). Then use the command:

```
dd bs=4M if=/dev/pendrive_name of=/dev/sd_name status=progress
```

Wait about 10 minutes. When it is ready you can insert SD card to RPi and boot. Now you just have to change the host
name (in Raspberry Menu>Preferences>Raspberry Pi Configuration). Then make sure that the mac address of the new RPi is
different from already existing in the network (it has to be different, but make sure :)). Now your RPi is configured
and you can run oca monitor.

# Adding application icon to the menu

To add application icon to the menu you have to symlink the desktop file to the `~/.local/share/applications/`
directory.
The desktop files are located in the `desktop` directory of the project.
The command to do this is e.g:

```bash
ln -s /src/oca_monitor/desktop/tvroom.desktop ~/.local/share/applications/ocam.desktop
```