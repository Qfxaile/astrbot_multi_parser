# 微博、小黑盒、知乎解析实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 AstrBot 多解析器插件中完整增加微博、小黑盒和知乎解析能力。

**Architecture:** 三个平台继续实现现有 `BaseParser` 接口并返回 `ParseResult`。微博和小黑盒各使用单一平台模块；知乎按请求、正文转换和路由拆包。所有图片复用统一安全物化流程，视频继续由入口层执行大小检查与发送降级。

**Tech Stack:** Python 3.10+、AstrBot、httpx、pytest、pytest-asyncio、Python 标准库 HTMLParser/JSON/正则表达式。

---

### Task 1: 注册、配置和默认启用

**Files:**
- Modify: `main.py`
- Modify: `platforms/__init__.py`
- Modify: `_conf_schema.json`
- Modify: `tests/test_config.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: 写注册失败测试**

在 `tests/test_config.py` 断言默认平台完整，在 `tests/test_main.py` 断言构造后的键集合：

```python
assert schema["enabled_platforms"]["default"] == [
    "bilibili", "douyin", "redbook", "weibo", "xiaoheihe", "zhihu"
]
assert set(plugin.parsers) == {
    "bilibili", "douyin", "redbook", "weibo", "xiaoheihe", "zhihu"
}
```

- [ ] **Step 2: 运行测试并确认因解析器未注册而失败**

Run: `python -m pytest tests/test_config.py tests/test_main.py -q`
Expected: FAIL，缺少 `weibo`、`xiaoheihe`、`zhihu`。

- [ ] **Step 3: 增加导出、注册和配置项**

`platforms/__init__.py` 导出三个类，`main.py` 构造三个实例。配置默认值加入三个名称，并增加三个可选 Cookie 文本项：

```python
self.parsers: dict[str, BaseParser] = {
    "bilibili": BilibiliParser(config),
    "douyin": DouyinParser(config),
    "redbook": RedBookParser(config),
    "weibo": WeiboParser(config),
    "xiaoheihe": XiaoheiheParser(config),
    "zhihu": ZhihuParser(config),
}
```

- [ ] **Step 4: 运行注册测试**

Run: `python -m pytest tests/test_config.py tests/test_main.py -q`
Expected: PASS。

- [ ] **Step 5: 提交公共接入**

```powershell
git add main.py platforms/__init__.py _conf_schema.json tests/test_config.py tests/test_main.py
git commit -m "feat(parser): 注册三平台解析器"
```

### Task 2: 微博 URL、状态数据和媒体转换

**Files:**
- Create: `platforms/weibo.py`
- Create: `tests/test_weibo.py`

- [ ] **Step 1: 写 URL、mid 和状态载荷失败测试**

测试普通链接、移动链接、TV、视频、文章、分享链接，并校验 base62 转换和图文顺序：

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://weibo.com/123456/P5kWdcfDe",
    "https://m.weibo.cn/status/5234367615996775",
    "https://weibo.com/tv/show/1034:5007449447661594?mid=5007452630158934",
    "https://video.weibo.com/show?fid=1034:5145615399845897",
    "https://weibo.com/ttarticle/p/show?id=2309404962180771742222",
    "https://mapp.api.weibo.cn/fx/233911ddcc6bffea835a55e725fb0ebc.html",
])
async def test_matches_supported_weibo_urls(url):
    assert await WeiboParser({}).match(ParseContext(text=url))

def test_status_payload_keeps_text_images_and_repost_order():
    result = WeiboParser({})._parse_status_payload(STATUS_PAYLOAD)
    assert result.title == "视频标题"
    assert result.author == "微博作者"
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "正文\n第二行"),
        ("image", "https://wx1.sinaimg.cn/large/a.jpg"),
        ("text", "转发自 @原作者\n原微博"),
        ("image", "https://wx2.sinaimg.cn/large/b.jpg"),
    ]
```

- [ ] **Step 2: 运行微博单元测试并确认失败**

Run: `python -m pytest tests/test_weibo.py -q`
Expected: FAIL，`platforms.weibo` 尚不存在。

- [ ] **Step 3: 实现 URL 路由、正文清理和状态转换**

实现 `WeiboParser`、`_base62_encode()`、`_mid_to_bid()`、`_strip_html()`、`_parse_status_payload()`。关键选择逻辑：

