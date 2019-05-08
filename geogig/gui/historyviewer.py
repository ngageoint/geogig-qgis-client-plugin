import math
from builtins import zip
from builtins import str
from copy import deepcopy

import os
import json
import sqlite3
from functools import partial
#from collections import defaultdict
from datetime import datetime

from qgis.PyQt.QtCore import Qt, pyqtSignal, QPoint, QRectF, QItemSelectionModel, QPointF, QLineF
from qgis.PyQt.QtGui import QIcon, QImage, QPixmap, QPainter, QColor, QPainterPath, QPen, QBrush, QPolygonF
from qgis.PyQt.QtWidgets import (QTreeWidget, QAbstractItemView, QMessageBox, QAction, QMenu,
                                 QInputDialog, QTreeWidgetItem, QLabel, QTextEdit, QListWidgetItem,
                                 QDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox, QApplication,
                                 QPushButton, QSplitter, QWidget, QTabWidget, QAbstractItemView, QTextBrowser,
                                 QSizePolicy)
from qgis.gui import QgsMessageBar, QgsFilterLineEdit
from qgis.utils import iface
from qgis.core import QgsApplication, QgsWkbTypes, QgsProject, QgsRectangle, QgsFeature, Qgis
from qgis.gui import QgsMapCanvas, QgsMapToolPan, QgsMessageBar

from geogig.layers.diffgeopkglayer import DiffGeoPKGMultiLayer
from geogig.gui.diffviewer import DiffViewerDialog, DiffViewerWidget
from geogig.gui.progressbar import setCurrentWindow, currentWindow
from geogig.gui.commitgraph import CommitGraph, COMMIT_NORMALIMPORTANCE, COMMIT_IMPORTANT, COMMIT_UNIMPORTANT
from geogig.protobuff.featuretype import FeatureTypeHelper

from qgiscommons2.gui import execute
from qgiscommons2.gui import showMessageDialog
from qgiscommons2.layers import loadLayerNoCrsDialog

def icon(f):
    return QIcon(os.path.join(os.path.dirname(__file__),
                            os.pardir, "ui", "resources", f))

resetIcon = icon("reset.png")
diffIcon = icon("diff-selected.png")
deleteIcon = QgsApplication.getThemeIcon('/mActionDeleteSelected.svg')
infoIcon = icon("repo-summary.png")
tagIcon = icon("tag.gif")
mergeIcon = icon("merge-24.png")

