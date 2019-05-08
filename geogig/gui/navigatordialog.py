# -*- coding: utf-8 -*-

import os
import sys
from functools import partial
from datetime import datetime

from requests.exceptions import ConnectionError

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QUrl, QSize, QSettings
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtWidgets import (QHeaderView, QVBoxLayout, QAbstractItemView, QTreeWidgetItem,
                                 QMessageBox, QInputDialog, QLabel, QHBoxLayout, QSizePolicy,
                                 QWidget, QPushButton, QApplication, QAction, QMenu, QMessageBox,
                                 QTextBrowser, QTreeWidget, QFileDialog)

from qgis.core import QgsApplication, QgsMessageLog, Qgis, QgsProject, QgsWkbTypes
from qgis.gui import QgsMessageBar
from qgis.utils import iface

from geogig.geogigwebapi.connector import Connector, getConnector, GeogigAuthException, GeogigError
from geogig.geogigwebapi.server import Server
from geogig.gui.commitgraph import CommitGraph
from geogig.gui.historyviewer import HistoryDiffViewerDialog
from geogig.gui.synchronizedialog import SynchronizeDialog
from geogig.gui.layerinfodialog import asHTML
from geogig.gui.layerexplorer import LayerExplorer
from geogig.gui.pullrequestsdialog import PullRequestsDialog
from geogig.gui.constellationviewer import ConstellationViewerDialog
from geogig.styles import saveStyleFromQgisLayer
from geogig.utils import GEOGIGID_FIELD
from geogig.layers import addGeogigLayer, isGeogigLayer

from qgiscommons2.gui import execute
from qgiscommons2.gui.paramdialog import openParametersDialog, Parameter, STRING, VECTOR, CHOICE
from qgiscommons2.layers import vectorLayers

from concurrent.futures import ThreadPoolExecutor

pluginPath = os.path.split(os.path.dirname(__file__))[0]

def icon(f):
    return QIcon(os.path.join(pluginPath, "ui", "resources", f))

serverIcon = icon("server.svg")
userIcon = icon("user.svg")
repoIcon = icon("database.svg")
pullRequestIcon = icon("upload.svg")
layerIcon = icon('geometry.png')
layersIcon = icon('layer_group.svg')
copyIcon  = icon('copy.png')
mergeIcon = icon("merge-24.png")

WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'navigatordialog.ui'))

def _servers():
    s = QSettings().value("geogig/servers", None)
    if s is None:
        return {}
    else:
        servers = s.split("|")
        serversdict = {}
        for server in servers:
            try:
                name, url = server.split(";")
                serversdict[name] = url
            except:
                pass
        return serversdict
        
def _saveServers(servers):
    s = "|".join([name + ";" + url for name, url in servers.items()])
    QSettings().setValue("geogig/servers", s)


# data["users"] => list of string (user)
# data["userRepos"] => dictionary String (username) -> dictionary of String (reponame)
# Repo -> json object of repo, with
#          ["pull_requests"] -> list of PR (json)
#          ["layers"] -> list of layer names (str)
class RepoDataPreloader:
    def __init__(self, server):
        object.__init__(self)
        self.server = server
        self.users = self.server.users()
        self.data = {"users": self.users}
        self.populate()

    def populate(self):
        self.data["userRepos"] = {}
        for user in self.users:
            self.populateUser(user)

    def populateUser(self,userName):
        repos = self.server.reposForUser(userName)
        self.data["userRepos"][userName] = {}
        for repo in repos:
            repoName = repo["identity"]
            self.data["userRepos"][userName][repoName] = repo
        with ThreadPoolExecutor(max_workers=6) as executor:
            for repo in repos:
                future = executor.submit(self.augementRepo, userName,repo)

    def augementRepo(self, userName, repo):
        repo["pull_requests"] = self.server.pullRequests(userName, repo["identity"])
        repo["layers"] = self.server.layers(userName, repo["identity"], "master")

