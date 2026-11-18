import logging

from PySide6.QtCore import QThread, Signal


class ImportWorker(QThread):
    progress = Signal(str, int, int, str)
    file_result = Signal(object, object)
    completed = Signal(int, object)
    failed = Signal(str)

    def __init__(self, service, paths, policy, parent=None):
        super().__init__(parent)
        self.service = service
        self.paths = paths
        self.policy = policy

    def run(self):
        try:
            batch, counts = self.service.run(
                self.paths, self.policy, self.progress.emit, self.file_result.emit,
            )
        except Exception as exc:
            # Parser and filesystem exceptions may include names or paths.
            logging.error("导入任务失败 (%s)", type(exc).__name__)
            self.failed.emit("导入中断。已处理的文件已保存在批次历史中。")
        else:
            self.completed.emit(batch, counts)

