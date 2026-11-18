# SmartReport 智表助手

SmartReport 是面向考务成绩归集的 Windows 离线桌面应用。第一阶段以“文件导入 → PDF 识别 → 人工核验 → 报表导出”为主线，在本机保存来源、成绩、小分和修改记录。

当前版本：`0.1.0`。适配特定的操作技能考核评分记录表、手信号识别考试报告；不保证任意 PDF 版式都能识别。程序不调用云端 OCR 或 AI 服务。

## 已实现功能

- **批量导入**：选择上级文件夹递归扫描 PDF、XLS、XLSX；支持多选文件、拖放文件或目录，以及显式选择 ZIP 的兼容入口。
- **进度与结果**：后台导入，显示扫描、文件和页进度，区分成功、待复核、损坏、无法读取、未识别、重复、类型跳过和排除等结果。
- **去重与来源**：按 SHA-256 跳过相同内容；支持重新导入独立版本，并标记待复核。保留批次、导入根、相对目录、文件及页码。
- **成绩查询**：按来源文件夹分组，父目录可查询子目录；叠加批次、日期、单位、工种、科目、核验状态和关键词筛选。
- **人工核验**：查看成绩、小分、原始字段、来源页、关联参考表及问题；核准或更正得分，并保存原值、原因和修改记录。
- **参考表**：XLS/XLSX 按工作表保存，依据来源目录关联资料。参考表尚不参与自动对账或成绩计算。
- **报表导出**：选择当前筛选或全部记录、自选字段和模板；核对稿用于检查，正式报表只输出已核准记录。

## 技术栈

| 层次 | 实现 |
| --- | --- |
| 运行环境 | Python 3.12+，主要验证环境为 Windows / Python 3.12 |
| 桌面界面 | PySide6 Essentials / Qt Widgets |
| PDF 解析 | PyMuPDF 原生文字提取和坐标表格解析 |
| 表格读写 | openpyxl、xlrd；pandas 列于运行依赖中，当前核心读写路径未使用 |
| 本地存储 | SQLite，启用外键与 WAL；分值核验使用 Decimal |
| 测试与分发 | pytest、PyInstaller 目录版 |

依赖范围见 `requirements.txt`，开发与打包依赖见 `requirements-dev.txt`。

## 系统架构

```text
Qt 界面 app/ui
  ├─ 文件导入页 → controllers.py / QThread → services/importer.py
  │                                        ├─ parsers/pdf.py
  │                                        ├─ parsers/reference.py
  │                                        └─ validators.py → database.py
  └─ 成绩管理页 → 查询 / 人工核准 → exporters.py → XLSX / CSV / TXT
```

每个文件单独写入事务。一个文件解析失败后继续处理其他文件。程序保留来源与核验问题，便于回到原件复核。更多信息见 [架构说明](docs/ARCHITECTURE.md) 和 [数据库设计](docs/DATABASE_DESIGN.md)。

## 安装与运行

安装 Python 3.12+ 和 Git，在 Windows PowerShell 中执行：

```powershell
git clone https://github.com/lqy-de/SmartReport.git
cd SmartReport
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.bat
```

也可从 Gitee 克隆：`git clone https://gitee.com/takeyourhand/smart-report.git`，然后进入克隆后的 `smart-report` 目录，执行相同的安装步骤。

`start.bat` 优先使用 `.venv`，兼容本机 `.deps` 依赖目录，最后使用 PATH 中的 Python。在源码环境也可直接执行：

```powershell
.\.venv\Scripts\python.exe -m app.main
```

默认数据目录为 `%LOCALAPPDATA%\.smartreport`，SQLite 文件为 `smartreport.sqlite3`，默认导出目录为其中的 `exports`。可指定独立数据目录：

```powershell
.\.venv\Scripts\python.exe -m app.main --data-dir .\.smartreport\demo-state
```

### 模拟样本与测试

