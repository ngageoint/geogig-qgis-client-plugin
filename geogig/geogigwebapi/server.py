import json
# import geojson
import sqlite3
import shutil
import time

import requests
import copy
import sys

from qgis.core import (QgsVectorFileWriter, QgsWkbTypes, QgsVectorLayer,
                        QgsCoordinateReferenceSystem, QgsFeatureRequest, 
                        QgsJsonExporter, QgsFeature, QgsField, QgsFields)
from qgis.PyQt.QtCore import QVariant, pyqtSignal, Qt, QTimer, QObject, QEventLoop, QCoreApplication
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import QApplication
#from qgiscommons2.files import tempFilename, tempFilenameInTempFolder
from qgiscommons2.gui import (execute, startProgressBar, closeProgressBar,
                                setProgressValue, setProgressText, isProgressCanceled)
from requests import HTTPError

from geogig.cleanse import *
from geogig.geogigwebapi.connector import GeogigError
from geogig.utils import GEOGIGID_FIELD
from geogig.protobuff.queryforlayerproto import QueryForLayerProto
from geogig.geogigwebapi.repomanagement import RepoManagement
from geogig.protobuff.proto2qgis import FeatureWriter, typeNumbToBinding
from geogig.geopkgtools import difference
from geogig.gui.progressbar import currentWindow
from itertools import islice, chain

STYLE = "Style"
ID = "id"
STYLETABLE = "__styles__"
STYLEBRANCH = "__styles__"

def _identities(objs):
    return [obj["identity"] for obj in objs]

def _name(objs):
    return [obj["name"] for obj in objs]



