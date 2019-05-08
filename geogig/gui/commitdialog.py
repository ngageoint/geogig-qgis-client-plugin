import os
from qgis.PyQt import uic

pluginPath = os.path.dirname(os.path.dirname(__file__))
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'commitdialog.ui'))

class CommitDialog(BASE, WIDGET):

    # None - don't do anything (normal)
    # CommitDialog.TEST_CASE_OVERRIDE = {"radioEditBuffer":False, "msg":"..."}
    # CommitDialog.TEST_CASE_OVERRIDE = {"radioEditBuffer":True, "msg":None }

    TEST_CASE_OVERRIDE = None


    def __init__(self, parent=None):
        super(CommitDialog, self).__init__(parent)
        self.setupUi(self)
        self.message = None
        self.radioCommit.setChecked(True)
        self.radioCommit.toggled.connect(self.toggled)
        self.radioEditBuffer.toggled.connect(self.toggled)
        if CommitDialog.TEST_CASE_OVERRIDE is not None:
            self.radioEditBuffer.setChecked(CommitDialog.TEST_CASE_OVERRIDE["radioEditBuffer"])
            if CommitDialog.TEST_CASE_OVERRIDE["msg"] is not None:
                self.txtMessage.setText(CommitDialog.TEST_CASE_OVERRIDE["msg"])
            else:
                self.message = None
            self.accept()

    def exec_(self):
        if CommitDialog.TEST_CASE_OVERRIDE is None:
            super(CommitDialog, self).exec_()

    def toggled(self):
        commit = self.radioCommit.isChecked()
        self.txtMessage.setEnabled(commit)
        self.label.setEnabled(commit)

    def accept(self):
        if self.radioCommit.isChecked():
            self.message = self.txtMessage.text()
        else:
            self.message = None
        self.close()



