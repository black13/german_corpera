#sifter
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem
from PyQt5.QtWidgets import (QApplication, QComboBox, QDialog,
QDialogButtonBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
QLabel, QLineEdit, QMenu, QMenuBar, QPushButton, QSpinBox, QTextEdit,
QVBoxLayout)
import sys
import itertools
import re

class List(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dropped = QtCore.pyqtSignal(list)
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

class App(QDialog):

    def __init__(self):
        super().__init__()
        self.title = 'PyQt5 layout - pythonspot.com'
        
        self.weights={}
        self.left = 10
        self.top = 10
        self.width = 320
        self.height = 700
        self.initUI()

    def eventFilter(self, source, event):
        if (event.type() == QtCore.QEvent.ContextMenu and
            source is self.LeftListBox):
            menu = QtWidgets.QMenu()
            menu.addAction('Delete')
            if menu.exec_(event.globalPos()):
                selected_items = self.LeftListBox.selectedItems()
                for item in selected_items:
                    r = self.LeftListBox.row(item)
                    self.LeftListBox.takeItem(r)
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
       
        self.LeftListBox = List()
        self.RightListBox = List()
        layout.addWidget(self.LeftListBox,1,0)
        layout.addWidget(self.RightListBox,1,1)
        self.LeftListBox.installEventFilter(self)
        self.horizontalGroupBox.setLayout(layout)
        self.RightListBox.dropped.connect(self.handleDropped)
        
    def handleDropped(self):
        print('dropped:')

    def _add_items_to_listWidget(self):
        f = open("german_sentences.txt","r",encoding="utf-8")
        t = f.read()
        l = t.split("\n")
        for i in l:
            item=QtWidgets.QListWidgetItem()
            item.setText(i)                        
            self.LeftListBox.addItem(item) 
        #compute weights
        words=list(itertools.chain(*[x.split(" ") for x in t.split('\n')]))
        words=list(set([x for x in [re.sub(r'^[.,(0-9]+','',re.sub(r'[.,?():]+$','',x)) for x in words] if len(x) > 0]))
        self.weights = { i : 0 for i in words}
    
    @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def on_itemClicked(self, item):
        if item.text() == "Select all":
            for row in range(1, self.list_widget.count()):
                it = self.LeftListBox.item(row)
                it.setCheckState(QtCore.Qt.Checked)

    @QtCore.pyqtSlot()
    def on_clicked(self):
        selected_items = self.LeftListBox.selectedItems()
        for item in selected_items:
            print(item.text())
            text=item.text()
            words=list(itertools.chain(*[x.split(" ") for x in text.split('\n')]))
            words=list(set([x for x in [re.sub(r'^[.,(0-9]+','',re.sub(r'[.,?():]+$','',x)) for x in words] if len(x) > 0]))
            for word in words:
                if word in self.weights:
                   self.weights[word] = self.weights[word] + 1

        for item in  self.visibleItems():
            print(item.text())

    @QtCore.pyqtSlot()
    def on_dropped(self,event):
        pass

    def visibleItems(self):
        rect = self.LeftListBox.viewport().contentsRect()
        top = self.LeftListBox.indexAt(rect.topLeft())
        if top.isValid():
            bottom = self.LeftListBox.indexAt(rect.bottomLeft())
        if not bottom.isValid():
            bottom = self.LeftListBox.model().index(self.LeftListBox.count() - 1)
        for index in range(top.row(), bottom.row() + 1):
            yield self.LeftListBox.item(index)    
        '''
        for row in range(1, self.LeftListBox.count()):
            it = self.LeftListBox.item(row)
            if it.checkState() == QtCore.Qt.Checked:
                print(it.text())
        '''
def main():
    app = QApplication(sys.argv)
    ex = App()
    sys.exit(app.exec_())
if __name__ == "__main__":
    main()