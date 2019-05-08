import requests
import json as _json
from qgiscommons2.gui.paramdialog import openParametersDialog, Parameter, STRING, PASSWORD
from qgis.PyQt import QtWidgets, QtGui, QtCore

class GeogigAuthException(Exception):
    pass

class GeogigError(Exception):
    def __init__(self, message, details=None,causedBy=None):
        super().__init__(message)
        self.details = details
        self.causedBy = causedBy


_connectors = {}

def getConnector(url, user=None, password=None, update=False):
    global _connectors
    if url not in _connectors or update:
        _connectors[url] = Connector(url, user, password)
    return _connectors[url]

class Connector():

    def __init__(self, url, user=None, password=None):
        self.user = user
        self.password = password 
        self.url = url

    def resetCredentials(self):
        self.user = None
        self.password = None

    def getPassword(self):
        # self.user = "dblasby"
        # self.password = "dblasby"
        if self.user is None or self.password is None:            
            params = [Parameter("username", "Username", "", STRING, ""),
                  Parameter("password", "Password", "", PASSWORD, "")]
            ret = openParametersDialog(params, "Geogig server credentials ({})".format(self.url))            
            if ret is not None:
                self.user = ret["username"]
                self.password = ret["password"]
                return True, True
            return False, True
        return True, False


    def getHttp(self, command, payload={}, headers={"Accept": "application/json"}):
        try:
            pwdok, prompted = self.getPassword()
            if pwdok:
                QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
                QtCore.QCoreApplication.processEvents()
                try:
                    url = self.url + command
                    r = requests.get(url, params=payload, headers=headers, auth=(self.user, self.password))
                    if r.status_code == 401:
                        if prompted:
                            self.resetCredentials()
                        raise GeogigAuthException() 
                    try:
                        r.raise_for_status()            
                    except Exception as e:
                        if prompted:
                            self.resetCredentials()
                        raise GeogigError("Error using GET at " + url, str(e),causedBy=e)
                    return r.json()
                except requests.exceptions.ConnectionError as e:
                    if prompted:
                        self.resetCredentials()
                    raise
            else:
                if prompted:
                    self.resetCredentials()
                raise GeogigAuthException()                
        finally:            
            QtWidgets.QApplication.restoreOverrideCursor()
            QtCore.QCoreApplication.processEvents()

    def post(self, command, json=None, params={}, headers={"Accept": "application/json"}):
        try:
            pwdok, prompted = self.getPassword()
            if pwdok:            
                QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
                QtCore.QCoreApplication.processEvents()
                try:
                    url = self.url + command
                    if json is not None:                      
                        r = requests.post(url, json=json, headers=headers, auth=(self.user, self.password))
                    else:
                        r = requests.post(url, data=params, headers=headers, auth=(self.user, self.password))
                    if r.status_code == 401:
                        if prompted:
                            self.resetCredentials()
                        raise GeogigAuthException() 
                    try:
                        r.raise_for_status()
                    except Exception as e:
                        if prompted:
                            self.resetCredentials()
                        raise GeogigError("Error using POST at " + url, str(e))                        
                    try:
                        return r.json()
                    except:
                        return []
                except requests.exceptions.ConnectionError as e:
                    if prompted:
                        self.resetCredentials()
                    raise
            else:
                if prompted:
                    self.resetCredentials()
                raise GeogigAuthException()                
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtCore.QCoreApplication.processEvents()

    def delete(self, command, headers={}):
        try:
            pwdok, prompted = self.getPassword()
            if pwdok:            
                QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
                QtCore.QCoreApplication.processEvents()
                try:
                    url = self.url + command              
                    r = requests.delete(url, headers=headers, auth=(self.user, self.password))
                    if r.status_code == 401:
                        if prompted:
                            self.resetCredentials()
                        raise GeogigAuthException()
                    try:              
                        r.raise_for_status()
                    except Exception as e:
                        if prompted:
                            self.resetCredentials()
                        raise GeogigError("Error using DELETE at " + url, str(e))
                except requests.exceptions.ConnectionError as e:
                    if prompted:
                        self.resetCredentials()
                    raise
            else:
                if prompted:
                    self.resetCredentials()
                raise GeogigAuthException() 
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtCore.QCoreApplication.processEvents()
      