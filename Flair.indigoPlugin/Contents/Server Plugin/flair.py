#! /usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import json
import time
import logging

#
# All interactions with the Flair servers are encapsulated in this class
#

CLIENT_ID = "mWmHRWAhipDket6vf7nAUIqrLhcskpRiYeJiSLbL"
CLIENT_SECRET = "ofcjvnX50UekEa02AxrlJTM6gleUl7Ulapd5ZMID0BLUObxFQsRPtS83m4I0"
SCOPE = 'structures.view vents.view vents.edit' 

class FlairAccount:

    def __init__(self, name = None, refresh_token = None, username = None, password = None):
        self.logger = logging.getLogger("Plugin.FlairAccount")
        self.authenticated = False
        self.next_refresh = time.time()
        self.structures = {}
                    
        self.name = name
        self.username = username
        self.password = password
        self.refresh_token = refresh_token
        if refresh_token and len(refresh_token):
            self.logger.debug(u"{}: FlairAccount __init__, using refresh token = {}".format(self.name, refresh_token))
            self.refresh_token = refresh_token
            self.do_token_refresh()
        else:
            self.logger.debug(u"{}: FlairAccount __init__, doing get_tokens()".format(self.name))
            self.get_tokens()
                
#
#   Flair Authentication functions
#
    def get_tokens(self):
    
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        params = {  
            'client_id': CLIENT_ID, 
            'client_secret': CLIENT_SECRET, 
            'grant_type':  'password',
            'username':  self.username, 
            'password':  self.password,
            'scope':  SCOPE       
        }
        
        try:
            request = requests.post('https://api.flair.co/oauth/token',  headers=headers, params=params)
        except requests.RequestException as e:
            self.logger.error("Token Request Error, exception = {}".format(e))
            self.authenticated = False
            return
            
        if request.status_code == requests.codes.ok:
            response = request.json()
            self.access_token = response['access_token']
            self.refresh_token = response['refresh_token']
            expires_in = response['expires_in']
            self.logger.debug("Token Request OK, response = {}".format(response))
            self.next_refresh = time.time() + (float(expires_in) * 0.80)
            self.authenticated = True
        else:
            self.logger.error("Token Request failed, response = {}".format(response))                
            self.authenticated = False

    def do_token_refresh(self):
        if not self.refresh_token:
            self.authenticated = False
            self.get_tokens()
            return
            
        self.logger.debug("Token Request with refresh_token = {}".format(self.refresh_token))

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        params = {  
            'client_id': CLIENT_ID, 
            'client_secret': CLIENT_SECRET, 
            'grant_type':  'refresh_token',
            'refresh_token':  self.refresh_token,
            'scope':  SCOPE        
        }
        try:
            request = requests.post('https://api.flair.co/oauth/token',  headers=headers, params=params)
        except requests.RequestException as e:
            self.logger.error("Token Refresh Error, exception = {}".format(e))
            self.refresh_token = None
            return
            
        if request.status_code == requests.codes.ok:
            response = request.json()
            self.access_token = response['access_token']
            self.refresh_token = response['refresh_token']
            expires_in = response['expires_in']
            self.logger.debug("Token Refresh OK, response = {}".format(response))
            self.next_refresh = time.time() + (float(expires_in) * 0.80)
            self.authenticated = True
            return
            
        try:
            error = request.json()['error']
            if error == 'invalid_grant':
                self.logger.error(u"{}: Authentication lost, please re-authenticate".format(self.name))
                self.refresh_token = None
                self.authenticated = False   
            else:                           
                self.logger.error("Token Refresh Error, error = {}".format(error))
                self.refresh_token = None
        except:
            pass

        
#
#   Flair API functions
#
        
