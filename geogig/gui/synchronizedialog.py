from datetime import datetime

from qgis.PyQt.QtWidgets import *

# from geogig.gui.synchronizedialog import SynchronizeDialog
# d = SynchronizeDialog()
# d.exec()
from geogig.geogigwebapi.server import Server
from geogig.gui.conflictdialog import ConflictDialog


class SynchronizeDialog(QDialog):

    # None - don't do anything (normal)
    # SynchronizeDialog.TEST_CASE_OVERRIDE = 1
    TEST_CASE_OVERRIDE = None

    def __init__(self, childUser, childRepoName, server, upstreamUser=None,
                upstreamRepoName=None, allowSelectRepo = True, parent=None):
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        super(SynchronizeDialog, self).__init__(parent)
        self.server = server
        self.childRepoName = childRepoName
        self.childUser = childUser
        self.synced = False
        layout = QVBoxLayout()
        hlayout = QHBoxLayout()
        label = QLabel("Upstream repo")
        hlayout.addWidget(label)
        self.comboOrigin = QComboBox()
        constellation = self.server.constellation(self.childUser, self.childRepoName)
        repos = [r.fullName() for r in constellation.all if r.fullName() != self.childUser + ":" + self.childRepoName]
        self.comboOrigin.addItems(repos)
        hlayout.addWidget(self.comboOrigin)

        if upstreamUser is not None and upstreamRepoName is not None:
            selected = upstreamUser + ":" + upstreamRepoName
            self.comboOrigin.setCurrentText(selected)

        if allowSelectRepo:
            layout.addLayout(hlayout)

        self.textWidget = QTextBrowser()
        self.textWidget.setOpenLinks(False)
        layout.addWidget(self.textWidget)
        
        self.comboOrigin.currentIndexChanged.connect(self.updateForCurrentUpstreamRepo)
        if repos:
            self.updateForCurrentUpstreamRepo()

        buttonLayout = QHBoxLayout()
        syncButton = QPushButton("Synchronize")
        syncButton.setEnabled(len(repos) > 0)
        syncButton.clicked.connect(self.sync)
        cancelButton = QPushButton("Cancel")
        cancelButton.clicked.connect(self.close)
        buttonLayout.addWidget(syncButton)
        buttonLayout.addWidget(cancelButton)
        layout.addLayout(buttonLayout)

        self.setLayout(layout)
        self.resize(500, self.height())
        if SynchronizeDialog.TEST_CASE_OVERRIDE is not None:
            self.sync()

    def exec_(self):
        if SynchronizeDialog.TEST_CASE_OVERRIDE is None:
            super(SynchronizeDialog, self).exec_()


    def sync(self):
        message = "Synchronize from " + self.upstreamFullName
        tx = self.server.openTransaction(self.childUser, self.childRepoName)
        conflicts = self.server.syncBranch(self.childUser, self.childRepoName,  
                                        self.upstreamUser, self.upstreamRepoName, tx,
                                           commitMessage=message)
        if not conflicts:
            message = "Synchronize from "+self.upstreamFullName
            ret = self.server.commitTransaction(self.childUser, self.childRepoName, tx, message)
            self.server.syncFinished.emit(self.childUser, self.childRepoName)
            if SynchronizeDialog.TEST_CASE_OVERRIDE is None:
                ret = QMessageBox.warning(self, "Synchronization Complete",
                                      "Repository '{}' is synchronized with upstream repository '{}'".format(
                                          self.childFullName, self.upstreamFullName),
                                      QMessageBox.Ok,
                                      QMessageBox.Ok)
            self.synced = True
            self.close()
            return  # done

        # there are conflicts
        # we need to resolve them, update WORK_HEAD, then commit transaction
        dialog = ConflictDialog(conflicts, localName="Child Repo", remoteName="Upstream Repo")
        dialog.exec_()
        if not dialog.executeMerge:
            self.server.abortTransaction(self.childUser, self.childRepoName, tx)
            ret = QMessageBox.warning(self, "Synchronization Aborted",
                                      "Repository '{}' is not synchronized with upstream repository '{}'".format(
                                          self.childFullName, self.upstreamFullName),
                                      QMessageBox.Ok,
                                      QMessageBox.Ok)
            self.close()
            return

        stageableActions = dialog.asStageable()

        for layerName, featureDic in stageableActions.items():
            allIds = list(featureDic.keys())
            featuresUpdate = [f for f in featureDic.values() if f is not None]
            idsToDelete = [fid for fid, f in featureDic.items() if f is None]

            self.server.addFeaturesToWorking(featuresUpdate,
                                             self.childUser, self.childRepoName,
                                             layerName, tx)
            if idsToDelete:
                self.server._deleteFeatures(idsToDelete,
                                            self.childUser, self.childRepoName,
                                            layerName, tx)
            # need to stage features that are resolved as Current
            # since it would be inserting identical features and remain unresolved
            self.server.stageFeatures(self.childUser, self.childRepoName,
                                      layerName, tx,
                                      ids=allIds)

        nconflicts = sum([len(c) for c in conflicts.values()])
        message = "Synchronize from {} with {} conflict".format(self.upstreamFullName,nconflicts)
        if nconflicts >1:
            message += "s" # pluralize
        completed, details = self.server.commitTransaction(self.childUser, self.childRepoName, tx, message)
        self.server.syncFinished.emit(self.childUser, self.childRepoName)
        if SynchronizeDialog.TEST_CASE_OVERRIDE is None:
            ret = QMessageBox.warning(self, "Synchronization Complete",
                                  "Repository '%s' is synchronized with upstream repository '%s'" 
                                  % (self.childFullName, self.upstreamFullName),
                                  QMessageBox.Ok,
                                  QMessageBox.Ok)
        self.synced = True       
        self.close()

    def updateForCurrentUpstreamRepo(self):
        self.setupMetadata()
        self.textWidget.setText(self.getHtml())

    def setupMetadata(self):
        self.upstreamUser, self.upstreamRepoName = self.comboOrigin.currentText().split(":")
        self.childFullName = self.childUser + ":" + self.childRepoName
        self.upstreamFullName = self.upstreamUser + ":" + self.upstreamRepoName

        behindCommits,behindDic = self.server.behindCommits(self.childUser, self.childRepoName,
                                                     self.upstreamUser ,self.upstreamRepoName)
        self.behindCommits = behindDic.values()
        self.nbehind = len(self.behindCommits)

        self.conflicts = self.server.branchConflicts(self.childUser, self.childRepoName, "master",
                                                     self.upstreamUser, self.upstreamRepoName, "master")

    def getHtml(self):
        result = "<b><font size=+2>Synchronize Repository</font></b></br><br><Br>"
        result += "Upstream Repository: {}<br>".format(self.upstreamFullName)
        result += "Child Repository: {}<br>".format(self.childFullName)
        result += "<br>"
        result += "Number of commits to pull:{}<br>".format(str(self.nbehind))
        result += "<table border=1>"
        result += "<tr><td><b>Commit ID</b></td><td><b>Message</b></td><td><b>Author</b></td><td><b>Date</b></td>"
        for c in self.behindCommits:
            timestamp = c["author"]["timestamp"] / 1000
            timestamp = datetime.fromtimestamp(timestamp).strftime(" %m/%d/%y %H:%M")
            result += "<tr><td><i>{}</i></td><td>{}</td><td>{}</td><td>{}</td>".format(
                c["id"][:8],c["message"],c["author"]["name"],timestamp
            )
        result += "</table>"
        result += "<br><br><br>"
        if self.conflicts:
            result += "Conflicts: <b>RESOLUTION REQUIRED</b><br>"
        else:
            result += "Conflicts: none<br>"
        return result