```python
def _select_video_url(page_info: object) -> str:
    if not isinstance(page_info, dict):
        return ""
    urls = page_info.get("urls")
    if not isinstance(urls, dict):
        return ""
    for key in ("mp4_720p_mp4", "mp4_hd_mp4", "mp4_ld_mp4"):
        value = urls.get(key)
        if isinstance(value, str) and value:
            return value if value.startswith("http") else f"https:{value}"
    return ""
```

- [ ] **Step 4: 运行纯转换测试**

Run: `python -m pytest tests/test_weibo.py -q -k "matches or payload or mid"`
Expected: PASS。

- [ ] **Step 5: 提交微博核心转换**

```powershell
git add platforms/weibo.py tests/test_weibo.py
git commit -m "feat(weibo): 解析微博状态与媒体"
```

### Task 3: 微博网络入口、长文章和视频页

**Files:**
- Modify: `platforms/weibo.py`
- Modify: `tests/test_weibo.py`

- [ ] **Step 1: 写 MockTransport 网络失败测试**

覆盖匿名状态接口不携带 Cookie、分享链接可信重定向、文章图文顺序和视频页媒体：

```python
def handler(request: httpx.Request) -> httpx.Response:
    assert "cookie" not in request.headers
    return httpx.Response(200, json={"ok": 1, "data": STATUS_PAYLOAD}, request=request)

result = await parser.parse(ParseContext(text="https://weibo.com/123/P5kWdcfDe"))
assert result.author == "微博作者"
```

- [ ] **Step 2: 运行网络测试并确认失败**

Run: `python -m pytest tests/test_weibo.py -q -k "parse_"`
Expected: FAIL，网络路由尚未完成。

- [ ] **Step 3: 实现状态、视频、文章和可信跳转请求**

所有请求使用统一超时；分享链接展开后校验主机：

```python
@staticmethod
def _is_weibo_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"weibo.com", "www.weibo.com", "m.weibo.cn", "card.weibo.com"} or host.endswith(".weibo.com")
```

长文章用 `HTMLParser` 生成 `OrderedContent`，图片 URL 规范化为 HTTPS；完成后调用 `materialize_images()`。

- [ ] **Step 4: 运行全部微博测试**

Run: `python -m pytest tests/test_weibo.py -q`
Expected: PASS。

- [ ] **Step 5: 提交微博完整支持**

```powershell
git add platforms/weibo.py tests/test_weibo.py
git commit -m "feat(weibo): 支持文章视频与分享链接"
```

### Task 4: 小黑盒帖子解析与签名请求

**Files:**
- Create: `platforms/xiaoheihe.py`
- Create: `tests/test_xiaoheihe.py`

- [ ] **Step 1: 写帖子 URL、签名和正文失败测试**

```python
@pytest.mark.asyncio
async def test_matches_bbs_share_url():
    parser = XiaoheiheParser({})
    context = ParseContext(text="https://api.xiaoheihe.cn/v3/bbs/app/api/web/share?link_id=123")
    assert await parser.match(context)

def test_post_payload_interleaves_text_images_and_video():
    result = XiaoheiheParser({})._parse_post_payload(POST_PAYLOAD)
    assert result.title == "帖子标题"
    assert result.author == "盒友"
    assert [(item.kind, item.value) for item in result.ordered_contents] == [
        ("text", "第一段"),
        ("image", "https://cdn.max-c.com/a.jpg"),
        ("text", "第二段"),
    ]
    assert result.video_url == "https://cdn.max-c.com/a.mp4"
```

- [ ] **Step 2: 运行小黑盒帖子测试并确认失败**

Run: `python -m pytest tests/test_xiaoheihe.py -q -k "bbs or post or sign"`
Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现链接识别、Cookie、签名和帖子数据转换**

实现 `_extract_link_id()`、`_sign_path()`、`_request_json()`、`_parse_post_payload()`。签名输入只包含规范路径、秒级时间戳和随机串，返回请求参数字典；日志不得输出签名或令牌。

正文解析接受字符串 HTML 块和结构化图片块，图片使用标准库 `HTMLParser` 提取：

```python
def _append_post_block(contents: list[OrderedContent], block: object) -> None:
    if isinstance(block, str):
        text, images = _parse_html_block(block)
        if text:
            contents.append(OrderedContent(kind="text", value=text))
        contents.extend(OrderedContent(kind="image", value=url) for url in images)
```

- [ ] **Step 4: 运行帖子测试**

Run: `python -m pytest tests/test_xiaoheihe.py -q -k "bbs or post or sign"`
Expected: PASS。

- [ ] **Step 5: 提交帖子解析**