class HistoryTree(QTreeWidget):

    historyChanged = pyqtSignal()

    def __init__(self, parent):
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        super(HistoryTree, self).__init__()
        self.repo = None
        self.layername = None
        self.selecting = False
        self.parent = parent
        self.showPopup = True
        self.initGui()

    # override the default autoscroll behavior
    #  this will not move the horizontal position of the scroll bar during a scroll-to
    # ie. when you click on a cell, it will bring that into view (if its large, it will change the x scroll)
    # this is very anoying
    def scrollTo(self, index, hint):
        oldH = self.horizontalScrollBar().value() # remember current horizontal value
        super().scrollTo(index, hint) # call default implementation
        self.horizontalScrollBar().setValue(oldH) # reset to old value

    def initGui(self):
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.header().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        self.setHeaderLabels(["Graph", "Description", "Author", "Date", "CommitID"])
        if self.showPopup:
            self.customContextMenuRequested.connect(self._showPopupMenu)
            self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def exportVersion(self, layer, commitid, live):
        from geogig.layers import addGeogigLayer
        addGeogigLayer(self.server, self.user, self.repo, layer, commitid, live, self)
        currentWindow().messageBar().pushMessage("Layer", "Layer was correctly added to QGIS project",
                                                level=Qgis.Info, duration=5)
        
    def _showPopupMenu(self, point):
        point = self.mapToGlobal(point)
        self.showPopupMenu(point)

    def showPopupMenu(self, point):
        selected = self.selectedItems()
        if selected and len(selected)==1:
            item = self.currentItem()
            layers = self.server.layers(self.user, self.repo, item.commit.commitid)
            exportVersionActions = []
            for layer in layers:
                exportVersionActions.append(QAction(resetIcon, "Add '%s' layer to QGIS from this commit (geopackage)" % layer, None))
                exportVersionActions[-1].triggered.connect(partial(self.exportVersion, layer, item.commit.commitid, False))
                exportVersionActions.append(QAction(resetIcon, "Add '%s' layer to QGIS from this commit (live link)" % layer, None))
                exportVersionActions[-1].triggered.connect(partial(self.exportVersion, layer, item.commit.commitid, True))
            menu = QMenu()

            revertAction = QAction("Revert changes introduced by this commit...", None)
            revertAction.triggered.connect(lambda: self.revert(item.commit.commitid))
            menu.addAction(revertAction)
            resetAction = QAction("Reset repository to this commit...", None)
            resetAction.triggered.connect(lambda: self.resetToCommit(item.commit.commitid))
            menu.addAction(resetAction)
            menu.addSeparator()
            exportDiffAction =  QAction(resetIcon, "Add DIFF layers to QGIS for this commit", None)
            exportDiffAction.triggered.connect(partial(self.exportDiff, item, None,self.layername))
            menu.addAction(exportDiffAction)
            if exportVersionActions:
                menu.addSeparator()
                for action in exportVersionActions:
                    menu.addAction(action)
            menu.exec_(point)
        if selected and len(selected) == 2:
            item0 = selected[0]
            item1 = selected[1]

            exportDiffAction =  QAction(resetIcon, "Add DIFF layers to QGIS for these commits", None)
            exportDiffAction.triggered.connect(partial(self.exportDiff, item0,  item1,self.layername))
            menu = QMenu()
            menu.addAction(exportDiffAction)
            menu.exec_(point)

    def exportDiff(self, item0, item1, layer=None):
        row0 = self.indexFromItem(item0).row()
        row1 = self.indexFromItem(item1).row() if item1 is not None else (row0 + 1)
        commitA = item0.commit.commitid
        commitB = item1.commit.commitid if item1 is not None else commitA + "~1"
        if item1 is None and len(item0.commit.parentIds) ==0:
            commitB = "0000000"
        if row0 > row1:
            commitB, commitA = commitA, commitB

        diffexporter = DiffGeoPKGMultiLayer(self.server,
                            self.user,
                            self.repo,
                            commitA,
                            commitB, layer=layer)
        diffexporter.addToProject()
        currentWindow().messageBar().pushMessage("Layers", "DIFF layers were correctly added to QGIS project",
                                                level=Qgis.Info, duration=5)

    def revert(self, commitid):
        lastCommit = self.graph.commits[0].commitid
        self.server.revert(self.user, self.repo, "master", commitid)
        commits, commitsDict = self.server.log(self.user, self.repo, "master")        
        if commits[0] == lastCommit:
            QMessageBox.warning(self, "Revert", "Commit could not be reverted")
        else:
            self.historyChanged.emit()

    def resetToCommit(self, commitid):
        self.server.reset(self.user, self.repo, "master", commitid)
        self.historyChanged.emit()      
        
    COMMIT_GRAPH_HEIGHT = 20
    COLUMN_SEPARATION = 20
    COMMIT_GRAPH_WIDTH = 300
    RADIUS = 5
    PEN_WIDTH = 4

    COLORS = [QColor(Qt.red),
              QColor(Qt.green),
              QColor(Qt.blue),
              QColor(Qt.black),
              QColor(255,166,0),
              QColor(Qt.darkGreen),
              QColor(Qt.darkBlue),
              QColor(Qt.cyan),
              QColor(Qt.magenta)]

    def createGraphImage(self):
        self.image = QPixmap(self.COMMIT_GRAPH_WIDTH, 1000).toImage()
        qp = QPainter(self.image)
        qp.fillRect(QRectF(0, 0, self.COMMIT_GRAPH_WIDTH, 1000), Qt.white);
        #qp.begin(self.image)
        self.drawLines(qp)
        qp.end()

    def drawLines(self, painter):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.HighQualityAntialiasing)
        self.linked = []
        self.columnColor = {}
        self.lastColor = -1
        def linkCommit(commit):
            for parent in commit.getParentsIfAvailable():
                try:
                    self.drawLine(painter, commit, parent)
                    if parent.commitid not in self.linked:
                        linkCommit(parent)
                except:
                    continue

        if self.graph.commits:
            linkCommit(self.graph.commits[0])

        y = len(self.graph.commits) * self.COLUMN_SEPARATION
        x = self.RADIUS * 3
        painter.setPen(self.COLORS[0])
        painter.setBrush(self.COLORS[0])
        painter.drawEllipse(QPoint(x, y), self.RADIUS, self.RADIUS)

    def drawLine(self, painter, commit, parent):
        commitRow = self.graph.commitRows[commit.commitid]
        commitCol = self.graph.commitColumns[commit.commitid]
        parentRow = self.graph.commitRows[parent.commitid]
        parentCol = self.graph.commitColumns[parent.commitid]
        commitX = self.RADIUS * 3 + commitCol * self.COLUMN_SEPARATION
        parentX = self.RADIUS * 3 + parentCol * self.COLUMN_SEPARATION
        commitY = commitRow * self.COMMIT_GRAPH_HEIGHT
        parentY = parentRow * self.COMMIT_GRAPH_HEIGHT
        color = self._columnColor(parentCol)

        if parent is not None and self.graph.isFauxLink(parent.commitid, commit.commitid)\
                and len(parent.childrenIds)>1:
            # draw a faux line
            path = QPainterPath()
            path.moveTo(parentX, parentY)
            path.lineTo(commitX , commitY)

            color = QColor(255,160,255)
            pen = QPen()
            pen.setWidth(2)
            pen.setBrush(color)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawPath(path)

            # draw arrow
            # draw arrow
            ARROW_POINT_SIZE = 9
            painter.setPen(color)
            painter.setBrush(color)
            line = QLineF(commitX , commitY, parentX, parentY)

            angle = math.acos(line.dx() / line.length())
            if line.dy() >= 0:
                angle = 2.0 * math.pi - angle

            sourcePoint = QPointF(commitX,commitY)
            sourceArrowP1 = sourcePoint + QPointF(math.sin(angle + math.pi / 3) * ARROW_POINT_SIZE,
                                                       math.cos(angle + math.pi / 3) * ARROW_POINT_SIZE)
            sourceArrowP2 = sourcePoint + QPointF(math.sin(angle + math.pi - math.pi / 3) * ARROW_POINT_SIZE,
                                                       math.cos(angle + math.pi - math.pi / 3) * ARROW_POINT_SIZE)
            arrow = QPolygonF([line.p1(), sourceArrowP1, sourceArrowP2])
            painter.drawPolygon(arrow)
            return

        path = QPainterPath()
        painter.setBrush(color)
        painter.setPen(color)

        if parentCol != commitCol:
            if parent.isFork() and commit.getParents()[0].commitid == parent.commitid:
                path.moveTo(commitX, commitY)
                path.lineTo(commitX, parentY)
                if parentX<commitX:
                    path.lineTo(parentX + self.RADIUS + 1, parentY)
                else:
                    path.lineTo(parentX - self.RADIUS, parentY)
                color = self._columnColor(commitCol)
            else:
                path2 = QPainterPath()
                path2.moveTo(commitX + self.RADIUS + 1, commitY)
                path2.lineTo(commitX + self.RADIUS + self.COLUMN_SEPARATION / 2, commitY + self.COLUMN_SEPARATION / 3)
                path2.lineTo(commitX + self.RADIUS + self.COLUMN_SEPARATION / 2, commitY - self.COLUMN_SEPARATION / 3)
                path2.lineTo(commitX + + self.RADIUS + 1, commitY)
                painter.setBrush(color)
                painter.setPen(color)
                painter.drawPath(path2)
                path.moveTo(commitX + self.RADIUS + self.COLUMN_SEPARATION / 2, commitY)
                path.lineTo(parentX, commitY)
                path.lineTo(parentX, parentY)

            if parent.isFork():
                if commitCol in self.columnColor.keys():
                    del self.columnColor[commitCol]
  
        else:
            path.moveTo(commitX, commitY)
            path.lineTo(parentX, parentY)

        pen = QPen(color, self.PEN_WIDTH, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin)
        painter.strokePath(path, pen)

        if not commit.commitid in self.linked:
            y = commitRow * self.COLUMN_SEPARATION
            x = self.RADIUS * 3 + commitCol * self.COLUMN_SEPARATION
            painter.setPen(color)
            painter.setBrush(color)
            painter.drawEllipse(QPoint(x, y), self.RADIUS, self.RADIUS)
            self.linked.append(commit.commitid)

    def _columnColor(self, column):
        if column in self.columnColor:
            color = self.columnColor[column]
        elif column == 0:
            self.lastColor += 1
            color = self.COLORS[0]
            self.columnColor[column] = color
        else:
            self.lastColor += 1
            color = self.COLORS[(self.lastColor % (len(self.COLORS)-1)) + 1]
            self.columnColor[column] = color
        return color

    def graphSlice(self, row, width):
        return self.image.copy(0, (row - .5) * self.COMMIT_GRAPH_HEIGHT,
                               width, self.COMMIT_GRAPH_HEIGHT)

    def updateContent(self, server, user, repo, graph, layername = None):
        self.server = server
        self.user = user
        self.repo = repo
        self.layername = layername
        self.graph = graph
        self.clear()
        self._updateContent()
        if graph.commits:
            self.setCurrentItem(self.topLevelItem(0))

    def _updateContent(self):
        if not self.graph:
            return
        self.createGraphImage()
        self.clear()

        if self.graph.commitColumns:
            width = self.COLUMN_SEPARATION * (max(self.graph.commitColumns.values()) + 1) + self.RADIUS +10
        else:
            width = self.COLUMN_SEPARATION

        for i, commit in enumerate(self.graph.commits):
            item = CommitTreeItem(commit, self)
            self.addTopLevelItem(item)
            img =self.graphSlice(i + 1, width)
            w = GraphWidget(img)
            w.setFixedHeight(self.COMMIT_GRAPH_HEIGHT)
            w.setFixedWidth(self.COMMIT_GRAPH_WIDTH )
            self.setItemWidget(item, 0, w)
            self.setColumnWidth(0, self.COMMIT_GRAPH_WIDTH)

        for i in range(1, 4):
            self.resizeColumnToContents(i)

        self.expandAll()

        self.header().resizeSection(0, width +20)

