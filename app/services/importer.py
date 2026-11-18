import hashlib
import os
import re
import stat
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from app.database import Database
from app.parsers.pdf import DamagedFile, UnreadableFile, UnrecognizedPdf, parse_pdf
from app.parsers.reference import read_reference


SUPPORTED = {".pdf", ".xls", ".xlsx"}
MAX_FILE = 128 * 1024**2
MAX_ZIP_TOTAL = 1024**3
MAX_ZIP_ENTRIES = 20_000
MAX_ZIP_RATIO = 500
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
APP_DIRECTORIES = {".smartreport", ".deps", ".venv", "__pycache__", ".pytest_cache", ".git"}


@dataclass(frozen=True)
class Source:
    path: Path
    root: str
    relative: str
    folder: str
    parent: str
    kind: str
    member: str | None = None

    @property
    def directory_key(self):
        if self.member is None:
            return os.path.normcase(str(self.path.parent)), None
        return os.path.normcase(str(self.path)), self.folder

    @classmethod
    def local(cls, path: Path, root: Path, kind: str | None = None):
        rel = path.relative_to(root).as_posix()
        folder = path.parent.relative_to(root).as_posix() if rel != "." else "."
        return cls(path, str(root), rel, folder, path.parent.name, kind or path.suffix.lower()[1:])

    @classmethod
    def archived(cls, path: Path, member: str, kind: str):
        relative = PurePosixPath(member)
        return cls(path, str(path), relative.as_posix(), relative.parent.as_posix(),
                   relative.parent.name or path.stem, kind, member)


@dataclass
class Outcome:
    status: str
    message: str
    records: int = 0
    review: int = 0
    duplicate_of: int | None = None


def linked(stat_result) -> bool:
    return stat.S_ISLNK(stat_result.st_mode) or bool(
        getattr(stat_result, "st_file_attributes", 0) & REPARSE_POINT
    )


def archive_path(name: str) -> PurePosixPath:
    raw = name.replace("\\", "/")
    parts = raw.rstrip("/").split("/")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        raise DamagedFile("ZIP 含有不安全的成员路径")
    return PurePosixPath(*parts)


def inspect_archive(archive: ZipFile):
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_ENTRIES or sum(i.file_size for i in entries) > MAX_ZIP_TOTAL:
        raise DamagedFile("ZIP 解压体积或成员数超过上限")
    occurrences = set()
    for member in entries:
        path = archive_path(member.filename)
        if path.as_posix().casefold() in occurrences:
            raise DamagedFile("ZIP 含有重复成员路径")
        occurrences.add(path.as_posix().casefold())
        if stat.S_ISLNK(member.external_attr >> 16):
            raise DamagedFile("ZIP 含有符号链接")
        if member.file_size and member.file_size / max(member.compress_size, 1) > MAX_ZIP_RATIO:
            raise DamagedFile("ZIP 含有异常压缩比的成员")
    return entries


def read_limited(stream) -> tuple[bytes, str]:
    digest = hashlib.sha256()
    data = bytearray()
    while chunk := stream.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > MAX_FILE:
            raise UnreadableFile("文件超过 128 MiB 的解析上限")
        digest.update(chunk)
    return bytes(data), digest.hexdigest()


