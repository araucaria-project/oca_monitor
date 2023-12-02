#!/usr/bin/env python

import json,requests,time

urls = ["http://192.168.20.97/state","http://192.168.20.109/state"]

while True:
    for url in urls:
        try:
            resp = requests.get(url)
            resp_json = resp.json()

            #resp_json_dumped = json.dumps(resp_json)
            #resp_json_dic = 
            data = resp_json['tempSensor']['sensors'][0]

            print(data[u'value']/100.)
        except:
            print(url,"not active")

    time.sleep(5)


'''#temperature:
192.168.20.98
192.168.20.109

#water level
192.168.20...

#diesel level
192.168.20...'''