class GraphWidget(QWidget):

    def __init__(self, img):
        QWidget.__init__(self)
        self.setFixedWidth(img.width())
        self.img = img

    def paintEvent(self, e):
        painter = QPainter(self)
        #painter.begin(self);
        painter.drawImage(0, 0, self.img)
        painter.end()

class CommitTreeItem(QTreeWidgetItem):

    def __init__(self, commit,parent):
        QTreeWidgetItem.__init__(self,parent)
        self.commit = commit
        self.ref = commit.commitid
        self.setupToolTip()

        self.setText(1, commit.message.splitlines()[0])
        self.setText(2, commit.author)
        timestamp = commit.timestamp / 1000
        self.setText(3, datetime.fromtimestamp(timestamp).strftime(" %m/%d/%y %H:%M"))
        self.setText(4, commit.commitid)

        font = self.font(0)
        if self.commit.getImportance() == COMMIT_IMPORTANT:
            color = QColor("#000000")
            font.setBold(True)
        elif self.commit.getImportance() == COMMIT_UNIMPORTANT:
            color = QColor("#909090")
            font.setItalic(True)
        else:
            color = QColor("#000000")
        for i in range(5):
            self.setForeground(i, QBrush(color))
            self.setFont(i, font)

    def setupToolTip(self):
        text= ""
        if self.commit.numbParents() > 0:
            parents = ",".join([c.commitid for c in self.commit.getParentsIfAvailable()])
            text = "Parents: "+parents
        self.setToolTip(0,text)
        self.setToolTip(1,text)
        self.setToolTip(2,text)

