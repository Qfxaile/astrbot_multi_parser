# Repository Guidelines

## 项目结构与模块组织

本仓库是 AstrBot 的多解析器插件。插件入口和业务逻辑位于仓库根目录及其 Python 模块中；解析器、平台适配和公共工具应按职责拆分，避免在入口文件堆积实现。测试代码放在 `tests/`（如目录已存在），静态资源或示例配置放在 `assets/`、`examples/` 等对应目录。新增模块时优先复用现有目录和命名方式。

## 构建、测试与开发命令

```powershell
python -m compileall .       # 快速检查 Python 语法
python -m pytest             # 运行全部测试
python -m pytest tests/test_parser.py -q  # 运行单个测试文件
```

若仓库提供 `requirements.txt` 或 `pyproject.toml`，请按其中声明安装依赖；不要将凭据写入配置文件。插件应通过 AstrBot 的本地开发实例验证加载、解析和异常处理行为。

## 编码风格与命名约定

遵循 PEP 8，使用 4 个空格缩进，文件编码为 UTF-8。函数和变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。类型注解应覆盖公开函数；复杂解析流程添加简洁中文注释。提交前使用项目已有的 formatter/linter（如 `ruff`、`black`）并保持导入顺序一致。

## 测试指南

测试框架优先使用 `pytest`。测试文件命名为 `test_*.py`，测试函数命名为 `test_<行为>`；为每个解析器覆盖正常输入、空值、格式错误和网络/外部服务失败等边界情况。修复缺陷时应添加回归测试，涉及异步代码时同时验证异常不会阻塞插件事件循环。当前测试范围仅限插件内部功能，暂不编写或执行依赖 AstrBot 本体的集成测试。

## 提交与 Pull Request 指南

提交信息使用 Conventional Commits，提交主题必须使用中文，例如 `fix(parser): 处理空响应` 或 `feat(platform): 新增来源适配器`，并保持祈使句和简短表达。Pull Request 应说明变更动机、影响范围和验证命令，关联相关 Issue；涉及用户可见行为时附上输入与输出示例。`docs/` 目录中的文档仅供本地使用，不得暂存或提交到 Git。提交前确认没有敏感配置、调试日志、`docs/` 目录内容或无关格式化改动。

## 配置与安全

API 密钥、Cookie、代理和 webhook 等敏感值只能通过 AstrBot 配置或环境变量提供，不得提交到 Git。处理外部内容时校验 URL、限制请求超时和响应大小，并对第三方解析失败返回可读错误而不是泄漏内部堆栈。