```powershell
git add platforms/xiaoheihe.py tests/test_xiaoheihe.py
git commit -m "feat(xiaoheihe): 解析社区帖子"
```

### Task 5: 小黑盒游戏详情与回退数据源

**Files:**
- Modify: `platforms/xiaoheihe.py`
- Modify: `tests/test_xiaoheihe.py`

- [ ] **Step 1: 写游戏网页状态和接口回退失败测试**

```python
def test_game_state_extracts_metadata_and_media():
    result = XiaoheiheParser({})._parse_game_state(GAME_STATE, "730", "pc")
    assert result.title == "Counter-Strike 2"
    assert "游戏类型: FPS" in result.extra_lines
    assert result.image_urls == ["https://cdn.max-c.com/game.jpg"]
```

- [ ] **Step 2: 运行游戏测试并确认失败**

Run: `python -m pytest tests/test_xiaoheihe.py -q -k game`
Expected: FAIL，游戏状态解析尚不存在。

- [ ] **Step 3: 实现 Nuxt 状态解析、对象选择和介绍回退**

实现 `_extract_nuxt_data()`、`_resolve_devalue()`、`_find_game()`、`_parse_game_state()`。递归解析设置最大深度和已访问对象集合；按 `appid` 选择候选，不匹配时抛出 `ValueError`。缺少简介时调用公开介绍接口并合并，不覆盖网页已有字段。

- [ ] **Step 4: 运行全部小黑盒测试**

Run: `python -m pytest tests/test_xiaoheihe.py -q`
Expected: PASS。

- [ ] **Step 5: 提交游戏解析**

```powershell
git add platforms/xiaoheihe.py tests/test_xiaoheihe.py
git commit -m "feat(xiaoheihe): 解析游戏详情"
```

### Task 6: 知乎正文工具和内容解析

**Files:**
- Create: `platforms/zhihu/__init__.py`
- Create: `platforms/zhihu/common.py`
- Create: `platforms/zhihu/content.py`
- Create: `tests/test_zhihu.py`

- [ ] **Step 1: 写 HTML 图文顺序、URL 规范化和去重失败测试**

```python
def test_html_body_keeps_text_image_order():
    blocks = parse_html_body('<p>第一段</p><figure><img data-original="//picx.zhimg.com/a.jpg"></figure><p>第二段</p>')
    assert [(block.kind, block.value) for block in blocks] == [
        ("text", "第一段"),
        ("image", "https://picx.zhimg.com/a.jpg"),
        ("text", "第二段"),
    ]
```

- [ ] **Step 2: 运行正文工具测试并确认失败**

Run: `python -m pytest tests/test_zhihu.py -q -k "html or normalize or dedup"`
Expected: FAIL，知乎包尚不存在。

- [ ] **Step 3: 实现纯函数和 HTMLParser**

`common.py` 实现 `normalize_text()`、`normalize_media_url()`、`media_key()`、`merge_unique_urls()`；`content.py` 实现过滤不可见标签的 `ZhihuHTMLParser` 和 `parse_html_body()`。只接受 HTTP(S)，协议相对 URL 补 `https:`。

- [ ] **Step 4: 运行正文工具测试**

Run: `python -m pytest tests/test_zhihu.py -q -k "html or normalize or dedup"`
Expected: PASS。

- [ ] **Step 5: 提交知乎正文基础**

```powershell
git add platforms/zhihu tests/test_zhihu.py
git commit -m "feat(zhihu): 提取有序图文正文"
```

### Task 7: 知乎问题、回答、文章和想法转换

**Files:**
- Create: `platforms/zhihu/handlers.py`
- Modify: `tests/test_zhihu.py`

- [ ] **Step 1: 写四类载荷失败测试**

```python
def test_answer_payload_builds_result():
    result = parse_answer_payload(ANSWER_PAYLOAD)
    assert result.title == "问题标题"
    assert result.author == "答主"
    assert result.extra_lines == ["赞同 12 | 评论 3 | 收藏 2"]
    assert result.ordered_contents[0].value == "回答正文"
```

分别断言问题描述和首答、专栏标题作者、想法正文媒体；错误容器必须抛出 `ValueError`。

- [ ] **Step 2: 运行处理器测试并确认失败**

Run: `python -m pytest tests/test_zhihu.py -q -k "question or answer or article or pin"`
Expected: FAIL，处理器尚不存在。

- [ ] **Step 3: 实现四类数据转换**

