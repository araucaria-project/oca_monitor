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
bbox_led_control_tvroom = {'tvroom':'192.168.7.221'}
bbox_led_control_kitchen ={'kitchen':'192.168.7.222'}
bbox_led_control_controlroom = {'controlroom':'192.168.7.223'}
bbox_led_control_tel = {'zb08':'192.168.7.216','wk06':'192.168.7.217','jk15':'192.168.7.218','iris':'192.168.7.215','wg25':'192.168.7.219','tmmt':'192.168.7.220'}
bbox_blinds_control = {'bodega':'192.168.7.190','kitchen':'192.168.7.191'}
bbox_bedroom_west = {'hot_water':'192.168.7.225'}
bbox_sirens = {'electric_room':'192.168.7.188'}

#pushover user,token
pushover = {'Piotrek':['uacjyhka7d75k5i3gmfhdg9pc2vqyf','adcte9qacd6jhmhch8dyw4e4ykuod2'],'Marek':['ugcgrfrrfn4eefnpiekgwqnxfwtrz5','adcte9qacd6jhmhch8dyw4e4ykuod2'],'OCMFON':['uqizn1afohvpeymtpu7cq67rabiidx','adcte9qacd6jhmhch8dyw4e4ykuod2'],'Weronika':['uqiowbkk91544jc5zab54vnsp5fjb2','adcte9qacd6jhmhch8dyw4e4ykuod2'],'Paulina':['ucw5v3tyxwpes9e6wznf59f2s7hfzy','adcte9qacd6jhmhch8dyw4e4ykuod2']}#,'Mikolaj':[],'Mirek':[],'Bartek':[]}
# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
