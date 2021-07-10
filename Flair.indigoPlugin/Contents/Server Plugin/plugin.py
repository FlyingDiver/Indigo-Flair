#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import platform
import time

from flair import FlairAccount
import temperature_scale


TEMPERATURE_SCALE_PLUGIN_PREF='temperatureScale'
TEMP_FORMATTERS = {
    'F': temperature_scale.Fahrenheit(),
    'C': temperature_scale.Celsius()
}
#   Plugin-enforced minimum and maximum setpoint ranges per temperature scale
ALLOWED_RANGE = {
    'F': (40,95),
    'C': (6,35)
}

HVAC_MODE_MAP = {
    'Heat'        : indigo.kHvacMode.Heat,
    'Cool'        : indigo.kHvacMode.Cool,
    'Auto'        : indigo.kHvacMode.HeatCool,
    'Fan'         : indigo.kHvacMode.Off,
    'Dry'         : indigo.kHvacMode.Off
}   

kHvacModeEnumToStrMap = {
    indigo.kHvacMode.Cool               : u"cool",
    indigo.kHvacMode.Heat               : u"heat",
    indigo.kHvacMode.HeatCool           : u"auto",
    indigo.kHvacMode.Off                : u"off",
    indigo.kHvacMode.ProgramHeat        : u"program heat",
    indigo.kHvacMode.ProgramCool        : u"program cool",
    indigo.kHvacMode.ProgramHeatCool    : u"program auto"
}

