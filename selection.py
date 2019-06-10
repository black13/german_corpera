from PyQt5 import QtCore, QtGui, QtWidgets
import qdarkstyle


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super(MainWindow,self).__init__(parent)

        self.main_frame()
        self.center() #center frame
        self.layout_init() #widgets layout

    def main_frame(self):
        ### actions on meenubar
        exitAct = QtWidgets.QAction(QtGui.QIcon('exit.png'), '&Exit', self)
        exitAct.setShortcut('Ctrl+Q')
        exitAct.setStatusTip('Exit application')
        exitAct.triggered.connect(self.close)
        self.statusBar()

        ### menubar
        menubar = self.menuBar()
        fileMenu = menubar.addMenu('&File')
        fileMenu.addAction(exitAct)
        fileMenu = menubar.addMenu('&VIew')
        fileMenu = menubar.addMenu('&Help')

        ### basic geometry and color
        self.setWindowTitle('DIGITAL CARE - Data Processing - WAREX Checklist')
        self.setStyleSheet((qdarkstyle.load_stylesheet_pyqt5()))

    def layout_init(self):
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        ### widgets
        pb = QtWidgets.QPushButton(self.tr("Run process"))
        pb.clicked.connect(self.on_clicked)
        ### List withc checkboxes
        checklist = ["Pliki z Errorami","Fatal w Komponentach","Play - automat do Aktywacji","Play - maile przy Dezaktywacji",\
                     "Play - komunikaty Dezaktywacyjne","Automat do przedłużania polis",\
                     "X-KOM - ilość polis","Neonet - ilość polis","Satysfakcja - ilość polis","PLK - zaczytanie plików do bazy"]

        ## Select all/unselect all
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.itemClicked.connect(self.on_itemClicked)
        selectall = QtWidgets.QListWidgetItem("Select all")
        self.list_widget.addItem(selectall)

        for i in checklist:
            item = QtWidgets.QListWidgetItem(i)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            self.list_widget.addItem(item)

        grid = QtWidgets.QGridLayout(central_widget)
        grid.addWidget(pb)
        grid.addWidget(self.list_widget)

    @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def on_itemClicked(self, item):
        if item.text() == "Select all":
            for row in range(1, self.list_widget.count()):
                it = self.list_widget.item(row)
                it.setCheckState(QtCore.Qt.Checked)

    @QtCore.pyqtSlot()
    def on_clicked(self):
        for row in range(1, self.list_widget.count()):
            it = self.list_widget.item(row)
            if it.checkState() == QtCore.Qt.Checked:
                print(it.text())

    def center(self):
        qr = self.frameGeometry()
        cp = QtWidgets.QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

if __name__ == '__main__':
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())