class Server(QObject, RepoManagement):

    repoForked= pyqtSignal(str, str, str)
    repoDeleted= pyqtSignal(str, str)
    repoCreated = pyqtSignal(str, str)
    branchCreated = pyqtSignal(str, str, str)
    branchDeleted = pyqtSignal(str, str, str)
    pullRequestCreated = pyqtSignal(str, str, int)
    pullRequestMerged = pyqtSignal(str, str, int)
    pullRequestClosed = pyqtSignal(str, str, int)
    syncFinished = pyqtSignal(str,str)
    commitMade = pyqtSignal(str,str)
    revertDone = pyqtSignal(str,str)
    resetDone = pyqtSignal(str,str)

    # object cache for sharing Server instances
    # connector URL -> Server instance
    objectCache = {}

    @staticmethod
    def getInstance(connector):
        url = connector.url
        if url in Server.objectCache:
            return Server.objectCache[url]
        instance = Server(connector)
        Server.objectCache[url] = instance
        return instance

    def __init__(self, connector):
        QObject.__init__(self)
        self.connector = connector
        
    def createUser(self, name, password, fullname, email, defaultstore):
        userinfo = {"identity": name,
          "privateProfile": {
            "defaultStore": {
              "identity": defaultstore
            },
            "emailAddress": email,
            "fullName": fullname
          },
          "siteAdmin": False,
          "type": "INDIVIDUAL"
        }
        self.connector.post("users", json=userinfo)
        self.connector.put("users/{}/password".format(name), payload={"newPassword": password})

    def deleteUser(self, user):
        user = cleanseUserName(user)
        self.connector.delete("users/{}".format(user))

    def users(self):        
        return _identities(self.connector.getHttp("users"))

    def layerInfo(self,user,repo,layer):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        return self.connector.getHttp("layers/{}/{}/{}".format(user, repo, layer))

    def pullRequest(self, user, repo, pr):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        pr = cleansePRId(pr)
        return self.connector.getHttp("repos/{}/{}/pulls/{}".format(user, repo, pr))

    # def pullRequestCommits(self, user, repo, pr):
    #     commits = self.connector.get("repos/{}/{}/pulls/{}/commits".format(user, repo, pr))
    #     return self._prepareCommits(commits)

    def pullRequests(self, user, repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        return self.connector.getHttp("repos/{}/{}/pulls".format(user, repo))

    def createPullRequest(self, user, repo, targetUser, targetRepo, title, branch, targetBranch,description=""):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        targetUser= cleanseUserName(targetUser)
        targetRepo = cleanseRepoName(targetRepo)
        targetBranch = cleanseBranchName(targetBranch)
        params = {"description": description,
                    "sourceRepositoryBranch": branch,
                    "sourceRepositoryOwner": user,
                    "sourceRepositryName": repo,
                    "targetBranch": targetBranch,
                    "title": title}
        ret = self.connector.post("repos/{}/{}/pulls".format(targetUser, targetRepo), json=params)
        self.pullRequestCreated.emit(targetUser, targetRepo, ret["id"])
        return ret["id"]

    # def pullRequestDiff(self, user, repo, pullRequestId):
    #     pr = self.connector.get("repos/{}/{}/pulls/{}".format(user, repo, pullRequestId))
    #     sourceRepo = pr["sourceRepo"]["identity"]
    #     sourceUser = pr["sourceRepo"]["owner"]["identity"]
    #     commits = self.connector.get("repos/{}/{}/pulls/{}/commits".format(user, repo, pullRequestId))
    #     newRef = commits[0]["id"]
    #     oldRef = commits[-1]["parentIds"][0]
    #     layers = self.layers(sourceUser, sourceRepo, newRef)
    #     diffs = {}
    #     for layer in layers:
    #         diffs[layer] = self.diff(sourceUser, sourceRepo, layer, newRef, oldRef)
    #     return diffs

    # def pullRequestTX(self,user,repo,pullRequestID):
    #     status= self.connector.get("/repos/{}/{}/pulls/{}/merge".format(user,repo,pullRequestID))
    #     return status["transaction"]

    def pullRequestMetaData(self,user,repo,pullRequestID):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        pullRequestID = cleansePRId(pullRequestID)
        while True:
            try:
                result = self._pullRequestMetaData(user,repo,pullRequestID)
                return result
            except GeogigError as ge:
                if ge.causedBy is None or not isinstance(ge.causedBy, HTTPError):
                    raise
                ee = ge.causedBy
                code = ee.response.status_code
                if code != 409:  # 409 = retry
                    raise  # abort
                QCoreApplication.processEvents()
                time.sleep(0.500)  # delay before re-try
                QCoreApplication.processEvents()

    def _pullRequestMetaData(self, user, repo, pullRequestID):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        pullRequestID = cleansePRId(pullRequestID)
        return self.connector.getHttp("/repos/{}/{}/pulls/{}/merge".format(user, repo, pullRequestID))

    def numberConflictsPR(self,user,repo,pullRequestID):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        pullRequestID = cleansePRId(pullRequestID)
        status = self.pullRequestMetaData(user, repo, pullRequestID)
        return status["numConflicts"]

    def affectedLayersPR(self, user, repo, pullRequestID):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        pullRequestID = cleansePRId(pullRequestID)
        status = self.pullRequestMetaData(user, repo, pullRequestID)
        return status["affectedLayers"]
        # status = self.connector.get("/repos/{}/{}/pulls/{}/merge".format(user, repo, pullRequestID))
        # return status["affectedLayers"]

    def getRepo(self,user,repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        return self.connector.getHttp("/repos/{}/{}".format(user, repo))

    def branchConflicts(self, user, repo, branch, user2, repo2, branch2):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        user2 = cleanseUserName(user2)
        repo2 = cleanseRepoName(repo2)
        branch = cleanseBranchName(branch)
        branch2 = cleanseBranchName(branch2)
        ret = self.connector.getHttp("/collab/{}/{}/{}/conflictswith/{}/{}/{}".format(user, repo, branch, user2, repo2, branch2))
        return ret

    def mergePullRequest(self, user, repo, pullRequestId):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        pullRequestId = cleansePRId(pullRequestId)
        ret = self.connector.post("repos/{}/{}/pulls/{}/merge".format(user, repo, pullRequestId))
        taskId = ret["id"]
        ok, result = self.waitForTask(taskId, "Processing changes on server")
        if ok:
            self.resetLogCache()
            self.pullRequestMerged.emit(user, repo, pullRequestId)
        return ok

    _logCache = {}

    def resetLogCache(self):
        self._logCache = {}  

    # child, parent
    def compareHistories(self, user, repo, user2 , repo2 , branch = "master", branch2 = "master"):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        user2 = cleanseUserName(user2)
        repo2 = cleanseRepoName(repo2)
        branch = cleanseBranchName(branch)
        branch2 = cleanseBranchName(branch2)
        if user2 is None:
            return 0, 0

        if user is None:
            return 0, 0

        result = self.connector.getHttp("collab/{}/{}/{}/aheadBehind/{}/{}/{}".format(
            user2,repo2,branch2,
            user, repo, branch))
        return len(result["commitsBehind"]),len(result["commitsAhead"])


    def fullHistoryCompare(self, user, repo, user2 , repo2 , branch = "master", branch2 = "master"):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        user2 = cleanseUserName(user2)
        repo2 = cleanseRepoName(repo2)
        branch = cleanseBranchName(branch)
        branch2 = cleanseBranchName(branch2)
        result = self.connector.getHttp("collab/{}/{}/{}/aheadBehind/{}/{}/{}".format(
            user2, repo2, branch2,
            user, repo, branch))
        return self._prepareCommits(result["commitsBehind"]),self._prepareCommits(result["commitsAhead"])

    def aheadCommits(self, user, repo, user2, repo2,branch = "master", branch2 = "master"):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        user2 = cleanseUserName(user2)
        repo2 = cleanseRepoName(repo2)
        branch = cleanseBranchName(branch)
        branch2 = cleanseBranchName(branch2)
        result = self.connector.getHttp("collab/{}/{}/{}/aheadBehind/{}/{}/{}".format(
            user2, repo2, branch2,
            user, repo, branch))

        return self._prepareCommits(result["commitsAhead"])

    def behindCommits(self, user, repo, user2, repo2, branch="master", branch2="master"):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        user2 = cleanseUserName(user2)
        repo2 = cleanseRepoName(repo2)
        branch = cleanseBranchName(branch)
        branch2 = cleanseBranchName(branch2)
        result = self.connector.getHttp("collab/{}/{}/{}/aheadBehind/{}/{}/{}".format(
            user2, repo2, branch2,
            user, repo, branch))
        return self._prepareCommits(result["commitsBehind"])

    def commonAncestor(self, user, repo, user2, repo2):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        user2 = cleanseUserName(user2)
        repo2 = cleanseRepoName(repo2)
        return self.connector.getHttp("collab/{}/{}/master/commonAncestor/{}/{}/master".format(user, repo, user2, repo2))["id"]

    def closePullRequest(self, user, repo, pullRequestId):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        pullRequestId = cleansePRId(pullRequestId)
        headers = {"Accept": "application/json","Content-Type": "application/json"}
        self.connector.post("/repos/{}/{}/pulls/{}/close".format(user, repo, pullRequestId),headers=headers)
        self.pullRequestClosed.emit(user, repo, pullRequestId)

    def updateFromUpstream(self, user, repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        parentName, parentUser = self.parentRepo(user, repo)
        if parentName is not None:
            pass

    def stores(self):
        return _identities(self.connector.getHttp("stores"))

    def createStore(self, name, server, port, database, schema, user, password):
        storeinfo = {"identity": name,  "enabled": True, 
                    "connectionInfo": {"type": "PostgresStoreInfo", 
                                        "server": server, 
                                        "port": int(port), 
                                        "database": database, 
                                        "schema": schema, 
                                        "user": user, 
                                        "password": password}}
        self.connector.post("stores", json=storeinfo)

    def openTransaction(self, user, repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        ret = self.connector.post("transactions/{}/{}".format(user, repo))
        return cleanseTransactionId(ret["id"])

    def abortTransaction(self, user, repo, transactionid):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        transactionid = cleanseTransactionId(transactionid)
        headers = {"Accept": "application/json"}
        ret = self.connector.post("transactions/{}/{}/{}/abort".format(user, repo, transactionid), headers=headers)

    def commitTransaction(self, user, repo, transactionid, message):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        transactionid = cleanseTransactionId(transactionid)
        headers = {"Accept": "application/json",
                    "messageTitle": message}
        ret = self.connector.post("transactions/{}/{}/{}/commit".format(user, repo, transactionid), headers=headers)
        taskId = ret["id"]
        return self.waitForTask(taskId, "Processing changes in server")


    def syncBranch(self, user, repo, parentUser, parentRepo, transactionid, branch = "master", parentBranch = "master", commitMessage=""):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        parentUser = cleanseUserName(parentUser)
        parentRepo = cleanseRepoName(parentRepo)
        branch = cleanseBranchName(branch)
        parentBranch = cleanseBranchName(parentBranch)
        transactionid = cleanseTransactionId(transactionid)
        headers = {"geogig-transaction-id": transactionid}
        pullArgs = {"remote_repo_owner": parentUser,
                    "remote_repo_name": parentRepo,
                    "remote_repo_head": parentBranch,
                    "commit_message": commitMessage}
        ret = self.connector.post("repos/{}/{}/branches/{}/sync".format(user, repo, branch),
                                    json=pullArgs, headers=headers)
        taskId = ret["id"]
        ret = self.waitForTask(taskId, "Processing changes in server")
        layers = self.layers(user, repo)
        q = QueryForLayerProto(self.connector)
        result = {}
        conflictsFound = False
        for layerName in layers:
            try:
                conflicts = q.queryConflict(user, repo, layerName, transactionid)
                conflicts2 = {}
                if conflicts:
                    conflictsFound = True
                for conflict in conflicts:
                    conflicts2[conflict["ID"]] = {}
                    conflicts2[conflict["ID"]]["origin"] = conflict["ancestor"]
                    conflicts2[conflict["ID"]]["local"] = conflict["theirs"]
                    conflicts2[conflict["ID"]]["remote"] = conflict["ours"]
                result[layerName] = conflicts2
            except Exception as e:
                raise GeogigError("Error getting diff from server", str(e))
        if conflictsFound:
            return result
        return []

    def waitForTask(self, taskId, msg):
        taskId = cleanseTaskId(taskId)
        checker = TaskChecker(self.connector, taskId, msg)
        loop = QEventLoop()
        checker.taskIsFinished.connect(loop.exit, Qt.QueuedConnection)
        checker.start()
        loop.exec_()
        return checker.ok, checker.response

    def getLayerDef(self,layer):
        layer = cleanseLayerName(layer)
        def _field(field):
            fieldtype =typeNumbToBinding(field.type())
            jsonfield = {
                  "binding": fieldtype,
                  "name": field.name(),
                  "nillable": True
                }
            return jsonfield

        def _geomType(geomtype):
            geomtypes = {QgsWkbTypes.PointGeometry: "MULTIPOINT",
                     QgsWkbTypes.LineGeometry: "MULTILINESTRING",
                     QgsWkbTypes.PolygonGeometry: "MULTIPOLYGON"}
            return geomtypes.get(geomtype)
        properties = [_field(f) for f in layer.fields()]
        geomType = _geomType(layer.geometryType())
        geomField = {
                      "binding": geomType,
                      "crs": {
                        "authorityCode": layer.crs().authid()
                      },
                      "name": "geom",
                      "nillable": True
                    }
        properties.append(geomField)
        layerdef = {
                  "defaultGeometry": "geom",
                  "name": layer.name(),
                  "objectType": "RevisionFeatureType",
                  "properties": properties
                }
        return layerdef

    def feature(self, user, repo, layer, fid, refspec):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        refspec = cleanseRefSpec(refspec)
        queryForLayerProto = QueryForLayerProto(self.connector)
        query = QueryForLayerProto.createQueryFIDs(refspec, [fid])
        url = QueryForLayerProto.createURL(self.connector,
                                           user, repo, layer)
        memLayer = queryForLayerProto.querySimple(url, query)
        return list(memLayer.getFeatures())[0]

    def addStyleTable(self, user, repo, transactionid):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        transactionid = cleanseTransactionId(transactionid)
        headers = {"Accept": "application/json",
                   "geogig-transaction-id": transactionid}
        properties = [{"binding": "STRING", "name": STYLE, "nillable": False}]
        layerdef = {
                  "defaultGeometry": None,
                  "name": STYLETABLE,
                  "objectType": "RevisionFeatureType",
                  "properties": properties
                }
        self.connector.post("layers/{}/{}".format(user, repo), json=layerdef, headers=headers)

    def addStyle(self, user, repo, layer, style):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        branches = self.branches(user, repo)
        if STYLEBRANCH not in branches:
            self.createBranch(user, repo, STYLEBRANCH, "master")
        transactionid = self.openTransaction(user, repo)            
        self.checkoutBranch(user, repo, STYLEBRANCH, transactionid)
        layers = self.layers(user, repo, STYLEBRANCH)
        if STYLETABLE not in layers:
            self.addStyleTable(user, repo, transactionid)
        properties = {STYLE: style}
        # feature = geojson.Feature(properties=properties)
        # feature["id"] = layer
        feature = {}
        feature["type"] = "Feature"
        feature["geometry"] = None
        feature["properties"] = properties
        feature["id"] = layer

        headers = {"Accept": "application/json",
                    "geogig-transaction-id": transactionid,
                    "Content-Type": "application/vnd.geo+json"}
        self.connector.post("layers/{}/{}/{}/features".format(user,repo, STYLETABLE), json=feature, headers=headers)
        
        self.commitTransaction(user, repo, transactionid, "Added style for layer '%s'" % layer)

    def getStyle(self, user, repo, layer):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        return self.feature(user, repo, STYLETABLE, layer, STYLEBRANCH)[STYLE]

    def addLayer(self, user, repo, layer, branch, message):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        branch = cleanseBranchName(branch)
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        startProgressBar("Sending to Geogig Server", 2, currentWindow().messageBar())
        # tx for this
        transactionid = self.openTransaction(user, repo)
        # create branch
        self.checkoutBranch(user, repo, branch, transactionid)

        # create layer (with feature type)
        headers = {"Accept": "application/json",
                   "geogig-transaction-id": transactionid}
        layerdef = self.getLayerDef(layer)
        self.connector.post("layers/{}/{}".format(user, repo), json=layerdef, headers=headers)

        # send features
        nfeatures = layer.featureCount()
        featureIterator = layer.getFeatures()
        BATCHSIZE = 1000
        featuresSent =0

        def _batch(iterable, size):
            sourceiter = iter(iterable)
            while True:
                batchiter = islice(sourceiter, size)
                try:
                    yield chain([next(batchiter)], batchiter)
                except StopIteration:
                    return
                    
        for batch in _batch(featureIterator, BATCHSIZE):
            batch = list(batch)
            progressText ="Sending features {:,}-{:,} of {:,}"\
                .format(featuresSent,featuresSent+len(batch),nfeatures)
            setProgressText(progressText)
            self.addFeaturesToWorking(batch,user,repo,layer.name(),transactionid)
            featuresSent += len(batch)

        #close transaction
        self.commitTransaction(user, repo, transactionid, message)

        closeProgressBar()
        QApplication.restoreOverrideCursor()

    def commitidForBranch(self, user, repo, branch):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        return self.commitForBranch(user, repo, branch)["id"]

    def commitForBranch(self, user, repo, branch):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        return self.connector.getHttp("repos/{}/{}/branches/{}".format(user, repo, branch))["commit"]

    def commitChanges(self, geogiglayer, message):
        transactionid = self.openTransaction(geogiglayer.user, geogiglayer.repo)
        self.checkoutBranch(geogiglayer.user, geogiglayer.repo, geogiglayer.branch, transactionid)
        self.addFeatures(geogiglayer, transactionid)
        self.modifyFeatures(geogiglayer, transactionid)
        self.deleteFeatures(geogiglayer, transactionid)
        self.commitTransaction(geogiglayer.user, geogiglayer.repo, transactionid, message)
        self.resetLogCache()
        self.commitMade.emit(geogiglayer.user, geogiglayer.repo)

    def addFeatures(self, geogiglayer, transactionid):
        transactionid = cleanseTransactionId(transactionid)
        addedFeatures = [fid for fid in geogiglayer.addedFeatures if fid >= 0]        
        if addedFeatures:
            features =[f for f in geogiglayer.layer.getFeatures(QgsFeatureRequest(addedFeatures))]
            self.addFeaturesToWorking(features, geogiglayer.user, geogiglayer.repo, geogiglayer.layername, transactionid)

    def modifyFeatures(self, geogiglayer, transactionid):
        if geogiglayer.modifiedFeatures:
            modifiedFeatures = [fid for fid in geogiglayer.modifiedFeatures if fid >= 0]
            request = QgsFeatureRequest()
            request.setFilterFids(modifiedFeatures)
            features =[f for f in geogiglayer.layer.getFeatures(request)]
            self.addFeaturesToWorking(features, geogiglayer.user, geogiglayer.repo, geogiglayer.layername, transactionid)

    # put these features in the WORKING_HEAD of the transaction
    #  This is for adds and modifies
    def addFeaturesToWorking(self, features, user, repo, layer, transactionid):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        transactionid = cleanseTransactionId(transactionid)
        if not features:
            return # nothing to do
        fw = FeatureWriter(features, typename=layer)
        fw_bytes = fw.asBytes()
        headers = {"Accept": "application/json",
                   "geogig-transaction-id": transactionid,
                   "Content-Type": "application/geogig.x-protobuf"}
        ret = self.connector.post("layers/{}/{}/{}/features".format(user, repo, layer),
                   params=fw_bytes, headers=headers)

    def stageFeatures(self, user, repo, layerName, transactionid,features=None,ids=None):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layerName = cleanseLayerName(layerName)
        transactionid = cleanseTransactionId(transactionid)
        if features is not None:
            ids = [layerName+"/"+f[GEOGIGID_FIELD] for f in features]
        else:
            ids =  [layerName+"/"+id for id in ids]

        headers = {"Accept": "application/json",
                   "geogig-transaction-id": transactionid}
        ret = self.connector.post("repos/{}/{}/geogig/rpc/stage".format(user, repo),
                                  headers=headers,json=ids )
        taskId = ret["id"]
        ret2 = self.waitForTask(taskId, "Processing changes in server")

    def deleteFeatures(self, geogiglayer, transactionid):
        transactionid = cleanseTransactionId(transactionid)
        if geogiglayer.deletedFeatures:
            self._deleteFeatures(geogiglayer.deletedFeatures, geogiglayer.user,
                                geogiglayer.repo, geogiglayer.layername, transactionid)

    def _deleteFeatures(self, featureIds, user, repo, layer, transactionid):
            user = cleanseUserName(user)
            repo = cleanseRepoName(repo)
            layer = cleanseLayerName(layer)
            transactionid = cleanseTransactionId(transactionid)
            headers = {"Accept": "application/json",
                        "geogig-transaction-id": transactionid}
            filters = {"featureIds": featureIds}
            ret = self.connector.post("layers/{}/{}/{}/rpc/delete".format(user, repo, layer, transactionid),
                                 headers=headers, json=filters)

    def deleteLayer(self, user, repo, branch, layer):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        branch = cleanseBranchName(branch)
        transactionid = self.openTransaction(user, repo)
        self.checkoutBranch(user, repo, branch, transactionid)
        headers = {"Accept": "application/json",
                    "geogig-transaction-id": transactionid}
        self.connector.delete("layers/{}/{}/{}".format(user, repo, layer), headers=headers)
        self.commitTransaction(user, repo, transactionid, "Deleted layer '{}'".format(layer))

    def diffSummary(self, user, repo, refspec, oldRef, rightUser=None, rightRepo=None):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        rightUser = cleanseUserName(rightUser)
        rightRepo = cleanseRepoName(rightRepo)
        refspec = cleanseRefSpec(refspec)
        oldRef = cleanseRefSpec(oldRef)
        params = {"left":refspec, "right":oldRef}
        if rightUser is not None and rightRepo is not None:
            params["rightUser"] = rightUser
            params["rightRepo"] = rightRepo

        ret = self.connector.getHttp("repos/{}/{}/geogig/rpc/diff/summary".format(user, repo), payload=params)
        if not ret:
            return 0,{} # no diff

        result =  {summary["path"]: summary for summary in ret}
        total = sum([(int(summary["featuresAdded"])+int(summary["featuresRemoved"])+int(summary["featuresChanged"])) for summary in ret])
        #return ret[0]["featuresAdded"], ret[0]["featuresRemoved"], ret[0]["featuresChanged"]
        return total,result

    # None --> PR is conflicted
    # if it gets a 409, will re-try until it succeeds
    def diffSummaryPR(self, user, repo, prid):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        prid = cleansePRId(prid)
        while True:
            try:
                result = self._diffSummaryPR(user, repo, prid)
                return result
            except GeogigError as ge:
                if ge.causedBy is None or not isinstance(ge.causedBy, HTTPError):
                    raise
                ee=ge.causedBy
                code = ee.response.status_code
                if code == 428:
                    return None,None  # in conflict, no diff possible
                if code != 409:  # 409 = retry
                    raise  # abort
                QCoreApplication.processEvents()
                time.sleep(0.500)  # delay before re-try
                QCoreApplication.processEvents()

    def _diffSummaryPR(self, user, repo, prid):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        prid = cleansePRId(prid)
        #"repos/{}/{}/pulls/{}/diff/summary"
        ret = self.connector.getHttp("repos/{}/{}/pulls/{}/diff/summary".format(user, repo, prid))
        result = {summary["path"]: summary for summary in ret}
        total = sum(
            [(int(summary["featuresAdded"]) + int(summary["featuresRemoved"]) + int(summary["featuresChanged"])) for
             summary in ret])
        # return ret[0]["featuresAdded"], ret[0]["featuresRemoved"], ret[0]["featuresChanged"]
        return total, result


    # None --> PR is conflicted
    # if it gets a 409, will re-try until it succeeds
    def diffPR(self, user, repo, layerName, prID):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        prID = cleansePRId(prID)
        layerName = cleanseLayerName(layerName)
        while True:
            try:
                result = self._diffPR(user, repo, layerName,prID)
                return result
            except GeogigError as ge:
                if ge.causedBy is None or not isinstance(ge.causedBy, HTTPError):
                    raise
                ee = ge.causedBy
                code = ee.response.status_code
                if code == 428:
                    return None  # in conflict, no diff possible
                if code != 409:  # 409 = retry
                    raise        # abort
                QCoreApplication.processEvents()
                time.sleep(0.500)  # delay before re-try
                QCoreApplication.processEvents()

    def _diffPR(self,user, repo, layerName,prID):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        prID = cleansePRId(prID)
        layerName = cleanseLayerName(layerName)
        q = QueryForLayerProto(self.connector)
        try:
            return q.queryDiffPR(user, repo, layerName,prID)
        except HTTPError as ee:
            raise
        except Exception as e:
            raise GeogigError("Error getting diff from server", str(e))

    # get a diff between two commits
    # see QueryForLayerProto#queryDiff for return type
    # (list of diff)
    def diff(self, user, repo, layer, refspec, oldRef, featureFilter=None,returnAsIterator=False,
             oldRefUser=None, oldRefRepoName=None):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        refspec = cleanseRefSpec(refspec)
        oldRef = cleanseRefSpec(oldRef)
        q = QueryForLayerProto(self.connector)
        try:
            return q.queryDiff(user, repo, layer, refspec, oldRef, featureFilter,
                               returnAsIterator=returnAsIterator,
                               oldRefUser=oldRefUser, oldRefRepoName=oldRefRepoName
                               )
        except:
            try:
                #might be a deleted layer. We try to compute the diff in reversed order of commits
                if oldRefRepoName is None:
                    diff = q.queryDiff(user, repo, layer, oldRef, refspec, featureFilter)
                else:
                    diff = q.queryDiff(oldRefUser,oldRefRepoName,layer,oldRef,refspec,featureFilter,
                                       oldRefUser=user, oldRefRepoName=repo
                                       )
                def invert(d):
                    d['geogig.changeType'] = 2
                    d['old'] = d['new']
                    d['new'] = None
                    return d
                inverted = [invert(d) for d in diff]
                return inverted
            except Exception as e:
                raise GeogigError("Error getting diff from server", str(e))

    def layerExtent(self, user, repo, layer, commitid):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        commitid = cleanseCommitId(commitid)
        return self.connector.getHttp("layers/{}/{}/{}/bounds".format(user, repo, layer), headers = {"head": commitid})

    def layerInfo(self, user, repo, layer, commitid="master"):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        commitid = cleanseCommitId(commitid)
        return self.connector.getHttp("layers/{}/{}/{}".format(user, repo, layer), headers = {"head": commitid})

    def layerCrs(self, user, repo, layer, commitid="master"):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        commitid = cleanseCommitId(commitid)
        info = self.layerInfo(user, repo, layer, commitid)
        authid = "EPSG:4326"
        for prop in info["type"]["properties"]:
            if prop["crs"] is not None and prop["crs"]["authorityCode"] is not None:
                authid = prop["crs"]["authorityCode"]
                break
        return QgsCoordinateReferenceSystem(authid)

    def getLayer(self, user, repo, layer, refspec, extent=None, screenWidth=None,
                    screenHeight=None, limit = None, simplifyGeom=True,
                    filepath=None):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        layer = cleanseLayerName(layer)
        refspec = cleanseRefSpec(refspec)
        query = QueryForLayerProto(self.connector)
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        if limit != 1:
            startProgressBar("Transferring data from GeoGig", 0, currentWindow().messageBar())
            setProgressValue(0)
        result= query.query(user,repo, layer, refspec, extent,
                           screenWidth,screenHeight,limit,
                           simplifyGeom=simplifyGeom,
                           filepath=filepath)
        if limit != 1:
            closeProgressBar()
        QApplication.restoreOverrideCursor()            
        return result

    def branches(self, user, repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        return _name(self.connector.getHttp("repos/{}/{}/branches".format(user, repo)))

    def createBranch(self, user, repo, branch, commitish):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        commitish = cleanseCommitId(commitish)
        params = {"commitish": commitish}
        self.connector.post("repos/{}/{}/branches/{}".format(user, repo, branch), params=params)
        self.branchCreated.emit(user, repo, branch)

    def deleteBranch(self, user, repo, branch):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        transactionid = self.openTransaction(user, repo)
        headers = {"Accept": "application/json",
                    "geogig-transaction-id": transactionid}
        self.connector.delete("repos/{}/{}/branches/{}".format(user, repo, branch), headers=headers)
        self.commitTransaction(user, repo, transactionid, "Deleted branch '{}'".format(branch))
        self.branchDeleted.emit(user, repo, branch)

    def resetToCommit(self,user,repo,branch,transactionid, baseRevisionId):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        transactionid = cleanseTransactionId(transactionid)
        baseRevisionId = cleanseCommitId(baseRevisionId)
        headers = {"Accept": "application/json",
                   "geogig-transaction-id": transactionid}
        params={"commit-ish":baseRevisionId}

        self.connector.post("/collab/{}/{}/{}/reset".format(user, repo, branch),params=params, headers=headers)

    def checkoutBranch(self, user, repo, branch, transactionid):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        transactionid = cleanseTransactionId(transactionid)
        headers = {"Accept": "application/json",
                    "geogig-transaction-id": transactionid}
        self.connector.post("repos/{}/{}/branches/{}/checkout".format(user, repo, branch), headers=headers)

    def revert(self, user, repo, branch, refspec):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        refspec = cleanseRefSpec(refspec)
        payload = {"commit-ish": refspec}
        ret = self.connector.post("collab/{}/{}/{}/revert".format(user, repo, branch), params=payload)
        taskId = ret["id"]
        self.waitForTask(taskId, "Processing changes in server")
        self.resetLogCache()
        self.revertDone.emit(user,repo)

    def reset(self, user, repo, branch, refspec):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        refspec = cleanseRefSpec(refspec)
        payload = {"commit-ish": refspec}
        self.connector.post("collab/{}/{}/{}/reset".format(user, repo, branch), params=payload)
        self.resetLogCache()
        self.resetDone.emit(user,repo)

    def log(self, user, repo, branch, layer = None):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        layer = cleanseLayerName(layer)
        try:
            payload = {"head": branch}
            if layer is not None:
                payload["path"] = layer
            commits = self.connector.getHttp("repos/{}/{}/geogig/rpc/log".format(user, repo), payload = payload)
            return self._prepareCommits(commits)
        except:
            return [], {}

    def logAll(self, user, repo, branch, layer):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        branch = cleanseBranchName(branch)
        layer = cleanseLayerName(layer)
        commitsAll, commitsDictAll = self.log(user,repo,branch)
        commitsLayer, commitsDictLayer = self.log(user,repo,branch,layer)
        return commitsAll, commitsDictAll,commitsLayer, commitsDictLayer

    def _prepareCommits(self, commits):
        if not commits:
            return [],{}
        commitsDict = {}
        for c in commits:
            c["childrenIds"] = []
            commitsDict[c["id"]] = c
        def addCommit(commit):
            try:
                for parentId in commit["parentIds"]:
                    parent = dictGet(commitsDict,parentId, None)
                    if commit["id"] not in parent["childrenIds"]:
                        parent["childrenIds"].append(commit["id"])
                        addCommit(parent)
            except:
                pass
        addCommit(commits[0])
        commitIds = [c["id"] for c in commits]
        return commitIds, commitsDict

    def layers(self, user, repo, refspec="WORK_HEAD"):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        refspec = cleanseRefSpec(refspec)
        headers = {"Accept": "application/json",
                    "head": refspec}
        return _name(self.connector.getHttp("layers/{}/{}".format(user, repo), headers=headers))

class TaskChecker(QObject):
    taskIsFinished = pyqtSignal()
    def __init__(self, connector, taskId, msg=None):
        QObject.__init__(self)
        taskId = cleanseTaskId(taskId)
        self.taskId = taskId
        self.connector = connector
        self.url = "{}tasks/{}".format(self.connector.url, str(self.taskId))
        self.canceled = False
        self.response = self.connector.getHttp("tasks/{}".format(str(self.taskId)))
        progress = self.response["progress"]
        if progress:
            self.maxvalue = max(0, progress["max_progress"])
            self.text = msg or progress["task_description"]
        else:
            self.maxvalue = 0
            self.text = "Waiting for task in server..."
        startProgressBar(self.text, self.maxvalue, currentWindow().messageBar())
        setProgressValue(0)

    def finished(self):
        QApplication.restoreOverrideCursor()
        closeProgressBar()

    def start(self):
        self.checkTask()

    def checkTask(self):
        if isProgressCanceled():
            self.ok = True
            self.canceled = True
            closeProgressBar()
            self.taskIsFinished.emit()
            return
        self.response = self.connector.getHttp("tasks/{}".format(str(self.taskId)))
        if self.response["status"] in ["COMPLETE"]:
            self.ok = True
            closeProgressBar()
            self.taskIsFinished.emit()
        elif self.response["status"] in ["FAILED", "ABORTED"]:
            self.ok = False
            closeProgressBar()
            self.taskIsFinished.emit()
        else:
            try:
                progressAmount = str(self.response["progress"]["progress"])
                if self.maxvalue:
                    try:
                        setProgressValue(float(progressAmount))
                    except:
                        text = "%s [%s]" % (self.text, progressAmount)
                        setProgressText(text)
                else:
                    text = "%s [%s]" % (self.text, progressAmount)
                    setProgressText(text)
            except KeyError:
                pass
            QTimer.singleShot(500, self.checkTask)