from io import BytesIO
from zipfile import ZipFile

import openpyxl
import xlrd

from app.parsers.pdf import DamagedFile, UnreadableFile


def read_reference(data: bytes, suffix: str) -> list[dict]:
    try:
        if suffix == ".xls":
            book = xlrd.open_workbook(file_contents=data, on_demand=True)
            try:
                return [
                    {"name": s.name, "rows": [s.row_values(i) for i in range(s.nrows)]}
                    for s in book.sheets()
                ]
            finally:
                book.release_resources()

        with ZipFile(BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 256 * 1024**2:
                raise UnreadableFile("参考表的解压体积超过 256 MiB")
            if any(item.flag_bits & 1 for item in archive.infolist()):
                raise UnreadableFile("参考表需要打开密码")
        book = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
        try:
            return [
                {"name": s.title, "rows": list(s.iter_rows(values_only=True))}
                for s in book.worksheets
            ]
        finally:
            book.close()
    except xlrd.XLRDError as exc:
        if "encrypted" in str(exc).lower():
            raise UnreadableFile("参考表需要打开密码") from exc
        raise DamagedFile("无法识别 XLS 参考表结构") from exc
    except (MemoryError, OSError, UnreadableFile):
        raise
    except Exception as exc:
        raise DamagedFile("参考表文件损坏、加密或表格格式无法识别") from exc