class HistoryTreeWrapper(QWidget):
    #A widget that includes a history tree, a filter text box and a the ability to simplify the tree view

    def __init__(self, history):
        QWidget.__init__(self)
        self.history = history
        self.history.historyChanged.connect(self.historyChanged)
        self.graph = history.graph
        hlayout = QHBoxLayout()
        self.searchBox = QgsFilterLineEdit()
        self.searchBox.setPlaceholderText("Enter text or date to filter")
        self.searchBox.textChanged.connect(self.filterCommits)
        hlayout.addWidget(self.searchBox)
        self.simplifyLog = False
        self.simplifyButton = QPushButton("Show Simplified History")        
        self.simplifyButton.clicked.connect(self.simplifyButtonClicked)
        hlayout.addWidget(self.simplifyButton)

        layout = QVBoxLayout()
        layout.setMargin(0)
        layout.addLayout(hlayout)

        layout.addWidget(history)
        self.setLayout(layout)

    def historyChanged(self):
        if self.history.layername is not None:
            commitsAll, commitsDictAll, commitsLayer, commitsDictLayer = self.history.server.logAll(self.history.user, self.history.repo,
                                                                                            "master", self.history.layername)
            self.graph = CommitGraph(commitsAll, commitsDictAll, commitsLayer)            
        else:
            commits, commitsDict = self.history.server.log(self.history.user, self.history.repo, "master")
            self.graph = CommitGraph(commits, commitsDict)
        self.history.graph = self.graph
        self.history._updateContent()

    def filterCommits(self, value):
        text = self.searchBox.text().strip(' ').lower()
        root = self.history.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            hide = bool(text) and not any(text in t.lower() for t in [item.text(1), item.text(2), item.text(3)])
            item.setHidden(hide)

    # creates a new CommitGraph, but simplified
    # a) only commits affecting layer
    # b) NO merge commits
    # c) we re-parent the commits so the graph is trivial
    def simplifyGraph(self, fullGraph):
        # find the set of commits to use
        # (either get all of them or just the layer-affecting sub-set
        mainCommitIds = fullGraph.importantCommitIds if fullGraph.importantCommitIds else fullGraph.commitIdList
        # we don't want merge commits - remove any that have multiple parents
        commits = [fullGraph.getById(id) for id in mainCommitIds]

        # re-parent the commits so the graph is a single verticle line (column 0)
        commits = [deepcopy(c.repo_json) for c in commits if len(c.parentIds) <=1]
        for idx,c in enumerate(commits):
            if idx != len(commits)-1:
                c["parentIds"] = [commits[idx+1]["id"]]
            else:
                pass # leave the parent commit here (its important that the system knows this isn't the first commit in the tree)

        commitids = [c["id"] for c in commits]
        commitDict = {c["id"]: c for c in commits}

        newGraph = CommitGraph(commitids,commitDict)
        newGraph.commitColumns = {c["id"]: 0 for c in commits} # shouldn't have to do this, but...
        return newGraph

    def simplifyButtonClicked(self):
        self.simplify(not self.simplifyLog)

    def simplify(self, simplifyLog):
        self.simplifyLog = simplifyLog
        if simplifyLog:
            self.simplifyButton.setText("Show Full History")
            graph = self.simplifyGraph(self.graph)
        else:
            self.simplifyButton.setText("Show Simplified History")
            graph = self.graph

        self.history.updateContent(self.history.server, self.history.user, self.history.repo, graph, self.history.layername)

    def updateContent(self, server, user, repo, graph, layername = None):
        self.graph = graph
        if self.simplifyLog:
            graph = self.simplifyGraph(graph)
        self.history.updateContent(server, user, repo, graph, layername)

