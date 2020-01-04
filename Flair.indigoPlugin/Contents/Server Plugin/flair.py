#! /usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import json
import time
import logging

#
# All interactions with the Ecobee servers are encapsulated in this class
#

CLIENT_ID = "mWmHRWAhipDket6vf7nAUIqrLhcskpRiYeJiSLbL"
CLIENT_SECRET = "ofcjvnX50UekEa02AxrlJTM6gleUl7Ulapd5ZMID0BLUObxFQsRPtS83m4I0"


class FlairAccount:

    def __init__(self, dev, refresh_token = None):
        self.logger = logging.getLogger("Plugin.EcobeeAccount")
        self.authenticated = False
        self.next_refresh = time.time()
        self.structures = {}
                    
        self.name = dev.name
        self.username = dev.pluginProps['username']
        self.password = dev.pluginProps['password']
        self.refresh_token = dev.pluginProps['RefreshToken']
        if refresh_token and len(refresh_token):
            self.logger.debug(u"{}: EcobeeAccount __init__, using refresh token = {}".format(self.name, refresh_token))
            self.refresh_token = refresh_token
            self.do_token_refresh()
        else:
            self.logger.debug(u"{}: EcobeeAccount __init__, doing get_tokens()".format(self.name))
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
            'scope':  'structures.view structures.edit'        
        }
        
        try:
            request = requests.post('https://api.flair.co/oauth/token',  headers=headers, params=params)
        except requests.RequestException, e:
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


    # called from __init__ or main loop to refresh the access tokens

    def do_token_refresh(self):
        if not self.refresh_token:
            self.authenticated = False
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
            'scope':  'structures.view structures.edit'        
        }
        try:
            request = requests.post('https://api.flair.co/oauth/token',  headers=headers, params=params)
        except requests.RequestException, e:
            self.logger.error("Token Refresh Error, exception = {}".format(e))
            self.next_refresh = time.time() + 300.0         # try again in five minutes
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
                self.authenticated = False   
            else:                           
                self.logger.error("Token Refresh Error, error = {}".format(error))
                self.next_refresh = time.time() + 300.0         # try again in five minutes
        except:
            pass

        self.next_refresh = time.time() + 300.0         # try again in five minutes

        
#
#   Flair API functions
#
        
#   Request all device data from the Flair servers.

    def server_update(self):
    
        header = {'Content-Type': 'application/json;charset=UTF-8',
                  'Authorization': 'Bearer ' + self.access_token}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept':       'application/json',
            'Authorization':'Bearer ' + self.access_token        
        }
        params = {}
            
        try:
            request = requests.get('https://api.flair.co/api/structures', headers=header, params=params)
        except requests.RequestException, e:
            self.logger.error(u"{}: Flair Account Update Error, exception = {}".format(self.name, e))
            return
            
        if request.status_code != requests.codes.ok:
            self.logger.error(u"{}: Flair Account Update failed, response = '{}'".format(self.name, request.text))                
            return
            
        for s in request.json()['data']:
            self.logger.info("{}: Flair structure id {}".format(s['attributes']['name'], s['id']))
            structure_dict = {}
            structure_dict['attributes'] =  s['attributes']
            for relationship in ['zones', 'thermostats', 'vents', 'rooms', 'pucks']:
                url = s['relationships'][relationship]['links']['related']
                self.logger.debug("{}: Fetching {}".format(self.name, url))
                try:
                    request = requests.get('https://api.flair.co'+url, headers=header, params=params)
                except requests.RequestException, e:
                    self.logger.error(u"{}: Flair Account Update Error, exception = {}".format(self.name, e))
            
                if request.status_code != requests.codes.ok:
                    self.logger.error(u"{}: Flair Account Update failed, response = '{}'".format(self.name, request.text))                
                else:
                    structure_dict[relationship] =  {}
                    for d in request.json()['data']:
                        self.logger.info("{}: Flair {} id {}".format(d['attributes']['name'], relationship, d['id']))
                        structure_dict[relationship][d['id']] =  d['attributes']
                   
            self.structures[s['id']] = structure_dict
 
    def dump_data(self):

        self.logger.info(json.dumps(self.structures, sort_keys=True, indent=4, separators=(',', ': ')))
             
            