class ImportService:
    def __init__(self, database: Database, excluded_roots=()):
        self.db = database
        self.excluded_roots = tuple(Path(p).resolve() for p in excluded_roots)

    def run(self, paths, policy="skip", progress=None, on_file=None):
        if policy not in ("skip", "reimport"):
            raise ValueError("重复文件处理方式无效")
        progress = progress or (lambda *args: None)
        on_file = on_file or (lambda *args: None)
        inputs = list(dict.fromkeys(Path(os.path.abspath(p)) for p in paths))
        batch = self.db.start_batch([str(p) for p in inputs], policy)
        counts = Counter()
        sources = []
        last_update = 0.0

        def record(source, outcome, **kwargs):
            self.db.save_file(source, batch, outcome, policy, **kwargs)
            counts[outcome.status] += 1
            counts["records"] += outcome.records
            counts["review_records"] += outcome.review
            on_file(source, outcome)

        try:
            def skip_scan(source, status, message):
                record(source, Outcome(status, message))

            progress("扫描", 0, 0, "正在检查所选路径…")
            exports = {p.resolve() for p in self.db.previous_exports()}
            for source in self._scan(inputs, exports, skip_scan):
                sources.append(source)
                stamp = time.monotonic()
                if stamp - last_update >= .05:
                    progress("扫描", len(sources), 0, f"已发现 {len(sources)} 个支持的文件")
                    last_update = stamp
            progress("解析", 0, len(sources), f"扫描完成，共 {len(sources)} 个待处理文件")
            for position, source in enumerate(sources, 1):
                progress("解析", position-1, len(sources), source.relative)
                self._process(
                    source, policy, record,
                    lambda page, pages: progress(
                        "解析", position-1, len(sources), f"{source.relative} · 第 {page}/{pages} 页"
                    ),
                )
                progress("解析", position, len(sources), source.relative)
        except BaseException:
            self.db.finish_batch(batch, dict(counts), "failed")
            raise
        self.db.finish_batch(batch, dict(counts), "finished")
        return batch, dict(counts)

    def _excluded(self, path: Path, exports: set[Path]) -> bool:
        canonical = path.resolve()
        return (canonical in exports or any(part.casefold() in APP_DIRECTORIES for part in canonical.parts)
                or any(canonical.is_relative_to(root) for root in self.excluded_roots))

    def _scan(self, inputs, exports, report):
        visited = set()
        explicit_archives = {path for path in inputs if path.suffix.lower() == ".zip"}

        def priority(path):
            try:
                directory = stat.S_ISDIR(path.lstat().st_mode)
            except OSError:
                directory = False
            return (not directory, len(path.parts))

        for path in sorted(inputs, key=priority):
            source = Source.local(path, path.parent)
            try:
                info = path.lstat()
                if linked(info):
                    report(source, "excluded", "已跳过符号链接或目录联接")
                elif self._excluded(path, exports):
                    report(source, "excluded", "已跳过程序目录、缓存或已导出的文件")
                elif stat.S_ISDIR(info.st_mode):
                    yield from self._directory(path, exports, visited, explicit_archives, report)
                elif stat.S_ISREG(info.st_mode):
                    yield from self._entry(source, exports, visited, report, explicit=True)
                else:
                    report(source, "unsupported", "已跳过非普通文件")
            except OSError:
                report(source, "unreadable", "路径不存在或没有读取权限")

    def _directory(self, root, exports, visited, explicit_archives, report):
        def walk_error(exc):
            path = Path(exc.filename) if exc.filename else root
            report(Source.local(path, root, "directory"), "unreadable", "无法读取目录")

        for base, directories, filenames in os.walk(root, topdown=True, onerror=walk_error):
            directory = Path(base)
            allowed = []
            for name in sorted(directories, key=str.casefold):
                path = directory / name
                source = Source.local(path, root, "directory")
                try:
                    if linked(path.lstat()) or self._excluded(path, exports):
                        report(source, "excluded", "已排除目录（程序文件、缓存或联接）")
                    else:
                        allowed.append(name)
                except OSError:
                    report(source, "unreadable", "无法读取目录")
            directories[:] = allowed
            for name in sorted(filenames, key=str.casefold):
                path = directory / name
                if path in explicit_archives:
                    continue
                source = Source.local(path, root)
                yield from self._entry(source, exports, visited, report)

    def _entry(self, source, exports, visited, report, explicit=False):
        path = source.path
        try:
            info = path.lstat()
            if self._excluded(path, exports) or linked(info):
                report(source, "excluded", "已跳过程序输出、缓存或文件链接")
                return
            if not stat.S_ISREG(info.st_mode):
                report(source, "unsupported", "已跳过非普通文件")
                return
        except OSError:
            report(source, "unreadable", "文件不存在或无法访问")
            return
        if path in visited:
            return
        visited.add(path)
        suffix = path.suffix.lower()
        if suffix in SUPPORTED or explicit and suffix == ".zip":
            yield source
        else:
            report(source, "unsupported", "已跳过不支持的类型")

    def _process(self, source, policy, record, page_progress, archive=None, member=None):
        if source.kind == "zip" and archive is None:
            self._process_archive(source, policy, record, page_progress)
            return
        digest = None
        try:
            if member is not None and member.flag_bits & 1:
                raise UnreadableFile("ZIP 成员需要密码")
            with (source.path.open("rb") if archive is None else archive.open(member)) as stream:
                data, digest = read_limited(stream)
            if policy == "skip" and self.db.previous_file(digest) is not None:
                record(source, Outcome("duplicate", "内容相同，已跳过"), digest=digest)
                return
            if source.kind == "pdf":
                exams, warnings = parse_pdf(data, page_progress)
                record(source, Outcome("parsed", "；".join(warnings)), digest=digest, exams=exams)
            else:
                worksheets = read_reference(data, "." + source.kind)
                detail = f"已读取 {len(worksheets)} 张工作表，可用于后续对账"
                record(source, Outcome("reference", detail), digest=digest, reference=worksheets)
        except (DamagedFile, BadZipFile, EOFError) as exc:
            detail = str(exc) if isinstance(exc, DamagedFile) else "文件结构或校验失败"
            record(source, Outcome("damaged", detail), digest=digest)
        except UnrecognizedPdf as exc:
            record(source, Outcome("unrecognized", str(exc)), digest=digest)
        except UnreadableFile as exc:
            record(source, Outcome("unreadable", str(exc)), digest=digest)
        except (OSError, NotImplementedError):
            record(source, Outcome("unreadable", "文件没有读取权限或读取方式不受支持"), digest=digest)
        except (RuntimeError, ValueError, IndexError):
            record(source, Outcome("unrecognized", "解析此文件时出现错误，需人工核对"), digest=digest)

    def _process_archive(self, source, policy, record, page_progress):
        try:
            with ZipFile(source.path) as archive:
                entries = inspect_archive(archive)
                files = 0
                for member in entries:
                    if member.is_dir():
                        continue
                    internal = archive_path(member.filename)
                    suffix = internal.suffix.lower()
                    entry = Source.archived(source.path, member.filename, suffix[1:])
                    if set(p.casefold() for p in internal.parts[:-1]) & APP_DIRECTORIES:
                        record(entry, Outcome("excluded", "已排除 ZIP 内程序缓存目录"))
                    elif suffix not in SUPPORTED:
                        record(entry, Outcome("unsupported", "已跳过 ZIP 内不支持的类型"))
                    else:
                        files += 1
                        self._process(entry, policy, record, page_progress, archive, member)
                record(source, Outcome("archive", f"ZIP 已扫描，支持文件 {files} 个。请查看各成员结果"))
        except DamagedFile as exc:
            record(source, Outcome("damaged", str(exc)))
        except (BadZipFile, EOFError):
            record(source, Outcome("damaged", "ZIP 文件损坏或格式无效"))
        except OSError:
            record(source, Outcome("unreadable", "无法读取 ZIP 文件"))