class HistoryDiffViewerWidget(QWidget):

    def __init__(self, dialog, server, user, repo, graph, layer=None, initialSimplify=False):
        self.graph = graph
        self.dialog = dialog
        self.server = server
        self.user = user
        self.repo = repo 
        self.layer = layer
        self.afterLayer = None
        self.beforeLayer = None
        self.extraLayers = [] # layers for the "Map" tab
        QWidget.__init__(self, iface.mainWindow())
        self.setWindowFlags(Qt.Window)
        self.simplifyLog = initialSimplify
        self.initGui()
        self.tabWidget.setVisible(False)
        self.setLabelText("Select a commit to show its content")
        self.label.setVisible(False)
        if self.graph.commits:
            self.history.setCurrentItem(self.history.topLevelItem(0))
            self.itemChanged(self.history.topLevelItem(0), None)
        self.history.currentItemChanged.connect(self.itemChanged)

    def setShowPopup(self, show):
        self.history.showPopup = show 

    def initGui(self):
        layout = QVBoxLayout()
        splitter = QSplitter()
        splitter.setOrientation(Qt.Vertical)

        self.history = HistoryTree(self.dialog)
        self.history.updateContent(self.server, self.user, self.repo, self.graph, self.layer)
        self.historyWithFilter = HistoryTreeWrapper(self.history)
        if self.simplifyLog:
            self.historyWithFilter.simplify(True)
        splitter.addWidget(self.historyWithFilter)
        self.tabWidget = QTabWidget()
        self.tabCanvas = QWidget()
        tabLayout = QVBoxLayout()
        tabLayout.setMargin(0)        
        self.canvas = QgsMapCanvas(self.tabCanvas)
        self.canvas.setCanvasColor(Qt.white)
        self.panTool = QgsMapToolPan(self.canvas)
        self.canvas.setMapTool(self.panTool)
        tabLayout.addWidget(self.canvas)
        self.labelNoChanges = QLabel("This commit doesn't change any geometry")
        self.labelNoChanges.setAlignment(Qt.AlignCenter)
        self.labelNoChanges.setVisible(False)
        tabLayout.addWidget(self.labelNoChanges)
        self.tabCanvas.setLayout(tabLayout)
        self.summaryTextBrowser = QTextBrowser()
        self.summaryTextBrowser.setOpenLinks(False)
        self.summaryTextBrowser.anchorClicked.connect(self.summaryTextBrowserAnchorClicked)
        self.tabWidget.addTab(self.summaryTextBrowser, "Commit Summary")
        self.tabWidget.addTab(self.tabCanvas, "Map")
        tabLayout = QVBoxLayout()
        tabLayout.setMargin(0)
        self.tabDiffViewer = QWidget()
        self.diffViewer = DiffViewerWidget({})
        tabLayout.addWidget(self.diffViewer)
        self.tabDiffViewer.setLayout(tabLayout)
        self.tabWidget.addTab(self.tabDiffViewer, "Attributes")
        splitter.addWidget(self.tabWidget)
        self.label = QTextBrowser()
        self.label.setVisible(False)
        splitter.addWidget(self.label)
        self.tabWidget.setCurrentWidget(self.tabDiffViewer)

        layout.addWidget(splitter)
        self.setLayout(layout)

        exportDiffButton = QPushButton("Export this commit's DIFF for all layers")
        exportDiffButton.clicked.connect(self.exportDiffAllLayers)

        layout.addWidget(exportDiffButton)
        self.label.setMinimumHeight(self.tabWidget.height())        
        self.setWindowTitle("Repository history")

    def summaryTextBrowserAnchorClicked(self,url):
        url = url.url() #convert to string
        item = self.history.currentItem()
        if item is None:
            return
        commitid = item.commit.commitid

        cmd,layerName = url.split(".",1)
        if cmd == "addLive":
            execute(lambda: self.history.exportVersion(layerName,commitid,True))
        elif cmd == "addGeoPKG":
            self.history.exportVersion(layerName,commitid,False)
        elif cmd == "exportDiff":
            execute(lambda: self.history.exportDiff(item, None,layer=layerName))

    def exportDiffAllLayers(self):
        item = self.history.currentItem()
        if item is not None:
            self.history.exportDiff(item, None)

    def setLabelText(self,text):
        self.label.setHtml("<br><br><br><center><b>{}</b></center>".format(text))

    def setContent(self, server, user, repo, graph, layer = None):
        self.server = server
        self.user = user
        self.repo = repo
        self.layer = layer
        self.graph = graph
        self.historyWithFilter.updateContent(server, user, repo, graph, layer)
        if self.history.graph.commits:
            self.history.setCurrentItem(self.history.topLevelItem(0))

    def itemChanged(self, current, previous, THRESHOLD = 1500):
        item = self.history.currentItem()
        if item is not None:
            commit = self.graph.getById(item.ref)
            if commit is None:
                self.tabWidget.setVisible(False)
                self.setLabelText("Select a commit to show its content")
                self.label.setVisible(True)
                return

            commit2 = commit.commitid + "~1"

            if not item.commit.hasParents():
                commit2 = "0000000000000000"

            total,details = self.server.diffSummary(self.user, self.repo,  commit2,commit.commitid)
            tooLargeDiff = total > THRESHOLD
            if tooLargeDiff:
                 html = "<br><br><center><b><font size=+3>Commit <font size=-0.1><tt>{}</tt></font> DIFF is too large to be shown</b></font><br>".format(commit.commitid[:8])
            else:
                html = "<br><br><center><b><font size=+3>Commit <font size=-0.1><tt>{}</tt></font> Summary</b></font><br>".format(commit.commitid[:8])
            html += "<table>"
            html += "<tr><Td style='padding:5px'><b>Layer&nbsp;Name</b></td><td style='padding:5px'><b>Additions</b></td><td style='padding:5px'><b>Deletions</b></td><td style='padding:5px'><b>Modifications</b></td><td></td><td></td><td></td></tr>"
            for detail in details.values():
                html += "<tr><td style='padding:5px'>{}</td><td style='padding:5px'><center>{:,}</center></td><td style='padding:5px'><center>{:,}</center></td><td style='padding:5px'><center>{:,}</center></td><td style='padding:5px'>{}</td><td style='padding:5px'>{}</td><td style='padding:5px'>{}</td></tr>".format(
                    detail["path"],
                    int(detail["featuresAdded"]), int(detail["featuresRemoved"]),int(detail["featuresChanged"]),
                    "<a href='addLive.{}'>Add Live</a>".format(detail["path"]),
                    "<a href='addGeoPKG.{}'>Add GeoPKG</a>".format(detail["path"]),
                    "<a href='exportDiff.{}'>Export Diff</a>".format(detail["path"])
                )
            html += "<tr></tr>"
            html += "<tr><td colspan=4>There is a total of {:,} features changed</td></tr>".format(total)
            html += "</table>"
            # html += "<br><br>There is a total of {:,} features changed".format(total)
            self.summaryTextBrowser.setHtml(html)
            self.label.setVisible(False)
            self.tabWidget.setVisible(True)
            self.tabWidget.setTabEnabled(1,not tooLargeDiff)
            self.tabWidget.setTabEnabled(2,not tooLargeDiff)
            if not tooLargeDiff:
                self.setDiffContent(commit, commit2)
        else:
            self.tabWidget.setVisible(False)
            self.setLabelText("Select a commit to show its content")
            self.label.setVisible(True)

    def setDiffContent(self, commit, commit2):
        if self.layer is None:
            layers = set(self.server.layers(self.user, self.repo, commit.commitid))
            layers2 = set(self.server.layers(self.user, self.repo, commit2))
            layers = layers.union(layers2)
        else:
            layers = [self.layer]

        diffs = {layer: execute(lambda: self.server.diff(self.user, self.repo, layer, commit.commitid, commit2)) for layer in layers}
        diffs = {key:value for (key,value) in diffs.items() if len(value) !=0}
        layers = [l for l in diffs.keys()]
        self.diffViewer.setChanges(diffs)

        self.canvas.setLayers([])
        self.removeMapLayers()
        extent = QgsRectangle()
        for layer in layers:
            if not diffs[layer]:
                continue
            beforeLayer, afterLayer = execute(lambda: self._getLayers(diffs[layer]))
            if afterLayer is not None:
                resourcesPath =  os.path.join(os.path.dirname(__file__), os.pardir, "resources")
                oldStylePath = os.path.join(resourcesPath, "{}_before.qml".format(
                                            QgsWkbTypes.geometryDisplayString(beforeLayer.geometryType())))
                newStylePath = os.path.join(resourcesPath, "{}_after.qml".format(
                                            QgsWkbTypes.geometryDisplayString(afterLayer.geometryType())))

                beforeLayer.loadNamedStyle(oldStylePath)
                afterLayer.loadNamedStyle(newStylePath)

                QgsProject.instance().addMapLayer(beforeLayer, False)
                QgsProject.instance().addMapLayer(afterLayer, False)

                extent.combineExtentWith(beforeLayer.extent())
                extent.combineExtentWith(afterLayer.extent())
                self.extraLayers.append(beforeLayer)
                self.extraLayers.append(afterLayer)
        # make extent a bit bit (10%) bigger
        # this gives some margin around the dataset (not cut-off at edges)
        if not extent.isEmpty():
            widthDelta = extent.width() * 0.05
            heightDelta = extent.height() * 0.05
            extent = QgsRectangle(extent.xMinimum() - widthDelta,
                                  extent.yMinimum() - heightDelta,
                                  extent.xMaximum() + widthDelta,
                                  extent.yMaximum() + heightDelta)

        layers = self.extraLayers
        hasChanges = False
        for layer in layers:
            if layer is not None and layer.featureCount() > 0:
                hasChanges = True
                break
        self.canvas.setLayers(layers)
        self.canvas.setExtent(extent)
        self.canvas.refresh()
                
        self.canvas.setVisible(hasChanges)
        self.labelNoChanges.setVisible(not hasChanges)

    def _getLayers(self, changes):
        ADDED, MODIFIED, REMOVED,  = 0, 1, 2
        def _feature(g, changeType):
            feat = QgsFeature()
            if g is not None:
                feat.setGeometry(g)
            feat.setAttributes([changeType])
            return feat
        if changes:
            f = changes[0]
            new = f["new"]            
            old = f["old"]
            reference = new or old
            geomtype = QgsWkbTypes.displayString(reference.geometry().wkbType())
            oldLayer = loadLayerNoCrsDialog(geomtype + "?crs=epsg:4326&field=geogig.changeType:integer", "old", "memory")
            newLayer = loadLayerNoCrsDialog(geomtype + "?crs=epsg:4326&field=geogig.changeType:integer", "new", "memory")
            oldFeatures = []
            newFeatures = []
            for f in changes:            
                new = f["new"]        
                old = f["old"]                  
                newGeom = new.geometry() if new is not None else None
                oldGeom = old.geometry() if old is not None else None
                if oldGeom is None:
                    feature = _feature(newGeom, ADDED)
                    newFeatures.append(feature)
                elif newGeom is None:
                    feature = _feature(oldGeom, REMOVED)
                    oldFeatures.append(feature)
                elif oldGeom.asWkt() != newGeom.asWkt():
                    feature = _feature(oldGeom, MODIFIED)
                    oldFeatures.append(feature)
                    feature = _feature(newGeom, MODIFIED)
                    newFeatures.append(feature)
                else:
                    feature = _feature(newGeom, MODIFIED)
                    newFeatures.append(feature)
            oldLayer.dataProvider().addFeatures(oldFeatures)
            newLayer.dataProvider().addFeatures(newFeatures)
        else:
            oldLayer = None
            newLayer = None

        return oldLayer, newLayer

    def removeMapLayers(self):
        for layer in self.extraLayers:
            if layer is not None:
                    QgsProject.instance().removeMapLayer(layer.id())
        self.extraLayers = []

class HistoryDiffViewerDialog(QDialog):

    def __init__(self, server, user, repo, graph, layer=None):
        super(HistoryDiffViewerDialog, self).__init__()
        self.resize(1024, 768)
        layout = QVBoxLayout()
        layout.setMargin(0)
        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.addWidget(self.bar)
        self.history = HistoryDiffViewerWidget(self, server, user, repo,graph, layer)
        layout.addWidget(self.history)
        self.setLayout(layout)
        self.setWindowTitle("History of " + user + ":" + repo)
        setCurrentWindow(self)

    def messageBar(self):
        return self.bar

    def closeEvent(self, evt):
        setCurrentWindow()
        self.history.removeMapLayers()
        evt.accept()
    