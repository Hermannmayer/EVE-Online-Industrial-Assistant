# services.char_config_validator

> 源文件 `services/char_config_validator.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

角色配置文件校验和迁移

## 函数

### `validate_char_config`

```python
def validate_char_config(data: dict) -> dict
```

校验角色配置的结构和类型是否正确。

定义行：`67`

### `migrate_char_config`

```python
def migrate_char_config(data: dict) -> dict
```

迁移旧配置到新格式。添加缺失的默认字段。

定义行：`148`

### `load_char_config`

```python
def load_char_config(path: str) -> dict
```

读取、校验、迁移一站式函数。

定义行：`215`
