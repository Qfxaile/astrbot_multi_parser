# 微博、小黑盒、知乎解析设计

## 背景与目标

当前插件通过统一的 `BaseParser`、`ParseContext` 和 `ParseResult` 接入 Bilibili、抖音和小红书。此次参考 MIT 许可的 `Zhalslar/astrbot_plugin_parser`，在不迁入其下载器、渲染器和配置体系的前提下，新增微博、小黑盒、知乎解析能力，并保持当前插件的消息发送、安全校验和配置方式。

目标覆盖参考插件中三个平台的主要内容类型：

- 微博：普通微博、转发微博、图文、视频、微博视频页、长文章和分享跳转链接。
- 小黑盒：社区帖子、分享链接、游戏详情页及其中的图文和视频。
- 知乎：问题、回答、专栏文章、想法及正文中的图文和视频。

不迁入参考插件的媒体卡片渲染、文件缓存、会话防抖和平台仲裁能力。这些属于另一套框架，不是新增解析器所必需。

## 总体架构

三个平台均实现现有 `BaseParser` 接口：

1. `match()` 只识别明确属于目标平台的 HTTP(S) URL。
2. `parse()` 负责短链展开、页面或接口请求、外部数据校验和统一结果转换。
3. 图文内容使用 `OrderedContent` 保留正文与图片顺序。
4. 图片交给 `BaseParser.materialize_images()` 下载为 Base64，并复用可信域名、默认端口、私有地址和重定向限制。
5. 视频只返回远程 URL，继续使用入口层现有的大小探测和发送降级策略。

入口层在 `main.py` 注册 `weibo`、`xiaoheihe`、`zhihu`，配置中的 `enabled_platforms` 决定是否启用。

## 微博解析器

`platforms/weibo.py` 支持以下入口：

- `weibo.com/<uid>/<bid>`
- `m.weibo.cn/status/<id>`、`m.weibo.cn/detail/<id>` 和移动端用户路径
- `weibo.com/tv/show/...?...mid=<mid>`
- `video.weibo.com/show?fid=<fid>`
- `mapp.api.weibo.cn/fx/<token>.html`
- `weibo.com/ttarticle/...id=<id>` 和 `card.weibo.com/article/.../id/<id>`

普通微博通过移动端状态接口获取数据。正文去除 HTML 标签并保留换行；图片使用大图地址；视频按 720p、HD、LD 顺序选择；转发微博追加到有序正文中并保留其媒体。TV 链接先把十进制 `mid` 转换为微博 base62 ID。视频页使用视频组件接口，长文章使用文章详情接口并按段落、图片顺序解析 HTML。

微博 Cookie 为可选配置，仅用于允许携带凭据的页面请求；匿名状态接口显式不携带 Cookie，避免重定向时泄漏。

## 小黑盒解析器

`platforms/xiaoheihe.py` 支持社区帖子和游戏详情的网页、分享入口：

- `api.xiaoheihe.cn/v3/bbs/app/api/web/share?...link_id=<id>`
- `api.xiaoheihe.cn/v3/bbs/app/api/share?...link_id=<id>`
- 小黑盒游戏分享链接及 `xiaoheihe.cn/app/bbs/link/<id>` 等规范页面
- 游戏详情网页及分享链接中的 `appid` 和游戏类型

帖子通过签名后的公开接口获取标题、作者、正文块、图片和视频，并按原顺序生成 `OrderedContent`。游戏详情优先解析网页中的 Nuxt 状态；缺少介绍时使用公开游戏介绍接口补齐，输出标题、平台/类型、发行信息、简介、图片和视频。

小黑盒的签名算法使用标准库实现。网络请求优先使用 `httpx`；若实际接口需要浏览器 TLS 指纹，则仅为该平台引入 `curl_cffi`，并通过线程桥接避免阻塞事件循环。`xhh_tokenid` 可从配置 Cookie 中读取，缺失时按参考流程匿名获取设备标识和令牌。