kFanModeEnumToStrMap = {
    indigo.kFanMode.Auto            : u"auto",
    indigo.kFanMode.AlwaysOn        : u"on"
}

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
        self.flair_hvacs = {}
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

        elif typeId == 'FlairVent': 
        
            if len(valuesDict['flair_vent']) == 0:
                errorsDict['flair_vent'] = u"Flair Vent must be selected"
            if len(valuesDict['flair_account']) == 0:
                errorsDict['flair_account'] = u"Flair Account must be selected"
            if len(valuesDict['flair_structure']) == 0:
                errorsDict['flair_structure'] = u"Flair Structure must be selected"

        elif typeId == 'FlairHVAC':
        
            if len(valuesDict['flair_vent']) == 0:
                errorsDict['flair_vent'] = u"Flair Vent must be selected"
            if len(valuesDict['flair_account']) == 0:
                errorsDict['flair_account'] = u"Flair Account must be selected"
            if len(valuesDict['flair_hvac']) == 0:
                errorsDict['flair_hvac'] = u"Flair Minisplit must be selected"
        
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
        
        elif dev.deviceTypeId == 'FlairVent':
            self.flair_vents[dev.id] = dev
            self.update_needed = True
            
        elif dev.deviceTypeId == 'FlairHVAC':
            self.flair_hvacs[dev.id] = dev
            self.update_needed = True
            

    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

        if dev.deviceTypeId == 'FlairAccount':
            if dev.id in self.flair_accounts:
                del self.flair_accounts[dev.id]
            
        elif dev.deviceTypeId == 'FlairVent':
            if dev.id in self.flair_vents:
                del self.flair_vents[dev.id]
 
        elif dev.deviceTypeId == 'FlairHVAC':
            if dev.id in self.flair_hvacs:
                del self.flair_hvacs[dev.id]
 
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

                        
                    for hvacID in self.flair_hvacs:
                        device = indigo.devices[hvacID]
                        hvac = self.account_data[int(device.pluginProps['flair_account'])][device.pluginProps['flair_structure']]['hvac-units'][device.pluginProps['flair_hvac']]
                        self.logger.threaddebug("{}: Device update data: {}".format(device.name, hvac))
                        update_list = []
                        update_list.append({'key' : "name",        'value' : hvac['name']})
                        update_list.append({'key' : "fan-speed",   'value' : hvac['fan-speed']})
                        update_list.append({'key' : "swing",       'value' : hvac['swing']})
                        update_list.append({'key' : "power",       'value' : hvac['power']})
                        
                        update_list.append({'key'           : "temperatureInput1", 
                                            'value'         : hvac['temperature'], 
                                            'uiValue'       : u"{}°F".format(hvac['temperature']),
                                            'decimalPlaces' : 0})
                        update_list.append({'key' : "hvacOperationMode", 'value' : HVAC_MODE_MAP[hvac['mode']]})
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

    def get_hvac_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug("get_hvac_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))

        try:
            structure = self.account_data[int(valuesDict["flair_account"])][valuesDict["flair_structure"]]
            vents = [
                (key, value['name'])
                for key, value in structure['hvac-units'].iteritems()
            ]
        except:
            vents = []
        self.logger.debug("get_hvac_list: vents = {}".format(vents))
        return vents
        
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
 

              
    def actionControlThermostat(self, action, device):
        self.logger.debug(u"{}: actionControlThermostat: action.deviceAction: {}".format(device.name, action.thermostatAction))
       ###### SET HVAC MODE ######
        if action.thermostatAction == indigo.kThermostatAction.SetHvacMode:
            self.handleChangeHvacModeAction(device, action.actionMode)

        ###### SET FAN MODE ######
        elif action.thermostatAction == indigo.kThermostatAction.SetFanMode:
            self.handleChangeFanModeAction(device, action.actionMode, u"hvacFanIsOn")

        ###### SET COOL SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.SetCoolSetpoint:
            newSetpoint = action.actionValue
            self.handleChangeSetpointAction(device, newSetpoint, u"setpointCool")

        ###### SET HEAT SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.SetHeatSetpoint:
            newSetpoint = action.actionValue
            self.handleChangeSetpointAction(device, newSetpoint, u"setpointHeat")

        ###### DECREASE/INCREASE COOL SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.DecreaseCoolSetpoint:
            newSetpoint = device.coolSetpoint - action.actionValue
            self.handleChangeSetpointAction(device, newSetpoint, u"setpointCool")

        elif action.thermostatAction == indigo.kThermostatAction.IncreaseCoolSetpoint:
            newSetpoint = device.coolSetpoint + action.actionValue
            self.handleChangeSetpointAction(device, newSetpoint, u"setpointCool")

        ###### DECREASE/INCREASE HEAT SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.DecreaseHeatSetpoint:
            newSetpoint = device.heatSetpoint - action.actionValue
            self.handleChangeSetpointAction(device, newSetpoint, u"setpointHeat")

        elif action.thermostatAction == indigo.kThermostatAction.IncreaseHeatSetpoint:
            newSetpoint = device.heatSetpoint + action.actionValue
            self.handleChangeSetpointAction(device, newSetpoint, u"setpointHeat")

        ###### REQUEST STATE UPDATES ######
        elif action.thermostatAction in [indigo.kThermostatAction.RequestStatusAll, indigo.kThermostatAction.RequestMode,
         indigo.kThermostatAction.RequestEquipmentState, indigo.kThermostatAction.RequestTemperatures, indigo.kThermostatAction.RequestHumidities,
         indigo.kThermostatAction.RequestDeadbands, indigo.kThermostatAction.RequestSetpoints]:
            self.update_needed = True

        ###### UNTRAPPED CONDITIONS ######
        # Explicitly show when nothing matches, indicates errors and unimplemented actions instead of quietly swallowing them
        else:
            self.logger.warning(u"{}: actionControlThermostat: Unimplemented action.deviceAction: {}".format(device.name, action.thermostatAction))

  
    ########################################
    # Process action request from Indigo Server to change main thermostat's main mode.
    ########################################

    def handleChangeHvacModeAction(self, device, newHvacMode):
        hvac_mode = kHvacModeEnumToStrMap.get(newHvacMode, u"unknown")
        self.logger.debug(u"{} ({}): Mode set to: {}".format(device.name, device.address, hvac_mode))

        self.update_needed = True
        if "hvacOperationMode" in device.states:
            device.updateStateOnServer("hvacOperationMode", newHvacMode)

    ########################################
    # Process action request from Indigo Server to change fan mode.
    ########################################
    
    def handleChangeFanModeAction(self, device, requestedFanMode, stateKey):
       
        newFanMode = kFanModeEnumToStrMap.get(requestedFanMode, u"auto")
        holdType = device.pluginProps.get("holdType", "nextTransition")
        
        if newFanMode == u"on":
            self.logger.info(u'{}: set fan to ON, leave cool at {} and heat at {}'.format(device.name, device.coolSetpoint, device.heatSetpoint))

        if newFanMode == u"auto":
            self.logger.info(u'{}: resume normal program to set fan to Auto'.format(device.name))

        self.update_needed = True
        if stateKey in device.states:
            device.updateStateOnServer(stateKey, requestedFanMode, uiValue="True")

    ########################################
    # Process action request from Indigo Server to change a cool/heat setpoint.
    ########################################
    
    def handleChangeSetpointAction(self, device, newSetpoint, stateKey):

        #   enforce minima/maxima based on the scale in use by the plugin
        newSetpoint = self._constrainSetpoint(newSetpoint)

        #   API uses F scale
        newSetpoint = self._toFahrenheit(newSetpoint)

        holdType = device.pluginProps.get("holdType", "nextTransition")

        if stateKey == u"setpointCool":
            self.logger.info(u'{}: set cool to: {} and leave heat at: {}'.format(device.name, newSetpoint, device.heatSetpoint))

        elif stateKey == u"setpointHeat":
            self.logger.info(u'{}: set heat to: {} and leave cool at: {}'.format(device.name, newSetpoint,device.coolSetpoint))

        else:
            self.logger.error(u'{}: handleChangeSetpointAction Invalid operation - {}'.format(device.name, stateKey))
        
        self.update_needed = True
        if stateKey in device.states:
            device.updateStateOnServer(stateKey, newSetpoint, uiValue="%.1f °F" % (newSetpoint))


    #   constrain a setpoint the range
    #   based on temperature scale in use by the plugin
    def _constrainSetpoint(self, value):
        allowedRange = ALLOWED_RANGE[self.pluginPrefs[TEMPERATURE_SCALE_PLUGIN_PREF]]
        return min(max(value, allowedRange[0]), allowedRange[1])

    #   convert value (in the plugin-defined scale)
    #   to Fahrenheit
    def _toFahrenheit(self,value):
        scale = self.pluginPrefs[TEMPERATURE_SCALE_PLUGIN_PREF]
        if scale == 'C':
            return (9 * value)/5 + 32
        return value

    def _setTemperatureScale(self, value):
        self.logger.debug(u'setting temperature scale to %s' % value)
        EcobeeThermostat.temperatureFormatter = TEMP_FORMATTERS.get(value)

          