```powershell
.\.venv\Scripts\python.exe samples\generate_samples.py
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

在界面选择 `samples/generated`，即可体验两份操作技能表和一份独立手信号报告。全部数据为程序虚构；独立手信号报告因缺少准考证号进入待复核。测试自动生成 PDF、临时参考工作簿和 ZIP，无需真实成绩单。详见 [模拟样本说明](samples/README.md) 和 [测试说明](docs/TEST_REPORT.md)。

### Windows 打包

安装开发依赖后执行 `build.bat`。产物位于 `.smartreport\dist\SmartReport`；分发整个目录，保留 `SmartReport.exe` 与同目录的 `_internal`。打包产物不提交 Git。

## 软件界面

项目目前包含“文件导入”和“成绩管理”两个页面，导出入口位于成绩管理。仓库暂未附带可安全公开的界面截图；后续可在仅导入模拟数据的独立数据目录中补充截图。

## PDF 成绩识别流程

1. 扫描支持的文件并排除程序数据、缓存、目录联接、符号链接和已登记的导出文件。
2. 计算 SHA-256，按批次策略跳过相同文件或保留重新导入的版本。
3. 以原生文字和标题识别操作技能表、手信号报告，处理同一 PDF 内的多场考试与续页。
4. 解析表头、总分、小分、配分、扣分与页码。手信号报告仅在同 PDF 内身份一致且姓名、日期匹配时继承相关身份字段。
5. 校验字段、分值范围、小分合计与打印总分差异，以及文件修改提示；不确定内容进入待复核。
6. 在 SQLite 保存来源、原始字段、明细和问题，由用户核准后导出正式报表。

扫描件、无文字层 PDF、新版式和密码保护文件可能无法识别。当前没有 OCR。规则详见 [版式说明](docs/SAMPLE_ANALYSIS.md)。

## 支持的导出格式

| 格式 | 内容 |
| --- | --- |
| XLSX | 成绩总表 / 小分明细；标题样式、筛选、冻结首行和百分比格式 |
| CSV | UTF-8 BOM，逗号分隔 |
| TXT | UTF-8 BOM，制表符分隔 |

两种模板均可选择字段。XLSX 文本按字符串保存，CSV/TXT 对可能成为公式的文本添加前缀。当前不提供 PDF、DOCX、旧版 XLS 或自定义模板管理导出。

## 使用注意事项与数据保护

- “已识别”表示通过当前规则，仍应核对原件。正式报表只包含已人工核准记录；核准得分与原值和修改原因分别留存。
- 界面成绩表和导出使用脱敏准考证号，但姓名、单位、路径等仍可能识别个人。SQLite、原始字段、参考表及来源文件含原始信息，不能视为匿名数据。
- 原件、数据库和导出应保留在授权的本地目录，妥善备份与控制访问。不要放入公开仓库，也不要提交带真实数据的截图。
- 文件夹扫描不会自动展开其中的 ZIP；需通过兼容入口选择或直接拖入 ZIP。ZIP 有成员路径、压缩比、体积等检查，单文件解析上限为 128 MiB。
- `.gitignore` 排除环境密钥、虚拟环境、缓存、日志、数据库、打包目录，以及所有 PDF、Excel、CSV/TSV、ZIP 等潜在敏感数据。`samples` 仅允许说明与生成器进入版本控制。
- `.gitignore` 不会清除已跟踪文件或 Git 历史。每次提交前复查暂存内容，禁止用 `git add -f` 绕过数据保护。发现历史中包含秘密或个人数据时，先停止推送并处理风险。
- 测试中用于验证加密 PDF 的固定密码仅用于临时合成文件，不是账号凭据。

## 双平台代码同步

两个独立远程仓库使用以下名称：

| remote | 仓库 |
| --- | --- |
| `github` | [GitHub / lqy-de/SmartReport](https://github.com/lqy-de/SmartReport) |
| `gitee` | [Gitee / takeyourhand/smart-report](https://gitee.com/takeyourhand/smart-report) |

新克隆目录通常只有 `origin`。先执行 `git remote -v`，只在相应名称不存在时添加；保留已有 `origin` 或其他地址，不覆盖它们：

```powershell
git remote add github https://github.com/lqy-de/SmartReport.git
git remote add gitee https://gitee.com/takeyourhand/smart-report.git
```

日常更新时先自行检查、选择文件并提交，再运行脚本：

```powershell
git status
git diff
# 按本次改动逐项添加文件，例如：
git add README.md
git diff --cached
git commit -m "docs: update SmartReport usage"
.\sync_repos.bat
```

也可在 Windows CMD 中进入项目目录运行 `sync_repos.bat`。脚本不执行 `git add` 或 `git commit`。存在未提交或未跟踪且未忽略的文件时会提示并停止；忽略文件不阻止同步。脚本推送当前已提交分支，按 GitHub、Gitee 顺序执行普通推送，并分别读取远程分支核对 Commit ID。任一推送或核验失败都会返回非零退出码，不会报告双平台成功，也不会回滚另一平台已经成功的推送。修复后重跑即可。

请通过平台登录或本机 Git 凭据管理器完成认证，勿将密码、Token 写入远程 URL、脚本或 README。若出现 non-fast-forward，先 fetch 并检查远程历史，完成必要的合并和测试后重试；不要强制推送。两边应使用同一分支和本地提交链，避免直接在两个平台分别编辑造成分叉。

仓库可见性遵循维护者在平台上的设置；本次配置已由维护者明确选择允许公开。提交安全检查仍适用于私人仓库。

## 后续开发计划（尚未实现）

- OCR 与扫描件识别，以及更多 PDF 版式适配。
- 参考工作簿自动对账与专门的对账工作区。
- 工作台统计、成绩分析与科目配置。
- 自定义模板管理与更多导出格式。
- 使用模拟数据补充界面截图和更全面的跨页、复杂版式回归样本。
