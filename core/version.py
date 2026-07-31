"""
单一版本来源（semver 2.0.0）。

发版时由 python-semantic-release 自动改写本文件（配置于 pyproject.toml
的 `[tool.semantic_release].version_variables`）；手动发版只需改这里的
`__version__`，并保证与 CHANGELOG.md 顶部版本段、git tag 三者一致。

版本递增规则（semver 2.0.0，0.x 阶段同样适用）：
- `feat` 提交递增 MINOR（0.7.0 → 0.8.0）
- `fix`/`perf` 提交递增 PATCH（0.7.0 → 0.7.1）
- 大版本（1.0.0 及以后）由发布者手动决定
"""

__version__ = "0.8.0"
