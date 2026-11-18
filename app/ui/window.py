from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from app.services.importer import ImportService
from app.ui.grades import GradesPage
from app.ui.import_page import ImportPage
from app.ui.style import stylesheet


class MainWindow(QMainWindow):
    def __init__(self, database, state):
        super().__init__()
        self.settings = QSettings("SmartReport", "SmartReport")
        self.dark = self.settings.value("dark", False, bool)
        self.close_when_finished = False
        self.setWindowTitle("SmartReport · 智表助手")
        self.resize(1250, 790)
        self.setMinimumSize(1030, 640)
        base = QWidget()
        base.setObjectName("workspace")
        self.setCentralWidget(base)
        layout = QHBoxLayout(base)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        nav = QWidget()
        nav.setObjectName("rail")
        nav.setFixedWidth(177)
        sidebar = QVBoxLayout(nav)
        sidebar.setContentsMargins(14, 25, 14, 18)
        sidebar.setSpacing(9)
        product = QLabel("SmartReport")
        product.setObjectName("product")
        sidebar.addWidget(product)
        name = QLabel("智表助手")
        name.setObjectName("productZh")
        sidebar.addWidget(name)
        sidebar.addSpacing(19)
        self.pages = QStackedWidget()
        self.import_page = ImportPage(database, ImportService(database, excluded_roots=(state,)))
        output = state / "exports"
        output.mkdir(parents=True, exist_ok=True)
        self.grades = GradesPage(database, output)
        self.import_page.imported.connect(self.on_imported)
        self.navigation = QButtonGroup(self)
        for title, page in (("文件导入", self.import_page), ("成绩管理", self.grades)):
            index = self.pages.addWidget(page)
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            sidebar.addWidget(button)
        self.navigation.idClicked.connect(self.pages.setCurrentIndex)
        self.navigation.button(0).setChecked(True)
        sidebar.addStretch()
        self.theme = QPushButton()
        self.theme.setObjectName("nav")
        self.theme.clicked.connect(self.toggle_theme)
        sidebar.addWidget(self.theme)
        layout.addWidget(nav)
        layout.addWidget(self.pages, 1)
        self.statusBar().showMessage("成绩数据保存在本机")
        self.update_theme()
        self.grades.reload()
        self.import_page.folder_button.setFocus()

    def update_theme(self):
        self.setStyleSheet(stylesheet(self.dark))
        self.theme.setText("切换浅色" if self.dark else "切换深色")

    def toggle_theme(self):
        self.dark = not self.dark
        self.settings.setValue("dark", self.dark)
        self.update_theme()

    def on_imported(self):
        if self.close_when_finished:
            QTimer.singleShot(0, self.close)
        else:
            self.grades.reload()

    def closeEvent(self, event):
        if self.import_page.busy:
            event.ignore()
            self.close_when_finished = True
            self.statusBar().showMessage("当前导入结束后关闭窗口")
        else:
            super().closeEvent(event)

