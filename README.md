# astrbot_multi_parser

B站、抖音、小红书等多平台内容解析插件。

## 功能

- 自动识别 B站 BV/AV 号和短链。
- 自动识别抖音、TikTok 链接。
- 自动识别小红书链接和部分 JSON 分享卡片。
- 先发送标题、作者、简介、封面、图集等解析信息。
- 解析成功后可给原消息添加表情回应。
- 解析到视频直链后，再单独通过 URL 发送视频，不下载到本地。
- 发送视频前检查远程文件大小，超过限制或大小未知时改用合并转发发送解析链接。

## 配置项

- `enabled_platforms`：启用的平台解析器，可选 `bilibili`、`douyin`、`redbook`。
- `douyin_api_url`：抖音解析 API 地址。
- `redbook_api_url`：小红书解析 API 地址。
- `request_timeout_seconds`：接口请求超时时间。
- `send_video_by_url`：解析到视频直链后是否直接通过 URL 发送视频。
- `max_video_size_mb`：直接发送视频的最大体积，超过后改用合并转发发送解析链接；小于等于 `0` 表示不限制。
- `allow_unknown_video_size`：无法通过 `HEAD` / `Range` 获取视频大小时，是否仍然直接发送视频。
- `size_check_timeout_seconds`：视频大小检查请求超时时间。
- `enable_parse_reaction`：解析成功后是否给原消息添加表情回应。
- `reaction_action`：OneBot 表情回应动作名，不同协议端可能不同，默认 `set_msg_emoji_like`。
- `reaction_emoji_id`：解析成功时使用的表情 ID，默认 `124`。

## 依赖

- `httpx`

## 架构

插件入口在 `main.py`，平台解析器放在 `platforms/`：

```text
platforms/
├── bilibili.py
├── douyin.py
└── redbook.py
```

后续新增平台时，新增一个解析器类并注册到 `main.py` 即可。

## 注意事项

- 插件不下载视频，不创建视频缓存。
- 插件只通过 `HEAD` / `Range` 探测视频大小，不会把完整视频下载到本地。
- 视频 URL 能否直接发送，取决于协议端和目标平台对远程视频 URL 的支持。
- 当视频超过大小限制，或大小未知且不允许发送时，插件会使用 OneBot 合并转发发送解析链接。
- 表情回应依赖协议端支持 `reaction_action` 对应动作；失败时只记录日志，不影响解析结果发送。
- 插件会先发送解析信息，再单独发送视频；即使视频发送失败，标题和封面也能保留。
- 小红书解析 API 默认是本地地址，需要你自己提供对应解析服务。
- 抖音解析 API、B站播放接口、小红书解析接口都可能因第三方服务变化而失效。
