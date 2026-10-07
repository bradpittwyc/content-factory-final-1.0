# Content Factory 1.0

面向 Tony English 的本地内容采集与英语学习素材加工工具。通过浏览器控制台管理 TikTok / YouTube 视频、外刊文章、双语跟读教案和绕口令，并将部分学习素材同步到腾讯云 COS。

## 功能

| 模块 | 功能 |
| --- | --- |
| TikTok | 扫描博主作品、批量下载、保存封面 / 字幕 / 元数据，支持代理与 Cookie |
| YouTube | 扫描频道、批量下载、选择画质、导出音频，提供字幕与学习文档功能 |
| 频道管理 | 保存跨平台博主、分类和下载记录 |
| 外刊内容工厂 | FT、The Economist、BNN Bloomberg 文章采集、阅读与管理；经济学人支持批量链接及粘贴正文导入 |
| 跟读教案 | 解析视频字幕，调用 DeepSeek 校对英文及翻译中文，上传视频、封面和课程 JSON |
| 绕口令 | 生成分级练习、配图及 Edge TTS 多语速音频 |

Bloomberg 模块目前采集 **BNN Bloomberg 网站的公开文章**，内容可能来自 Bloomberg、Reuters 或其他作者。它不直接采集 Bloomberg.com 的订阅全文。

**Bloomberg 主站已完成十篇批量试抓，全文结构仍在核验。** 2026-10-04 对 `www.bloomberg.com` 的独立检查取得最新站点地图的 170 个链接；三篇新闻的直接 HTTP 访问及其中一篇的新建 Chrome 会话访问均返回 403。随后通过用户已登录浏览器中的扩展取得一篇主站文章，过滤两段关联阅读后留下 14 段、547 词，作者与发布日期均保存。正文未见明显截断，但尚未逐段对照页面确认全文完整性。BNN 的试抓结果不能作为主站批量采集成功的证据。[主站检查报告](data/bloomberg_main_probe/report.json)与[候选链接](data/bloomberg_main_probe/candidates.json)单独保存。

十篇批量试抓实际保存了 10 个不同的主站文章链接，共 5,468 词，首末保存时间相差约 95 秒；作者和发布日期均完整，当前连同首篇共 11 篇。检查发现初版仅提取段落，漏掉列表，并可能遗漏短段落。扩展 v1.1 已加入列表、小标题与短段落提取，需在 Chrome 扩展页重新加载后复抓这十篇；队列会优先更新旧版采集结果。[首轮十篇报告](data/bloomberg_main_probe/batch_10_report.json)。

### Bloomberg 主站：使用已登录浏览器验证

为使用用户现有订阅会话，新增独立的 `bloomberg_main_extension/` 扩展与 `bloomberg_main_bridge.py` 本地接收服务。扩展直接读取当前页面的正文，不导出 Cookie；首次使用需要手动加载扩展并核验真实正文。

1. 执行 `python bloomberg_main_bridge.py`，启动 `127.0.0.1:8011` 接收服务。
2. 在已登录 Bloomberg 的 Chrome 中打开 `chrome://extensions`，开启开发者模式，选择“加载已解压的扩展程序”，选中本仓库的 `bloomberg_main_extension` 文件夹。
3. 打开一篇可以阅读全文的 Bloomberg.com 文章，点击扩展的“采集当前文章”。
4. 检查 `data/bloomberg_main_articles.json` 与浏览器中的正文是否一致；单篇完整性确认后，使用扩展的“试抓队列前 10 篇”。

正文候选与诊断记录分别保存到 `data/bloomberg_main_articles.json` 和 `data/bloomberg_main_inbox/`。这些数据独立于 BNN 的文章库，并合并显示在 Bloomberg Studio。正文保留有序内容块（段落、列表项、小标题和独立引用）；至少四段、150 词的 DOM 正文仅标记为 `body_candidate`，不能单凭长度宣称全文完整；需要检查首篇。机器人验证或订阅提示会暂停采集，无法识别的正文会跳过并保存诊断记录。

主站接收与来源校验的离线测试：`python -m unittest test_bloomberg_main_bridge -v`。

### 指定 Tech 栏目采集

扩展 v1.2 增加“试抓 Tech 前 10 篇”按钮，入口固定为 `https://www.bloomberg.com/technology`。在 `chrome://extensions` 重新加载本仓库的扩展后，点击该按钮即可：

