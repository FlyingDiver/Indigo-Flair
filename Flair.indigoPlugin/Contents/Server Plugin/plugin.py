#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import platform
import time

from flair import FlairAccount


class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))


    def startup(self):
        self.logger.info(u"Starting Flair")
       
        macOS = platform.mac_ver()[0]
        self.logger.debug(u"macOS {}, Indigo {}".format(macOS, indigo.server.version))
        if int(macOS[3:5]) < 13:
            self.logger.error(u"Unsupported macOS version! {}".format(macOS))
                
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "15")) *  60.0
        self.logger.debug(u"updateFrequency = {}".format(self.updateFrequency))
        self.next_update = time.time() + self.updateFrequency
        
        self.flair_accounts = {}
        self.flair_vents = {}
        self.account_data = {}
        
        self.update_needed = False
        

    def shutdown(self):
        self.logger.info(u"Stopping Flair")
        

    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        updateFrequency = int(valuesDict['updateFrequency'])
        if (updateFrequency < 5) or (updateFrequency > 60):
            errorDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 5 and 60)"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)

        return True

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.logger.debug(u"closedPrefsConfigUi called")
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))

            self.updateFrequency = float(valuesDict['updateFrequency']) * 60.0
            self.logger.debug(u"updateFrequency = {}".format(self.updateFrequency))
            self.next_update = time.time()
        
        
    def deviceStartComm(self, dev):
        self.logger.info(u"{}: Starting {} Device {}".format(dev.name, dev.deviceTypeId, dev.id))
        
        if dev.deviceTypeId == 'FlairAccount':     # create the Flair account object.  It will attempt to refresh the auth token.
            
            account = FlairAccount(dev, refresh_token = dev.pluginProps['RefreshToken'])
            self.flair_accounts[dev.id] = account
            newProps = dev.pluginProps
            newProps["RefreshToken"] = account.refresh_token
            dev.replacePluginPropsOnServer(newProps)
            
            dev.updateStateOnServer(key="authenticated", value=account.authenticated)
            self.update_needed = True
        
        elif dev.deviceTypeId == 'FlairVent':
            self.flair_vents[dev.id] = dev
            

    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

        if dev.deviceTypeId == 'FlairAccount':
            if dev.id in self.flair_accounts:
                del self.flair_accounts[dev.id]
            
        elif dev.deviceTypeId == 'FlairVent':
            if dev.id in self.flair_vents:
                del self.flair_vents[dev.id]
 
    # need this to keep the device from start/stop looping when the refresh token is updated
    
    def didDeviceCommPropertyChange(self, origDev, newDev):
        if newDev.deviceTypeId == "FlairAccount":
            if origDev.pluginProps['username'] != newDev.pluginProps['username']:
                return True
            elif origDev.pluginProps['password'] != newDev.pluginProps['password']:
                return True    
            return False    
        
        else:
            return True  


    ########################################
        
    def runConcurrentThread(self):
        self.logger.debug(u"runConcurrentThread starting")
        try:
            while True:
                
                if (time.time() > self.next_update) or self.update_needed:
                    self.update_needed = False
                    self.next_update = time.time() + self.updateFrequency
                
                    # update from Flair servers
                    
                    for accountID, account in self.flair_accounts.iteritems():
                        device = indigo.devices[accountID]
                        if not account.authenticated:
                            device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                            self.logger.debug("{}: Flair account not authenticated, skipping update".format(device.name))
                        else:
                            self.account_data[accountID] = account.server_update()
                            device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

                            
                    # update devices
                    
                    for ventID in self.flair_vents:
                        device = indigo.devices[ventID]
                        vent = self.account_data[int(device.pluginProps['flair_account'])][device.pluginProps['flair_structure']]['vents'][device.pluginProps['flair_vent']]
                        vopen = vent['percent-open']
                        device.updateStateOnServer("brightnessLevel", vopen)
                        if vopen == 0:
                            device.updateStateImageOnServer(indigo.kStateImageSel.FanOff)
                        elif vopen == 100:
                            device.updateStateImageOnServer(indigo.kStateImageSel.FanHigh)
                        else:
                            device.updateStateImageOnServer(indigo.kStateImageSel.FanMedium)
                        
                        
                        

                # Refresh the auth tokens as needed.  Refresh interval for each account is calculated during the refresh
                
                for accountID, account in self.flair_accounts.items():
                    if time.time() > account.next_refresh:
                        if account.authenticated:
                            account.do_token_refresh()  
                            device = indigo.devices[accountID]                  
                            newProps = device.pluginProps
                            newProps["RefreshToken"] = account.refresh_token
                            device.replacePluginPropsOnServer(newProps)

                        else:
                            self.logger.error("Flair account {} not authenticated, skipping refresh".format(accountID))

                self.sleep(2.0)

        except self.StopThread:
            self.logger.debug(u"runConcurrentThread ending")
            pass

                
    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def get_account_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug("get_account_list: typeId = {}, targetId = {}, valuesDict = {}".format(typeId, targetId, valuesDict))
        accounts = [
            (accountID, indigo.devices[accountID].name)
            for accountID in self.flair_accounts
        ]
        self.logger.debug("get_account_list: accounts = {}".format(accounts))
        return accounts
        

    def get_structure_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug("get_structure_list: typeId = {}, targetId = {}, valuesDict = {}".format(typeId, targetId, valuesDict))
        
        try:
            structures = [
                (key, value['attributes']['name'])
                for key, value in self.account_data[int(valuesDict["flair_account"])].iteritems()
            ]
        except:
            structures = []
        self.logger.debug("get_structure_list: structures = {}".format(structures))
        return structures
        
        

    def get_vent_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug("get_vent_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))

        try:
            structure = self.account_data[int(valuesDict["flair_account"])][valuesDict["flair_structure"]]
            self.logger.debug("get_vent_list: structure->vents = {}".format(structure['vents']))
            vents = [
                (key, value['name'])
                for key, value in structure['vents'].iteritems()
            ]
        except:
            vents = []
        self.logger.debug("get_vent_list: vents = {}".format(vents))
        return vents
        

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict      

        
    def actionControlUniversal(self, action, dev):
        self.logger.debug(u"{}: action.actionControlUniversal: {}".format(dev.name, action.deviceAction))
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.update_needed = True
        else:
            self.logger.warning(u"{}: Unimplemented action.deviceAction: {}".format(dev.name, action.deviceAction))

        
    def menuDumpData(self):
        self.logger.debug(u"menuDumpData")
        for accountID in self.flair_accounts:
            device = indigo.devices[accountID]
            self.logger.info("{} ({}): Data:\n{}".format(device.name, device.id, json.dumps(self.account_data[accountID], sort_keys=True, indent=4, separators=(',', ': '))))
        return True

             
            

