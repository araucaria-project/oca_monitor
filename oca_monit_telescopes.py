#!urs/bin/env python

#################################################################
#                                                               #
#         TELESCOPES CLASS TO BE DISPLAYED IN OCA_MONITOR       #
#                   Cerro Armazones Observatory                 #
#                      Araucaria Group, 2023                    #
#               contact person pwielgor@camk.edu.pl             #
#                                                               #
#################################################################

class telescope():
    def __init__(self,name,ticport,cdtvpath,fitspath):
        self.name = name
        self.ticport = ticport
        self.cdtv = cdtvpath
        self.fitspath = fitspath

    #def update_status(self):

    #def cdtvimage(self):

    #def lastfits(self):

telescopesList=[telescope("WK06",1,1,1),telescope("ZB08",1,1,1),telescope("JK15",1,1,1),telescope("IRIS",1,1,1)]#,telescope("WG25",1,1,1)]

'''class Telescope(QtWidgets.QWidget):
    def __init__(self,name,port,lastim_location,ctv):
        self.name = name
        self.port = port'''
