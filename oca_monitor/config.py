import os

from dynaconf import Dynaconf

# For the configuration values, see settings.toml and (optionally) .secrets.toml

# Default configuration is in [oca] section

settings = Dynaconf(
    envvar_prefix="OCAMONITOR",
    settings_files=['settings.toml', '.secrets.toml'],
    environments=True,
    env_switcher='OCAMONITOR_ENV',
)
bbox_tsensors = {'westbedroom':'192.168.7.199','eastbedroom':'192.168.7.198','electricroom':'192.168.7.206','batteryroom':'192.168.7.207','zb08':'192.168.7.202','jk15':'192.168.7.204'}
bbox_htsensors = {'controlroom':'192.168.7.192','serverroom':'192.168.7.193'}
bbox_led_control = {'tvroom':'192.168.7.221'}
bbox_led_control_tel = {'zb08':'192.168.7.216'}
bbox_blinds_control = {'bodega':'192.168.7.190','kitchen':'192.168.7.191'}
# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