class NavigatorDialog(BASE, WIDGET):

    def __init__(self):
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        super(NavigatorDialog, self).__init__(None)
        self.reposItem = None
        self.setupUi(self)
        self.addDescriptionPanel()

        self.repoTree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.repoTree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.repoTree.customContextMenuRequested.connect(self.showPopupMenu)
        self.repoTree.itemSelectionChanged.connect(self.selectionChanged)
        self.repoTree.itemDoubleClicked.connect(self.treeItemDoubleClicked)

        def keyPressEvent(event):
            item = self.repoTree.currentItem()
            if item is not None:
                #print (event.key())
                if (event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return) and item.childCount() == 0:
                    item.doubleClicked()
                elif (event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return):
                    item.setExpanded(not item.isExpanded())
                else:
                   QTreeWidget.keyPressEvent(self.repoTree, event)
            else:
                QTreeWidget.keyPressEvent(self.repoTree, event)
        self.repoTree.keyPressEvent = keyPressEvent

        self.fillTree()

        self.repoTree.topLevelItem(0).setExpanded(True)

        def onItemExpanded(item):
            item.onExpanded()
        self.repoTree.itemExpanded.connect(onItemExpanded)

        if self.repoTree.topLevelItem(0).childCount() > 0:
            self.repoTree.topLevelItem(0).child(0).setSelected(True)
            self.repoTree.setCurrentItem(self.repoTree.topLevelItem(0).child(0))
            self.selectionChanged()

    def treeItemDoubleClicked(self):
        item = self.repoTree.currentItem()
        if item:
            self.runAndUpdatePanel(item.doubleClicked)

    def addDescriptionPanel(self):
        class MyBrowser(QTextBrowser):
            def loadResource(self, type, name):
                return None
        self.descriptionPanel = MyBrowser()
        self.descriptionPanel.setOpenLinks(False)
        def linkClicked(url):
            self.runAndUpdatePanel(self.repoTree.currentItem().actions()[url.url()])            
        self.descriptionPanel.anchorClicked.connect(linkClicked)
        self.descriptionPanel.setHtml("")
        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setMargin(0)
        layout.addWidget(self.descriptionPanel)
        self.descriptionWidget.setLayout(layout)

    def selectionChanged(self):
        self.updateDescription()

    def updateDescription(self):
        item = self.repoTree.currentItem()
        if item:
            html = self.prepareDescriptionHtml(item.html(), item.header(), item.actions())
            self.descriptionPanel.setText(html)

    def prepareDescriptionHtml(self, html, header, actions):
        header = u'<div style="background-color:#C7DBFC;"><h1>&nbsp;' + header + '</h1></div>'
        html += "<p><h3><b>Available actions</b></h3></p><ul>"
        if actions:
            for action in actions:
                html += '<li><a href="' + action + '">' + action + '</a></li>\n'
        else:
                html += '<li>No actions available for this item</li>'
        html += '</ul>'
        html = u"""
            <!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
            <html>
            <head>
            <style type="text/css">
                h1 { color: #555555}
                a { text-decoration: none; color: #3498db; font-weight: bold; }
                a.edit { color: #9f9f9f; float: right; font-weight: normal; }
                p { color: #666666; }
                b { color: #333333; }
                .section { margin-top: 25px; }
                table.header th { background-color: #dddddd; }
                table.header td { background-color: #f5f5f5; }
                table.header th, table.header td { padding: 0px 10px; }
                table td { padding-right: 20px; }
                .underline { text-decoration:underline; }
            </style>
            </head>
            <body>
            %s %s <br>
            </body>
            </html>
            """ % (header, html)
        return html

    def showPopupMenu(self, point):
        item = self.repoTree.currentItem()
        self.menu = self.createMenu(item)
        point = self.repoTree.mapToGlobal(point)
        self.menu.popup(point)

    def runAndUpdatePanel(self, f):
        try:
            f()
        finally:
            self.updateDescription()

    def createMenu(self, item):
        menu = QMenu()
        for text, func in item.actions().items():
            action = QAction(text, menu)
            action.triggered.connect(partial(self.runAndUpdatePanel, func))
            menu.addAction(action)  
        if isinstance(item, RefreshableGeogigItem):
            action = QAction("Refresh", menu)  
            action.triggered.connect(partial(self.runAndUpdatePanel, item.refreshContent))
            menu.addAction(action)
        return menu

    def fillTree(self):
        self.repoTree.clear()        
        item = ServersItem()
        self.repoTree.addTopLevelItem(item)

        self.repoTree.sortItems(0, Qt.AscendingOrder)

    def itemFromPath(self, *path):
        def _find(name, parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.text(0) == name:
                    return child
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.text(0).startswith(name):
                    return child

        path = list(path)
        item = self.repoTree.invisibleRootItem().child(0)
        for p in path:
            item = _find(p, item)

        return item

    def refreshItem(self, *path):
        item = self.itemFromPath(path)
        item.refreshContent()

def expandChildren(item):
    for i in range(item.childCount()):
        child = item.child(i)
        expandChildren(child)
    item.setExpanded(True)

class GeogigItem(QTreeWidgetItem):
    def __init__(self):
        QTreeWidgetItem.__init__(self)
    
    def html(self):
        return ""

    def header(self):
        return self.text(0)

    def onExpanded(self):
        pass

    def doubleClicked(self):
        if self.childCount() == 0:
            try:
                list(self.actions().values())[0]()
            except IndexError:
                pass

class RefreshableGeogigItem(GeogigItem):
    def __init__(self):
        GeogigItem.__init__(self)

    def refreshContent(self):
        self.takeChildren()
        self.populate()
        self.treeWidget().itemSelectionChanged.emit()

class ServersItem(RefreshableGeogigItem):
    def __init__(self):
        RefreshableGeogigItem.__init__(self)
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setText(0, "Servers")
        self.setIcon(0, serverIcon)
        self.populate()

    def populate(self):
        for name, url in _servers().items():
            item = ServerItem(url, name)
            self.addChild(item)
        self.setExpanded(True)

    def actions(self):
        return {"Add new server...": self.addNewServer}

    def addNewServer(self):
        params = [Parameter("url", "URL", "", STRING, "http://localhost:8181"),
                  Parameter("name", "Name", "", STRING, "")]
        
        urls = []
        for i in range(self.childCount()):
            serverItem = self.child(i)
            urls.append(serverItem.url)
        ret = openParametersDialog(params, "New server")
        if ret is not None:
            url = ret["url"]
            url = url + "/" if not url.endswith("/") else url
            if url in urls:
                raise GeogigError("A server item with that url already exists")
            item = ServerItem(url, ret["name"])
            self.addChild(item)
            servers = _servers()
            servers[ret["name"]] = url
            _saveServers(servers)

class ServerItem(RefreshableGeogigItem):
    def __init__(self, url, name):
        RefreshableGeogigItem.__init__(self)
        self.url = url
        self.name = name
        self.connector = None
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setText(0, name + " [not connected]")
        self.setIcon(0, serverIcon)

        self.connector = getConnector(self.url)

        self.server = Server.getInstance(self.connector)
        self.server.repoDeleted.connect(self._repoDeleted)
        self.server.repoForked.connect(self._repoForked)
        self.server.repoCreated.connect(self._repoCreated)
        self.server.pullRequestCreated.connect(self._pullRequestCreated)
        self.server.pullRequestMerged.connect(self._pullRequestMerged)
        self.server.pullRequestClosed.connect(self._pullRequestClosed)
        self.server.syncFinished.connect(self._syncFinished)

        self.usersItem = None

    def _userItems(self, user):
        items = []
        if self.usersItem is not None:
            for i in range(self.usersItem.childCount()):
                child = self.usersItem.child(i)
                if child.user == user:
                    items.append(child)
                    break
            if user == self.connector.user:
                items.append(self.myUserItem)

        return items

    def _itemsFromRepo(self, user, repo):
        items = []
        userItems = self._userItems(user)
        for userItem in userItems:
            for i in range(userItem.childCount()):
                repoItem = userItem.child(i)
                if repoItem.repo == repo:
                    items.append(repoItem)
                    break

        return items

    def _pullRequestCreated(self, user, repo, prId):
        pr = self.server.pullRequest(user, repo, prId)
        items = self._itemsFromRepo(user, repo)
        for item in items:
            prItem = PullRequestItem(pr, repo, user, self.server)
            item.pullRequestsItem.addChild(prItem)
        iface.messageBar().pushMessage("Add layer", "Pull request correctly created", level=Qgis.Info, duration=5)

    def _pullRequestMerged(self, user, repo, prId):
        #pr = self.server.pullRequest(user, repo, prId)
        items = self._itemsFromRepo(user, repo)
        for item in items:
            for i in range(item.pullRequestsItem.childCount()):
                prItem = item.pullRequestsItem.child(i)
                if prItem is None or prItem.pullRequestId == prId:
                    item.pullRequestsItem.takeChild(i)
        iface.messageBar().pushMessage("PR", "Pull request correctly merged", level=Qgis.Info, duration=5)

    def _syncFinished(self,user,repo):
        iface.messageBar().pushMessage("PULL", "Sync request finished", level=Qgis.Info, duration=5)

    #same as _pullRequestMerged()
    def _pullRequestClosed(self, user, repo, prId):
        #pr = self.server.pullRequest(user, repo, prId)
        items = self._itemsFromRepo(user, repo)
        for item in items:
            for i in range(item.pullRequestsItem.childCount()):
                prItem = item.pullRequestsItem.child(i)
                if prItem is None:
                    continue
                if prItem.pullRequestId == prId:
                    item.pullRequestsItem.takeChild(i)
        iface.messageBar().pushMessage("PR", "Pull request correctly closed", level=Qgis.Info, duration=5)

    def _repoForked(self, user, repo, forkName):
        userItems = self._userItems(self.connector.user)
        for userItem in userItems:
            repo = self.server.repo(self.connector.user, forkName)
            item = RepoItem(repo, self.server)
            userItem.addChild(item)  

    def _repoCreated(self, user, repo):        
        userItems = self._userItems(user)
        repo = self.server.repo(user, repo)
        for userItem in userItems:            
            item = RepoItem(repo, self.server)
            userItem.addChild(item)                

    def _repoDeleted(self, user, repo):
        items = self._itemsFromRepo(user, repo)
        for item in items:
            item.parent().takeChild(item.parent().indexOfChild(item))
        
    def populate(self):           
        try:
            preloadedData = RepoDataPreloader(self.server).data
            self.usersItem = UsersItem(self.server,preloadedData=preloadedData)
            self.addChild(self.usersItem)              
        except ConnectionError:
            raise GeogigError("Connection error. Server not available or might not be a GeoGig server.")
        try:
            self.myUserItem = UserItem(self.connector.user, self.server, preloadedData=preloadedData["userRepos"][self.connector.user])
            self.myUserItem.setText(0, "My repos")
            self.myUserItem.setIcon(0, repoIcon)
            self.addChild(self.myUserItem)
            self.myUserItem.setExpanded(True)
        except:
            pass
        self.setExpanded(True)

    def refreshContent(self):
        self.takeChildren()        
        self.populate()        
        self.setText(0, "{} [connected as {}]".format(self.name, self.connector.user))

    def actions(self):
        if self.childCount():
            actions = {"Change user...": self.changeUser}
        else:
            actions = {"Connect...": self.connect}
        actions["Remove server"] = self.removeServer
        return actions

    def changeUser(self):
        self.connector.resetCredentials()
        self.refreshContent()

    def connect(self):
        self.refreshContent()

    def removeServer(self):
        self.parent().takeChild(self.parent().indexOfChild(self))
        servers = _servers()     
        del servers[self.name]
        _saveServers(servers)

    def html(self):
        html = "<ul><li><b>Server URL: </b>%s</li>" % self.url
        return html

class UsersItem(RefreshableGeogigItem):
    def  __init__(self, server,preloadedData=None):
        RefreshableGeogigItem.__init__(self)
        self.server = server
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setText(0, "Users")
        self.setIcon(0, userIcon)
        self.populate(preloadedData=preloadedData)

    def populate(self,preloadedData=None):
        if preloadedData is None:
            users = self.server.users()
            for user in users:
                item = UserItem(user, self.server)
                self.addChild(item)
        else:
            userRepos = preloadedData["userRepos"]
            for userName,repos in userRepos.items():
                item = UserItem(userName, self.server,preloadedData=repos)
                self.addChild(item)

    def actions(self):
        return {"Create user": self.createUser}

    def createUser(self):
        stores = self.server.stores()
        params = [Parameter("email", "Email", "", STRING, ""),
                  Parameter("username", "Username", "", STRING, ""),
                  Parameter("password", "Password", "", STRING, ""),
                  Parameter("fullname", "Full name", "", STRING, ""),
                  Parameter("defaultstore", "Default Store", "", CHOICE, stores)]
        
        ret = openParametersDialog(params, "New user")
        if ret is not None:
            self.server.createUser(ret["username"], ret["password"], ret["fullname"],
                            ret["email"], ret["defaultstore"])
            self.refreshContent()
    

class UserItem(RefreshableGeogigItem):
    def __init__(self, user, server,preloadedData=None):
        RefreshableGeogigItem.__init__(self)
        self.user = user
        self.server = server
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self.belongsToLoggedUser = self.server.connector.user == self.user
        self.setText(0, user)
        self.setIcon(0, userIcon)
        self.populate(preloadedData)

    def populate(self,preloadedData=None):
        if preloadedData is None:
            repos = self.server.reposForUser(self.user)
            for repo in repos:
                item = RepoItem(repo, self.server)
                self.addChild(item)
        else:
            for repoName,repo in preloadedData.items():
                item = RepoItem(repo, self.server,preloadedData=repo)
                self.addChild(item)

    def actions(self):
        if self.belongsToLoggedUser:
            return {"Create repository...": self.createRepo}
        else:
            return {}

    def deleteUser(self):
        self.server.deleteUser(self.user)
        self.parent().refreshContent()

    def createRepo(self):
        #stores = self.server.stores()
        params = [Parameter("reponame", "Repository name", "", STRING, "")]
        ret = openParametersDialog(params, "New repository")
        if ret is not None:    
            self.server.createRepo(self.user, ret["reponame"])  
  
class RepoItem(RefreshableGeogigItem):
    def __init__(self, repo, server, preloadedData=None):
        RefreshableGeogigItem.__init__(self)
        self.repo = repo["identity"]
        self.user = repo["owner"]["identity"]
        self.forkedFrom = repo["forked_from"]
        self.server = server
        self.belongsToLoggedUser = self.server.connector.user == self.user
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        reponame = self.repo
        if self.forkedFrom:
            reponame += " [forked from {}/{}]".format(self.forkedFrom["owner"]["identity"], self.forkedFrom["identity"])
        self.setText(0, reponame)
        self.setIcon(0, repoIcon)
        self.populate(preloadedData=preloadedData)

    def onExpanded(self):
        expandChildren(self)

    def populate(self, preloadedData=None):
        if preloadedData is None:
            self.layersItem = LayersItem(self.repo, self.user, self.server)
            self.addChild(self.layersItem)
            self.pullRequestsItem = PullRequestsItem(self.repo, self.user, self.server)
            self.addChild(self.pullRequestsItem)
        else:
            self.layersItem = LayersItem(self.repo, self.user, self.server, preloadedData=preloadedData["layers"])
            self.addChild(self.layersItem)
            self.pullRequestsItem = PullRequestsItem(self.repo, self.user, self.server, preloadedData=preloadedData["pull_requests"])
            self.addChild(self.pullRequestsItem)

    def actions(self):
        actions = {"Show log...": self.showLog,
                 "Fork repository...": self.forkRepo}
        if self.belongsToLoggedUser:
            actions.update({"Add layer...": self.importLayer,
                          "Delete repository": self.deleteRepo,
                          "Create pull request...": self.createPullRequest})
            actions.update({"Pull changes from another repo...": self.pullFromAnotherRepo})
        actions.update({"Show repo constellation...": self.showConstellation})

        return actions

    def importLayer(self):
        params = [Parameter("layer", "Layer to add", "", VECTOR, ""),
                  Parameter("message", "Commit message", "", STRING, "")]
        ret = openParametersDialog(params, "Add layer")
        if ret is not None:
            if ret["layer"] is None:
                return
            if isGeogigLayer(ret["layer"]):
                raise GeogigError("Selected layer is already a Geogig layer")
            if GEOGIGID_FIELD in [f.name().lower() for f in ret["layer"].fields()]:
                raise GeogigError("Selected layer has a 'geogigid' field")
            msg = ret["message"] or "Added layer '{}'".format(ret["layer"].name())
            self.server.addLayer(self.user, self.repo, ret["layer"], "master", msg)
            saveStyleFromQgisLayer(ret["layer"], self.server, self.user, self.repo)
            self.refreshContent()
            iface.messageBar().pushMessage("Add layer", "Layer correctly imported", level=Qgis.Info, duration=5)

    def showConstellation(self):
        dlg = ConstellationViewerDialog(self.server, self.user, self.repo)
        dlg.show()
        dlg.exec_()
        pass

    def deleteRepo(self):
        constellation = self.server.constellation(self.user, self.repo)
        for repo in constellation.all:
            if (repo.forkedFrom is not None and repo.forkedFrom.ownerName == self.user
                    and repo.forkedFrom.repoName == self.repo):
                QMessageBox.warning(iface.mainWindow(),
                                    "Cannot delete repository",
                                    "Repository has children. You have to delete the children before deleting it.")
                return
        ret = QMessageBox.critical(iface.mainWindow(),
                                    "Delete repository",
                                    "Are you sure you want to delete this repository?",
                                    QMessageBox.Ok | QMessageBox.Cancel)
        if ret == QMessageBox.Ok:
            self.server.deleteRepo(self.user, self.repo)

    def forkRepo(self):
        name = self.repo if not self.belongsToLoggedUser else self.repo + "_2"        
        repoName, okPressed = QInputDialog.getText(navigatorInstance, "Fork repo","Name for forked repo:", text=name)
        if okPressed:
            self.server.forkRepo(self.user, self.repo, repoName)

    def pullFromAnotherRepo(self):
        if self.forkedFrom:
            upstreamUser = self.forkedFrom["owner"]["identity"]
            upstreamRepoName = self.forkedFrom["identity"]
        else:
            upstreamUser = None
            upstreamRepoName = None
        syncDialog = SynchronizeDialog(self.user, self.repo, self.server, upstreamUser, upstreamRepoName)
        syncDialog.exec_()

    def showLog(self):
        commits, commitsDict = self.server.log(self.user, self.repo, "master")
        graph = CommitGraph(commits, commitsDict)
        dialog = HistoryDiffViewerDialog(self.server, self.user, self.repo, graph)
        dialog.exec_()

    def createPullRequest(self):
        if self.forkedFrom:
            defaultParent = self.forkedFrom["owner"]["identity"] + ":" + self.forkedFrom["identity"]
        else:
            defaultParent = None
        dialog = PullRequestsDialog(self.server, self.user, self.repo, True, defaultParent = defaultParent)
        dialog.exec_()

    def header(self):
        return self.repo

    def html(self):
        commit = self.server.commitForBranch(self.user, self.repo, "master")
        if commit is None:
            html = "<ul><li><b>No commits in this repository.</b></li>"
        else:
            date = datetime.fromtimestamp(commit["author"]["timestamp"] / 1000).strftime("%m/%d/%y %H:%M")
            html = ("<ul><li><b>Last commit: </b>%s [%s], made by %s [%s]</li>" % 
                        (commit["message"], commit["id"][:8], commit["author"]["name"], date))
        if self.forkedFrom is not None:
            html += "<li><b>Parent: </b>%s:%s</li>" % (self.forkedFrom["owner"]["identity"],
                                                        self.forkedFrom["identity"])
            try:
                behind, ahead = self.server.compareHistories(self.user, self.repo,
                                                             self.forkedFrom["owner"]["identity"],self.forkedFrom["identity"])
                if behind + ahead == 0:
                    status = "Repository in sync with parent"             
                else:                
                    status = "{} commits behind parent. {} commits ahead of parent".format(behind, ahead)
            except Exception as e:
                status = "Parent not available"
            html += "<li><b>Status: </b>%s</li></ul>" % status
        return html

class LayerItem(GeogigItem):
    def __init__(self, layer, repo, user, server):
        GeogigItem.__init__(self)
        self.layer = layer
        self.repo = repo
        self.user = user
        self.server = server
        self.infoJson = None
        self.belongsToLoggedUser = self.server.connector.user == self.user
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setText(0, layer)
        self.setIcon(0, layerIcon)

    def actions(self):
        return {"Add to QGIS project (live link)": self.addToQgisLive,
                "Add to QGIS project (geopackage)": self.addToQgis,
                "Show log (diff viewer)...": self.showLog,
                "Show log (layer explorer)...": self.showLayerExplorer,
                "Delete layer": self.deleteLayer}
 
    def showLog(self):
        commitsAll, commitsDictAll, commitsLayer, commitsDictLayer = self.server.logAll(self.user, self.repo,
                                                                                            "master", self.layer)
        graph = CommitGraph(commitsAll, commitsDictAll, commitsLayer)
        dialog = HistoryDiffViewerDialog(self.server, self.user, self.repo, graph, self.layer)
        dialog.exec_()

    def showLayerExplorer(self):
        commitsAll, commitsDictAll, commitsLayer, commitsDictLayer = self.server.logAll(self.user, self.repo,
                                                                                            "master", self.layer)
        graph = CommitGraph(commitsAll, commitsDictAll, commitsLayer)
        dialog = LayerExplorer(self.server, self.user, self.repo, graph, self.layer)
        dialog.exec_()        

    def html(self):
        if self.infoJson is None:
            self.infoJson = self.server.layerInfo(self.user, self.repo, self.layer)
        return asHTML(self.infoJson)

    def addToQgis(self):
        commitid = self.server.commitidForBranch(self.user, self.repo, "master")
        addGeogigLayer(self.server, self.user, self.repo, self.layer, commitid, False)

    def addToQgisLive(self):
        commitID = "HEAD"
        addGeogigLayer(self.server, self.user, self.repo, self.layer,commitID, True)
        
    def deleteLayer(self):
        self.server.deleteLayer(self.user, self.repo, "master", self.layer)
        self.parent().refreshContent()

class LayersItem(RefreshableGeogigItem):
    def __init__(self, repo , user, server,preloadedData=None):
        RefreshableGeogigItem.__init__(self)            
        self.repo = repo
        self.user = user
        self.server = server
        self.belongsToLoggedUser = self.server.connector.user == self.user
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self.setText(0, "Layers")
        self.setIcon(0, layersIcon)
        self.populate(preloadedData)

    def populate(self,preloadedData=None):
        if preloadedData is None:
            layers = self.server.layers(self.user, self.repo, "master")
        else:
            layers = preloadedData
        for layer in layers:
            item = LayerItem(layer, self.repo, self.user, self.server)
            self.addChild(item)

    def actions(self):
        actions = {}
        if self.belongsToLoggedUser:            
            actions.update({"Add layer...": self.parent().importLayer})
        return actions

class PullRequestsItem(RefreshableGeogigItem):
    def __init__(self, repo, user, server,preloadedData=None):
        RefreshableGeogigItem.__init__(self)            
        self.repo = repo
        self.user = user
        self.server = server
        self.belongsToLoggedUser = self.server.connector.user == self.user
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self.setText(0, "Pull requests")
        self.setIcon(0, pullRequestIcon)
        self.populate(preloadedData)

    def populate(self,preloadedData=None):
        if preloadedData is None:
            pullRequests = self.server.pullRequests(self.user, self.repo)
        else:
            pullRequests=preloadedData
        for pr in pullRequests:
            if pr["sourceRepo"] is not None:
                item = PullRequestItem(pr, self.repo, self.user, self.server)
                self.addChild(item)

    def actions(self):
        return {}

class PullRequestItem(GeogigItem):
    def __init__(self, pullRequest, repo, user, server):
        GeogigItem.__init__(self)            
        self.repo = repo
        self.user = user
        self.pullRequestId = pullRequest["id"]
        self.pullRequestName = pullRequest["title"]
        self.server = server
        self.belongsToLoggedUser = self.server.connector.user == self.user
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.setText(0, pullRequest["title"])
        self.setIcon(0, pullRequestIcon)

    def actions(self):
        return {"Show details...": self.viewPullRequest}

    def viewPullRequest(self):
        dlg = PullRequestsDialog(self.server, self.user, self.repo, False, 
                            prName = self.pullRequestName, prID = self.pullRequestId)
        dlg.exec_()

navigatorInstance = NavigatorDialog()
