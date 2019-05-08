from qgis.utils import iface

from geogig.geogigwebapi.connector import Connector
from geogig.geogigwebapi.server import Server
from geogig.gui.conflictdialog import ConflictDialog
from geogig.gui.extentdialog import ExtentDialog
from geogig.gui.synchronizedialog import SynchronizeDialog
from geogig.layers import addGeogigLayer
from geogig.layers.diffgeopkglayer import DiffGeoPKGMultiLayerForPR

from geogig.tests.testsupport import addGeoPKG, nFeatures, changeExtent, deleteRepo, getFeatureByGGID, getChangeSet, \
    nchanges, editFeature, getCommit, getDiff, removeAllLayers, addLive, createPR

# import sys
# sys.path.append('//Applications//PyCharm.app//Contents//debug-eggs//pycharm-debug.egg')
# import pydevd
# pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
#                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
#                 suspend=False)


url = "http://localhost:8181/"
user = "GISAnalyst"
passwd = "gisgis"

connector = Connector(url,user,passwd)
server = Server.getInstance(connector)
server.connector.user = user
server.connector.password=passwd

repo_parent="TESTCASE.PARENT"
repo_child="TESTCASE.CHILD"

layer = "buildings"

def setup():
    # clean
    clean()
    # setup
    server.forkRepo("administrator", "GOLD.osm_missouri", repo_parent)
    server.forkRepo(user, repo_parent, repo_child)

def clean():
    removeAllLayers()
    deleteRepo(server, user, repo_child)
    deleteRepo(server, user, repo_parent)


# test changing the extent of the geopkg
def test_extentChange():
    setup()
    gg_l = addGeoPKG(server,user,repo_child,layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])
    assert nFeatures(gg_l) == 540
    assert nchanges(gg_l) == 0

    changeExtent(gg_l,[-90.32864847488405, 38.718090322113035, -90.25242806015014, 38.75957458267212])
    assert nFeatures(gg_l) == 582
    assert nchanges(gg_l) ==0
    clean()


# test for picking up changes from the repo to the geopkg
def test_update():
    setup()
    gg_live = addLive(server,user,repo_child,layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])
    gg_geopkg = addGeoPKG(server, user, repo_child, layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])

    # edit and commit on live
    f2 = editFeature(gg_live, "298497401", "name", "testcasename3", msg="tc_update.1")
    myCommit = getCommit(server, user, repo_child, "tc_update.1")
    assert myCommit is not None
    commitDiff = getDiff(server, user, repo_child, layer, myCommit['id'])
    assert len(commitDiff) == 1

    # geopkg doesn't have the change
    f = getFeatureByGGID(gg_geopkg, "298497401")
    assert f is not None
    assert f["name"] != "testcasename3"
    assert nchanges(gg_geopkg) == 0

    # grab the change from the live layer
    gg_geopkg.updateRevision()

    # geopkg has the change
    f = getFeatureByGGID(gg_geopkg, "298497401")
    assert f is not None
    assert f["name"] == "testcasename3"
    assert nchanges(gg_geopkg) == 0

    clean()