1. 在已登录的浏览器中打开 Tech 页面，提取内容区域内的主站文章链接，排除导航、页脚、视频及外部网站链接。
2. 将栏目候选队列保存到 `data/bloomberg_main_columns/tech.json`，按 URL 去重，跳过已用新版正文提取器保存的文章。
3. 按页面链接顺序试抓最多 10 篇，保存 `columns: ["tech"]` 和栏目入口信息。页面出现的 Opinion 文章与文字 Newsletter 链接也可以进入队列；正文仍需通过结构检查。

此模式抓取当前栏目页已加载的文章链接，尚未实现栏目历史分页或无限滚动。Tech 是频道范围，包含其页面展示的不同文章系列。遇到机器人验证或正文无法识别会暂停；真实 Tech 链接发现和正文采集结果需通过已登录浏览器确认，离线测试通过不代表该栏目已经完成实测。

扩展 v1.2.1 会校验后台采集器版本。弹窗应显示“扩展 v1.2.1 · 后台已连接”；若仍显示旧版批量结束状态，须在扩展管理页点击重新加载。2026-10-05 首次 Tech 操作后，服务端未收到栏目发现记录，库存仍为 11 篇且最近记录来自旧版提取器，因此该次操作没有验证 Tech 采集成功。

随后 Tech 栏目发现成功，保存 36 个候选链接和 8 篇正文候选；一篇长文因正文容器无法识别而暂停。质量检查发现一篇文章的正文与不同标题的 SoftBank 文章完全重复，已隔离到 `data/bloomberg_main_quarantine/` 并安排复抓。扩展 v1.2.2 优先选取当前文章的第一个正文容器，逐篇新建标签页，过滤链接型推荐标题；服务端拒绝不同 URL 下完全相同的正文。无法识别或重复正文会记录并跳过，登录或机器人验证仍会暂停。剩余 Tech 记录标记为待复抓，[首轮 Tech 报告](data/bloomberg_main_probe/tech_report.json)保留原始统计与隔离说明。

v1.2.2 复抓实测：尝试 10 篇，保存 8 篇，跳过 2 篇；Tech 库存合计 3,957 词，作者和发布日期齐全，无重复正文，待复抓标记已清除。此前错配的文章本次未通过正文检查，没有再次入库。该结果验证了 Tech 队列和错误内容过滤流程；长文页面适配与逐篇全文对照仍待完成。[复抓报告](data/bloomberg_main_probe/tech_recheck_report.json)。

### 多专栏与 Takeaways（v1.4.0）

