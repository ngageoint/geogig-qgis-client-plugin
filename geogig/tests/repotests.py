from geogig.geogigwebapi.connector import Connector
from geogig.geogigwebapi.server import Server

from qgis.core import QgsPointXY, QgsGeometry, QgsFeature, QgsVectorLayer, QgsRectangle, QgsFeatureRequest, QgsExpression

import os
import uuid
import random	

URL = "http://localhost:8181/"
ROOTREPO = "rootrepo"
CONFLICTEDREPO = "conflictedrepo"
NOTCONFLICTEDREPO = "notconflictedrepo"
FORKEDREPO = "forkedrepo"
MODIFYANDDELETECONFLICTEDREPO = "modifyanddeleteconflictedrepo"

USER1 = "volaya"
USER2 = "volaya2"
PASSWORD = "volaya"
LAYERNAME = "squares"
LAYERNAME2 = "squares2"
FIELDNAME = "value"

baseLayer = QgsVectorLayer(os.path.join(os.path.dirname(__file__), LAYERNAME + ".geojson"), LAYERNAME, "ogr")
baseLayer2 = QgsVectorLayer(os.path.join(os.path.dirname(__file__), LAYERNAME + ".geojson"), LAYERNAME2, "ogr")

def addLayer(server, user, repo, layer = baseLayer):
	server.addLayer(user, repo, layer, "master", "Added layer")

def getFeatureFromGeogigId(layer, fid):
    features = list(layer.getFeatures(QgsFeatureRequest(
                            QgsExpression('"geogigid"=\'{}\''.format(fid)))))
    if features:
        return features[0]
    else:
        return None

def commitAddFeatures(server, user, repo):
	count = 3
	for i in range(count):
		feature = QgsFeature(baseLayer.fields())
		x = random.uniform(0,1)
		y = random.uniform(0,1)
		feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(x, y, x + 0.1, y + 0.1)))
		feature.setAttributes([random.uniform(0,10)])		
		transactionid = server.openTransaction(user, repo)
		server.addFeaturesToWorking([feature], user, repo, LAYERNAME, transactionid)   
		server.commitTransaction(user, repo, transactionid, "Added new feature")

def commitDeleteFeature(server, user, repo, featureId):
	transactionid = server.openTransaction(user, repo)
	server._deleteFeatures([featureId], user, repo, LAYERNAME, transactionid)
	server.commitTransaction(user, repo, transactionid, "Deleted feature " + featureId)

def commitModifyGeometry(server, user, repo, featureId):
	layer = server.getLayer(user, repo, LAYERNAME, "master")
	feature = getFeatureFromGeogigId(layer, featureId)
	x = random.uniform(0,1)
	y = random.uniform(0,1)
	feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(x, y, x + .1, y + .1)))
	transactionid = server.openTransaction(user, repo)
	server.addFeaturesToWorking([feature], user, repo, LAYERNAME, transactionid) 
	server.commitTransaction(user, repo, transactionid, "Modified geometry of feature " + featureId)

def commitModifyAttribute(server, user, repo, layername, featureId, newValue):
	layer = server.getLayer(user, repo, layername, "master")
	feature = getFeatureFromGeogigId(layer, featureId)
	feature[FIELDNAME] = newValue	
	transactionid = server.openTransaction(user, repo)
	server.addFeaturesToWorking([feature], user, repo, layername, transactionid)
	server.commitTransaction(user, repo, transactionid, "Modified atribute of feature {} to '{}'".format(featureId, newValue))

def createUsers():
	pass


# from geogig.tests.repotests import createTestScenario,cleanTestRepos,debug
# createTestScenario()
def createTestScenario():	
	createUsers()	
	try:
		cleanTestRepos()
	except:
		pass
	server1 = Server(Connector(URL, USER1, PASSWORD))
	server2 = Server(Connector(URL, USER2, PASSWORD))
	server1.createRepo(USER1, ROOTREPO)
	addLayer(server1, USER1, ROOTREPO, baseLayer)
	commitAddFeatures(server1, USER1, ROOTREPO)
	layer = server1.getLayer(USER1, ROOTREPO, LAYERNAME, "master")
	ids = [f["geogigid"] for f in layer.getFeatures()]
	idToDelete = ids[-1]
	idToModify = ids[0]
	idToModify2 = ids[1]
	idToModify3 = ids[2]
	commitDeleteFeature(server1, USER1, ROOTREPO, idToDelete)
	server1.forkRepo(USER1, ROOTREPO, FORKEDREPO)
	server2.forkRepo(USER1, ROOTREPO, ROOTREPO)
	server2.forkRepo(USER1, ROOTREPO, CONFLICTEDREPO)
	server2.forkRepo(USER1, ROOTREPO, NOTCONFLICTEDREPO)
	server2.forkRepo(USER1, ROOTREPO, MODIFYANDDELETECONFLICTEDREPO)
	server2.forkRepo(USER2, ROOTREPO, FORKEDREPO)
	commitModifyAttribute(server1, USER2, FORKEDREPO, LAYERNAME, idToModify3, 7)
	pr = server2.createPullRequest(USER2, FORKEDREPO, USER2, NOTCONFLICTEDREPO, "Not conflicted PR", "master", "master")
	server2.mergePullRequest(USER2, NOTCONFLICTEDREPO, pr)	
	commitModifyAttribute(server1, USER1, ROOTREPO, LAYERNAME, idToModify, 2)
	commitModifyAttribute(server2, USER2, CONFLICTEDREPO, LAYERNAME, idToModify, 3)
	commitModifyAttribute(server2, USER2, NOTCONFLICTEDREPO, LAYERNAME, idToModify2, 3)
	commitModifyGeometry(server1, USER1, ROOTREPO, idToModify)
	commitDeleteFeature(server2, USER2, MODIFYANDDELETECONFLICTEDREPO, idToModify)
	server2.createPullRequest(USER2, CONFLICTEDREPO, USER1, ROOTREPO, "Conflicted PR", "master", "master")
	server2.createPullRequest(USER2, MODIFYANDDELETECONFLICTEDREPO, USER1, ROOTREPO, "Conflicted (modify & delete) PR", "master", "master")
	server2.createPullRequest(USER2, NOTCONFLICTEDREPO, USER1, ROOTREPO, "Not conflicted PR", "master", "master")
	addLayer(server1, USER1, ROOTREPO, baseLayer2)
	layer2 = server1.getLayer(USER1, ROOTREPO, LAYERNAME2, "master")
	ids2 = [f["geogigid"] for f in layer.getFeatures()]
	commitModifyAttribute(server1, USER1, ROOTREPO, LAYERNAME, ids2[0], 2)

def cleanTestRepos():
	server1 = Server(Connector(URL, USER1, PASSWORD))
	server2 = Server(Connector(URL, USER2, PASSWORD))
	safeDeleteRepo(server1,USER1, ROOTREPO)
	safeDeleteRepo(server1,USER1, FORKEDREPO)
	safeDeleteRepo(server2,USER2, ROOTREPO)
	safeDeleteRepo(server2,USER2, FORKEDREPO)
	safeDeleteRepo(server2,USER2, CONFLICTEDREPO)
	safeDeleteRepo(server2,USER2, NOTCONFLICTEDREPO)
	safeDeleteRepo(server2,USER2, MODIFYANDDELETECONFLICTEDREPO)


def safeDeleteRepo(server,user,reponame):
	try:
		server.deleteRepo(user,reponame)
	except:
		import sys
		a =  sys.exc_info()
		pass


def debug():
	import pydevd
	pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
                 suspend=False)