#   Request all device data from the Flair servers.

    def server_update(self):
    
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept':       'application/json',
            'Authorization':'Bearer ' + self.access_token        
        }
        params = {}
            
        try:
            s_request = requests.get('https://api.flair.co/api/structures', headers=headers, params=params)
        except requests.RequestException as e:
            self.logger.error(u"{}: Flair Account Update Error, exception = {}".format(self.name, e))
            return None
            
        s_response = s_request.json()        
        if s_request.status_code != requests.codes.ok:
            self.logger.error(u"{}: Flair Account Update failed, response =\n{}".format(self.name, json.dumps(s_response, sort_keys=True, indent=4, separators=(',', ': '))))                 
            return None
            
        for s in s_response['data']:
            
            # save the structure data
            
            structure_dict = {}
            structure_dict['structure'] =  s['attributes']
            
            # loop to collect related data
            
            for relationship in ['thermostats', 'rooms', 'pucks', 'hvac-units']:

                url = s['relationships'][relationship]['links']['related']
                self.logger.debug("{}: Fetching {}".format(self.name, url))
                try:
                    r_request = requests.get('https://api.flair.co'+url, headers=headers, params=params)
                except requests.RequestException as e:
                    self.logger.error(u"{}: Flair Account Update Error, exception = {}".format(self.name, e))

                r_response = r_request.json()                    
                if r_request.status_code != requests.codes.ok:
                    self.logger.error(u"{}: Flair Account Update failed, response =\n{}".format(self.name, json.dumps(r_response, sort_keys=True, indent=4, separators=(',', ': '))))                 
                else:
                    structure_dict[relationship] =  {}
                    for d in r_response['data']:
                        structure_dict[relationship][d['id']] =  d['attributes']
                    self.logger.debug("{}: Fetched {} {} records".format(self.name, len(structure_dict[relationship]), relationship))
                    
            # special handling for vent data to get the current readings as well
            
            url = s['relationships']['vents']['links']['related']
            self.logger.debug("{}: Fetching {}".format(self.name, url))
            try:
                v_request = requests.get('https://api.flair.co'+url, headers=headers, params=params)
            except requests.RequestException as e:
                self.logger.error(u"{}: Flair Account Update Error, exception =\n{}".format(self.name, e))
        
            v_response = v_request.json()                    
            if v_request.status_code != requests.codes.ok:
                self.logger.error(u"{}: Flair Account Update failed, response =\n{}".format(self.name, json.dumps(v_response, sort_keys=True, indent=4, separators=(',', ': '))))                 
            else:
                structure_dict['vents'] =  {}
                
                for vents in v_response['data']:
                    temp =  vents['attributes']
                    
                    url = vents['relationships']['current-reading']['links']['related']
                    self.logger.debug("{}: Fetching {}".format(self.name, url))
                    try:
                        vent_request = requests.get('https://api.flair.co'+url, headers=headers)
                    except requests.RequestException as e:
                        print("Vents Request Error, exception = {}".format(e))
                        return
        
                    vent_data = vent_request.json()                    
                    if vent_request.status_code != requests.codes.ok:
                        self.logger.error(u"{}: Flair Account Update failed, response =\n{}".format(self.name, json.dumps(v2_response, sort_keys=True, indent=4, separators=(',', ': '))))                 
                    else:
                        temp.update(vent_data['data']['attributes'])

                    structure_dict['vents'][d['id']] = temp
                self.logger.debug("{}: Fetched {} vent records".format(self.name, len(structure_dict['vents'])))
                   
            self.structures[s['id']] = structure_dict
        
        return self.structures
        
    def set_vent(self, vent_id, per_open):

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + self.access_token 
        }
        patch_data = {  
            "data": {
                "type": "vents",
                "attributes": {
                    "percent-open": per_open
                },
            "relationships": {}
            }
        }     
          
        try:
            url = 'https://api.flair.co/api/vents/' + vent_id
            request = requests.patch(url, headers=headers, data=json.dumps(patch_data))
        except requests.RequestException as e:
            self.logger.error("Vent PATCH Request Error, exception = {}".format(e))
            return
        response = request.json()        
        if request.status_code == requests.codes.ok:
            self.logger.threaddebug("Vent PATCH Request OK, response =\n{}".format(json.dumps(response, sort_keys=True, indent=4, separators=(',', ': '))))
        else:
            self.logger.error("Vent PATCH Request failed, url = {}".format(url))
            self.logger.error("Vent PATCH Request failed, data = {}".format(patch_data))
            self.logger.error("Vent PATCH Request failed, response =\n{}".format(json.dumps(response, sort_keys=True, indent=4, separators=(',', ': '))))               


    def set_hvac_setpoint(self, hvac_id, temperature):

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + self.access_token 
        }
        patch_data = {
            "data": {
                "type": "hvac-units",
                "attributes": {
                    "temperature": temperature,
                    "fan-speed": "High",
                    "swing": "Off",
                    "mode": "Heat",
                    "power": "On"
                },
                "relationships": {}
            }
        }        
        
        try:
            url = 'https://api.flair.co/api/hvac-units/' + vent_id
            request = requests.patch(url, headers=headers, data=json.dumps(patch_data))
        except requests.RequestException as e:
            self.logger.error("HVAC PATCH Request Error, exception = {}".format(e))
            return
        response = request.json()        
        if request.status_code == requests.codes.ok:
            self.logger.threaddebug("HVAC PATCH Request OK, response =\n{}".format(json.dumps(response, sort_keys=True, indent=4, separators=(',', ': '))))
        else:
            self.logger.error("HVAC PATCH Request failed, url = {}".format(url))
            self.logger.error("HVAC PATCH Request failed, data = {}".format(patch_data))
            self.logger.error("HVAC PATCH Request failed, response =\n{}".format(json.dumps(response, sort_keys=True, indent=4, separators=(',', ': '))))               


    def set_hvac_mode(self, hvac_id, mode):

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + self.access_token 
        }
        patch_data = {
            "data": {
                "type": "hvac-units",
                "attributes": {
                    "temperature": temperature,
                    "fan-speed": "High",
                    "swing": "Off",
                    "mode": "Heat",
                    "power": "On"
                },
                "relationships": {}
            }
        }        
        
        try:
            url = 'https://api.flair.co/api/hvac-units/' + vent_id
            request = requests.patch(url, headers=headers, data=json.dumps(patch_data))
        except requests.RequestException as e:
            self.logger.error("HVAC PATCH Request Error, exception = {}".format(e))
            return
        response = request.json()        
        if request.status_code == requests.codes.ok:
            self.logger.threaddebug("HVAC PATCH Request OK, response =\n{}".format(json.dumps(response, sort_keys=True, indent=4, separators=(',', ': '))))
        else:
            self.logger.error("HVAC PATCH Request failed, url = {}".format(url))
            self.logger.error("HVAC PATCH Request failed, data = {}".format(patch_data))
            self.logger.error("HVAC PATCH Request failed, response =\n{}".format(json.dumps(response, sort_keys=True, indent=4, separators=(',', ': '))))               