# test conflict and sync
def test_conflict():
    setup()
    gg_geopkg = addGeoPKG(server, user, repo_child, layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])
    editFeature(gg_geopkg, "298497401", "name", "testcasename4_conflictchild", msg="tc_child.2")
    prid = createPR(server,user,repo_child,user,repo_parent,"tc_pr_conflict","tc_pr_conflict_desc")

    # commit directly with parent
    gg_live = addLive(server,user,repo_parent,layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])
    editFeature(gg_live, "298497401", "name", "testcasename4_conflictparent", msg="tc_parent.1")

    # pr is now in conflict.  Verify
    # verify - simple check parent and child are in conflict
    inConflict = server.branchConflicts(user, repo_child, "master", user, repo_parent, "master")
    assert inConflict

    # verify - pr is in conflict
    fullDiffSummaryTotal, fullDiffSummary = server.diffSummaryPR(user, repo_parent, prid)
    assert fullDiffSummary is None

    tx = server.openTransaction(user,repo_child)
    conflicts = server.syncBranch(user,repo_child,
                                  user, repo_parent, tx,
                                  commitMessage="tx1")
    assert conflicts
    cs = list(conflicts["buildings"].values())
    assert len(cs) == 1
    assert cs[0]['origin']['name'] == ''
    assert cs[0]['local']['name'] == 'testcasename4_conflictchild'
    assert cs[0]['remote']['name'] == 'testcasename4_conflictparent'

    ConflictDialog.TEST_CASE_OVERRIDE = ConflictDialog.REMOTE
    dialog = ConflictDialog(conflicts, localName="Child Repo", remoteName="Upstream Repo")
    r=dialog.exec_()
    stageableActions = dialog.asStageable()
    assert stageableActions["buildings"]["298497401"]["name"] == "testcasename4_conflictparent"

    ConflictDialog.TEST_CASE_OVERRIDE = ConflictDialog.LOCAL
    dialog = ConflictDialog(conflicts, localName="Child Repo", remoteName="Upstream Repo")
    r = dialog.exec_()
    stageableActions = dialog.asStageable()
    assert stageableActions["buildings"]["298497401"]["name"] == "testcasename4_conflictchild"

    SynchronizeDialog.TEST_CASE_OVERRIDE = True
    dlg= SynchronizeDialog(user,repo_child,server,user,repo_parent,allowSelectRepo=False)
    r=dlg.exec_()

    # verify sync - should see a sync commit and the TWO commits, above...
    logCommitIds, logCommitsDict = server.log(user, repo_child, "master")
    sync_c = logCommitsDict[logCommitIds[0]]
    assert "Synchronize" in sync_c["message"]  # PR sync message
    assert len(sync_c["parentIds"]) == 2  # two parents (merge)
    work_parent_c = logCommitsDict[logCommitIds[1]]
    assert work_parent_c["message"] == "tc_parent.1"
    assert len(work_parent_c["parentIds"]) == 1  # 1 parents (work commit)
    work_child_c = logCommitsDict[logCommitIds[2]]
    assert work_child_c["message"] == "tc_child.2"
    assert len(work_child_c["parentIds"]) == 1  # 1 parents (work commit)

    # merge PR and verify parent changed
    merged = server.mergePullRequest(user, repo_parent, prid)
    assert merged
    # verify change is in parent
    gg_geopkg_merged = addGeoPKG(server, user, repo_parent, layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])
    f = getFeatureByGGID(gg_geopkg_merged, "298497401")
    assert f is not None
    assert f["name"] == "testcasename4_conflictchild"
    logCommitIds, logCommitsDict = server.log(user, repo_parent, "master")
    merge_c = logCommitsDict[logCommitIds[0]]
    assert "#"+str(prid) in merge_c["message"]  # PR merge message
    assert len(merge_c["parentIds"] ) ==2 # two parents (merge)
    work_c = logCommitsDict[logCommitIds[1]]
    assert sync_c["id"] ==  work_c["id"]
    assert len(work_c["parentIds"]) == 2  # 2 parents sync)

    clean()


