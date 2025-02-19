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
ht_subjects = {'controlroom-htsensor':['',900,350],'serverroom-htsensor':['',650,350],'iris-htsensor':['IRIS',0,0],'zb08-htsensor':['ZB08',0,0],'jk15-htsensor':['JK15',0,0],'wk06-htsensor':['WK06',300,350],'kitchen-htsensor':['',1150,350],'bodega-tsensor':['',1350,350],'tvroom-htsensor':['',900,600],'bedroom-east-tsensor':['',1100,900],'bedroom-west-tsensor':['',650,900],'electricroom-tsensor':['Electric room',0,0],'batteryroom-tsensor':['Battery room',0,0]}#',bedroom-small':['',650,600]}
#small bathroom 1200,600, bath west 650,720, bath east 700,900
bbox_htsensors = {'controlroom':'192.168.7.192','serverroom':'192.168.7.193'}
bbox_led_control_main={'tvroom':'192.168.7.221','kitchen':'192.168.7.222','controlroom':'192.168.7.223'}
bbox_led_control_tel = {'zb08':'192.168.7.216','wk06':'192.168.7.217','jk15':'192.168.7.218','iris':'192.168.7.215','wg25':'192.168.7.219','tmmt':'192.168.7.220'}
bbox_blinds_control = {'bodega':'192.168.7.190','kitchen':'192.168.7.191'}
bbox_bedroom_west = {'hot_water':'192.168.7.225'}
bbox_sirens = {'electric_room':'192.168.7.188'}

#pushover user,token
pushover = {'Piotrek':['uacjyhka7d75k5i3gmfhdg9pc2vqyf','adcte9qacd6jhmhch8dyw4e4ykuod2'],'Marek':['ugcgrfrrfn4eefnpiekgwqnxfwtrz5','adcte9qacd6jhmhch8dyw4e4ykuod2'],'OCMFON':['uqizn1afohvpeymtpu7cq67rabiidx','adcte9qacd6jhmhch8dyw4e4ykuod2'],'Weronika':['uqiowbkk91544jc5zab54vnsp5fjb2','adcte9qacd6jhmhch8dyw4e4ykuod2'],'Paulina':['ucw5v3tyxwpes9e6wznf59f2s7hfzy','adcte9qacd6jhmhch8dyw4e4ykuod2'],'Bartek':['um9frmos5gui4i57evs98yr6x33w93','adcte9qacd6jhmhch8dyw4e4ykuod2']}#,'Mikolaj':[],'Mirek':[],'Bartek':[]}
# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.