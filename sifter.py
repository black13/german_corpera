#sifter
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem
from PyQt5.QtWidgets import (QApplication, QComboBox, QDialog,
QDialogButtonBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
QLabel, QLineEdit, QMenu, QMenuBar, QPushButton, QSpinBox, QTextEdit,
QVBoxLayout)
import sys

class List(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setDragDropMode(self.DragDrop)
        self.setSelectionMode(self.ExtendedSelection)
        self.setAcceptDrops(True)

    def dropEvent(self, event):        
        if event.source() == self:
            event.setDropAction(QtCore.Qt.MoveAction)
            QtWidgets.QListWidget.dropEvent(self, event)
        elif isinstance(event.source(), QtWidgets.QListWidget):
            source_widget = event.source()
            #item = self.itemAt(event.pos())
            #row = self.row(item) if item else self.count()
            #print(source_widget)
           
            selected_items = source_widget.selectedItems()
            #print([x.text() for x in selected_items])
            for i, data_item in enumerate(selected_items):
                it = QtWidgets.QListWidgetItem()
                it.setText(data_item.text())
                self.addItem ( it)
                source_widget.removeItemWidget (data_item)
            
            #remove drag items
            for item in selected_items:
                r = source_widget.row(item)
                source_widget.takeItem(r)
    '''            
    def mousePressEvent(self, QMouseEvent):
        if QMouseEvent.button() == Qt.LeftButton:
            print("Left Button Clicked")
        elif QMouseEvent.button() == Qt.RightButton:
            #do what you want here
            print("Right Button Clicked")
    
    def mouseDoubleClickEvent(self, event):
        source_widget = event.source()
        selected_items = source_widget.selectedItems()
        for item in selected_items:
            r = source_widget.row(item)
            source_widget.takeItem(r)
    '''
class App(QDialog):

    def __init__(self):
        super().__init__()
        self.title = 'PyQt5 layout - pythonspot.com'

        self.left = 10
        self.top = 10
        self.width = 320
        self.height = 700
        self.initUI()

    def eventFilter(self, source, event):
        if (event.type() == QtCore.QEvent.ContextMenu and
            source is self.left):
            menu = QtWidgets.QMenu()
            menu.addAction('Delete')
            if menu.exec_(event.globalPos()):
                selected_items = self.left.selectedItems()
                for item in selected_items:
                    r = self.left.row(item)
                    self.left.takeItem(r)
            return True
        return super(QDialog, self).eventFilter(source, event)

    def initUI(self):
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)
        
        self.createGridLayout()
        
        windowLayout = QVBoxLayout()
        windowLayout.addWidget(self.horizontalGroupBox)
        self.setLayout(windowLayout)
        self._add_items_to_listWidget()
        self.show()
    
    def createGridLayout(self):
        self.horizontalGroupBox = QGroupBox("Grid")
        layout = QGridLayout()
       
        self.left = List()
        self.right = List()
        layout.addWidget(self.left,1,0)
        layout.addWidget(self.right,1,1)
        self.left.installEventFilter(self)
        self.horizontalGroupBox.setLayout(layout)

    def _add_items_to_listWidget(self):
        f = open("german_sentences.txt","r",encoding="utf-8")
        t = f.read()
        l = t.split("\n")
        for i in l:
            item=QtWidgets.QListWidgetItem()
            item.setText(i)                        
            self.left.addItem(item) 

def main():
    app = QApplication(sys.argv)
    ex = App()
    sys.exit(app.exec_())
if __name__ == "__main__":
    main()