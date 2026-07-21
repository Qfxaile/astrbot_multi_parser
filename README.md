# AstrBot 多平台内容解析器

> 自动识别聊天消息中的 Bilibili、抖音、小红书、贴吧、微博、小黑盒和知乎链接，并发送作品信息、正文图片或视频。

<p align="center">
  <img src="logo.png" alt="AstrBot 多平台内容解析器图标" width="180">
</p>

[![Version](https://img.shields.io/badge/version-v0.3.0-2f6f5e)](https://github.com/Qfxaile/astrbot_multi_parser/releases)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-3776ab)](https://www.python.org/)
[![AstrBot Plugin](https://img.shields.io/badge/AstrBot-plugin-4c78a8)](https://astrbot.app/)
[![License](https://img.shields.io/badge/license-MIT-2f6f5e)](LICENSE)

本项目是面向 AstrBot 的第三方社区插件，不属于 AstrBot 官方项目，也不受下列内容平台赞助、认可或维护。

## 功能概览

- **自动识别链接**：无需命令，直接发送受支持的链接或分享卡片即可触发解析。
- **覆盖七个平台**：支持 Bilibili、抖音、小红书、贴吧、微博、小黑盒和知乎的常见视频、图文及分享链接。
- **保留原图质量**：图片在内存中下载后以原始字节发送，不主动缩放或转码。
- **灵活组织内容**：可选择始终合并、超过图片或文字阈值时合并，或始终普通发送。
- **控制视频体积**：发送前探测远程视频大小，超过限制时改为发送解析链接。
- **按需配置 Cookie**：所有平台 Cookie 均为可选项，可提高受登录态或风控影响内容的解析成功率。

## 支持范围

| 平台 | 视频 | 图文 | 短链 | 其他内容 |
| --- | :---: | :---: | :---: | --- |
| Bilibili | BV 号、AV 号 | Opus 图文、专栏 | `b23.tv`、`bili2233.cn` | 动态 |
| 抖音 | 大陆抖音视频 | 普通图文、Slides | `v.douyin.com`、`jx.douyin.com` | 分享页链接 |
| 小红书 | 视频笔记 | 图文笔记 | `xhslink.com` | 部分 JSON 分享卡片 |
| 贴吧 | 首帖视频 | 楼主首帖正文 | - | `tieba.baidu.com/p/<帖子ID>` |
| 微博 | 普通视频、微博视频页、TV | 普通微博、转发微博、长文章 | `mapp.api.weibo.cn` | 桌面端和移动端微博 |
| 小黑盒 | 帖子视频、游戏视频 | 社区帖子、游戏截图 | BBS/API 分享链接 | 游戏简介、评分与价格 |
| 知乎 | 正文内视频 | 问题、回答、专栏文章、想法 | `link.zhihu.com` | 页面数据回退解析 |

> [!NOTE]
> 当前不支持 TikTok，也不解析 Bilibili 音频、独立音轨或 `au` 号。

### 消息适配器

合并转发节点支持 `aiocqhttp` 和 `satori`；其他 AstrBot 适配器会尝试降级为普通消息链，但未经过完整兼容性验证。表情回应和视频超限后的 OneBot 合并转发只在兼容的 OneBot 协议端可用。

### 环境要求

- AstrBot：建议使用最新稳定版 4.x；本项目尚未锁定最低 AstrBot 版本。
- Python：3.10 或更高版本，与 AstrBot 运行环境保持一致。
- 网络：AstrBot 实例需要能够访问目标内容平台及其媒体 CDN。
- 依赖：AstrBot 安装插件时会读取根目录 `requirements.txt`。

## 安装

### 插件市场

优先通过 AstrBot WebUI 的插件市场安装。安装或更新后，在插件管理页面重载插件，并按需修改配置。

### 手动安装

在 AstrBot 根目录下执行：

```powershell
Set-Location data/plugins
git clone https://github.com/Qfxaile/astrbot_multi_parser.git astrbot_plugin_multi_parser
```

随后按 [AstrBot 官方插件指南](https://docs.astrbot.app/dev/star/plugin-new.html) 完成依赖安装，并在 WebUI 中重载插件。插件目录名建议保持为小写且以 `astrbot_plugin_` 开头。

## 配置说明

所有配置均可在 AstrBot 插件配置页面中修改。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `platform_switches` | 对象（布尔开关） | 七个平台全部启用 | 分别控制 B站、抖音、小红书、贴吧、微博、小黑盒和知乎解析器 |
| `forward_mode` | 选项 | `threshold` | 内容发送方式：始终合并、超过阈值时合并或始终不合并（不推荐） |
| `forward_image_threshold` | 整数 | `2` | 阈值模式下，图片数量严格超过该值时合并发送 |
| `forward_text_threshold` | 整数 | `260` | 阈值模式下，最终可见文字字符数严格超过该值时合并发送 |
| `request_timeout_seconds` | 整数 | `30` | 平台页面和接口请求超时，单位为秒 |
| `image_download_concurrency` | 整数 | `4` | 同时下载的图片数量，取值范围为 `1`～`16` |
| `send_video_by_url` | 布尔值 | `true` | 是否通过远程 URL 直接发送解析到的视频 |
| `max_video_size_mb` | 浮点数 | `50` | 视频直发体积上限，单位为 MB；小于等于 `0` 表示不限制 |
| `allow_unknown_video_size` | 布尔值 | `false` | 无法探测视频大小时，是否仍尝试直接发送 |
| `size_check_timeout_seconds` | 浮点数 | `10` | 视频大小探测超时，单位为秒 |
| `enable_parse_reaction` | 布尔值 | `true` | 识别到受支持链接后，是否给原消息添加表情回应 |
| `reaction_action` | 字符串 | `set_msg_emoji_like` | OneBot 表情回应动作名，需与协议端保持一致 |
| `reaction_emoji_id` | 字符串 | `124` | 表情回应使用的表情 ID |
| `bilibili_cookies` | 文本 | 空 | 可选；用于 B站 页面和接口请求，可提高登录态或风控场景下的解析成功率 |
| `douyin_cookies` | 文本 | 空 | 可选；缺少 `ttwid` 时会尝试注册匿名会话 |
| `redbook_cookies` | 文本 | 空 | 可选；可提高部分内容或无水印资源的可用性 |
| `tieba_cookies` | 文本 | 空 | 可选；用于贴吧页面请求，可降低安全验证导致的解析失败 |
| `weibo_cookies` | 文本 | 空 | 可选；用于需要登录态的微博页面请求 |
| `xiaoheihe_cookies` | 文本 | 空 | 可选；未配置时自动申请匿名设备令牌 |
| `zhihu_cookies` | 文本 | 空 | 可选；用于知乎页面和接口请求 |

> [!WARNING]
> Cookie 属于敏感凭据。请仅通过 AstrBot 配置页面提供，不要写入代码、README、Issue、测试样例或日志。提交问题前请先删除 URL 查询参数中的令牌及日志中的个人信息。

## 消息发送策略

### 图文内容

1. 插件先整理标题、作者、简介等元数据。
2. Bilibili 图文按正文、图片和图片失败提示在原内容中的顺序发送。
3. 图片会下载到内存并编码为 Base64，不写入本地文件或缓存。
4. `forward_mode` 可选择以下三种方式：

| 模式 | 处理方式 |
| --- | --- |
| `always` | 标题、作者、简介、正文和图片始终放入一条合并转发消息 |
| `threshold` | 图片数严格超过 `forward_image_threshold`，或最终可见文字字符数严格超过 `forward_text_threshold` 时，使用一条合并转发消息 |
| `never` | 始终使用普通消息链，不推荐，可能造成刷屏 |

5. `threshold` 模式默认在图片超过 2 张或文字超过 260 字时合并；两个条件满足任意一个即可触发。
6. 合并转发仅用于 `aiocqhttp` 和 `satori`；其他平台会自动降级为普通消息链。
7. 单张图片下载失败时，原位置会显示“第 N 张图片获取失败”，其余内容继续发送。
8. 合并转发会先合并相邻文本并保留图文顺序；超过 QQ 官方 100 节点上限时均衡分批，投递失败时按原顺序缩小批次重试，单节点仍失败则降级为普通消息。

### 视频内容

启用 `send_video_by_url` 后，插件只通过 `HEAD` 或 `Range` 请求探测文件大小，不会把完整视频下载到本地。

| 检查结果 | 处理方式 |
| --- | --- |
| 文件大小未超过 `max_video_size_mb` | 通过远程 URL 单独发送视频 |
| 文件大小超过限制 | 使用 OneBot 合并转发发送解析链接 |
| 文件大小未知，且不允许未知大小 | 使用 OneBot 合并转发发送解析链接 |
| 文件大小未知，但允许未知大小 | 尝试通过远程 URL 发送视频 |
| 合并转发调用失败 | 降级为普通文本，附带失败原因和视频链接 |

插件会先发送作品信息，再处理视频。即使视频发送失败，已经解析到的标题和封面仍会保留。

## 常见问题

<details>
<summary><strong>为什么解析成功了，却没有直接发出视频？</strong></summary>

视频可能超过 `max_video_size_mb`，也可能无法通过 `HEAD` 或 `Range` 获取大小。此时默认改用合并转发发送解析链接。可以根据协议端能力调整 `max_video_size_mb` 或 `allow_unknown_video_size`。

</details>

<details>
<summary><strong>为什么视频 URL 在协议端发送失败？</strong></summary>

插件不会下载视频，而是让协议端拉取远程 URL。协议端通常无法携带插件请求使用的 Cookie 或 Referer，因此部分有防盗链或时效限制的 CDN 地址可能失效。

</details>

<details>
<summary><strong>为什么图片看起来被压缩了？</strong></summary>

插件发送的是平台源文件字节，不会主动缩放或转码 JPEG、WebP 等图片。协议端或目标聊天平台仍可能在接收后再次压缩。

</details>

<details>
<summary><strong>为什么表情回应没有出现？</strong></summary>

表情回应依赖 OneBot 客户端支持 `reaction_action` 指定的动作。动作不可用、消息 ID 缺失或调用失败时只记录日志，不会中断内容解析。

</details>

<details>
<summary><strong>为什么同一个链接突然无法解析？</strong></summary>

平台页面结构、公开接口、签名规则和 CDN 策略都可能变化。可以先检查 Cookie 与网络连通性；如果多个链接同时失效，通常需要更新对应平台解析器。

</details>

## 安全与隐私

- 各平台 Cookie 仅随对应平台域请求发送，不会带到分享跳转目标或跨域图片 CDN。
- 小黑盒未配置 Cookie 时会向其设备指纹服务申请匿名设备 ID，不会上传聊天内容或用户凭据。
- 图片地址必须使用 HTTP(S)、默认端口和受信任的平台域名；私有地址及不安全重定向会被拒绝。
- 图片重定向最多跟随 5 次，并在每次跳转前重新校验目标地址。
- 图片错误日志仅记录主机名和错误摘要，避免泄漏带令牌的完整 URL。
- 图片仅在内存中短暂处理；视频始终使用远程 URL，不创建本地媒体缓存。

## 项目结构

```text
astrbot_plugin_multi_parser/
├── main.py                    # 插件装配、事件监听与解析调度
├── core/                      # 解析契约、HTTP 安全、媒体物化和渲染
├── services/                  # 配置迁移、消息交付和视频策略
├── platforms/                 # 各内容平台适配器
│   ├── xiaoheihe/             # 小黑盒路由、帖子、游戏、签名和指纹
│   └── zhihu/                 # 知乎路由、请求、载荷处理和正文提取
├── tests/                     # pytest 单元测试
├── _conf_schema.json          # AstrBot 插件配置定义
├── metadata.yaml              # AstrBot 插件市场元数据
├── requirements.txt           # Python 运行时依赖
├── CHANGELOG.md               # 版本变更记录
└── LICENSE                    # 项目及第三方许可声明
```

解析器统一继承 `core/parser.py` 中的 `BaseParser`，返回 `core/contracts.py` 中的 `ParseResult`。新增平台时应优先复用 `core/` 与 `services/` 的稳定能力，通常需要：

1. 在 `platforms/` 中实现新的解析器类。
2. 实现链接匹配和内容解析，并复用统一图片物化逻辑。
3. 在 `platforms/__init__.py` 导出解析器。
4. 在 `services/configuration.py` 注册解析器类型。
5. 在 `_conf_schema.json` 的 `platform_switches` 中添加对应布尔开关。
6. 为正常输入、空值、格式错误和网络失败添加测试。

## 开发与验证

插件依赖 AstrBot API，推荐按官方目录布局开发：

```powershell
git clone https://github.com/AstrBotDevs/AstrBot.git
Set-Location AstrBot/data/plugins
git clone https://github.com/Qfxaile/astrbot_multi_parser.git astrbot_plugin_multi_parser
Set-Location astrbot_plugin_multi_parser
```

不要在 Conda `base` 环境中安装依赖。请按 AstrBot 官方文档使用本体根目录的 `.venv`，然后安装插件运行时依赖：

```powershell
& ..\..\..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```powershell
& ..\..\..\.venv\Scripts\python.exe -m ruff format --check .
& ..\..\..\.venv\Scripts\python.exe -m ruff check .
& ..\..\..\.venv\Scripts\python.exe -m pytest
```

涉及插件加载、协议端媒体发送或表情回应的修改，还需要启动 AstrBot，在 WebUI 中重载插件并进行集成验证。

## 已知限制

- 平台页面和公开接口发生变化后，对应解析器可能需要同步更新。
- 远程视频能否发送，取决于协议端及目标聊天平台是否支持远程视频 URL。
- 内容合并转发目前仅对 `aiocqhttp` 和 `satori` 启用。
- 视频链接的有效期、防盗链策略和可访问区域由内容平台决定。

## 贡献与安全

- 普通缺陷、功能建议和新平台适配可通过 [GitHub Issues](https://github.com/Qfxaile/astrbot_multi_parser/issues) 讨论。
- 安全漏洞或凭据泄漏风险请通过 [GitHub Security Advisories](https://github.com/Qfxaile/astrbot_multi_parser/security/advisories/new) 私下报告，不要提交公开 Issue。
- 提交第三方代码或算法前，必须确认许可证兼容，并在 README 与 `LICENSE` 中保留来源和许可声明。

## 参考项目与致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)：插件运行平台与开发 API。本项目遵循其插件目录、元数据、异步网络、日志和调试规范。
- [Zhalslar/astrbot_plugin_parser](https://github.com/Zhalslar/astrbot_plugin_parser)：微博、小黑盒和知乎解析实现的参考来源；小黑盒签名算法与匿名设备指纹请求参数在其 MIT 许可实现基础上改写。

参考范围包括 `platforms/weibo.py`、`platforms/xiaoheihe/` 和 `platforms/zhihu/`。上游项目采用 [MIT License](https://github.com/Zhalslar/astrbot_plugin_parser/blob/master/LICENSE)。感谢上述项目及其贡献者。

## 免责声明

- 本项目仅提供公开链接的技术解析与消息展示能力，不提供内容托管、下载站或访问控制绕过服务。
- 使用者应遵守所在地法律法规、AstrBot 使用规范、目标平台服务条款及内容版权要求；不得将本项目用于侵权、批量抓取、规避风控或其他滥用行为。
- Cookie、账号和协议端配置由使用者自行保管。因配置不当、凭据泄漏、账号限制、内容丢失或第三方服务变化造成的损失，项目维护者不承担责任。
- 解析结果来自第三方平台，项目不保证其准确性、完整性、持续可用性或适用于特定目的。
- 各平台名称和商标归其权利人所有；本项目与 AstrBot 官方及各内容平台均无隶属、授权或背书关系。

软件本身还受 MIT 许可证中的“按原样提供、无担保”条款约束。

## 许可证

本项目采用 [MIT License](LICENSE) 发布。参考项目的版权归原作者所有。
