from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (QHBoxLayout,
                                 QVBoxLayout,
                                 QSizePolicy, QLabel, QMessageBox, QTextBrowser, QDialog, QPushButton, QPlainTextEdit)
from qgis.gui import QgsMessageBar
from qgis.core import Qgis
from geogig.gui.diffviewer import DiffViewerWidget, DiffViewerDialog
from geogig.gui.historyviewer import HistoryDiffViewerWidget
from geogig.gui.conflictdialog import ConflictDialog
from qgiscommons2.gui import execute, closeProgressBar
import sys
import os
from geogig.gui.commitgraph import CommitGraph
from geogig.gui.progressbar import setCurrentWindow
from geogig.gui.synchronizedialog import SynchronizeDialog
from geogig.layers.diffgeopkglayer import DiffGeoPKGMultiLayer, DiffGeoPKGMultiLayerForPR

sys.path.append(os.path.dirname(__file__))
pluginPath = os.path.split(os.path.dirname(__file__))[0]
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'pullrequestsdialog.ui'))

class PullRequestsDialog(WIDGET, BASE):

    def __init__(self, server, user, repo, creatingPr, prName = None, prID=None, defaultParent=None):
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        super(PullRequestsDialog, self).__init__()
        self.fullDiffSummary = {}
        self.server = server
        self.user = user 
        self.repo = repo
        self.history = None
        self.creatingPr = creatingPr
        self.prDescription = ""
        # self.prDescription = "hi there this is my desc\nthis is line two\nthis is line 3"


        self.setupUi(self)

        self.setWindowTitle("Pull Requests Viewer [{}/{}]".format(user, repo))
        self.setWindowModality(0)
        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(0, self.bar)

        self.belongsToLoggedUser = self.server.connector.user == self.user

        self.buttonClose.setVisible(not creatingPr)
        self.buttonMerge.setVisible(not creatingPr)
        self.buttonExportDiff.setVisible(not creatingPr)

        self.comboPr.setVisible(not creatingPr)
        self.labelPr.setVisible(not creatingPr)
        self.labelTarget.setVisible(creatingPr)
        self.comboTarget.setVisible(creatingPr)
        self.labelPrName.setVisible(creatingPr)
        self.txtPrName.setVisible(creatingPr)
        self.txtPrName.textChanged.connect(self.setupInfo)
        self.buttonCreate.setVisible(creatingPr)
        self.buttonMerge.clicked.connect(self.mergePullRequest)
        self.buttonClose.clicked.connect(self.closePullRequest)
        self.buttonCreate.clicked.connect(self.createPullRequest)
        self.buttonTestMergeability.clicked.connect(self.testMergeability)

        self.buttonExportDiff.clicked.connect(self.exportAllDiff)
        
        self.buttonExportDiff.setEnabled(False)
        self.buttonClose.setEnabled(False)
        self.buttonCreate.setEnabled(False)
        self.buttonMerge.setEnabled(False)
        self.buttonTestMergeability.setEnabled(False)

        self.fullHistory = None
        self.tabWidget.currentChanged.connect(self.tabChanged)
        self.textPullRequestInfo.anchorClicked.connect(self.textPullRequestInfoAnchorClicked)
        self.textPullRequestInfo.setOpenLinks(False)

        self.tabWidget.widget(2).setLayout(QVBoxLayout())
        self.tabWidget.widget(2).layout().setMargin(0)
        if not creatingPr:
            self.prs = {"{} (#{})".format(pr["title"],pr["id"]):pr for pr in self.server.pullRequests(self.user, self.repo)}
            names = list(self.prs.keys())
            self.comboPr.addItems(names)
            if prName is not None:
                tx = "{} (#{})".format(prName,prID)
                self.comboPr.setCurrentIndex(names.index(tx))
            self.comboPr.currentIndexChanged.connect(self.fillWithPrData)
            if self.prs:
                self.fillWithPrData()
        else:
            constellation = self.server.constellation(self.user, self.repo)
            repos = [r.fullName() for r in constellation.all if r.fullName() != self.user + ":" + self.repo]
            self.comboTarget.addItems(repos)
            if defaultParent is not None:                
                self.comboTarget.setCurrentText(defaultParent)
            if repos:
                self.fillWithPrData()
                self.comboTarget.currentIndexChanged.connect(self.fillWithPrData)
            else:
                if self.tabWidget.count() > 1:
                    self.tabWidget.removeTab(0)
                    self.tabWidget.removeTab(1)

    # 0 = info, 1 = commits, 2= combined
    def tabIndex(self,wantedIndx):
        if wantedIndx==0:
            return self.tabWidget.indexOf(self.textPullRequestInfo)
        if wantedIndx == 1:
            return self.tabWidget.indexOf(self.history)
        if wantedIndx == 2:
            return self.tabWidget.indexOf(self.fullHistory)

    def clearLayout(self,layout):
         while (layout.count() >0):
             child = layout.takeAt(0)

    def tabChanged(self,tabIdx):
        THRESHOLD = 1500

        if tabIdx != 2:  # the full changed view
            return
        if self.fullHistory is not None:
            return
        if not self.fullDiffSummary:
            return
        if self.fullDiffSummaryTotal > THRESHOLD:
            text = QTextBrowser()
            text.setHtml("<br><br><br><center><font size=+3><b>Too many changes to show - {:,} features changed</b></font>".
                         format(self.fullDiffSummaryTotal))
            layout =self.tabWidget.widget(2).layout()
            self.clearLayout(layout)
            #layout.setMargin(0)
            layout.addWidget(text)
            self.fullHistory = layout
            #self.tabWidget.widget(2).setLayout(layout)
            return
        # need to set it up
        layout = self.tabWidget.widget(2).layout()
        self.clearLayout(layout)

        #layout.setMargin(0)
        pr = self.prs[self.comboPr.currentText()]
        prid = pr["id"]
        total, diffsummary = self.server.diffSummaryPR(self.user, self.repo, prid)
        if total is None:
            text = QTextBrowser()
            text.setHtml(
                "<br><br><br><center><font size=+3><b>PR is in Conflict - Please Synchronize</b></font>".
                format(self.fullDiffSummaryTotal))
            layout = self.tabWidget.widget(2).layout()
            #layout.setMargin(0)
            self.clearLayout(layout)

            layout.addWidget(text)
            self.fullHistory = layout

            #self.tabWidget.widget(2).setLayout(layout)
            return
        layers = [l["path"] for l in diffsummary.values()]

        diffs = {layer: execute(lambda: list(self.server.diffPR(self.user, self.repo, layer, prid)[1])) for layer in layers}

        fullDiffView = DiffViewerWidget(diffs)
        fullDiffView.selectFirstChangedFeature()
        layout.addWidget(fullDiffView)
        self.fullHistory = layout
        #self.tabWidget.widget(2).setLayout(layout)

    def createPullRequest(self):
        user2, repo2 = self.comboTarget.currentText().split(":")
        name = self.txtPrName.text()
        if name:
            conflicts = self.server.branchConflicts(self.user, self.repo, "master", user2, repo2, "master")
            if conflicts:
                ret = QMessageBox.warning(self, "Conflicts with target repository",
                                          "This Pull Request is in conflict with the target repo.\n"
                                          "Please SYNC changes from target repo (and resolve conflicts) before making a PR!",
                                          QMessageBox.Ok,
                                          QMessageBox.Ok)
                return
            # this assumes sending to parent
            commitsBehind,commitsAhead  =self.server.compareHistories(self.user, self.repo, user2, repo2)
            if commitsBehind > 0 :
                msgBox = QMessageBox()
                msgBox.setText("Target repo has changes")
                msgBox.setInformativeText( "The target repo has changes not in this repo - we recommend SYNC those changes before creating a PR")
                msgBox.setStandardButtons(QMessageBox.Ok | QMessageBox.Abort)
                msgBox.setDefaultButton(QMessageBox.Abort)
                ret = msgBox.exec_()
                if ret == QMessageBox.Abort:
                    return
            self.server.createPullRequest(self.user, self.repo, user2, repo2, name, "master", "master",
                                          description=self.prDescription)
            self.close()
        else:
            self.bar.pushMessage("Error", "Enter a valid pull request name", level=Qgis.Warning)

    def testMergeability(self):
        if self.creatingPr:
            user2, repo2 = self.comboTarget.currentText().split(":")
            conflicts = self.server.branchConflicts(self.user, self.repo, "master", user2, repo2, "master")
        else:
            pr = self.prs[self.comboPr.currentText()]
            conflicts = self.server.numberConflictsPR(self.user, self.repo, pr["id"])
            conflicts = conflicts>0

        if conflicts:
            self.bar.pushMessage("Error", "Pull request cannot be merged without conflicts", level=Qgis.Warning)
        else:
            self.bar.pushMessage("Mergeable","Pull request can be merged without conflicts", level=Qgis.Success)

    def mergePullRequest(self):
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        pr = self.prs[self.comboPr.currentText()]
        merged = self.server.mergePullRequest(self.user, self.repo, pr["id"])
        if not merged:
            msgBox = QMessageBox()
            msgBox.setText("Conflicts in PR")
            msgBox.setInformativeText("There are conflicts.\n"
                                     "Source repo needs to be synchronized and conflicts solved.\n"
                                     "This will modify the source repo.")
            msgBox.setIcon(QMessageBox.Warning)
            syncButton = msgBox.addButton("Continue", QMessageBox.ActionRole)
            abortButton = msgBox.addButton(QMessageBox.Abort)

            msgBox.exec_()

            if msgBox.clickedButton() == syncButton:
                # do sync
                syncDialog = SynchronizeDialog(pr["sourceRepo"]["owner"]["identity"], pr["sourceRepo"]["identity"],                                                   
                                               self.server,
                                               pr["targetRepo"]["owner"]["identity"], pr["targetRepo"]["identity"],
                                               False)
                syncDialog.exec_()
                if syncDialog.synced:
                    self.mergePullRequest()
                else:
                    self.close()
            elif msgBox.clickedButton() == abortButton:
                self.close()
        else:
            self.close()

    def closePullRequest(self):
        pr = self.prs[self.comboPr.currentText()]
        self.server.closePullRequest(self.user, self.repo, pr["id"])
        if self.comboPr.count() == 1:
            self.close()
        else:
            self.comboPr.removeItem(self.comboPr.currentIndex())

    INFOTAB = 0
    CHANGESTAB = 1
    COMBINEDCHANGESTAB = 2
    def fillWithPrData(self):
        if self.creatingPr:
            user2, repo2 = self.comboTarget.currentText().split(":")
            if self.tabWidget.count() > 2:
                self.tabWidget.removeTab(2)
                self.tabWidget.setCurrentIndex(0) #summary
            commits, commitsDict = self.server.aheadCommits(self.user, self.repo, user2, repo2)
            user = self.user
            repo = self.repo
            user2, repo2 = self.comboTarget.currentText().split(":")
            behind,ahead  = self.server.compareHistories(self.user, self.repo, user2, repo2)
            self.outOfSync = behind != 0
            self.inConflict = self.server.branchConflicts(self.user, self.repo, "master", user2, repo2, "master")

            self.fullDiffSummaryTotal,self.fullDiffSummary = self.server.diffSummary(user2, repo2, "HEAD", "HEAD", self.user, self.repo)
        else:
            pr = self.prs[self.comboPr.currentText()]
            self.prDescription = pr["description"] if pr["description"] is not None else ""
            user = pr["sourceRepo"]["owner"]["identity"]
            repo = pr["sourceRepo"]["identity"]
            user2 = pr["targetRepo"]["owner"]["identity"]
            repo2 = pr["targetRepo"]["identity"]
            commits, commitsDict = self.server.aheadCommits(user, repo, user2, repo2)
            behind, ahead = self.server.compareHistories(user, repo, user2, repo2)
            self.outOfSync = behind != 0

            self.fullDiffSummaryTotal, self.fullDiffSummary = self.server.diffSummaryPR(self.user, self.repo, pr["id"])
            self.inConflict = self.fullDiffSummaryTotal is None
            self.tabWidget.setCurrentIndex(0)  # summary
            self.fullHistory = None
    
        if self.history is None:
            layout = QVBoxLayout()
            layout.setMargin(0)
            self.history = HistoryDiffViewerWidget(self, self.server, user, repo, 
                                        CommitGraph(commits, commitsDict), initialSimplify=True)
            self.history.setShowPopup(False)
            layout.addWidget(self.history)
            self.tabWidget.widget(1).setLayout(layout)
        else:
            self.history.setContent(self.server, self.user, self.repo, CommitGraph(commits, commitsDict))

        self.setupInfo()
        self.buttonClose.setEnabled(self.belongsToLoggedUser)
        self.buttonCreate.setEnabled(len(commits) > 0)
        self.buttonMerge.setEnabled(len(commits) > 0 and self.belongsToLoggedUser)
        self.buttonTestMergeability.setEnabled(len(commits) > 0)
       # self.buttonExportDiff.setEnabled(not self.outOfSync)

    def setupInfo(self):
        if self.inConflict and not self.creatingPr:
            pr = self.prs[self.comboPr.currentText()]
            if pr is None:
                self.textPullRequestInfo.setHtml("No PR")
                return
            self.setupConflicting(pr)
        elif self.inConflict and self.creatingPr:
            self.setupConflictingCreate()
        elif self.creatingPr:
            self.setupInfoCreating()
        else:
            pr = self.prs[self.comboPr.currentText()]
            if pr is None:
                self.textPullRequestInfo.setHtml("No PR")
                return
            self.setupInfoPR(pr)

        if self.creatingPr:
            self.buttonExportDiff.setEnabled(not (self.outOfSync or self.inConflict))
        else:
            self.buttonExportDiff.setEnabled(not self.inConflict)

    def textPullRequestInfoAnchorClicked(self,url):
        url = url.url()  # convert to string
        cmd, layerName = url.split(".", 1)
        if cmd == "editDesc":
            dlg = EditDescription(self.prDescription)
            r = dlg.exec_()
            if r:
                self.prDescription = dlg.description
                self.setupInfo()
        if cmd == "exportDiff":
            execute(lambda: self.exportDiff(layer=layerName))
        if cmd == "exportDiffLocal":
            execute(lambda: self.exportDiffLocal(layer=layerName))
        if cmd == "sync":
            if self.creatingPr:
                user = self.user
                repo = self.repo
                user2, repo2 = self.comboTarget.currentText().split(":")

                syncDialog = SynchronizeDialog(user, repo, self.server, user2, repo2, False)
                syncDialog.exec_()
                try:
                    self.showNormal()
                    self.raise_()
                    self.activateWindow()
                except:
                    pass
            else:
                pr = self.prs[self.comboPr.currentText()]
                user = pr["sourceRepo"]["owner"]["identity"]
                repo = pr["sourceRepo"]["identity"]
                user2 = pr["targetRepo"]["owner"]["identity"]
                repo2 = pr["targetRepo"]["identity"]
                syncDialog = SynchronizeDialog(user,repo, self.server, user2, repo2, False)
                syncDialog.exec_()
                try:
                    self.showNormal()
                    self.raise_()
                    self.activateWindow()
                except:
                    pass
            self.fillWithPrData()

    def setupConflictingCreate(self):
        html = "" if not self.outOfSync else "<font color=red>"
        html += '<br><center><font size=+2><b>Creating PR - "{}"</b></font><br>'.format(self.txtPrName.text())
        user2, repo2 = self.comboTarget.currentText().split(":")
        html += "<i>{}:{} </i>&#8594;<i> {}:{}</i><br>".format(self.user, self.repo, user2, repo2)

        html += "<br><br>"
        html += "<font size=+2><b>Source Repository is in conflict with Target Repository</b></font><br>"
        html += "You must synchronize the source repository and resolve conflicts<br>"
        html += "<br><a href='sync.'><font size=+1>Click here to synchronize now</font></a>"
        self.textPullRequestInfo.setHtml(html)


    def setupConflicting(self,pr):
        html = "" if not self.outOfSync else "<font color=red>"
        html += '<center><font size=+2><b>PR - "{}" (#{})</b></font><br>'.format(pr["title"], pr["id"])
        html += "<i>{}:{} </i>&#8594;<i> {}:{}</i><br>".format(
            pr["sourceRepo"]["owner"]["identity"], pr["sourceRepo"]["identity"],
            pr["targetRepo"]["owner"]["identity"], pr["targetRepo"]["identity"])
        html += "Created By: {}<br><br>".format(pr["createdBy"]["identity"])
        html += "<br><br>"
        html += "<font size=+2><b>Source Repository is in conflict with Target Repository</b></font><br>"
        html += "You must synchronize the source repository and resolve conflicts<br>"
        html += "<br><a href='sync.'><font size=+1>Click here to synchronize now</font></a>"
        self.textPullRequestInfo.setHtml(html)


    def setupInfoPR(self,pr):
        html = "" if not self.outOfSync else  "<font color=#B46400>"
        html += '<center><font size=+2><b>PR - "{}" (#{})</b></font><br>'.format(pr["title"], pr["id"])
        html += "<i>{}:{} </i>&#8594;<i> {}:{}</i><br>".format(
            pr["sourceRepo"]["owner"]["identity"], pr["sourceRepo"]["identity"],
            pr["targetRepo"]["owner"]["identity"], pr["targetRepo"]["identity"])
        html += "Created By: {}<br><br>".format(pr["createdBy"]["identity"])
        if self.fullDiffSummaryTotal == 0:
            html += "<br><font size=+2>No Changes</font>"
        if self.fullDiffSummary:
            html += "<table>"
            html += "<tr><Td style='padding:5px'><b>Layer&nbsp;Name</b></td><td style='padding:5px'><b>Additions</b></td><td style='padding:5px'><b>Deletions</b></td><td style='padding:5px'><b>Modifications</b></td><td></td></tr>"
            for detail in self.fullDiffSummary.values():
                added = "{:,}".format(int(detail["featuresAdded"]))
                removed = "{:,}".format( int(detail["featuresRemoved"]))
                modified = "{:,}".format( int(detail["featuresChanged"]))

                linkexport =  "<a href='exportDiff.{}'>Export Diff</a>".format(detail["path"])
                html += "<tr><td style='padding:5px'>{}</td><td style='padding:5px'><center>{}</center></td><td style='padding:5px'><center>{}</center></td><td style='padding:5px'><center>{}</center></td><td style='padding:5px'>{}</td></tr>".format(
                    detail["path"],
                    added, removed, modified,
                    linkexport
                )
            html += "<tr></tr>"
            commits = ""
            if self.history is not None and self.history.graph is not None:
                n = len(self.history.graph.commits)
                commits = " in {} commit".format(n)
                if n > 1:
                    commits += "s"  # commit -> commits


            html += "<tr><td colspan=4>There is a total of {}.</td></tr>".format(commits)
            html += "</table>"

            html += "<br>"
            desc = self.prDescription.replace("\n", "<br>")
            html += "<table><tr><td style='padding-right:400px'>Description:&nbsp;&nbsp; </td></tr>"
            html += "<tr><td><p style='background: #f9f9f9;border-left: 10px solid #ccc;'><i>{}</i></p></td></tr>".format(
                desc)
            html += "</table>"

            if self.outOfSync:
                html += "<center><br><br><b>The source repository is out-of-sync with the target repository.</b><br>"
                html += "<a href='sync.'>Click here to synchronize now</a>"

        self.textPullRequestInfo.setHtml(html)

    def setupInfoCreating(self):
        html = "" if not self.outOfSync else  "<font color=#B46400>"
        html += '<br><center><font size=+2><b>Creating PR - "{}"</b></font><br>'.format(self.txtPrName.text())
        user2, repo2 = self.comboTarget.currentText().split(":")
        html += "<i>{}:{} </i>&#8594;<i> {}:{}</i><br>".format(self.user,self.repo,user2,repo2)
        if self.fullDiffSummaryTotal == 0:
            html += "<br><font size=+2>No Changes</font>"
        if self.fullDiffSummary:
            html += "<table>"
            html += "<tr><Td style='padding:5px'><b>Layer&nbsp;Name</b></td><td style='padding:5px'><b>Additions</b></td><td style='padding:5px'><b>Deletions</b></td><td style='padding:5px'><b>Modifications</b></td><td style='padding:5px'><b></b></td></tr>"
            for detail in self.fullDiffSummary.values():
                added = "{:,}".format(int(detail["featuresAdded"])) if not self.outOfSync else "<font size=-1><i>unknown</i></font>"
                removed = "{:,}".format(int(detail["featuresRemoved"])) if not self.outOfSync else "<font size=-1><i>unknown</i></font>"
                modified = "{:,}".format(int(detail["featuresChanged"])) if not self.outOfSync else "<font size=-1><i>unknown</i></font>"

                exportText = "<td style='padding:5px'><a href='exportDiffLocal.{}'>Export Diff</a></td>".format(detail["path"]) if not self.outOfSync else ""

                html += "<tr><td style='padding:5px'>{}</td><td  valign=middle style='padding:5px'><center>{}</center></td><td  valign=middle style='padding:5px'><center>{}</center></td><td valign=middle style='padding:5px'><center>{}</center></td><td valign=middle style='padding:5px'>{}</td></tr>".format(
                    detail["path"],
                    added,removed,modified,exportText
                )
            html += "<tr></tr>"
            commits = ""
            if self.history is not None and self.history.graph is not None:
                n = len(self.history.graph.commits)
                commits = "{} commit".format(n)
                if n > 1:
                    commits += "s" # commit -> commits
            if not self.outOfSync:
                html += "<tr><td colspan=4>There is a total of {:,} features changed in {}.</td></tr>".format(self.fullDiffSummaryTotal,commits)
            else:
                html += "<tr><td colspan=4>There is a total of {}.</td></tr>".format(commits)

            html += "</table>"
        if self.outOfSync:
            html += "<center><br><br>The source repository is out-of-sync with the target repository.<br>"
            html += "Synchronize the source repository to get more accurate information.<br>"
            html += "<br><a href='sync.'><font size=+1>Click here to synchronize now</font></a>"
        html += "<br>"
        desc = self.prDescription.replace("\n","<br>")
        linktext = "add description" if desc is None or desc == '' else "edit description"
        link = "<a href='editDesc.'>{}</a>".format(linktext)
        html += "<table><tr><td style='padding-right:400px'>Description:&nbsp;&nbsp;{}</td></tr>".format(link)
        html += "<tr><td><p style='background: #f9f9f9;border-left: 10px solid #ccc;'><i>{}</i></p></td></tr>".format(desc)
        html += "</table>"
        self.textPullRequestInfo.setHtml(html)


    def exportAllDiff(self):
        execute(lambda: self.exportDiff())

    def exportDiffLocal(self,layer=None):
        user2, repo2 = self.comboTarget.currentText().split(":")
        ex = DiffGeoPKGMultiLayer(self.server, self.user, self.repo, "HEAD","HEAD", layer=layer,
                                  commitAUser=user2,commitARepo=repo2)
        ex.addToProject()

    def exportDiff(self,flag=False,layer = None):
        pr = self.prs[self.comboPr.currentText()]
        prid = pr["id"]
        ex = DiffGeoPKGMultiLayerForPR(self.server, self.user, self.repo, prid,layer=layer)
        ex.addToProject()

    def closeEvent(self, evt):
        if self.history is not None:
            self.history.removeMapLayers()
        evt.accept()


class EditDescription(QDialog):
    def __init__(self,description, parent=None):
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        super(EditDescription, self).__init__(parent)
        self.description = description

        layout = QVBoxLayout()

        self.textWidget = QPlainTextEdit()
        self.textWidget.setPlainText(self.description)
        layout.addWidget(self.textWidget)

        buttonLayout = QHBoxLayout()
        okButton = QPushButton("Ok")
        okButton.clicked.connect(self.ok)
        cancelButton = QPushButton("Cancel")
        cancelButton.clicked.connect(self.reject)
        buttonLayout.addWidget(okButton)
        buttonLayout.addWidget(cancelButton)
        layout.addLayout(buttonLayout)

        self.setLayout(layout)
        self.resize(650, self.height())
        self.setWindowTitle("Edit dR description")

    def ok(self):
        self.description = self.textWidget.toPlainText()
        self.accept()