# create a PR and merge it - verify (including export diff)
def test_PR():
    setup()
    gg_geopkg = addGeoPKG(server, user, repo_child, layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])

    # edit feature and commit to child
    f2 = editFeature(gg_geopkg, "298497401", "name", "testcasename4", msg="tc_update.2")
    f = getFeatureByGGID(gg_geopkg, "298497401")
    assert f is not None
    assert f["name"] == "testcasename4"
    assert nchanges(gg_geopkg) == 0
    myCommit = getCommit(server, user, repo_child, "tc_update.2")
    assert myCommit is not None
    commitDiff = getDiff(server, user, repo_child, layer, myCommit['id'])
    assert len(commitDiff) == 1

    # verify changes being handled properly (non-pr)
    fullDiffSummaryTotal,fullDiffSummary =server.diffSummary(user, repo_parent, "HEAD", "HEAD",
                                                             user,repo_child)
    assert fullDiffSummaryTotal == 1
    assert fullDiffSummary['buildings']['featuresAdded'] == 0
    assert fullDiffSummary['buildings']['featuresChanged'] == 1
    assert fullDiffSummary['buildings']['featuresRemoved'] == 0

    # create a PR child->parent
    prid = createPR(server,user,repo_child,user,repo_parent,"tc_pr1","tc_pr1_desc")
    pr = server.pullRequest(user,repo_parent,prid)
    assert pr is not None
    assert pr["id"] == prid
    fullDiffSummaryTotal, fullDiffSummary = server.diffSummaryPR(user, repo_parent,prid)
    assert fullDiffSummaryTotal==1
    assert fullDiffSummary['buildings']['featuresAdded'] ==0
    assert fullDiffSummary['buildings']['featuresChanged'] == 1
    assert fullDiffSummary['buildings']['featuresRemoved'] == 0

    # verify that the PR is identifying changes
    diff = list(server.diffPR(user, repo_parent, layer, prid)[1])
    assert len(diff) == 1
    assert diff[0]["ID"] == "298497401"
    assert diff[0]["geogig.changeType"] == 1
    assert diff[0]["old"]["name"] == ""
    assert diff[0]["new"]["name"] == "testcasename4"

    # verify export diff as layer
    ex = DiffGeoPKGMultiLayerForPR(server, user, repo_parent, prid, layer=layer)
    addedLayers = ex.addToProject()
    assert len(addedLayers) == 1
    assert addedLayers[0].name().startswith("DIFF")
    assert addedLayers[0].name().endswith(layer)
    fs = list(addedLayers[0].getFeatures())
    assert len(fs)==2 # for old/new
    assert fs[0]["GeoGig.ChangeType"] == 'modified.before'
    assert fs[0]["geogigid"] == '298497401'
    assert fs[0]["name"] == ''
    assert fs[1]["GeoGig.ChangeType"] == 'modified.after'
    assert fs[1]["geogigid"] == '298497401'
    assert fs[1]["name"] == 'testcasename4'

    # merge PR
    merged = server.mergePullRequest(user, repo_parent, pr["id"])
    assert merged
    # verify change is in parent
    gg_geopkg_merged = addGeoPKG(server, user, repo_parent, layer,[-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])
    f = getFeatureByGGID(gg_geopkg_merged, "298497401")
    assert f is not None
    assert f["name"] == "testcasename4"
    logCommitIds, logCommitsDict = server.log(user, repo_parent, "master")
    merge_c = logCommitsDict[logCommitIds[0]]
    assert "#"+str(prid) in merge_c["message"]  # PR merge message
    assert len(merge_c["parentIds"] ) ==2 # two parents (merge)
    work_c = logCommitsDict[logCommitIds[1]]
    assert work_c["message"] == "tc_update.2"
    assert len(work_c["parentIds"]) == 1  # 1 parents (work commit)
    clean()



# test simple edit with and without committing
def test_edit():
    setup()

    gg_l = addGeoPKG(server, user, repo_child, layer,
                     [-90.28819846952946, 38.71762103437104, -90.21506999993802, 38.75710403972375])
    f = getFeatureByGGID(gg_l, "298497401")
    assert f is not None

    # make chagne, but do not commit
    f2 = editFeature(gg_l, "298497401", "name", "testcasename", msg=None)
    assert nchanges(gg_l) == 1

    # make chagne, and commit
    f2 = editFeature(gg_l, "298497401", "name", "testcasename2", msg="c1")
    assert nchanges(gg_l) == 0

    # get the commit and verify it
    myCommit = getCommit(server, user, repo_child, "c1")
    assert myCommit is not None
    commitDiff = getDiff(server, user, repo_child, layer, myCommit['id'])
    assert len(commitDiff) == 1

    clean()


test_extentChange()
test_edit()
test_update()
test_PR()
test_conflict()

pass


print("""
import geogig.tests.geopkgtests
""")

print("from importlib import reload")
print ("geogig.tests.geopkgtests = reload(geogig.tests.geopkgtests)")
print ("geogig.tests.testsupport = reload(geogig.tests.testsupport)")