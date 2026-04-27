# EVE 商人助手

EVE Online 市场数据查询与分析工具，基于 Flet 构建的桌面应用程序。

## 功能特性

- 📊 **市场价格查询**：实时抓取伏尔戈星域（The Forge，含吉他）的市场订单
- 🔍 **物品搜索**：支持中英文名称模糊搜索
- 🏭 **制造业计算**：BOM 材料清单与制造成本分析
- 📦 **仓库管理**：物品清单与库存追踪
- 📈 **贸易分析**：买卖价差与利润率计算
- 🖼️ **物品图标**：自动缓存 EVE Image Server 物品图标

## 目录结构

```
EVE商人助手_v1.0.0/
├── EVE商人助手.exe        # 主程序（双击运行）
├── database/               # 数据库目录（离线物品数据）
│   └── items.db           #   物品信息数据库
├── data/                   # 运行期数据目录
│   ├── search_history.json    # 搜索历史
│   ├── window_geometry.json   # 窗口位置记忆
│   └── update_progress.json   # 价格更新进度
└── README.md               # 本文件
```

> **说明**：图标缓存目录 `data/caches/icons/` 会在首次运行时自动创建。

## 安装使用

### 方式一：下载 ZIP 发行包（推荐）

1. 从 [Releases](../../releases) 页面下载 `EVE商人助手_v1.0.0.zip`
2. 解压到任意目录（路径中建议不要包含中文/空格）
3. 双击运行 `EVE商人助手.exe`

> ⚠️ 首次运行时若 Windows Defender 提示风险，点击"更多信息" → "仍要运行"即可
> ⚠️ 请确保解压后 `database/items.db` 与 exe 在同一级目录

### 方式二：开发环境运行

```bash
# 1. 克隆仓库
git clone https://github.com/Hermannmayer/eve.git
cd eve

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库（下载物品数据）
python services/workers/getitems.py

# 4. 可选：下载物品图标
python services/workers/geticon.py

# 5. 运行主程序
python Main.py
```

## 打包构建

本项目使用 **PyInstaller** 将 Python 代码打包为独立的 Windows exe 文件，
`database/` 和 `data/` 等用户数据目录与 exe 分离放置。

### 前置条件

```bash
pip install pyinstaller
```

### 一键打包

```bash
python build_release.py
```

执行完毕后将在 `dist/` 目录生成：

```
dist/
├── EVE商人助手_v1.0.0/          # 完整目录（可直接运行）
│   ├── EVE商人助手.exe
│   ├── database/items.db
│   ├── data/
│   └── README.md
└── EVE商人助手_v1.0.0.zip        # 压缩包（用于分发）
```

### 仅打包 exe 不压缩

```bash
python build_release.py --skip-zip
```

### 手动打包步骤

如果希望手动控制打包过程：

1. **PyInstaller 打包**
   ```bash
   pyinstaller EVE商人助手.spec --noconfirm
   ```

2. **整理目录**（手动将 database/ 和 data/ 复制到 exe 同目录）

3. **结果结构**
   ```
   EVE商人助手_v1.0.0/
   ├── EVE商人助手.exe     ← PyInstaller 产物
   ├── database/            ← 离线数据（手动复制）
   │   └── items.db
   ├── data/                ← 用户数据（运行期生成）
   └── README.md
   ```

## 数据来源

- **物品数据**：[SDE API](https://sde.jita.space/) (Static Data Export)
- **市场价格**：[EVE ESI API](https://esi.evetech.net/) (EVE Swagger Interface)
- **物品图标**：[EVE Image Server](https://images.evetech.net/)

## 技术栈

- **UI 框架**：[Flet](https://flet.dev/) — Python 原生桌面 UI
- **异步 HTTP**：aiohttp + tenacity（自动重试）
- **数据库**：SQLite（aiosqlite 异步访问）
- **打包工具**：PyInstaller
- **Python 版本**：3.10+

## 开发计划

- [ ] 多区域价格对比
- [ ] 价格走势图（历史数据）
- [ ] 批量导入导出
- [ ] 自动更新检查

---

*Made for EVE Online players* 🚀
