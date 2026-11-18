import argparse
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from app.database import Database
from app.ui.window import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(prog="SmartReport")
    parser.add_argument("--data-dir", type=Path, default=Path(
        os.environ.get("LOCALAPPDATA", Path.home())
    ) / ".smartreport")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    application = QApplication([sys.argv[0]])
    application.setApplicationName("SmartReport")
    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 10))
    try:
        state = args.data_dir.resolve()
        database = Database(state / "smartreport.sqlite3")
        window = MainWindow(database, state)
    except Exception as exc:
        logging.error("SmartReport 启动失败 (%s)", type(exc).__name__)
        QMessageBox.critical(None, "SmartReport 无法启动", "请检查应用数据目录的读取和写入权限。")
        return 1
    window.show()
    if args.smoke_test:
        QTimer.singleShot(250, application.quit)
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())

