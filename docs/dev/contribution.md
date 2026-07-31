# 贡献指南

欢迎提交 Issue 和 Pull Request！以下是参与贡献的流程。

## 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 稳定主分支，触发自动发版 |
| `develop` | 开发集成分支（可选） |
| `feat/*` | 功能开发分支 |
| `fix/*` | Bug 修复分支 |

## Commit 规范

提交信息使用中文，遵循 Conventional Commits 格式（用于 python-semantic-release 自动解析）：

```
<type>: <描述>

<可选正文>
```

### Type 类型

| Type | 用途 | 影响版本 |
|------|------|----------|
| `feat` | 新功能 | MINOR（0.2.0 → 0.3.0）|
| `fix` | Bug 修复 | MINOR（0.x 阶段）|
| `perf` | 性能优化 | MINOR（0.x 阶段）|
| `docs` | 文档更新 | 不触发发版 |
| `refactor` | 重构 | 不触发发版 |
| `test` | 测试 | 不触发发版 |
| `chore` | 杂务 | 不触发发版 |
| `ci` | CI 配置 | 不触发发版 |
| `style` | 代码风格 | 不触发发版 |

### 示例

```bash
feat: 新增生产计划甘特图视图
fix: 修复安装费计算使用 adjusted_price 而非实时卖出价
docs: 更新 API 参考文档
```

> ⚠️ **0.x 阶段**：feat/fix/perf 都会触发 MINOR bump（PATCH 在 0.x 阶段不使用）。

## Pull Request 流程

1. **Fork** 或创建功能分支
2. 开发并确保代码质量：
   ```bash
   ruff check . --fix
   ruff format .
   mypy . --ignore-missing-imports
   pytest tests/ -q --quick
   ```
3. 提交 PR，使用中文描述变更内容
4. CI 自动运行全部检查（ruff + mypy + pytest + 版本校验）
5. 等待 Review 后合并

## 代码质量要求

- **Ruff**：零 lint 错误 + 格式化通过
- **Mypy**：类型检查通过
- **测试**：新功能必须有对应测试
- **覆盖**：整体覆盖率 > 70%
- **提交前**：`ruff check . && ruff format --check . && mypy . && pytest tests/ -q --quick`

## 开发环境搭建

详见 [开发环境](/dev/setup)。

## 许可证

本项目基于 [Apache License 2.0](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/blob/main/LICENSE) 开源。提交 PR 即表示同意你的贡献在同协议下发布。