Bloomberg Studio 增加专栏标签、文章数量、专栏筛选及“管理 Bloomberg 专栏与自动采集范围”。刷新会保留当前专栏。内置 Tech、[Finance](https://www.bloomberg.com/industries/finance)、[Economics](https://www.bloomberg.com/economics)、[Big Take](https://www.bloomberg.com/bigtake) 和 [AI Today](https://www.bloomberg.com/account/newsletters/ai-today)，也可添加自定义主站栏目入口。添加栏目默认不启用自动采集，勾选后才参与轮换。

自动计划是**所有启用专栏合计每轮最多尝试一篇**，依次轮换，不按专栏数增加抓取频率。间隔持久化在调度数据库，默认 120 分钟；2026-10-07 本机排查期间调整为 **10 分钟**，界面以服务返回的实际间隔为准。每个专栏独立保存发现队列，文章按 URL 全局去重；同一篇文章可以归属多个专栏，发现已有文章时只补充归属。旧 Tech 调度数据库自动迁移并保留任务与去重状态。新专栏的真实浏览器正文适配需逐一验证，尤其 Big Take 的长文可能仍进入人工检查。

AI Today 为 newsletter，用户提供的账户入口可能跳转到 `/standalone/ai-today/`。其自动采集默认关闭；扩展只接受该入口中明确标注 AI Today 或最新一期的 newsletter 链接，没有有效文章链接则报失败，不能把订阅页面或其他推荐文章入库。需先选择 AI Today 手动试抓，确认文章发现成功后才能勾选自动采集。

扩展弹窗增加专栏选择、“立即采集所选专栏 1 篇”和“试抓所选专栏前 10 篇”。更新后需重新加载扩展，确认版本 v1.4.1。旧 `/automation/tech/*` 路径兼容保留，新扩展使用 `/automation/bloomberg/*`。

标题下的 Takeaways 位于独立组件，旧版本只读取正文容器，因此没有保存。v1.4.0 将页面原有要点分别保存为 `takeaways`、`takeaways_source` 和 `takeaways_status`，阅读器、纯文本复制和单篇 Markdown 复制/下载均包含要点及其来源标识；AI 要点不混入记者正文或正文词数，也不作为正文通过校验的依据。无要点或组件为空时记录状态，不生成替代摘要。历史文章需重新入库才能补齐，旧版客户端复抓不会抹除已经保存的要点。

### Tech 自动采集（v1.3.0）

WSJ 初版开发中：`wsj_store.py` 提供独立文章库、来源校验、栏目队列与正文诊断；8011 服务新增 `/wsj/capture`、`/wsj/columns/{section}/discover` 和 `/wsj/queue/{section}`，8000 提供 `/api/wsj/articles`。`wsj_extension/` 支持当前文章、右键与栏目最多十篇试抓，成功后关闭扩展弹窗或自建单篇标签页。需加载这一独立扩展，并使用可阅读全文的订阅会话。工厂 WSJ 工作台界面及真实浏览器全文验证尚未完成，不代表已验证批量抓取。未配置 WSJ 自动计划。离线校验：`python -m unittest test_wsj_store`。

扩展 v1.3.1 支持右键入库：在 Bloomberg 主站文章页面空白处或选中文本后右键，选择“将当前 Bloomberg 文章入库”；在文章链接上右键，选择“将这篇 Bloomberg 文章入库”。链接模式在后台打开目标文章，成功后关闭采集标签页，失败则保留页面供检查。页面提示与扩展弹窗显示结果。右键操作沿用订阅登录和正文校验，不修改每两小时的自动计划；如自动任务正在运行，先等待完成或暂停。

v1.3.2 在单篇入库成功后自动关闭扩展弹窗；右键链接打开的采集页在确认保存后立即关闭。失败时保留弹窗或采集页以便检查，用户原有文章标签页保留。

自动计划 **每轮最多尝试 1 篇**，使用已配置的间隔。需要 8011 接收服务和已登录 Bloomberg 的 Chrome 持续运行；扩展弹窗关闭不影响调度。电脑休眠或 Chrome 关闭时不能抓取，恢复后最多补一轮。扩展 v1.4.1 会等待栏目页面加载文章链接，对空列表在同一轮再重试两次，并保存失败阶段、HTTP 状态和页面信息；重试栏目发现不会增加文章尝试次数。

1. 启动或重启 `python bloomberg_main_bridge.py`，然后在 `chrome://extensions` 点击该扩展的“重新加载”。当前弹窗应显示 v1.4.1。
2. 点击“开启 / 恢复自动采集”。首次开启后等待当前配置的间隔；想立即验证可选择专栏并点击立即采集，同时将下轮顺延一个间隔。
3. 查看弹窗的计划与结果，或刷新 Bloomberg Studio 查看计划和浏览器在线状态。点击“暂停自动采集”会关闭计划并停止当前自动任务。

每轮先重新发现 Tech 栏目链接，再领取一篇尚未采集的文章；队列为空保存 0 篇。失败不补抓第二篇：网络失败最多在后续周期重试三次，无法识别或重复正文进入人工检查；登录失效或机器人验证暂停，处理后点“开启 / 恢复”。自动采集只保存具有明确时区发布时间、发布于最近 72 小时内且通过正文检查的文章，正文完整性仍需人工核验。

任务与去重状态持久化到 `data/bloomberg_tech_scheduler.sqlite3`（不提交 Git）；已确认结果幂等登记，扩展 worker 重启后通过 alarm 恢复未完成步骤。当前版操作入口在扩展，网页控制台提供只读状态。自动轮次清理已知 UTC 发布时间过期的主站正文，以及超过 72 小时的 inbox/隔离文件；无时区的历史数据留待迁移，不静默改写日期。

离线验证：`python -m unittest test_bloomberg_tech_scheduler test_bloomberg_automation_api test_bloomberg_main_bridge test_bloomberg_extension_popup -v`；扩展恢复验证：`node test_bloomberg_automation_worker.js`。这些测试不代表真实登录浏览器已经完成定时运行实测。[设计与后续范围](docs/bloomberg-tech-automation.md)。

## 环境与安装

主要开发环境为 Windows，建议使用 Python 3.11。原生目录选择、浏览器登录及部分前端同步路径依赖本机环境。

仓库暂未提供锁定版本的依赖清单。以下安装命令依据当前代码导入整理，不代表已验证的跨环境兼容性组合：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install fastapi uvicorn pydantic yt-dlp beautifulsoup4 httpx curl-cffi playwright DrissionPage python-docx cos-python-sdk-v5 edge-tts customtkinter requests
python -m playwright install chromium
```

视频合并、音频提取需要 FFmpeg，并确保 `ffmpeg` 可通过 PATH 调用：

```powershell
python --version
ffmpeg -version
```

TikTok 的原生浏览器扫描优先使用已安装的 Chrome，失败时尝试 Edge。采集能力受网络、登录状态和目标网站变化影响。

## 启动

### 网页控制台（主要入口）

在项目目录执行：

```powershell
python web_app.py
```

也可双击 `启动网页控制台.bat`。默认监听 `127.0.0.1:8000` 并自动打开浏览器：

[打开本地控制台](http://127.0.0.1:8000)

应用启动时会启动 FT 后台调度线程；可以通过控制台的调度开关暂停。

### 桌面 GUI 与命令行

旧的桌面界面入口仍保留：

```powershell
python gui.py
```

也可双击 `启动GUI.bat`。TikTok 命令行示例：

```powershell
python tiktok_downloader.py charlidamelio --max 20
python tiktok_downloader.py charlidamelio --list-only
python tiktok_downloader.py charlidamelio --cookies cookies.txt --date-after 20260101
```

## 配置

`config.json` 保存控制台的下载目录、代理、封面及字幕选项等设置。控制台可以配置学习服务参数，但独立教案处理器当前从 `.env` 读取 `DEEPSEEK_API_KEY`，两者尚未统一。

需要 AI 翻译、云同步或绕口令配图时，在项目根目录创建 `.env`，按需填写：

```dotenv
DEEPSEEK_API_KEY=your_deepseek_key
COS_SECRET_ID=your_cos_secret_id
COS_SECRET_KEY=your_cos_secret_key
COS_REGION=your_cos_region
COS_BUCKET=your_cos_bucket
GEMINI_IMAGE_API_KEY=your_image_service_key
```

配图服务还支持 `GEMINI_IMAGE_BASE_URL` 配置；具体请求格式见 `tony_tonguetwister_processor.py`。未配置凭证时，相关功能可能失败或跳过处理。视频下载完成后会尝试自动提炼教案及上传 COS，因此完整下载加工流程需要相应配置。

COS 上传器会尝试为生成对象设置 `public-read`，供前端播放和读取。

FT / 经济学人的 Cookie 可在控制台设置。`ft_sync_extension/` 是 Chrome 扩展，可读取已登录 FT 的 Cookie 并同步到本地控制台。

`.env` 不应提交到 Git。部分 Cookie 和调度文件虽然已加入 `.gitignore`，仍在当前仓库中被跟踪；忽略规则不会自动取消这些文件的跟踪。

## 采集与数据流程

```text
视频链接 / 博主 / 频道 → 扫描与下载 → 视频、封面、字幕
                                      ↓
                               字幕校对与中文翻译
                                      ↓
                           课程 JSON → 腾讯云 COS
                                      ↓
                              Tony English 前端

外刊栏目 / RSS / 文章链接 → 正文解析与去重 → data/*_articles.json
```

### 外刊存储与 FT 调度

- FT、经济学人、BNN Bloomberg 使用本地 JSON 存储。读取文章列表时，代码设计为清理超过 3 天的文章，优先依据 `scraped_at`，其次依据 `published_at`。
- FT 默认每轮采集一篇，轮换 technology、markets、companies、world、home。成功后按配置间隔（默认 60 分钟）加 1–5 分钟随机延迟安排下一轮。
- FT 遇到正文安全验证时设置两小时冷却；手动试跑默认忽略冷却限制。
- BNN Bloomberg 的现有扫描器从三个栏目页寻找文章链接，按 URL / 标题去重，仅接受至少 4 段、150 词的正文；默认每栏目最多尝试 4 个候选链接。

单独运行 Bloomberg 小批量扫描：

```powershell
python bloomberg_store.py
```

该入口每栏目最多尝试 2 个候选链接。通过函数可调整数量，例如每栏目最多尝试 20 个：

```powershell
python -c "import bloomberg_store as b; print('新增文章数:', len(b.scan_bloomberg_syndication(limit_per_section=20)))"
```

`limit_per_section` 限制的是候选链接尝试数量，实际新增数取决于栏目链接数量、去重结果和正文质量。

### Bloomberg 批量试抓

`bloomberg_bulk.py` 从栏目页及近几天的每日站点地图发现链接，跨来源去重，排除视频、FAQ、企业新闻稿（`press-releases`）及投资推广（`investment-trends`）栏目，并逐篇记录结果。默认最多尝试 100 个未入库链接，请求启动间隔至少 1 秒。

```powershell
# 只生成本地采集结果和报告
python bloomberg_bulk.py --max-articles 100 --days 7 --delay 1

# 同时把合格文章导入网页控制台
python bloomberg_bulk.py --max-articles 100 --days 7 --delay 1 --import
```

每次运行在 `data/bloomberg_runs/<UTC时间>/` 保存 `store_before.json`（运行前备份）、`articles.json`（本次合格正文）和 `report.json`（逐篇状态及统计）。每篇处理后保存进度；中断后重跑会跳过已导入的文章，未导入的试抓结果不会自动恢复。

遇到 HTTP 403 / 429 时停止本轮并保留结果；短文、缺少可识别正文的页面及明确标记付费的文章不入库。批量结果文件作为本次试验记录保留，控制台文章库仍适用前述三天保留逻辑。`--days` 是站点地图发现窗口，不是正文发布日期过滤条件；同一地图可能包含较早发布但最近更新的文章。

验证 Bloomberg 正文边界、元数据及 URL 过滤逻辑：

```powershell
python -m unittest test_bloomberg_parser -v
```

首轮实测（2026-10-04，100 次正文请求，约 195 秒）：

| 结果 | 数量 |
| --- | ---: |
| 发现候选链接 | 139 |
| 新增合格新闻 / 评论文章 | 77 |
| 排除企业新闻稿及投资推广 | 14 |
| 正文或长度不达标 | 7 |
| 网络超时 | 2 |

新增文章已导入控制台，原有 12 篇保留，试验结束时库存为 89 篇。77 篇新增文章均取得发布日期，URL / ID 无重复，合计约 5.6 万英文词；这些检查不代表已逐篇人工核验。

[查看首轮逐篇报告](data/bloomberg_runs/20261004T124024352454Z/report.json)。首轮是在抓取后剔除推广内容，因此该目录额外保留 `articles_before_editorial_filter.json` 供比对。后续批量运行会在发现链接时直接过滤这些栏目。

## 代码结构

| 文件 / 目录 | 职责 |
| --- | --- |
| `web_app.py` | FastAPI API、任务状态、下载流程及内嵌 HTML / CSS / JavaScript 控制台 |
| `gui.py`、`tiktok_downloader.py` | 桌面 GUI 和 TikTok CLI |
| `chrome_scraper.py` | Playwright 原生浏览器扫描 |
| `channels_store.py` | 频道与博主 JSON 存储 |
| `ft_store.py`、`ft_scheduler.py` | FT 正文采集、RSS、存储与后台调度 |
| `ft_scraper.py` | 独立的 FT 登录、采集及监控命令行工具 |
| `economist_store.py`、`bloomberg_store.py` | 经济学人及 BNN Bloomberg 采集与存储 |
| `bloomberg_bulk.py` | Bloomberg 批量试抓、限速、备份与逐篇结果报告 |
| `tony_lesson_processor.py`、`tony_youtube_processor.py` | 视频字幕处理、跟读课程生成及同步 |
| `tony_tonguetwister_processor.py` | 绕口令、配图及多语速音频生成 |
| `youtube_study_helper.py` | 音频提取、双语字幕和 Word 学习文档输出 |
| `cos_service.py` | 腾讯云 COS 上传 |
| `ft_sync_extension/` | FT Cookie 同步扩展 |
| `data/` | 外刊文章、频道记录、课程和运行状态 |

## 当前限制

- `web_app.py` 同时包含后端与大段网页代码；当前没有独立前端构建流程，也没有数据库。
- Tony English 前端同步及 APK 下载依赖写死的 `tony-frontend-demo` 本机路径，迁移环境时需要修改。
- YouTube 下载流程附带的双语字幕 / Word 学习文档目前使用示例句子与词汇；独立教案处理器才会读取实际视频字幕并调用翻译。
- `economist_store.py` 的文章读取逻辑使用了未导入的 `timedelta`，异常会被捕获并返回空列表，需修复后验证经济学人文章显示。
- Bloomberg 正文解析限定在文章容器内，并优先读取结构化元数据中的发布日期和作者；旧库存仍可能保留早期解析器写入的采集时间作为发布日期。网站结构变化或正文格式不匹配时会跳过文章。
- 除 Bloomberg 的离线解析测试外，仓库中的其他 `test_*.py` 主要是联网或浏览器诊断脚本，没有完整的自动化回归测试套件。
