import time

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QTimer, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from app.database import Database
from app.ui.dialogs import ExportDialog
from app.ui.window import MainWindow


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application, tmp_path):
    state = tmp_path / ".smartreport"
    database = Database(state / "test.sqlite3")
    window = MainWindow(database, state)
    window.show()
    yield window
    window.close()
    application.processEvents()


def wait_import(application, page):
    until = time.monotonic() + 25
    while page.busy and time.monotonic() < until:
        application.processEvents()
        time.sleep(.005)
    assert not page.busy


def test_primary_folder_action_and_background_progress(application, window, tmp_path, monkeypatch):
    root = tmp_path / "批次"
    root.mkdir()
    (root / "说明.dat").write_bytes(b"skipped")
    (root / "损坏.pdf").write_bytes(b"damaged")
    seen = []

    def fake_picker(parent, title, initial_dir):
        seen.append(title)
        return str(root)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_picker)
    original = window.import_page.service.run

    def delayed_run(*args):
        time.sleep(.12)
        return original(*args)

    monkeypatch.setattr(window.import_page.service, "run", delayed_run)
    ticks = []
    page = window.import_page
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(10)
    try:
        assert window.pages.currentWidget() is page
        page.folder_button.click()
        assert page.busy and not page.folder_button.isEnabled()
        wait_import(application, page)
    finally:
        timer.stop()
    assert seen == ["选择成绩文件夹"]
    assert ticks
    assert page.metrics["unsupported"].text() == "1"
    assert page.metrics["damaged"].text() == "1"
    assert page.folder_button.isEnabled()


def test_drag_drop_handles_folder_and_file(application, window, tmp_path):
    root = tmp_path / "拖入文件夹"
    root.mkdir()
    (root / "说明.dat").write_bytes(b"skipped")
    drop_file = tmp_path / "坏文件.pdf"
    drop_file.write_bytes(b"damaged")
    urls = QMimeData()
    urls.setUrls([QUrl.fromLocalFile(str(root)), QUrl.fromLocalFile(str(drop_file))])
    args = (Qt.DropAction.CopyAction, urls, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    enter = QDragEnterEvent(QPoint(3, 3), *args)
    drop = QDropEvent(QPointF(3, 3), *args)
    page = window.import_page
    page.dragEnterEvent(enter)
    assert enter.isAccepted()
    page.dropEvent(drop)
    assert drop.isAccepted()
    wait_import(application, page)
    assert page.metrics["unsupported"].text() == "1"
    assert page.metrics["damaged"].text() == "1"


def test_group_select_query_and_export_current_rows(application, window, tmp_path, monkeypatch, samples):
    from openpyxl import load_workbook

    root = tmp_path / "父目录"
    for branch, sample in (("东区", samples[0]), ("西区", samples[1])):
        leaf = root / branch / "同名"
        leaf.mkdir(parents=True)
        (leaf / "成绩.pdf").write_bytes(sample.read_bytes())
    window.import_page.start([root])
    wait_import(application, window.import_page)
    window.navigation.button(1).click()
    grades = window.grades
    assert grades.model.rowCount() == 2
    first = grades.tree.topLevelItem(0).child(0).child(0)
    assert first.text(0).startswith("东区")
    grades.tree.setCurrentItem(first)
    assert grades.model.rowCount() == 1
    assert grades.model.rows[0]["folder"] == "东区/同名"
    grades.search.setText("西区")
    grades.apply_filters()
    assert grades.model.rowCount() == 0
    grades.search.clear()
    grades.apply_filters()
    target = tmp_path / "当前筛选.xlsx"
    monkeypatch.setattr(ExportDialog, "exec", lambda _: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ExportDialog, "target", lambda *_: target)
    monkeypatch.setattr(QMessageBox, "exec", lambda _: 0)
    grades.export()
    book = load_workbook(target, read_only=True)
    try:
        assert book.active.max_row == 2
    finally:
        book.close()