实现 `parse_question_payload()`、`parse_answer_payload()`、`parse_article_payload()`、`parse_pin_payload()`。统计值统一格式化为整数、万、亿；首个视频写入 `video_url`，额外视频写入有序文本：

```python
if videos:
    result.video_url = videos[0]
    result.ordered_contents.extend(
        OrderedContent(kind="text", value=f"视频链接: {url}")
        for url in videos[1:]
    )
```

- [ ] **Step 4: 运行处理器测试**

Run: `python -m pytest tests/test_zhihu.py -q -k "question or answer or article or pin"`
Expected: PASS。

- [ ] **Step 5: 提交知乎数据转换**

```powershell
git add platforms/zhihu/handlers.py tests/test_zhihu.py
git commit -m "feat(zhihu): 转换问题回答文章与想法"
```

### Task 8: 知乎请求与 URL 路由

**Files:**
- Create: `platforms/zhihu/request.py`
- Create: `platforms/zhihu/parser.py`
- Modify: `platforms/zhihu/__init__.py`
- Modify: `tests/test_zhihu.py`

- [ ] **Step 1: 写路由、可信跳转、回退和 Cookie 隔离失败测试**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://www.zhihu.com/question/1",
    "https://www.zhihu.com/question/1/answer/2",
    "https://zhuanlan.zhihu.com/p/3",
    "https://www.zhihu.com/pin/4",
    "https://www.zhihu.com/tardis/zm/art/5",
])
async def test_matches_supported_zhihu_urls(url):
    assert await ZhihuParser({}).match(ParseContext(text=url))
```

- [ ] **Step 2: 运行路由测试并确认失败**

Run: `python -m pytest tests/test_zhihu.py -q -k "matches or redirect or fallback or cookie"`
Expected: FAIL，路由和请求层尚不存在。

- [ ] **Step 3: 实现请求客户端和内容路由**

`ZhihuRequest` 构造只属于 `.zhihu.com` 的 Cookie；`ZhihuParser.parse()` 提取 URL，可信展开后按正则路由。API 无数据或返回风控页时回退页面初始状态/元数据；不可信目标抛出 `ValueError("知乎分享链接跳转到不可信域名")`。解析完成后以内容页面为 Referer 调用 `materialize_images()`。

- [ ] **Step 4: 运行全部知乎测试**

Run: `python -m pytest tests/test_zhihu.py -q`
Expected: PASS。

- [ ] **Step 5: 提交知乎完整支持**

```powershell
git add platforms/zhihu tests/test_zhihu.py
git commit -m "feat(zhihu): 支持内容请求与链接路由"
```

### Task 9: 文档、元数据和完整验证

**Files:**
- Modify: `README.md`
- Modify: `metadata.yaml`
- Modify: `requirements.txt`（仅在实现确需新增运行依赖时）

- [ ] **Step 1: 更新用户文档和版本**

README 平台列表、配置表、触发示例、项目结构、已知限制加入三个平台；`metadata.yaml` 描述改为六平台并提升次版本。Cookie 安全说明包含三个新增配置。

- [ ] **Step 2: 检查 Conda 环境**

Run: `conda info --envs`
Expected: 当前活动环境不是 `base`；若是 `base`，不安装任何依赖，仅使用项目现有环境完成可执行验证。

- [ ] **Step 3: 运行新增平台测试**

Run: `python -m pytest tests/test_weibo.py tests/test_xiaoheihe.py tests/test_zhihu.py -q`
Expected: PASS。

- [ ] **Step 4: 运行全部测试**

Run: `python -m pytest -q`
Expected: PASS，且现有 Bilibili、抖音、小红书行为无回归。

- [ ] **Step 5: 检查语法和差异**

Run: `python -m compileall .`
Expected: 编译成功，无语法错误。

Run: `git diff --check`
Expected: 无空白错误。

Run: `git status --short`
Expected: 仅包含本任务文件和用户原有的 `platforms/redbook.py`、`tests/test_redbook.py`；后两者不纳入提交。

- [ ] **Step 6: 提交文档与最终集成**

```powershell
git add README.md metadata.yaml requirements.txt
git commit -m "docs(parser): 更新六平台使用说明"
```

- [ ] **Step 7: 逐项完成验收审计**

将设计中的微博六类入口、小黑盒帖子/游戏、知乎四类内容、配置注册、安全边界、单元测试和全量测试分别映射到源码或测试证据。任何一项缺少直接证据时继续补齐，不以局部测试通过代替完整验收。
