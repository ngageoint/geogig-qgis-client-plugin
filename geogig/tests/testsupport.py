from qgis.PyQt import QtCore
from qgis._core import QgsProject, QgsRectangle
from qgis.utils import iface

from geogig.geopkgtools import getChangeSet
from geogig.gui.commitdialog import CommitDialog
from geogig.gui.extentdialog import ExtentDialog
from geogig.layers import addGeogigLayer, _geogigLayers, time
from geogig.utils import getFeatureFromGeogigId


def addGeoPKG(server,user,repo,layer,extent):
    # t = [a for a in _geogigLayers]
    commitid = server.commitidForBranch(user,repo, "master")
    if extent is not None:
        ExtentDialog.TEST_CASE_OVERRIDE = {"radioRestrictedExtent": True, "radioFullExtent": False,
                                           "extent": extent}
    else:
        ExtentDialog.TEST_CASE_OVERRIDE = {"radioRestrictedExtent": False, "radioFullExtent": True,
                                           "extent": None}
    r = addGeogigLayer(server, user, repo, layer, commitid, False, iface)
    gg_layer = _geogigLayers[-1]
    wait_until(lambda:gg_layer.layer is not None )
    if not r:
        raise Exception("could not add geopkg")

    return gg_layer

def addLive(server,user,repo,layer,extent):
    if extent is None:
        raise Exception("extent is none!")
    iface.mapCanvas().setExtent(QgsRectangle(extent[0],extent[1],extent[2],extent[3]))
    r = addGeogigLayer(server, user, repo, layer, "HEAD", True, iface)
    if not r:
        raise Exception("could not add live layer")
    iface.mapCanvas().setExtent(QgsRectangle(extent[0], extent[1], extent[2], extent[3]))
    gg_layer = _geogigLayers[-1]
    gg_layer.layerRefresher.setFullDetail(True)
    wait_until(lambda:gg_layer.layer is not None )
    iface.mapCanvas().setExtent(QgsRectangle(extent[0], extent[1], extent[2], extent[3]))
    wait_until(lambda: nFeatures(gg_layer) > 1 )
    return gg_layer


def wait_until(pred, maxtime=5, deltatime=0.25):
  endtime = time.time() + maxtime
  QtCore.QCoreApplication.processEvents()
  while time.time() <= endtime:
    if pred():
        QtCore.QCoreApplication.processEvents()
        return True
    time.sleep(deltatime)
    QtCore.QCoreApplication.processEvents()
  return False



def changeExtent(gglayer,extent):
    if extent is not None:
        ExtentDialog.TEST_CASE_OVERRIDE = {"radioRestrictedExtent": True, "radioFullExtent": False,
                                           "extent": extent}
    else:
        ExtentDialog.TEST_CASE_OVERRIDE = {"radioRestrictedExtent": False, "radioFullExtent": True,
                                           "extent": None}
    gglayer.layer.setAbstract("")
    gglayer.changeExtent()
    wait_until(lambda: gglayer.layer.abstract()!="")
    gglayer.layer.dataProvider().forceReload()
    pass

def getFeatureByGGID(gglayer,ggid):
    return getFeatureFromGeogigId(ggid,gglayer.layer)

def getChangeset(gglayer):
    return getChangeSet(gglayer.gpkgPath)

def nchanges(gglayer):
    changes = getChangeSet(gglayer.gpkgPath)
    return len(changes)

def editFeature(gglayer,ggid,attname,newattvalue,msg=None):
    if msg is None:
        CommitDialog.TEST_CASE_OVERRIDE = {"radioEditBuffer": True, "msg": None}
    else:
        CommitDialog.TEST_CASE_OVERRIDE = {"radioEditBuffer": False, "msg": msg}
    f = getFeatureByGGID(gglayer,ggid)
    f[attname] = newattvalue
    gglayer.layer.startEditing()
    gglayer.layer.updateFeature(f)
    gglayer.layer.commitChanges()
    return f

def nFeatures(gglayer):
    return len(list(gglayer.layer.getFeatures()))

def deleteRepo(server,user,repo):
    try:
        server.deleteRepo(user,repo)
    except:
        pass

def getCommit(server,user,repo,msg=None):
    logCommitIds, logCommitsDict = server.log(user, repo, "master")
    if msg is None:
        lastCommit = logCommitsDict[logCommitIds[0]]
        return lastCommit
    else:
        return [c for c in logCommitsDict.values() if c['message'] == msg][0]

def getDiff(server,user,repo,layer,commitid):
    diff = server.diff(user,repo,layer,commitid,commitid+"~1")
    return diff

def removeAllLayers():
    for tl in QgsProject.instance().layerTreeRoot().findLayers():
        l = tl.layer()
        QgsProject.instance().removeMapLayer(l.id())

def createPR(server,user,repo,user2,repo2,prname,prdescription=""):
    conflicts = server.branchConflicts(user, repo, "master", user2, repo2, "master")
    if conflicts:
        raise Exception("in conflict")
    commitsBehind, commitsAhead = server.compareHistories(user, repo, user2, repo2)
    prid = server.createPullRequest(user, repo, user2, repo2, prname, "master", "master",
                                  description=prdescription)
    return prid