## 知乎解析器

知乎实现拆为 `platforms/zhihu/` 包，避免单文件承担 URL 路由、网络请求、HTML 解析和结果转换：

- `parser.py`：公共解析器入口和 URL 路由。
- `request.py`：短链展开、API/页面请求和 Cookie 请求头。
- `content.py`：HTML、页面状态和媒体内容提取。
- `handlers.py`：问题、回答、文章和想法的数据转换。
- `common.py`：文本、URL、去重和计数格式化工具。

支持：

- `zhihu.com/question/<qid>`
- `zhihu.com/question/<qid>/answer/<aid>`
- `zhuanlan.zhihu.com/p/<id>`
- `zhihu.com/pin/<id>`
- `zhihu.com/tardis/zm/art/<id>` 等移动分享入口
- `link.zhihu.com` 等可确认目标域名的跳转链接

问题页返回问题描述和默认排序首条回答；回答、文章、想法返回作者、正文、统计信息和媒体。数据源优先使用公开 API 或页面初始状态，缺失时回退到 HTML 元数据。正文解析过滤脚本、样式、内嵌框架等不可见节点，保持段落和图片顺序，媒体 URL 做规范化和去重。

## 数据模型与发送

现有 `ParseResult` 足以表达单视频和有序图文。若一个内容包含多个视频，解析器把首个视频放入 `video_url`，其余视频作为带标签的链接放入有序文本，避免为本次功能扩张入口层发送协议。

转发微博、知乎引用块和小黑盒复杂正文使用 `OrderedContent` 展平为可读顺序。当前多图合并转发阈值和平台兼容判断保持不变。

## 配置与依赖

新增配置：

- `enabled_platforms` 默认加入 `weibo`、`xiaoheihe`、`zhihu`。
- `weibo_cookies`、`xiaoheihe_cookies`、`zhihu_cookies`：均为可选文本。

公共超时继续使用 `request_timeout_seconds`。不记录 Cookie、完整签名 URL 或包含令牌的异常地址。

依赖遵循最小化原则。优先使用已有 `httpx` 和 Python 标准库；只有确认小黑盒请求需要 TLS 模拟时才加入受限版本的 `curl_cffi`。

## 错误处理与安全

- 短链只接受最终落在对应平台可信域名的地址。
- 所有外部 JSON 容器在读取前检查类型，缺失关键数据时返回明确错误。
- HTTP 状态错误、风控页面、内容删除和格式变化使用平台化中文错误，不暴露堆栈或敏感参数。
- 每个平台声明独立的图片可信域名后缀，继续复用统一图片下载安全边界。
- Cookie 只设置到所属主域；跨域 CDN 图片请求不携带平台 Cookie。
- 同一正文内图片和视频按规范化 URL 去重。

## 测试与验收

新增三个测试文件，使用 `httpx.MockTransport` 或对请求适配层打桩，不依赖真实网络：

- URL 匹配与非目标 URL 拒绝。
- 短链展开和不可信重定向拒绝。
- 各内容类型的正常载荷转换。
- 空容器、字段类型错误、删除内容和 HTTP 失败。
- 正文图文顺序、媒体去重、原图选择和图片可信域名。
- Cookie 域隔离及错误消息不泄漏令牌。
- `main.py` 默认注册和配置启停行为。

验收时依次运行新增平台测试、现有全部测试、`python -m compileall .`。同时检查 `git diff`，确认未覆盖工作区中原有的 `platforms/redbook.py` 和 `tests/test_redbook.py` 改动。

## 文档与许可

README、配置说明、项目结构和平台列表同步更新。实现参考 MIT 许可仓库的公开行为与算法思路；如复制达到实质性代码片段，需在仓库中补充对应版权与 MIT 许可声明。优先采用适配当前项目接口的独立实现，降低许可和后续维护成本。
