#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import platform
import time

from flair import FlairAccount

import temperature_scale

REFRESH_TOKEN_PLUGIN_PREF='refreshToken-'
TEMPERATURE_SCALE_PLUGIN_PREF='temperatureScale'


TEMP_FORMATTERS = {
    'F': temperature_scale.Fahrenheit(),
    'C': temperature_scale.Celsius(),
    'K': temperature_scale.Kelvin(),
    'R': temperature_scale.Rankine()
}

#   Plugin-enforced minimum and maximum setpoint ranges per temperature scale
ALLOWED_RANGE = {
    'F': (40,95),
    'C': (6,35),
    'K': (277,308),
    'R': (500,555)
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
        

    ########################################
        
    def runConcurrentThread(self):
        self.logger.debug(u"runConcurrentThread starting")
        try:
            while True:
                
                if (time.time() > self.next_update) or self.update_needed:
                    self.update_needed = False
                    self.next_update = time.time() + self.updateFrequency
                
                    # update from Flair servers
                    
                    for accountID, account in self.flair_accounts.items():
                        if account.authenticated:
                            account.server_update()
                            indigo.devices[accountID].updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                        else:
                            indigo.devices[accountID].updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                            self.logger.debug("Flair account {} not authenticated, skipping update".format(accountID))

                    # now update all the Indigo devices         
                    
#                    for dev in self.flair_thermostats.values():
#                        dev.update()
                                        

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
        self.logger.threaddebug("get_account_list: typeId = {}, targetId = {}, valuesDict = {}".format(typeId, targetId, valuesDict))
        accounts = [
            (account.dev.id, indigo.devices[account.dev.id].name)
            for account in self.flair_accounts.values()
        ]
        self.logger.debug("get_account_list: accounts = {}".format(accounts))
        return accounts
        

    def get_vent_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_device_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))

        try:
            flair_account = self.flair_accounts[int(valuesDict["flair_account"])]
        except:
            self.logger.debug("get_vent_list: no active accounts, returning empty list")
            return []
        
        if valuesDict["deviceType"] == "FlairVent":
        
            available_devices =[]
            for iden, therm in Flair.thermostats.items():
                if iden not in active_stats:
                    available_devices.append((iden, therm["name"]))
        
            if targetId:
                try:
                    dev = indigo.devices[targetId]
                    available_devices.insert(0, (dev.pluginProps["address"], dev.name))
                except:
                    pass
                        
        else:
            self.logger.warning("get_device_list: unknown deviceType = {}".format(valuesDict["deviceType"]))
          
        self.logger.debug("get_device_list: available_devices for {} = {}".format(valuesDict["deviceType"], available_devices))
        return available_devices     

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict      

        
    def deviceStartComm(self, dev):

        self.logger.info(u"{}: Starting {} Device {}".format(dev.name, dev.deviceTypeId, dev.id))
        
        dev.stateListOrDisplayStateIdChanged()

        if dev.deviceTypeId == 'FlairAccount':     # create the Flair account object.  It will attempt to refresh the auth token.
            
            account = FlairAccount(dev, refresh_token = dev.pluginProps['RefreshToken'])
            self.flair_accounts[dev.id] = account
            newProps = dev.pluginProps
            newProps["RefreshToken"] = account.refresh_token
            dev.replacePluginPropsOnServer(newProps)
            
            dev.updateStateOnServer(key="authenticated", value=account.authenticated)
            self.update_needed = True
                            
        elif dev.deviceTypeId == 'FlairThermostat':

            self.flair_thermostats[dev.id] = FlairThermostat(dev)
            self.update_needed = True
            
            

    def deviceStopComm(self, dev):

        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

        if dev.deviceTypeId == 'FlairAccount':
            if dev.id in self.flair_accounts:
                del self.flair_accounts[dev.id]
            
        elif dev.deviceTypeId == 'FlairThermostat':
            if dev.id in self.flair_thermostats:
                del self.flair_thermostats[dev.id]
 
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
    # Thermostat Action callbacks
    ########################################
    
    # Main thermostat action bottleneck called by Indigo Server.
   
    def actionControlThermostat(self, action, dev):
        self.logger.debug(u"{}: action.thermostatAction: {}".format(dev.name, action.thermostatAction))
       ###### SET HVAC MODE ######
        if action.thermostatAction == indigo.kThermostatAction.SetHvacMode:
            self.handleChangeHvacModeAction(dev, action.actionMode)

        ###### SET FAN MODE ######
        elif action.thermostatAction == indigo.kThermostatAction.SetFanMode:
            self.handleChangeFanModeAction(dev, action.actionMode, u"hvacFanIsOn")

        ###### SET COOL SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.SetCoolSetpoint:
            newSetpoint = action.actionValue
            self.handleChangeSetpointAction(dev, newSetpoint, u"setpointCool")

        ###### SET HEAT SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.SetHeatSetpoint:
            newSetpoint = action.actionValue
            self.handleChangeSetpointAction(dev, newSetpoint, u"setpointHeat")

        ###### DECREASE/INCREASE COOL SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.DecreaseCoolSetpoint:
            newSetpoint = dev.coolSetpoint - action.actionValue
            self.handleChangeSetpointAction(dev, newSetpoint, u"setpointCool")

        elif action.thermostatAction == indigo.kThermostatAction.IncreaseCoolSetpoint:
            newSetpoint = dev.coolSetpoint + action.actionValue
            self.handleChangeSetpointAction(dev, newSetpoint, u"setpointCool")

        ###### DECREASE/INCREASE HEAT SETPOINT ######
        elif action.thermostatAction == indigo.kThermostatAction.DecreaseHeatSetpoint:
            newSetpoint = dev.heatSetpoint - action.actionValue
            self.handleChangeSetpointAction(dev, newSetpoint, u"setpointHeat")

        elif action.thermostatAction == indigo.kThermostatAction.IncreaseHeatSetpoint:
            newSetpoint = dev.heatSetpoint + action.actionValue
            self.handleChangeSetpointAction(dev, newSetpoint, u"setpointHeat")

        ###### REQUEST STATE UPDATES ######
        elif action.thermostatAction in [indigo.kThermostatAction.RequestStatusAll, indigo.kThermostatAction.RequestMode,
         indigo.kThermostatAction.RequestEquipmentState, indigo.kThermostatAction.RequestTemperatures, indigo.kThermostatAction.RequestHumidities,
         indigo.kThermostatAction.RequestDeadbands, indigo.kThermostatAction.RequestSetpoints]:
            self.update_needed = True

        ###### UNTRAPPED CONDITIONS ######
        # Explicitly show when nothing matches, indicates errors and unimplemented actions instead of quietly swallowing them
        else:
            self.logger.warning(u"{}: Unimplemented action.thermostatAction: {}".format(dev.name, action.thermostatAction))

    def actionControlUniversal(self, action, dev):
        self.logger.debug(u"{}: action.actionControlUniversal: {}".format(dev.name, action.deviceAction))
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.update_needed = True
        else:
            self.logger.warning(u"{}: Unimplemented action.deviceAction: {}".format(dev.name, action.deviceAction))


    ########################################
    # Activate Comfort Setting callback
    ########################################
    
    def actionActivateComfortSetting(self, action, dev):
        self.logger.debug(u"{}: actionActivateComfortSetting".format(dev.name))
        defaultHold = dev.pluginProps.get("holdType", "nextTransition")

        climate = action.props.get("climate")
        holdType = action.props.get("holdType", defaultHold)
        self.flair_thermostats[dev.id].set_climate_hold(climate, holdType)

    def climateListGenerator(self, filter, valuesDict, typeId, targetId):                                                                                                                 
        self.logger.debug(u"climateListGenerator: typeId = {}, targetId = {}".format(typeId, targetId))
        return self.flair_thermostats[targetId].get_climates()

    ########################################
    # Set Hold Type
    ########################################
    
    def actionSetDefaultHoldType(self, action, dev):
        self.logger.debug(u"{}: actionSetDefaultHoldType".format(dev.name))
         
        props = dev.pluginProps
        props["holdType"] = action.props.get("holdType", "nextTransition")
        dev.replacePluginPropsOnServer(props)                
 
 
    ########################################
    # Resume Program callbacks
    ########################################
    
    def menuResumeAllPrograms(self):
        self.logger.debug(u"menuResumeAllPrograms")
        for devId, thermostat in self.flair_thermostats.items():
            if indigo.devices[devId].deviceTypeId == 'FlairThermostat':
                thermostat.resume_program()

    def menuResumeProgram(self, valuesDict, typeId):
        self.logger.debug(u"menuResumeProgram")
        try:
            deviceId = int(valuesDict["targetDevice"])
        except:
            self.logger.error(u"Bad Device specified for Resume Program operation")
            return False

        for thermId, thermostat in self.flair_thermostats.items():
            if thermId == deviceId:
                thermostat.resume_program()
        return True
        
    def menuDumpThermostat(self):
        self.logger.debug(u"menuDumpThermostat")
        for accountID, account in self.flair_accounts.items():
            account.dump_data()
        return True

    def actionResumeAllPrograms(self, action, dev):
        self.logger.debug(u"actionResumeAllPrograms")
        for devId, thermostat in self.flair_thermostats.items():
            if indigo.devices[devId].deviceTypeId == 'FlairThermostat':
                thermostat.resume_program()

    def actionResumeProgram(self, action, dev):
        self.logger.debug(u"{}: actionResumeProgram".format(dev.name))
        self.flair_thermostats[dev.id].resume_program()
    
    def pickThermostat(self, filter=None, valuesDict=None, typeId=0):
        retList = []
        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == 'FlairThermostat':
                retList.append((dev.id, dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList



    ########################################
    # Process action request from Indigo Server to change main thermostat's main mode.
    ########################################

    def handleChangeHvacModeAction(self, dev, newHvacMode):
        hvac_mode = kHvacModeEnumToStrMap.get(newHvacMode, u"unknown")
        self.logger.debug(u"{} ({}): Mode set to: {}".format(dev.name, dev.address, hvac_mode))

        self.flair_thermostats[dev.id].set_hvac_mode(hvac_mode)
        self.update_needed = True
        if "hvacOperationMode" in dev.states:
            dev.updateStateOnServer("hvacOperationMode", newHvacMode)

    ########################################
    # Process action request from Indigo Server to change a cool/heat setpoint.
    ########################################
    
    def handleChangeSetpointAction(self, dev, newSetpoint, stateKey):

        #   enforce minima/maxima based on the scale in use by the plugin
        newSetpoint = self._constrainSetpoint(newSetpoint)

        #   API uses F scale
        newSetpoint = self._toFahrenheit(newSetpoint)

        holdType = dev.pluginProps.get("holdType", "nextTransition")

        if stateKey == u"setpointCool":
            self.logger.info(u'{}: set cool to: {} and leave heat at: {}'.format(dev.name, newSetpoint, dev.heatSetpoint))
            self.flair_thermostats[dev.id].set_hold_temp(newSetpoint, dev.heatSetpoint, holdType)

        elif stateKey == u"setpointHeat":
            self.logger.info(u'{}: set heat to: {} and leave cool at: {}'.format(dev.name, newSetpoint,dev.coolSetpoint))
            self.flair_thermostats[dev.id].set_hold_temp(dev.coolSetpoint, newSetpoint, holdType)

        else:
            self.logger.error(u'{}: handleChangeSetpointAction Invalid operation - {}'.format(dev.name, stateKey))
        
        self.update_needed = True
        if stateKey in dev.states:
            dev.updateStateOnServer(stateKey, newSetpoint, uiValue="%.1f °F" % (newSetpoint))


