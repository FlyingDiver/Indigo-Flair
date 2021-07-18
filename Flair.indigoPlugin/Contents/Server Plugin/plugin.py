#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import platform
import time

from flair import FlairAccount


minMacOS = "10.13"
def versiontuple(v):
    return tuple(map(int, (v.split("."))))

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
        if versiontuple(macOS) < versiontuple(minMacOS):
            self.logger.error(u"Unsupported macOS version! {}".format(macOS))
                
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "15")) *  60.0
        self.logger.debug(u"updateFrequency = {}".format(self.updateFrequency))
        self.next_update = time.time() + self.updateFrequency
        
        self.flair_accounts = {}
        self.flair_vents = {}
        self.flair_pucks = {}

        self.account_data = {}
        
        self.update_needed = False
        

    def shutdown(self):
        self.logger.info(u"Stopping Flair")
        

    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi, valuesDict = {}".format(valuesDict))
        errorDict = indigo.Dict()

        updateFrequency = int(valuesDict['updateFrequency'])
        if (updateFrequency < 5) or (updateFrequency > 60):
            errorDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 5 and 60)"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)

        return True


    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.logger.debug(u"closedPrefsConfigUi, userCancelled = {}, valuesDict = {}".format(userCancelled, valuesDict))
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


    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        self.logger.debug(u"validateDeviceConfigUi, devId = {}, typeId = {}, valuesDict = {}".format(devId, typeId, valuesDict))
        errorsDict = indigo.Dict()
    
        if typeId ==  'FlairAccount':
            if len(valuesDict['username']) == 0:
                errorsDict['username'] = u"Username required"
            if len(valuesDict['password']) == 0:
                errorsDict['password'] = u"Password required"

        elif typeId == 'FlairPuck': 
        
            if len(valuesDict['flair_puck']) == 0:
                errorsDict['flair_puck'] = u"Flair Puck must be selected"
            if len(valuesDict['flair_account']) == 0:
                errorsDict['flair_account'] = u"Flair Account must be selected"
            if len(valuesDict['flair_structure']) == 0:
                errorsDict['flair_structure'] = u"Flair Structure must be selected"

        elif typeId == 'FlairVent': 
        
            if len(valuesDict['flair_vent']) == 0:
                errorsDict['flair_vent'] = u"Flair Vent must be selected"
            if len(valuesDict['flair_account']) == 0:
                errorsDict['flair_account'] = u"Flair Account must be selected"
            if len(valuesDict['flair_structure']) == 0:
                errorsDict['flair_structure'] = u"Flair Structure must be selected"
        
        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)
    
    def closedDeviceConfigUi(self, valuesDict, userCancelled, typeId, devId):
        self.logger.debug(u"closedDeviceConfigUi, userCancelled = {}, devId = {}, typeId = {}, valuesDict = {}".format(userCancelled, devId, typeId, valuesDict))

        
    def deviceStartComm(self, dev):
        self.logger.info(u"{}: Starting {} Device {}".format(dev.name, dev.deviceTypeId, dev.id))
        
        if dev.deviceTypeId == 'FlairAccount':     # create the Flair account object.  It will attempt to refresh the auth token.
            
            account = FlairAccount(dev.name, refresh_token = dev.pluginProps['RefreshToken'], username = dev.pluginProps['username'], password = dev.pluginProps['password'])
            self.flair_accounts[dev.id] = account
            newProps = dev.pluginProps
            newProps["RefreshToken"] = account.refresh_token
            dev.replacePluginPropsOnServer(newProps)
            
            dev.updateStateOnServer(key="authenticated", value=account.authenticated)
            self.update_needed = True
        
        elif dev.deviceTypeId == 'FlairPuck':
            self.flair_pucks[dev.id] = dev
            self.update_needed = True
            
        elif dev.deviceTypeId == 'FlairVent':
            self.flair_vents[dev.id] = dev
            self.update_needed = True
                        

    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

        if dev.deviceTypeId == 'FlairAccount':
            if dev.id in self.flair_accounts:
                del self.flair_accounts[dev.id]
            
        elif dev.deviceTypeId == 'FlairPuck':
            if dev.id in self.flair_pucks:
                del self.flair_pucks[dev.id]
 
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
            return False  


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
                    
                    for puckID in self.flair_pucks:
                        device = indigo.devices[puckID]
                        puck = self.account_data[int(device.pluginProps['flair_account'])][device.pluginProps['flair_structure']]['pucks'][device.pluginProps['flair_puck']]
                        self.logger.threaddebug("{}: Device update data: {}".format(device.name, puck))
                        update_list = []
                        update_list.append({'key' : "name",                  'value' : puck['name']})
                        update_list.append({'key' : "current-humidity",      'value' : puck['current-humidity']})
                        update_list.append({'key' : "updated-at",            'value' : puck['updated-at']})
                        
                        temp = float(puck['current-temperature-c'])
                        update_list.append({'key' : "current-temperature-c", 'value' : temp})
                        if self.pluginPrefs[TEMPERATURE_SCALE_PLUGIN_PREF] == "C":
                            update_list.append({'key' : 'sensorValue', 'value' : temp, 'uiValue': "{:.1f} °C".format(temp)})
                        else:
                            temp = (9.0 * temp)/5.0 + 32.0
                            update_list.append({'key' : 'sensorValue', 'value' : temp, 'uiValue': "{:.1f} °F".format(temp)})

                        device.updateStatesOnServer(update_list)

                        
                    for ventID in self.flair_vents:
                        device = indigo.devices[ventID]
                        vent = self.account_data[int(device.pluginProps['flair_account'])][device.pluginProps['flair_structure']]['vents'][device.pluginProps['flair_vent']]
                        self.logger.threaddebug("{}: Device update data: {}".format(device.name, vent))
                        update_list = []
                        update_list.append({'key' : "name",               'value' : vent['name']})
                        update_list.append({'key' : "percent-open",       'value' : vent['percent-open'], 'uiValue': "{}%".format(vent['percent-open']) })
                        update_list.append({'key' : "duct-temperature-c", 'value' : vent['duct-temperature-c']})
                        update_list.append({'key' : "duct-pressure",      'value' : vent['duct-pressure']})
                        update_list.append({'key' : "system-voltage",     'value' : vent['system-voltage']})
                        update_list.append({'key' : "rssi",               'value' : vent['rssi']})
                        update_list.append({'key' : "updated-at",         'value' : vent['updated-at']})
                        update_list.append({'key' : "brightnessLevel",    'value' : vent['percent-open'], 'uiValue': "{}%".format(vent['percent-open']) })
                        device.updateStatesOnServer(update_list)
                        
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
                (key, value['structure']['name'])
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
            vents = [
                (key, value['name'])
                for key, value in structure['vents'].iteritems()
            ]
        except:
            vents = []
        self.logger.debug("get_vent_list: vents = {}".format(vents))
        return vents

    def get_puck_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug("get_puck_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))

        try:
            structure = self.account_data[int(valuesDict["flair_account"])][valuesDict["flair_structure"]]
            pucks = [
                (key, value['name'])
                for key, value in structure['pucks'].iteritems()
            ]
        except:
            pucks = []
        self.logger.debug("get_pucks_list: pucks = {}".format(pucks))
        return pucks
        
    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict      

        
    ########################################
    #
    # Menu commands
    #
    ########################################

    def menuDumpData(self):
        self.logger.debug(u"menuDumpData")
        for accountID in self.flair_accounts:
            device = indigo.devices[accountID]
            self.logger.info("{} ({}): Data:\n{}".format(device.name, device.id, json.dumps(self.account_data[accountID], sort_keys=True, indent=4, separators=(',', ': '))))
        return True


    ########################################
    #
    # Device Actions
    #
    ########################################

    def setVentOpening(self, pluginAction, device):
        account = self.flair_accounts[int(device.pluginProps['flair_account'])]
        vent_id = device.pluginProps['flair_vent']
        percent_open =  int(pluginAction.props['percent_open'])
        self.logger.debug(u"{}: setVentOpening to {}%".format(device.name, percent_open))
        account.set_vent(vent_id, percent_open)


    ########################################
    #
    # Indigo UI Controls
    #
    ########################################
 
    def actionControlUniversal(self, action, device):
        self.logger.debug(u"{}: action.actionControlUniversal: {}".format(device.name, action.deviceAction))
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.update_needed = True
        else:
            self.logger.warning(u"{}: actionControlUniversal: Unimplemented action.deviceAction: {}".format(device.name, action.deviceAction))

    def actionControlDevice(self, action, device):
        self.logger.debug(u"{}: actionControlDevice: action.deviceAction: {}".format(device.name, action.deviceAction))
        
        if action.deviceAction == indigo.kDeviceAction.TurnOn:

            account = self.flair_accounts[int(device.pluginProps['flair_account'])]
            vent_id = device.pluginProps['flair_vent']
            account.set_vent(vent_id, 100)
            device.updateStateOnServer("brightnessLevel", 100)
        
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:

            account = self.flair_accounts[int(device.pluginProps['flair_account'])]
            vent_id = device.pluginProps['flair_vent']
            account.set_vent(vent_id, 0)
            device.updateStateOnServer("brightnessLevel", 0)
            
        elif action.deviceAction == indigo.kDeviceAction.SetBrightness:

            newBrightness = action.actionValue
            account = self.flair_accounts[int(device.pluginProps['flair_account'])]
            vent_id = device.pluginProps['flair_vent']
            account.set_vent(vent_id, int(newBrightness))
            device.updateStateOnServer("brightnessLevel", newBrightness)

        elif action.deviceAction == indigo.kDeviceAction.BrightenBy:

            newBrightness = device.brightness + action.actionValue
            if newBrightness > 100:
                newBrightness = 100
            account = self.flair_accounts[int(device.pluginProps['flair_account'])]
            vent_id = device.pluginProps['flair_vent']
            account.set_vent(vent_id, int(newBrightness))
            device.updateStateOnServer("brightnessLevel", newBrightness)

        ###### DIM BY ######
        elif action.deviceAction == indigo.kDeviceAction.DimBy:
            newBrightness = device.brightness - action.actionValue
            if newBrightness < 0:
                newBrightness = 0
            account = self.flair_accounts[int(device.pluginProps['flair_account'])]
            vent_id = device.pluginProps['flair_vent']
            account.set_vent(vent_id, int(newBrightness))
            device.updateStateOnServer("brightnessLevel", newBrightness)

        else:
            self.logger.warning(u"{}: actionControlDevice: Unimplemented action.deviceAction: {}".format(device.name, action.deviceAction))
 
