# 软件组成部分分析与开发文档
_Exported on 2025/5/16 at GMT+8 18:57:26 from Cursor (0.50.4)_

---

**User**

分析一下这个软件所有的组成部分，都实现了什么功能，每个功能都具体用了哪些模块，根据以上形成一个开发文档

---

**Cursor**

让我帮您分析这个项目的组成部分。首先我需要查看项目的具体文件结构和内容。

根据项目文件结构分析，这是一个基于C#开发的EVE Online（星战前夜）游戏辅助工具软件。让我为您详细分析各个模块的功能：

# EVE Dealer T2 开发文档

## 1. 核心功能模块

### 1.1 制造系统
主要文件：
- `PageManufacture.cs`（主制造页面）
- `PageManufacture_EIV.cs`（制造价值评估）
- `PageManufacture_Invents.cs`（发明系统）
- `pageManufacture_Products.cs`（产品管理）
- `pageManufacture_Cargos.cs`（货物管理）

功能：
- 制造计划管理
- 材料计算
- 成本核算
- 发明效率计算
- 产品管理
- 库存追踪

### 1.2 行星开发系统
主要文件：
- `PagePlanet.cs`
- `PagePlanet_NewPlanet.cs`
- `PagePlanet_ToCargo.cs`

功能：
- 行星设施管理
- 新行星建设规划
- 资源运输管理
- 产出计算

### 1.3 市场交易系统
主要文件：
- `PageSearcherV2.cs`
- `PageMarketDetails.cs`
- `PageMyOrders.cs`
- `PageSellRecord.cs`

功能：
- 市场数据查询
- 价格分析
- 订单管理
- 销售记录追踪
- 交易历史统计

### 1.4 资产管理系统
主要文件：
- `PageStorage.cs`
- `PageAssetStastics.cs`
- `PageStorage_Suggest.cs`
- `pageStorage_ComplexRigs.cs`

功能：
- 资产统计
- 库存管理
- 物品建议系统
- 装备配件管理

### 1.5 蓝图研究系统
主要文件：
- `PageResearchBluePrint.cs`
- `PageBluePrints.cs`
- `Dialog_InventSetting.cs`

功能：
- 蓝图研究管理
- 材料效率研究
- 时间效率研究
- 发明设置

### 1.6 运输系统
主要文件：
- `PageHauler.cs`
- `PageHauler_CalcReport.cs`
- `PageCargoOrContract.cs`

功能：
- 运输路线规划
- 货物体积计算
- 合同管理
- 运输报告生成

## 2. 辅助功能模块

### 2.1 设置系统
主要文件：
- `PageSetting_Char.cs`
- `Setting_SuggestSettings.cs`
- `Setting_IndustDefaultFacilitys.cs`

功能：
- 角色技能设置
- 建议系统配置
- 默认设施设置
- 工业方法设置

### 2.2 数据统计分析
主要文件：
- `RPTOrderChangeReport.cs`
- `PageAssetStastics.cs`
- `frmDataSetView.cs`

功能：
- 订单变化报告
- 资产统计分析
- 数据集查看

### 2.3 界面组件
主要文件：
- `EVEDealer_Main.cs`（主界面）
- `PayWinV3.cs`（支付窗口）
- `PicInfo.cs`（图片信息显示）

功能：
- 主程序界面管理
- 支付系统界面
- 信息展示组件

## 3. 工具类

多个以`GClass`开头的文件（如`GClass144.cs`、`GClass139.cs`等）提供了各种辅助功能：
- 数据处理
- 计算功能
- 工具方法
- 通用类库

## 4. 技术特点

1. 使用C#开发，基于.NET Framework
2. 采用Windows Forms构建用户界面
3. 模块化设计，功能分离清晰
4. 包含完整的配置和设置系统
5. 提供详细的数据统计和分析功能

## 5. 项目结构特点

1. 每个主要功能模块都有对应的Designer文件，说明采用了Windows Forms设计器
2. 使用了大量的辅助类来处理复杂的游戏机制计算
3. 模块间职责划分清晰，便于维护和扩展
4. 包含完整的错误处理和日志系统

这个软件是一个功能丰富的EVE Online游戏辅助工具，主要面向工业生产、贸易和资产管理等游戏内容，为玩家提供全面的数据分析和管理功能。

---

**User**

我现在想仿照这个软件使用.net写一个相同功能的软件，我没有开发经验，请告诉我如何开始

---

**Cursor**

作为一个没有开发经验的初学者，我来为您制定一个循序渐进的学习和开发计划：

## 1. 基础知识准备

### 1.1 开发环境搭建
1. 下载安装 Visual Studio（推荐使用 Visual Studio 2022 Community 版本，免费）
2. 安装必要的组件：
   - .NET Desktop Development
   - Windows Forms Development

### 1.2 必要的编程基础学习（按顺序）
1. C#基础语法（2-3周）
   - 变量和数据类型
   - 控制流程（if, for, while等）
   - 类和对象
   - 异常处理

2. Windows Forms基础（1-2周）
   - 窗体设计
   - 常用控件使用
   - 事件处理

3. 数据处理基础（1-2周）
   - JSON处理
   - XML处理
   - 文件读写

## 2. 项目起步

### 2.1 创建基础项目
1. 创建新项目：
```
File -> New -> Project -> Windows Forms App (.NET Framework)
```

2. 设置项目结构：
```
YourProject/
├── Forms/          # 存放所有窗体
├── Models/         # 数据模型
├── Services/       # 业务逻辑
├── Utils/          # 工具类
└── Resources/      # 资源文件
```

### 2.2 从简单功能开始
建议按以下顺序开发：

1. **第一阶段：基础界面**（2-3周）
   - 主窗体设计
   - 菜单栏实现
   - 基本导航

2. **第二阶段：数据管理**（3-4周）
   - 物品数据库
   - 价格信息存储
   - 基础配置系统

3. **第三阶段：核心功能**（按优先级）

从简单的功能开始：
1. **市场查询模块**（最简单）
```csharp
// 示例：创建简单的市场查询窗体
public partial class MarketSearchForm : Form
{
    public MarketSearchForm()
    {
        InitializeComponent();
    }

    private void SearchButton_Click(object sender, EventArgs e)
    {
        string itemName = searchTextBox.Text;
        // 实现搜索逻辑
    }
}
```

2. **库存管理模块**
3. **制造计算模块**

## 3. 开发建议

### 3.1 学习资源
1. 在线教程：
   - Bilibili上的C#教程
   - Microsoft Learn平台
   - CSDN社区

2. 参考书籍：
   - 《C#入门经典》
   - 《C#图解教程》

### 3.2 开发工具
1. 版本控制：
   - 安装Git
   - 创建GitHub账号
   - 学习基本的Git操作

2. 调试工具：
   - Visual Studio调试器
   - 日志记录工具

### 3.3 具体步骤示例

1. **创建第一个窗体**：
```csharp
// MainForm.cs
public partial class MainForm : Form
{
    public MainForm()
    {
        InitializeComponent();
        InitializeMenuStrip();
    }

    private void InitializeMenuStrip()
    {
        MenuStrip mainMenu = new MenuStrip();
        ToolStripMenuItem fileMenu = new ToolStripMenuItem("文件");
        ToolStripMenuItem marketMenu = new ToolStripMenuItem("市场");
        
        mainMenu.Items.Add(fileMenu);
        mainMenu.Items.Add(marketMenu);
        
        this.MainMenuStrip = mainMenu;
        this.Controls.Add(mainMenu);
    }
}
```

2. **创建基础数据模型**：
```csharp
// Models/Item.cs
public class Item
{
    public int Id { get; set; }
    public string Name { get; set; }
    public double Price { get; set; }
    public string Category { get; set; }
}
```

3. **创建简单的数据服务**：
```csharp
// Services/ItemService.cs
public class ItemService
{
    private List<Item> _items = new List<Item>();

    public void AddItem(Item item)
    {
        _items.Add(item);
    }

    public Item FindItem(string name)
    {
        return _items.FirstOrDefault(x => x.Name == name);
    }
}
```

### 3.4 开发时间规划

1. **入门学习阶段**：1-2个月
   - C#基础
   - Windows Forms基础
   - 简单项目实践

2. **基础功能开发**：2-3个月
   - 界面框架
   - 基础数据处理
   - 简单功能模块

3. **核心功能开发**：3-6个月
   - 市场系统
   - 制造系统
   - 资产管理

### 3.5 注意事项

1. **循序渐进**
   - 不要一开始就尝试实现所有功能
   - 先实现基础功能，再逐步添加复杂功能

2. **代码管理**
   - 经常备份代码
   - 做好版本控制
   - 编写注释

3. **测试**
   - 每个功能完成后进行测试
   - 记录并修复发现的问题

4. **寻求帮助**
   - 加入开发者社区
   - 在遇到问题时及时求助
   - 参考开源项目

如果您需要具体某个模块的实现细节，或者遇到具体的技术问题，随时可以继

```plaintext
File -> New -> Project -> Windows Forms App (.NET Framework)
```

```plaintext
YourProject/
├── Forms/          # 存放所有窗体
├── Models/         # 数据模型
├── Services/       # 业务逻辑
├── Utils/          # 工具类
└── Resources/      # 资源文件
```

```csharp
// 示例：创建简单的市场查询窗体
public partial class MarketSearchForm : Form
{
    public MarketSearchForm()
    {
        InitializeComponent();
    }

    private void SearchButton_Click(object sender, EventArgs e)
    {
        string itemName = searchTextBox.Text;
        // 实现搜索逻辑
    }
}
```

```csharp
// MainForm.cs
public partial class MainForm : Form
{
    public MainForm()
    {
        InitializeComponent();
        InitializeMenuStrip();
    }

    private void InitializeMenuStrip()
    {
        MenuStrip mainMenu = new MenuStrip();
        ToolStripMenuItem fileMenu = new ToolStripMenuItem("文件");
        ToolStripMenuItem marketMenu = new ToolStripMenuItem("市场");
        
        mainMenu.Items.Add(fileMenu);
        mainMenu.Items.Add(marketMenu);
        
        this.MainMenuStrip = mainMenu;
        this.Controls.Add(mainMenu);
    }
}
```

```csharp
// Models/Item.cs
public class Item
{
    public int Id { get; set; }
    public string Name { get; set; }
    public double Price { get; set; }
    public string Category { get; set; }
}
```

```csharp
// Services/ItemService.cs
public class ItemService
{
    private List<Item> _items = new List<Item>();

    public void AddItem(Item item)
    {
        _items.Add(item);
    }

    public Item FindItem(string name)
    {
        return _items.FirstOrDefault(x => x.Name == name);
    }
}
```

---

**User**

请分布列出我要进行的软件编写工作

---

**Cursor**

我将为您详细列出软件开发的具体工作清单，按照开发阶段和优先级进行排序：

# EVE辅助软件开发工作清单

## 第一阶段：基础框架搭建（预计耗时：2-3周）

### 1. 项目初始化
- [ ] 创建Windows Forms项目
- [ ] 建立基础文件夹结构
- [ ] 创建Git仓库进行版本控制

### 2. 主界面框架
- [ ] 设计并实现主窗体（MainForm）
- [ ] 创建菜单栏系统
- [ ] 实现基本的窗体切换功能
- [ ] 设计统一的界面风格

### 3. 数据基础
- [ ] 创建基础数据模型类
- [ ] 实现数据存储机制
- [ ] 建立配置文件系统

## 第二阶段：基础功能模块（预计耗时：4-6周）

### 1. 物品管理系统
- [ ] 物品数据模型设计
- [ ] 物品基本信息显示
- [ ] 物品搜索功能
- [ ] 物品分类管理

### 2. 市场数据模块
- [ ] 市场价格查询界面
- [ ] 价格数据存储结构
- [ ] 简单的价格比较功能
- [ ] 历史价格记录功能

### 3. 基础设置系统
- [ ] 用户偏好设置
- [ ] 界面显示设置
- [ ] 数据更新设置
- [ ] 基本系统配置

## 第三阶段：核心功能开发（预计耗时：8-12周）

### 1. 制造系统
- [ ] 制造界面设计
- [ ] 材料清单计算
- [ ] 成本核算功能
- [ ] 制造效率计算
- [ ] 材料需求分析
- [ ] 利润计算器

### 2. 资产管理系统
- [ ] 资产列表显示
- [ ] 资产分类管理
- [ ] 资产价值计算
- [ ] 库存管理功能
- [ ] 资产变动追踪

### 3. 市场交易系统
- [ ] 订单管理界面
- [ ] 买卖订单记录
- [ ] 交易历史统计
- [ ] 价格趋势分析
- [ ] 交易利润计算

### 4. 蓝图研究系统
- [ ] 蓝图管理界面
- [ ] 研究时间计算
- [ ] 材料效率计算
- [ ] 发明概率计算
- [ ] 研究成本分析

## 第四阶段：高级功能开发（预计耗时：8-12周）

### 1. 行星开发系统
- [ ] 行星资源显示
- [ ] 行星设施管理
- [ ] 产出计算器
- [ ] 运输规划
- [ ] 收益分析

### 2. 运输系统
- [ ] 路线规划
- [ ] 货物体积计算
- [ ] 运输成本计算
- [ ] 安全系数评估
- [ ] 最优路线推荐

### 3. 数据分析系统
- [ ] 市场趋势分析
- [ ] 利润报表生成
- [ ] 资产价值统计
- [ ] 交易历史分析
- [ ] 收益率计算

## 第五阶段：优化和完善（预计耗时：4-6周）

### 1. 性能优化
- [ ] 数据加载优化
- [ ] 界面响应优化
- [ ] 内存使用优化
- [ ] 数据库查询优化

### 2. 用户体验改进
- [ ] 界面美化
- [ ] 操作流程优化
- [ ] 快捷键支持
- [ ] 自定义界面布局

### 3. 辅助功能
- [ ] 数据备份还原
- [ ] 错误日志系统
- [ ] 帮助文档
- [ ] 自动更新系统

## 开发建议

### 工具准备
1. 开发环境
   - Visual Studio 2022 Community
   - .NET Framework SDK
   - Git版本控制工具

2. 辅助工具
   - SQLite数据库工具
   - JSON编辑器
   - 图形设计工具

### 开发方法
1. 每个功能模块建议按照以下步骤进行：
   - 界面设计
   - 基础功能实现
   - 数据处理
   - 功能测试
   - 优化完善

2. 版本控制建议：
   - 每完成一个小功能就提交代码
   - 编写清晰的提交说明
   - 定期备份代码

### 测试方案
1. 功能测试
   - 单元测试
   - 界面测试
   - 数据准确性测试

2. 性能测试
   - 响应速度测试
   - 内存占用测试
   - 数据处理效率测试

### 注意事项
1. 代码规范
   - 统一的命名规则
   - 清晰的代码注释
   - 模块化的代码结构

2. 数据安全
   - 定期数据备份
   - 敏感数据加密
   - 异常处理机制

3. 用户体验
   - 界面友好性
   - 操作便捷性
   - 响应及时性

这个开发计划可以根据您的实际情况进行调整，建议先完成基础功能，再逐步添加高级功能。每个阶段完成后进行充分测试，确保软件的稳定性和可用性。

---

**User**

 我该建立什么样的基础文件夹结构

---

**Cursor**

我来为您详细说明一个合理的项目文件夹结构：

# 项目文件夹结构设计

```
EVE_Assistant/
├── src/                           # 源代码根目录
│   ├── Forms/                     # 窗体文件目录
│   │   ├── MainForm/             # 主窗体
│   │   ├── Market/               # 市场相关窗体
│   │   │   ├── MarketSearch.cs
│   │   │   ├── MarketDetails.cs
│   │   │   └── OrderManagement.cs
│   │   ├── Manufacturing/        # 制造相关窗体
│   │   │   ├── ManufacturingMain.cs
│   │   │   ├── BlueprintCalculator.cs
│   │   │   └── MaterialList.cs
│   │   ├── Assets/              # 资产管理窗体
│   │   └── Settings/            # 设置窗体
│   │
│   ├── Models/                   # 数据模型类
│   │   ├── Items/               # 物品相关模型
│   │   │   ├── Item.cs
│   │   │   ├── Blueprint.cs
│   │   │   └── Material.cs
│   │   ├── Market/              # 市场相关模型
│   │   │   ├── Order.cs
│   │   │   └── Price.cs
│   │   └── Manufacturing/       # 制造相关模型
│   │
│   ├── Services/                # 业务逻辑服务
│   │   ├── DataService/        # 数据服务
│   │   │   ├── ItemDataService.cs
│   │   │   ├── MarketDataService.cs
│   │   │   └── DatabaseService.cs
│   │   ├── CalculationService/ # 计算服务
│   │   │   ├── ProfitCalculator.cs
│   │   │   └── MaterialCalculator.cs
│   │   └── ApiService/         # API服务
│   │
│   ├── Utils/                  # 工具类
│   │   ├── Constants/         # 常量定义
│   │   ├── Helpers/          # 辅助方法
│   │   └── Extensions/       # 扩展方法
│   │
│   ├── Data/                  # 数据文件
│   │   ├── Database/         # 数据库文件
│   │   ├── Config/          # 配置文件
│   │   └── Cache/           # 缓存文件
│   │
│   └── Resources/            # 资源文件
│       ├── Images/          # 图片资源
│       ├── Icons/          # 图标资源
│       └── Localization/   # 本地化资源
│
├── tests/                    # 测试项目目录
│   ├── UnitTests/          # 单元测试
│   └── IntegrationTests/   # 集成测试
│
├── docs/                    # 文档目录
│   ├── api/               # API文档
│   └── user/             # 用户文档
│
└── tools/                 # 工具和脚本目录
```

## 关键文件夹说明和示例代码

### 1. Forms 目录
主要存放所有窗体文件，建议按功能模块分类：

```csharp
// Forms/MainForm/MainForm.cs
public partial class MainForm : Form
{
    public MainForm()
    {
        InitializeComponent();
        InitializeMainMenu();
    }

    private void InitializeMainMenu()
    {
        // 主菜单初始化代码
    }
}
```

### 2. Models 目录
存放数据模型类：

```csharp
// Models/Items/Item.cs
public class Item
{
    public int Id { get; set; }
    public string Name { get; set; }
    public decimal BasePrice { get; set; }
    public string Category { get; set; }
    public string Description { get; set; }
}

// Models/Market/Order.cs
public class MarketOrder
{
    public long OrderId { get; set; }
    public int ItemId { get; set; }
    public decimal Price { get; set; }
    public int Volume { get; set; }
    public OrderType Type { get; set; }
    public DateTime Created { get; set; }
}
```

### 3. Services 目录
业务逻辑服务类：

```csharp
// Services/DataService/ItemDataService.cs
public class ItemDataService
{
    private readonly DatabaseService _db;

    public ItemDataService(DatabaseService db)
    {
        _db = db;
    }

    public async Task<Item> GetItemByIdAsync(int id)
    {
        // 获取物品数据的实现
    }
}

// Services/CalculationService/ProfitCalculator.cs
public class ProfitCalculator
{
    public decimal CalculateManufacturingProfit(Blueprint blueprint, 
                                              List<Material> materials)
    {
        // 计算制造利润的实现
    }
}
```

### 4. Utils 目录
工具类和辅助方法：

```csharp
// Utils/Helpers/NumberFormatter.cs
public static class NumberFormatter
{
    public static string FormatISK(decimal value)
    {
        // ISK格式化实现
    }
}

// Utils/Constants/GameConstants.cs
public static class GameConstants
{
    public const decimal SALES_TAX = 0.08m;
    public const decimal BROKER_FEE = 0.03m;
}
```

### 5. Data 目录
配置文件示例：

```json
// Data/Config/settings.json
{
    "DatabaseSettings": {
        "ConnectionString": "Data Source=eveassistant.db",
        "AutoBackup": true,
        "BackupInterval": 24
    },
    "ApiSettings": {
        "BaseUrl": "https://esi.evetech.net/latest",
        "Timeout": 30
    }
}
```

## 创建步骤

1. **创建基础目录结构**：
```powershell
# 使用PowerShell创建目录结构
$dirs = @(
    "src/Forms/MainForm",
    "src/Forms/Market",
    "src/Forms/Manufacturing",
    "src/Models/Items",
    "src/Models/Market",
    "src/Services/DataService",
    "src/Services/CalculationService",
    "src/Utils/Helpers",
    "src/Utils/Constants",
    "src/Data/Config",
    "src/Resources/Images",
    "tests/UnitTests",
    "docs/api",
    "docs/user"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force
}
```

2. **创建基础类文件**：
```powershell
# 创建基础类文件
$files = @(
    "src/Forms/MainForm/MainForm.cs",
    "src/Models/Items/Item.cs",
    "src/Services/DataService/DatabaseService.cs",
    "src/Utils/Constants/GameConstants.cs"
)

foreach ($file in $files) {
    New-Item -ItemType File -Path $file -Force
}
```

## 注意事项

1. **命名规范**
   - 文件夹名使用PascalCase
   - 类文件名与类名一致
   - 保持目录结构清晰和有意义

2. **文件组织**
   - 相关的文件放在同一目录下
   - 避免目录层次过深
   - 保持目录结构的一致性

3. **版本控制**
   - 创建.gitignore文件，排除不需要版本控制的文件
   - 及时提交代码变更
   - 保持提交信息清晰明确

4. **文档维护**
   - 在docs目录下保持文档更新
   - 记录重要的开发决策
   - 维护API文档和用户手册

这个文件结构设计可以帮助您更好地组织代码，提高开发效率，使项目更容易维护和扩展。您可以根据实际需求对这个结构进行适当调整。

```plaintext
EVE_Assistant/
├── src/                           # 源代码根目录
│   ├── Forms/                     # 窗体文件目录
│   │   ├── MainForm/             # 主窗体
│   │   ├── Market/               # 市场相关窗体
│   │   │   ├── MarketSearch.cs
│   │   │   ├── MarketDetails.cs
│   │   │   └── OrderManagement.cs
│   │   ├── Manufacturing/        # 制造相关窗体
│   │   │   ├── ManufacturingMain.cs
│   │   │   ├── BlueprintCalculator.cs
│   │   │   └── MaterialList.cs
│   │   ├── Assets/              # 资产管理窗体
│   │   └── Settings/            # 设置窗体
│   │
│   ├── Models/                   # 数据模型类
│   │   ├── Items/               # 物品相关模型
│   │   │   ├── Item.cs
│   │   │   ├── Blueprint.cs
│   │   │   └── Material.cs
│   │   ├── Market/              # 市场相关模型
│   │   │   ├── Order.cs
│   │   │   └── Price.cs
│   │   └── Manufacturing/       # 制造相关模型
│   │
│   ├── Services/                # 业务逻辑服务
│   │   ├── DataService/        # 数据服务
│   │   │   ├── ItemDataService.cs
│   │   │   ├── MarketDataService.cs
│   │   │   └── DatabaseService.cs
│   │   ├── CalculationService/ # 计算服务
│   │   │   ├── ProfitCalculator.cs
│   │   │   └── MaterialCalculator.cs
│   │   └── ApiService/         # API服务
│   │
│   ├── Utils/                  # 工具类
│   │   ├── Constants/         # 常量定义
│   │   ├── Helpers/          # 辅助方法
│   │   └── Extensions/       # 扩展方法
│   │
│   ├── Data/                  # 数据文件
│   │   ├── Database/         # 数据库文件
│   │   ├── Config/          # 配置文件
│   │   └── Cache/           # 缓存文件
│   │
│   └── Resources/            # 资源文件
│       ├── Images/          # 图片资源
│       ├── Icons/          # 图标资源
│       └── Localization/   # 本地化资源
│
├── tests/                    # 测试项目目录
│   ├── UnitTests/          # 单元测试
│   └── IntegrationTests/   # 集成测试
│
├── docs/                    # 文档目录
│   ├── api/               # API文档
│   └── user/             # 用户文档
│
└── tools/                 # 工具和脚本目录
```

```csharp
// Forms/MainForm/MainForm.cs
public partial class MainForm : Form
{
    public MainForm()
    {
        InitializeComponent();
        InitializeMainMenu();
    }

    private void InitializeMainMenu()
    {
        // 主菜单初始化代码
    }
}
```

```csharp
// Models/Items/Item.cs
public class Item
{
    public int Id { get; set; }
    public string Name { get; set; }
    public decimal BasePrice { get; set; }
    public string Category { get; set; }
    public string Description { get; set; }
}

// Models/Market/Order.cs
public class MarketOrder
{
    public long OrderId { get; set; }
    public int ItemId { get; set; }
    public decimal Price { get; set; }
    public int Volume { get; set; }
    public OrderType Type { get; set; }
    public DateTime Created { get; set; }
}
```

```csharp
// Services/DataService/ItemDataService.cs
public class ItemDataService
{
    private readonly DatabaseService _db;

    public ItemDataService(DatabaseService db)
    {
        _db = db;
    }

    public async Task<Item> GetItemByIdAsync(int id)
    {
        // 获取物品数据的实现
    }
}

// Services/CalculationService/ProfitCalculator.cs
public class ProfitCalculator
{
    public decimal CalculateManufacturingProfit(Blueprint blueprint, 
                                              List<Material> materials)
    {
        // 计算制造利润的实现
    }
}
```

```csharp
// Utils/Helpers/NumberFormatter.cs
public static class NumberFormatter
{
    public static string FormatISK(decimal value)
    {
        // ISK格式化实现
    }
}

// Utils/Constants/GameConstants.cs
public static class GameConstants
{
    public const decimal SALES_TAX = 0.08m;
    public const decimal BROKER_FEE = 0.03m;
}
```

```json
// Data/Config/settings.json
{
    "DatabaseSettings": {
        "ConnectionString": "Data Source=eveassistant.db",
        "AutoBackup": true,
        "BackupInterval": 24
    },
    "ApiSettings": {
        "BaseUrl": "https://esi.evetech.net/latest",
        "Timeout": 30
    }
}
```

```powershell
# 使用PowerShell创建目录结构
$dirs = @(
    "src/Forms/MainForm",
    "src/Forms/Market",
    "src/Forms/Manufacturing",
    "src/Models/Items",
    "src/Models/Market",
    "src/Services/DataService",
    "src/Services/CalculationService",
    "src/Utils/Helpers",
    "src/Utils/Constants",
    "src/Data/Config",
    "src/Resources/Images",
    "tests/UnitTests",
    "docs/api",
    "docs/user"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force
}
```

```powershell
# 创建基础类文件
$files = @(
    "src/Forms/MainForm/MainForm.cs",
    "src/Models/Items/Item.cs",
    "src/Services/DataService/DatabaseService.cs",
    "src/Utils/Constants/GameConstants.cs"
)

foreach ($file in $files) {
    New-Item -ItemType File -Path $file -Force
}
```

---

**User**

 我该怎么设计并实现主窗体（MainForm）

---

**Cursor**

我来为您详细说明如何设计和实现主窗体。我们将分步骤实现一个专业的主窗体界面。

## 1. 主窗体基础设计

首先创建主窗体的基本结构：

```csharp
// Forms/MainForm/MainForm.cs
public partial class MainForm : Form
{
    private Panel mainPanel;           // 主内容面板
    private MenuStrip mainMenuStrip;   // 主菜单栏
    private StatusStrip statusStrip;   // 状态栏
    private ToolStrip toolStrip;       // 工具栏
    
    public MainForm()
    {
        InitializeComponent();
        InitializeMainForm();
    }

    private void InitializeMainForm()
    {
        // 设置窗体基本属性
        this.Text = "EVE Assistant";
        this.WindowState = FormWindowState.Maximized;
        this.MinimumSize = new Size(800, 600);
        
        // 初始化各个组件
        InitializeMenuStrip();
        InitializeToolStrip();
        InitializeMainPanel();
        InitializeStatusStrip();
    }
}
```

## 2. 菜单栏实现

```csharp
private void InitializeMenuStrip()
{
    mainMenuStrip = new MenuStrip();

    // 文件菜单
    var fileMenu = new ToolStripMenuItem("文件(&F)");
    fileMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("新建(&N)", null, OnNewFile),
        new ToolStripMenuItem("保存(&S)", null, OnSaveFile),
        new ToolStripSeparator(),
        new ToolStripMenuItem("退出(&X)", null, OnExit)
    });

    // 市场菜单
    var marketMenu = new ToolStripMenuItem("市场(&M)");
    marketMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("市场查询", null, OnMarketSearch),
        new ToolStripMenuItem("订单管理", null, OnOrderManagement),
        new ToolStripMenuItem("价格分析", null, OnPriceAnalysis)
    });

    // 制造菜单
    var manufacturingMenu = new ToolStripMenuItem("制造(&P)");
    manufacturingMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("制造计算器", null, OnManufacturing),
        new ToolStripMenuItem("蓝图管理", null, OnBlueprintManagement),
        new ToolStripMenuItem("材料计算", null, OnMaterialCalculation)
    });

    // 资产菜单
    var assetsMenu = new ToolStripMenuItem("资产(&A)");
    assetsMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("资产概览", null, OnAssetsOverview),
        new ToolStripMenuItem("库存管理", null, OnInventoryManagement)
    });

    // 设置菜单
    var settingsMenu = new ToolStripMenuItem("设置(&S)");
    settingsMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("程序设置", null, OnSettings),
        new ToolStripMenuItem("数据更新", null, OnDataUpdate)
    });

    // 添加所有菜单项到菜单栏
    mainMenuStrip.Items.AddRange(new ToolStripItem[]
    {
        fileMenu,
        marketMenu,
        manufacturingMenu,
        assetsMenu,
        settingsMenu
    });

    this.Controls.Add(mainMenuStrip);
}
```

## 3. 工具栏实现

```csharp
private void InitializeToolStrip()
{
    toolStrip = new ToolStrip();
    
    // 添加常用功能按钮
    toolStrip.Items.AddRange(new ToolStripItem[]
    {
        new ToolStripButton("市场查询", null, OnMarketSearch),
        new ToolStripButton("制造", null, OnManufacturing),
        new ToolStripButton("资产", null, OnAssetsOverview),
        new ToolStripSeparator(),
        new ToolStripButton("设置", null, OnSettings)
    });

    this.Controls.Add(toolStrip);
}
```

## 4. 主面板实现

```csharp
private void InitializeMainPanel()
{
    mainPanel = new Panel
    {
        Dock = DockStyle.Fill,
        AutoScroll = true
    };

    // 创建欢迎页面或默认视图
    CreateWelcomeView();
    
    this.Controls.Add(mainPanel);
}

private void CreateWelcomeView()
{
    var welcomeLabel = new Label
    {
        Text = "欢迎使用 EVE Assistant",
        Font = new Font("Microsoft YaHei", 24F, FontStyle.Bold),
        AutoSize = true,
        TextAlign = ContentAlignment.MiddleCenter
    };

    // 居中显示欢迎文本
    welcomeLabel.Location = new Point(
        (mainPanel.Width - welcomeLabel.Width) / 2,
        (mainPanel.Height - welcomeLabel.Height) / 2
    );

    mainPanel.Controls.Add(welcomeLabel);
}
```

## 5. 状态栏实现

```csharp
private void InitializeStatusStrip()
{
    statusStrip = new StatusStrip();

    // 添加状态信息
    var statusLabel = new ToolStripStatusLabel("就绪");
    var timeLabel = new ToolStripStatusLabel();
    
    // 更新时间显示
    Timer timer = new Timer();
    timer.Interval = 1000;
    timer.Tick += (s, e) => 
    {
        timeLabel.Text = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
    };
    timer.Start();

    statusStrip.Items.AddRange(new ToolStripItem[]
    {
        statusLabel,
        new ToolStripStatusLabel("|"),
        timeLabel
    });

    this.Controls.Add(statusStrip);
}
```

## 6. 事件处理方法

```csharp
// 菜单事件处理方法
private void OnNewFile(object sender, EventArgs e)
{
    // 实现新建文件功能
}

private void OnSaveFile(object sender, EventArgs e)
{
    // 实现保存功能
}

private void OnExit(object sender, EventArgs e)
{
    if (MessageBox.Show("确定要退出程序吗？", "确认", 
        MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
    {
        Application.Exit();
    }
}

private void OnMarketSearch(object sender, EventArgs e)
{
    // 打开市场查询窗体
    var marketForm = new MarketSearchForm();
    OpenChildForm(marketForm);
}

// 子窗体管理
private Form activeForm = null;
private void OpenChildForm(Form childForm)
{
    if (activeForm != null)
    {
        activeForm.Close();
    }
    
    activeForm = childForm;
    childForm.TopLevel = false;
    childForm.FormBorderStyle = FormBorderStyle.None;
    childForm.Dock = DockStyle.Fill;
    
    mainPanel.Controls.Clear();
    mainPanel.Controls.Add(childForm);
    childForm.Show();
}
```

## 7. 主题和样式设置

```csharp
private void ApplyTheme()
{
    // 设置窗体主题颜色
    this.BackColor = Color.FromArgb(45, 45, 48);
    mainMenuStrip.BackColor = Color.FromArgb(45, 45, 48);
    mainMenuStrip.ForeColor = Color.White;
    toolStrip.BackColor = Color.FromArgb(45, 45, 48);
    toolStrip.ForeColor = Color.White;
    
    // 设置菜单项样式
    foreach (ToolStripMenuItem item in mainMenuStrip.Items)
    {
        SetMenuItemStyle(item);
    }
}

private void SetMenuItemStyle(ToolStripMenuItem item)
{
    item.BackColor = Color.FromArgb(45, 45, 48);
    item.ForeColor = Color.White;
    
    foreach (ToolStripItem subItem in item.DropDownItems)
    {
        if (subItem is ToolStripMenuItem)
        {
            SetMenuItemStyle(subItem as ToolStripMenuItem);
        }
    }
}
```

## 8. 完整的主窗体类

```csharp
public partial class MainForm : Form
{
    // ... 前面定义的所有字段 ...

    public MainForm()
    {
        InitializeComponent();
        InitializeMainForm();
        ApplyTheme();
    }

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        // 加载用户设置
        LoadUserSettings();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        // 保存用户设置
        SaveUserSettings();
    }

    private void LoadUserSettings()
    {
        // 从配置文件加载用户设置
        try
        {
            // 实现配置加载逻辑
        }
        catch (Exception ex)
        {
            MessageBox.Show($"加载配置失败: {ex.Message}", "错误",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void SaveUserSettings()
    {
        // 保存用户设置到配置文件
        try
        {
            // 实现配置保存逻辑
        }
        catch (Exception ex)
        {
            MessageBox.Show($"保存配置失败: {ex.Message}", "错误",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    // ... 前面实现的所有方法 ...
}
```

## 使用说明

1. 创建项目时，将上述代码保存在 `Forms/MainForm/MainForm.cs` 文件中
2. 确保添加必要的引用：
```csharp
using System;
using System.Drawing;
using System.Windows.Forms;
```

3. 在 `Program.cs` 中设置启动窗体：
```csharp
static class Program
{
    [STAThread]
    static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
    }
}
```

这个主窗体设计提供了：
- 完整的菜单系统
- 工具栏快捷访问
- 状态栏信息显示
- 主题样式支持
- 子窗体管理
- 配置保存/加载
- 专业的界面布局

您可以根据需要进一步扩展和修改这个基础框架。

```csharp
// Forms/MainForm/MainForm.cs
public partial class MainForm : Form
{
    private Panel mainPanel;           // 主内容面板
    private MenuStrip mainMenuStrip;   // 主菜单栏
    private StatusStrip statusStrip;   // 状态栏
    private ToolStrip toolStrip;       // 工具栏
    
    public MainForm()
    {
        InitializeComponent();
        InitializeMainForm();
    }

    private void InitializeMainForm()
    {
        // 设置窗体基本属性
        this.Text = "EVE Assistant";
        this.WindowState = FormWindowState.Maximized;
        this.MinimumSize = new Size(800, 600);
        
        // 初始化各个组件
        InitializeMenuStrip();
        InitializeToolStrip();
        InitializeMainPanel();
        InitializeStatusStrip();
    }
}
```

```csharp
private void InitializeMenuStrip()
{
    mainMenuStrip = new MenuStrip();

    // 文件菜单
    var fileMenu = new ToolStripMenuItem("文件(&F)");
    fileMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("新建(&N)", null, OnNewFile),
        new ToolStripMenuItem("保存(&S)", null, OnSaveFile),
        new ToolStripSeparator(),
        new ToolStripMenuItem("退出(&X)", null, OnExit)
    });

    // 市场菜单
    var marketMenu = new ToolStripMenuItem("市场(&M)");
    marketMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("市场查询", null, OnMarketSearch),
        new ToolStripMenuItem("订单管理", null, OnOrderManagement),
        new ToolStripMenuItem("价格分析", null, OnPriceAnalysis)
    });

    // 制造菜单
    var manufacturingMenu = new ToolStripMenuItem("制造(&P)");
    manufacturingMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("制造计算器", null, OnManufacturing),
        new ToolStripMenuItem("蓝图管理", null, OnBlueprintManagement),
        new ToolStripMenuItem("材料计算", null, OnMaterialCalculation)
    });

    // 资产菜单
    var assetsMenu = new ToolStripMenuItem("资产(&A)");
    assetsMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("资产概览", null, OnAssetsOverview),
        new ToolStripMenuItem("库存管理", null, OnInventoryManagement)
    });

    // 设置菜单
    var settingsMenu = new ToolStripMenuItem("设置(&S)");
    settingsMenu.DropDownItems.AddRange(new ToolStripItem[]
    {
        new ToolStripMenuItem("程序设置", null, OnSettings),
        new ToolStripMenuItem("数据更新", null, OnDataUpdate)
    });

    // 添加所有菜单项到菜单栏
    mainMenuStrip.Items.AddRange(new ToolStripItem[]
    {
        fileMenu,
        marketMenu,
        manufacturingMenu,
        assetsMenu,
        settingsMenu
    });

    this.Controls.Add(mainMenuStrip);
}
```

```csharp
private void InitializeToolStrip()
{
    toolStrip = new ToolStrip();
    
    // 添加常用功能按钮
    toolStrip.Items.AddRange(new ToolStripItem[]
    {
        new ToolStripButton("市场查询", null, OnMarketSearch),
        new ToolStripButton("制造", null, OnManufacturing),
        new ToolStripButton("资产", null, OnAssetsOverview),
        new ToolStripSeparator(),
        new ToolStripButton("设置", null, OnSettings)
    });

    this.Controls.Add(toolStrip);
}
```

```csharp
private void InitializeMainPanel()
{
    mainPanel = new Panel
    {
        Dock = DockStyle.Fill,
        AutoScroll = true
    };

    // 创建欢迎页面或默认视图
    CreateWelcomeView();
    
    this.Controls.Add(mainPanel);
}

private void CreateWelcomeView()
{
    var welcomeLabel = new Label
    {
        Text = "欢迎使用 EVE Assistant",
        Font = new Font("Microsoft YaHei", 24F, FontStyle.Bold),
        AutoSize = true,
        TextAlign = ContentAlignment.MiddleCenter
    };

    // 居中显示欢迎文本
    welcomeLabel.Location = new Point(
        (mainPanel.Width - welcomeLabel.Width) / 2,
        (mainPanel.Height - welcomeLabel.Height) / 2
    );

    mainPanel.Controls.Add(welcomeLabel);
}
```

```csharp
private void InitializeStatusStrip()
{
    statusStrip = new StatusStrip();

    // 添加状态信息
    var statusLabel = new ToolStripStatusLabel("就绪");
    var timeLabel = new ToolStripStatusLabel();
    
    // 更新时间显示
    Timer timer = new Timer();
    timer.Interval = 1000;
    timer.Tick += (s, e) => 
    {
        timeLabel.Text = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
    };
    timer.Start();

    statusStrip.Items.AddRange(new ToolStripItem[]
    {
        statusLabel,
        new ToolStripStatusLabel("|"),
        timeLabel
    });

    this.Controls.Add(statusStrip);
}
```

```csharp
// 菜单事件处理方法
private void OnNewFile(object sender, EventArgs e)
{
    // 实现新建文件功能
}

private void OnSaveFile(object sender, EventArgs e)
{
    // 实现保存功能
}

private void OnExit(object sender, EventArgs e)
{
    if (MessageBox.Show("确定要退出程序吗？", "确认", 
        MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
    {
        Application.Exit();
    }
}

private void OnMarketSearch(object sender, EventArgs e)
{
    // 打开市场查询窗体
    var marketForm = new MarketSearchForm();
    OpenChildForm(marketForm);
}

// 子窗体管理
private Form activeForm = null;
private void OpenChildForm(Form childForm)
{
    if (activeForm != null)
    {
        activeForm.Close();
    }
    
    activeForm = childForm;
    childForm.TopLevel = false;
    childForm.FormBorderStyle = FormBorderStyle.None;
    childForm.Dock = DockStyle.Fill;
    
    mainPanel.Controls.Clear();
    mainPanel.Controls.Add(childForm);
    childForm.Show();
}
```

```csharp
private void ApplyTheme()
{
    // 设置窗体主题颜色
    this.BackColor = Color.FromArgb(45, 45, 48);
    mainMenuStrip.BackColor = Color.FromArgb(45, 45, 48);
    mainMenuStrip.ForeColor = Color.White;
    toolStrip.BackColor = Color.FromArgb(45, 45, 48);
    toolStrip.ForeColor = Color.White;
    
    // 设置菜单项样式
    foreach (ToolStripMenuItem item in mainMenuStrip.Items)
    {
        SetMenuItemStyle(item);
    }
}

private void SetMenuItemStyle(ToolStripMenuItem item)
{
    item.BackColor = Color.FromArgb(45, 45, 48);
    item.ForeColor = Color.White;
    
    foreach (ToolStripItem subItem in item.DropDownItems)
    {
        if (subItem is ToolStripMenuItem)
        {
            SetMenuItemStyle(subItem as ToolStripMenuItem);
        }
    }
}
```

```csharp
public partial class MainForm : Form
{
    // ... 前面定义的所有字段 ...

    public MainForm()
    {
        InitializeComponent();
        InitializeMainForm();
        ApplyTheme();
    }

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        // 加载用户设置
        LoadUserSettings();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        // 保存用户设置
        SaveUserSettings();
    }

    private void LoadUserSettings()
    {
        // 从配置文件加载用户设置
        try
        {
            // 实现配置加载逻辑
        }
        catch (Exception ex)
        {
            MessageBox.Show($"加载配置失败: {ex.Message}", "错误",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void SaveUserSettings()
    {
        // 保存用户设置到配置文件
        try
        {
            // 实现配置保存逻辑
        }
        catch (Exception ex)
        {
            MessageBox.Show($"保存配置失败: {ex.Message}", "错误",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    // ... 前面实现的所有方法 ...
}
```

```csharp
using System;
using System.Drawing;
using System.Windows.Forms;
```

```csharp
static class Program
{
    [STAThread]
    static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
    }
}
```

---

**User**

给出完整的代码

---

**Cursor**

我将为您提供一个完整的主窗体实现代码。我们将创建以下文件：

1. 首先创建必要的文件夹结构：
```
EVE_Assistant/
├── src/
│   ├── Forms/
│   │   └── MainForm/
│   ├── Models/
│   ├── Services/
│   └── Utils/
```

## 1. 主程序入口 (Program.cs)

```csharp
using System;
using System.Windows.Forms;

namespace EVE_Assistant
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }
}
```

## 2. 主窗体 (MainForm.cs)

```csharp
using System;
using System.Drawing;
using System.Windows.Forms;
using System.Configuration;
using System.Collections.Generic;

namespace EVE_Assistant
{
    public partial class MainForm : Form
    {
        #region Fields
        private Panel mainPanel;
        private MenuStrip mainMenuStrip;
        private StatusStrip statusStrip;
        private ToolStrip toolStrip;
        private Form activeForm;
        private Dictionary<string, Form> formCache;
        #endregion

        #region Constructor
        public MainForm()
        {
            InitializeComponent();
            formCache = new Dictionary<string, Form>();
            InitializeMainForm();
            ApplyTheme();
        }
        #endregion

        #region Initialization Methods
        private void InitializeMainForm()
        {
            // 设置窗体基本属性
            this.Text = "EVE Assistant";
            this.WindowState = FormWindowState.Maximized;
            this.MinimumSize = new Size(1024, 768);
            this.Icon = Properties.Resources.AppIcon; // 需要添加图标资源

            // 初始化各个组件
            InitializeMenuStrip();
            InitializeToolStrip();
            InitializeMainPanel();
            InitializeStatusStrip();
        }

        private void InitializeMenuStrip()
        {
            mainMenuStrip = new MenuStrip();
            mainMenuStrip.Renderer = new CustomMenuRenderer();

            // 文件菜单
            var fileMenu = CreateMenuItem("文件(&F)", new[]
            {
                CreateMenuItem("新建(&N)", OnNewFile, Keys.Control | Keys.N),
                CreateMenuItem("保存(&S)", OnSaveFile, Keys.Control | Keys.S),
                new ToolStripSeparator(),
                CreateMenuItem("退出(&X)", OnExit, Keys.Alt | Keys.F4)
            });

            // 市场菜单
            var marketMenu = CreateMenuItem("市场(&M)", new[]
            {
                CreateMenuItem("市场查询", OnMarketSearch),
                CreateMenuItem("订单管理", OnOrderManagement),
                CreateMenuItem("价格分析", OnPriceAnalysis)
            });

            // 制造菜单
            var manufacturingMenu = CreateMenuItem("制造(&P)", new[]
            {
                CreateMenuItem("制造计算器", OnManufacturing),
                CreateMenuItem("蓝图管理", OnBlueprintManagement),
                CreateMenuItem("材料计算", OnMaterialCalculation)
            });

            // 资产菜单
            var assetsMenu = CreateMenuItem("资产(&A)", new[]
            {
                CreateMenuItem("资产概览", OnAssetsOverview),
                CreateMenuItem("库存管理", OnInventoryManagement)
            });

            // 设置菜单
            var settingsMenu = CreateMenuItem("设置(&S)", new[]
            {
                CreateMenuItem("程序设置", OnSettings),
                CreateMenuItem("数据更新", OnDataUpdate)
            });

            // 帮助菜单
            var helpMenu = CreateMenuItem("帮助(&H)", new[]
            {
                CreateMenuItem("查看帮助", OnHelp, Keys.F1),
                CreateMenuItem("检查更新", OnCheckUpdate),
                new ToolStripSeparator(),
                CreateMenuItem("关于", OnAbout)
            });

            mainMenuStrip.Items.AddRange(new ToolStripItem[]
            {
                fileMenu,
                marketMenu,
                manufacturingMenu,
                assetsMenu,
                settingsMenu,
                helpMenu
            });

            this.Controls.Add(mainMenuStrip);
        }

        private void InitializeToolStrip()
        {
            toolStrip = new ToolStrip();
            toolStrip.Renderer = new CustomToolStripRenderer();

            // 添加工具栏按钮
            toolStrip.Items.AddRange(new ToolStripItem[]
            {
                CreateToolStripButton("市场查询", OnMarketSearch, Properties.Resources.Market),
                CreateToolStripButton("制造", OnManufacturing, Properties.Resources.Manufacturing),
                CreateToolStripButton("资产", OnAssetsOverview, Properties.Resources.Assets),
                new ToolStripSeparator(),
                CreateToolStripButton("设置", OnSettings, Properties.Resources.Settings)
            });

            this.Controls.Add(toolStrip);
        }

        private void InitializeMainPanel()
        {
            mainPanel = new Panel
            {
                Dock = DockStyle.Fill,
                AutoScroll = true,
                BackColor = Color.FromArgb(28, 28, 30)
            };

            CreateWelcomeView();
            this.Controls.Add(mainPanel);
        }

        private void InitializeStatusStrip()
        {
            statusStrip = new StatusStrip();
            statusStrip.BackColor = Color.FromArgb(45, 45, 48);

            var statusLabel = new ToolStripStatusLabel("就绪");
            var serverStatusLabel = new ToolStripStatusLabel("服务器状态: 在线");
            var timeLabel = new ToolStripStatusLabel();

            // 更新时间显示
            Timer timer = new Timer();
            timer.Interval = 1000;
            timer.Tick += (s, e) =>
            {
                timeLabel.Text = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
            };
            timer.Start();

            statusStrip.Items.AddRange(new ToolStripItem[]
            {
                statusLabel,
                new ToolStripStatusLabel("|"),
                serverStatusLabel,
                new ToolStripStatusLabel("|"),
                timeLabel
            });

            this.Controls.Add(statusStrip);
        }
        #endregion

        #region Helper Methods
        private ToolStripMenuItem CreateMenuItem(string text, EventHandler onClick = null, Keys shortcut = Keys.None)
        {
            var item = new ToolStripMenuItem(text);
            if (onClick != null)
                item.Click += onClick;
            if (shortcut != Keys.None)
                item.ShortcutKeys = shortcut;
            return item;
        }

        private ToolStripMenuItem CreateMenuItem(string text, ToolStripItem[] dropDownItems)
        {
            var item = new ToolStripMenuItem(text);
            item.DropDownItems.AddRange(dropDownItems);
            return item;
        }

        private ToolStripButton CreateToolStripButton(string text, EventHandler onClick, Image image)
        {
            return new ToolStripButton(text, image, onClick)
            {
                DisplayStyle = ToolStripItemDisplayStyle.ImageAndText,
                ImageScaling = ToolStripItemImageScaling.None
            };
        }

        private void CreateWelcomeView()
        {
            var welcomePanel = new Panel
            {
                Dock = DockStyle.Fill,
                BackColor = Color.FromArgb(28, 28, 30)
            };

            var welcomeLabel = new Label
            {
                Text = "欢迎使用 EVE Assistant",
                Font = new Font("Microsoft YaHei", 24F, FontStyle.Bold),
                ForeColor = Color.White,
                AutoSize = true,
                TextAlign = ContentAlignment.MiddleCenter
            };

            var versionLabel = new Label
            {
                Text = $"版本 {Application.ProductVersion}",
                Font = new Font("Microsoft YaHei", 12F),
                ForeColor = Color.Gray,
                AutoSize = true,
                TextAlign = ContentAlignment.MiddleCenter
            };

            // 居中显示欢迎文本
            welcomeLabel.Location = new Point(
                (mainPanel.Width - welcomeLabel.Width) / 2,
                (mainPanel.Height - welcomeLabel.Height) / 2
            );

            versionLabel.Location = new Point(
                (mainPanel.Width - versionLabel.Width) / 2,
                welcomeLabel.Bottom + 10
            );

            welcomePanel.Controls.AddRange(new Control[] { welcomeLabel, versionLabel });
            mainPanel.Controls.Add(welcomePanel);
        }
        #endregion

        #region Event Handlers
        private void OnNewFile(object sender, EventArgs e)
        {
            MessageBox.Show("新建文件功能待实现", "提示");
        }

        private void OnSaveFile(object sender, EventArgs e)
        {
            MessageBox.Show("保存功能待实现", "提示");
        }

        private void OnExit(object sender, EventArgs e)
        {
            if (MessageBox.Show("确定要退出程序吗？", "确认",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                Application.Exit();
            }
        }

        private void OnMarketSearch(object sender, EventArgs e)
        {
            OpenChildForm("MarketSearch", () => new MarketSearchForm());
        }

        private void OnOrderManagement(object sender, EventArgs e)
        {
            OpenChildForm("OrderManagement", () => new OrderManagementForm());
        }

        private void OnPriceAnalysis(object sender, EventArgs e)
        {
            OpenChildForm("PriceAnalysis", () => new PriceAnalysisForm());
        }

        private void OnManufacturing(object sender, EventArgs e)
        {
            OpenChildForm("Manufacturing", () => new ManufacturingForm());
        }

        private void OnBlueprintManagement(object sender, EventArgs e)
        {
            OpenChildForm("BlueprintManagement", () => new BlueprintManagementForm());
        }

        private void OnMaterialCalculation(object sender, EventArgs e)
        {
            OpenChildForm("MaterialCalculation", () => new MaterialCalculationForm());
        }

        private void OnAssetsOverview(object sender, EventArgs e)
        {
            OpenChildForm("AssetsOverview", () => new AssetsOverviewForm());
        }

        private void OnInventoryManagement(object sender, EventArgs e)
        {
            OpenChildForm("InventoryManagement", () => new InventoryManagementForm());
        }

        private void OnSettings(object sender, EventArgs e)
        {
            OpenChildForm("Settings", () => new SettingsForm());
        }

        private void OnDataUpdate(object sender, EventArgs e)
        {
            OpenChildForm("DataUpdate", () => new DataUpdateForm());
        }

        private void OnHelp(object sender, EventArgs e)
        {
            System.Diagnostics.Process.Start("https://wiki.eveassistant.com");
        }

        private void OnCheckUpdate(object sender, EventArgs e)
        {
            MessageBox.Show("检查更新功能待实现", "提示");
        }

        private void OnAbout(object sender, EventArgs e)
        {
            MessageBox.Show(
                "EVE Assistant\n" +
                $"版本: {Application.ProductVersion}\n" +
                "作者: Your Name\n" +
                "Copyright © 2024",
                "关于",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );
        }
        #endregion

        #region Form Management
        private void OpenChildForm(string formKey, Func<Form> formFactory)
        {
            if (activeForm != null)
            {
                activeForm.Hide();
            }

            if (!formCache.ContainsKey(formKey))
            {
                formCache[formKey] = formFactory();
                Form childForm = formCache[formKey];
                childForm.TopLevel = false;
                childForm.FormBorderStyle = FormBorderStyle.None;
                childForm.Dock = DockStyle.Fill;
                mainPanel.Controls.Add(childForm);
            }

            activeForm = formCache[formKey];
            activeForm.Show();
            activeForm.BringToFront();
        }
        #endregion

        #region Theme
        private void ApplyTheme()
        {
            // 主窗体
            this.BackColor = Color.FromArgb(28, 28, 30);
            
            // 菜单栏
            mainMenuStrip.BackColor = Color.FromArgb(45, 45, 48);
            mainMenuStrip.ForeColor = Color.White;

            // 工具栏
            toolStrip.BackColor = Color.FromArgb(45, 45, 48);
            toolStrip.ForeColor = Color.White;

            // 状态栏
            statusStrip.BackColor = Color.FromArgb(45, 45, 48);
            statusStrip.ForeColor = Color.White;

            // 应用菜单样式
            foreach (ToolStripMenuItem item in mainMenuStrip.Items)
            {
                SetMenuItemStyle(item);
            }
        }

        private void SetMenuItemStyle(ToolStripMenuItem item)
        {
            item.BackColor = Color.FromArgb(45, 45, 48);
            item.ForeColor = Color.White;

            foreach (ToolStripItem subItem in item.DropDownItems)
            {
                if (subItem is ToolStripMenuItem)
                {
                    SetMenuItemStyle(subItem as ToolStripMenuItem);
                }
            }
        }
        #endregion

        #region Settings
        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            LoadUserSettings();
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            base.OnFormClosing(e);
            SaveUserSettings();
        }

        private void LoadUserSettings()
        {
            try
            {
                // 从配置文件加载设置
                if (Properties.Settings.Default.WindowState != FormWindowState.Minimized)
                {
                    this.WindowState = Properties.Settings.Default.WindowState;
                }
                if (this.WindowState == FormWindowState.Normal)
                {
                    this.Size = Properties.Settings.Default.WindowSize;
                    this.Location = Properties.Settings.Default.WindowLocation;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"加载配置失败: {ex.Message}", "错误",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void SaveUserSettings()
        {
            try
            {
                // 保存窗体状态
                Properties.Settings.Default.WindowState = this.WindowState;
                if (this.WindowState == FormWindowState.Normal)
                {
                    Properties.Settings.Default.WindowSize = this.Size;
                    Properties.Settings.Default.WindowLocation = this.Location;
                }
                Properties.Settings.Default.Save();
            }
            catch (Exception ex)
            {
                MessageBox.Show($"保存配置失败: {ex.Message}", "错误",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        #endregion
    }

    #region Custom Renderers
    public class CustomMenuRenderer : ToolStripProfessionalRenderer
    {
        public CustomMenuRenderer() : base(new CustomColorTable()) { }

        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e)
        {
            if (!e.Item.Selected)
                base.OnRenderMenuItemBackground(e);
            else
            {
                var rc = new Rectangle(Point.Empty, e.Item.Size);
                using (var brush = new SolidBrush(Color.FromArgb(63, 63, 70)))
                {
                    e.Graphics.FillRectangle(brush, rc);
                }
            }
        }
    }

    public class CustomColorTable : ProfessionalColorTable
    {
        public override Color MenuItemSelected
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemSelectedGradientBegin
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemSelectedGradientEnd
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemPressedGradientBegin
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemPressedGradientEnd
        {
            get { return Color.FromArgb(63, 63, 70); }
        }
    }

    public class CustomToolStripRenderer : ToolStripProfessionalRenderer
    {
        public CustomToolStripRenderer() : base(new CustomColorTable()) { }

        protected override void OnRenderButtonBackground(ToolStripItemRenderEventArgs e)
        {
            if (!e.Item.Selected)
                base.OnRenderButtonBackground(e);
            else
            {
                var rc = new Rectangle(Point.Empty, e.Item.Size);
                using (var brush = new SolidBrush(Color.FromArgb(63, 63, 70)))
                {
                    e.Graphics.FillRectangle(brush, rc);
                }
            }
        }
    }
    #endregion
}
```

## 3. 应用程序设置 (App.config)

```xml
<?xml version="1.0" encoding="utf-8" ?>
<configuration>
    <configSections>
        <sectionGroup name="userSettings" type="System.Configuration.UserSettingsGroup, System, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089" >
            <section name="EVE_Assistant.Properties.Settings" type="System.Configuration.ClientSettingsSection, System, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089" allowExeDefinition="MachineToLocalUser" requirePermission="false" />
        </sectionGroup>
    </configSections>
    <startup> 
        <supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.7.2" />
    </startup>
    <userSettings>
        <EVE_Assistant.Properties.Settings>
            <setting name="WindowState" serializeAs="String">
                <value>Normal</value>
            </setting>
            <setting name="WindowSize" serializeAs="String">
                <value>1024, 768</value>
            </setting>
            <setting name="WindowLocation" serializeAs="String">
                <value>100, 100</value>
            </setting>
        </EVE_Assistant.Properties.Settings>
    </userSettings>
</configuration>
```

## 4. 用户设置类 (Settings.cs)

```csharp
namespace EVE_Assistant.Properties {
    internal sealed partial class Settings {
        public Settings() {
            // // 要添加事件处理程序以在设置更改时保存设置，请取消注释下面的行：
            // this.SettingChanging += this.SettingChangingEventHandler;
        }
        
        private void SettingChangingEventHandler(object sender, System.Configuration.SettingChangingEventArgs e) {
            // 在此处添加用于处理 SettingChangingEvent 事件的代码。
        }
    }
}
```

## 5. 资源文件

在项目中添加Resources.resx文件，包含以下资源：
- AppIcon.ico - 应用程序图标
- Market.png - 市场图标
- Manufacturing.png - 制造图标
- Assets.png - 资产图标
- Settings.png - 设置图标

## 使用说明

1. 创建新的Windows Forms项目
2. 将上述代码复制到相应的文件中
3. 添加必要的资源文件
4. 编译运行项目

这个实现提供了：
- 完整的主窗体框架
- 主题支持
- 窗体状态保存/恢复
- 子窗体缓存管理
- 自定义菜单渲染
- 完整的事件处理系统

注意：
1. 需要实现各个子窗体（如MarketSearchForm等）
2. 需要添加相应的图标资源
3. 可能需要根据实际需求调整主题颜色
4. 可能需要添加更多的功能模块

这个框架可以作为开发EVE辅助工具的良好起点，您可以根据需要继续扩展功能。

```plaintext
EVE_Assistant/
├── src/
│   ├── Forms/
│   │   └── MainForm/
│   ├── Models/
│   ├── Services/
│   └── Utils/
```

```csharp
using System;
using System.Windows.Forms;

namespace EVE_Assistant
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }
}
```

```csharp
using System;
using System.Drawing;
using System.Windows.Forms;
using System.Configuration;
using System.Collections.Generic;

namespace EVE_Assistant
{
    public partial class MainForm : Form
    {
        #region Fields
        private Panel mainPanel;
        private MenuStrip mainMenuStrip;
        private StatusStrip statusStrip;
        private ToolStrip toolStrip;
        private Form activeForm;
        private Dictionary<string, Form> formCache;
        #endregion

        #region Constructor
        public MainForm()
        {
            InitializeComponent();
            formCache = new Dictionary<string, Form>();
            InitializeMainForm();
            ApplyTheme();
        }
        #endregion

        #region Initialization Methods
        private void InitializeMainForm()
        {
            // 设置窗体基本属性
            this.Text = "EVE Assistant";
            this.WindowState = FormWindowState.Maximized;
            this.MinimumSize = new Size(1024, 768);
            this.Icon = Properties.Resources.AppIcon; // 需要添加图标资源

            // 初始化各个组件
            InitializeMenuStrip();
            InitializeToolStrip();
            InitializeMainPanel();
            InitializeStatusStrip();
        }

        private void InitializeMenuStrip()
        {
            mainMenuStrip = new MenuStrip();
            mainMenuStrip.Renderer = new CustomMenuRenderer();

            // 文件菜单
            var fileMenu = CreateMenuItem("文件(&F)", new[]
            {
                CreateMenuItem("新建(&N)", OnNewFile, Keys.Control | Keys.N),
                CreateMenuItem("保存(&S)", OnSaveFile, Keys.Control | Keys.S),
                new ToolStripSeparator(),
                CreateMenuItem("退出(&X)", OnExit, Keys.Alt | Keys.F4)
            });

            // 市场菜单
            var marketMenu = CreateMenuItem("市场(&M)", new[]
            {
                CreateMenuItem("市场查询", OnMarketSearch),
                CreateMenuItem("订单管理", OnOrderManagement),
                CreateMenuItem("价格分析", OnPriceAnalysis)
            });

            // 制造菜单
            var manufacturingMenu = CreateMenuItem("制造(&P)", new[]
            {
                CreateMenuItem("制造计算器", OnManufacturing),
                CreateMenuItem("蓝图管理", OnBlueprintManagement),
                CreateMenuItem("材料计算", OnMaterialCalculation)
            });

            // 资产菜单
            var assetsMenu = CreateMenuItem("资产(&A)", new[]
            {
                CreateMenuItem("资产概览", OnAssetsOverview),
                CreateMenuItem("库存管理", OnInventoryManagement)
            });

            // 设置菜单
            var settingsMenu = CreateMenuItem("设置(&S)", new[]
            {
                CreateMenuItem("程序设置", OnSettings),
                CreateMenuItem("数据更新", OnDataUpdate)
            });

            // 帮助菜单
            var helpMenu = CreateMenuItem("帮助(&H)", new[]
            {
                CreateMenuItem("查看帮助", OnHelp, Keys.F1),
                CreateMenuItem("检查更新", OnCheckUpdate),
                new ToolStripSeparator(),
                CreateMenuItem("关于", OnAbout)
            });

            mainMenuStrip.Items.AddRange(new ToolStripItem[]
            {
                fileMenu,
                marketMenu,
                manufacturingMenu,
                assetsMenu,
                settingsMenu,
                helpMenu
            });

            this.Controls.Add(mainMenuStrip);
        }

        private void InitializeToolStrip()
        {
            toolStrip = new ToolStrip();
            toolStrip.Renderer = new CustomToolStripRenderer();

            // 添加工具栏按钮
            toolStrip.Items.AddRange(new ToolStripItem[]
            {
                CreateToolStripButton("市场查询", OnMarketSearch, Properties.Resources.Market),
                CreateToolStripButton("制造", OnManufacturing, Properties.Resources.Manufacturing),
                CreateToolStripButton("资产", OnAssetsOverview, Properties.Resources.Assets),
                new ToolStripSeparator(),
                CreateToolStripButton("设置", OnSettings, Properties.Resources.Settings)
            });

            this.Controls.Add(toolStrip);
        }

        private void InitializeMainPanel()
        {
            mainPanel = new Panel
            {
                Dock = DockStyle.Fill,
                AutoScroll = true,
                BackColor = Color.FromArgb(28, 28, 30)
            };

            CreateWelcomeView();
            this.Controls.Add(mainPanel);
        }

        private void InitializeStatusStrip()
        {
            statusStrip = new StatusStrip();
            statusStrip.BackColor = Color.FromArgb(45, 45, 48);

            var statusLabel = new ToolStripStatusLabel("就绪");
            var serverStatusLabel = new ToolStripStatusLabel("服务器状态: 在线");
            var timeLabel = new ToolStripStatusLabel();

            // 更新时间显示
            Timer timer = new Timer();
            timer.Interval = 1000;
            timer.Tick += (s, e) =>
            {
                timeLabel.Text = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
            };
            timer.Start();

            statusStrip.Items.AddRange(new ToolStripItem[]
            {
                statusLabel,
                new ToolStripStatusLabel("|"),
                serverStatusLabel,
                new ToolStripStatusLabel("|"),
                timeLabel
            });

            this.Controls.Add(statusStrip);
        }
        #endregion

        #region Helper Methods
        private ToolStripMenuItem CreateMenuItem(string text, EventHandler onClick = null, Keys shortcut = Keys.None)
        {
            var item = new ToolStripMenuItem(text);
            if (onClick != null)
                item.Click += onClick;
            if (shortcut != Keys.None)
                item.ShortcutKeys = shortcut;
            return item;
        }

        private ToolStripMenuItem CreateMenuItem(string text, ToolStripItem[] dropDownItems)
        {
            var item = new ToolStripMenuItem(text);
            item.DropDownItems.AddRange(dropDownItems);
            return item;
        }

        private ToolStripButton CreateToolStripButton(string text, EventHandler onClick, Image image)
        {
            return new ToolStripButton(text, image, onClick)
            {
                DisplayStyle = ToolStripItemDisplayStyle.ImageAndText,
                ImageScaling = ToolStripItemImageScaling.None
            };
        }

        private void CreateWelcomeView()
        {
            var welcomePanel = new Panel
            {
                Dock = DockStyle.Fill,
                BackColor = Color.FromArgb(28, 28, 30)
            };

            var welcomeLabel = new Label
            {
                Text = "欢迎使用 EVE Assistant",
                Font = new Font("Microsoft YaHei", 24F, FontStyle.Bold),
                ForeColor = Color.White,
                AutoSize = true,
                TextAlign = ContentAlignment.MiddleCenter
            };

            var versionLabel = new Label
            {
                Text = $"版本 {Application.ProductVersion}",
                Font = new Font("Microsoft YaHei", 12F),
                ForeColor = Color.Gray,
                AutoSize = true,
                TextAlign = ContentAlignment.MiddleCenter
            };

            // 居中显示欢迎文本
            welcomeLabel.Location = new Point(
                (mainPanel.Width - welcomeLabel.Width) / 2,
                (mainPanel.Height - welcomeLabel.Height) / 2
            );

            versionLabel.Location = new Point(
                (mainPanel.Width - versionLabel.Width) / 2,
                welcomeLabel.Bottom + 10
            );

            welcomePanel.Controls.AddRange(new Control[] { welcomeLabel, versionLabel });
            mainPanel.Controls.Add(welcomePanel);
        }
        #endregion

        #region Event Handlers
        private void OnNewFile(object sender, EventArgs e)
        {
            MessageBox.Show("新建文件功能待实现", "提示");
        }

        private void OnSaveFile(object sender, EventArgs e)
        {
            MessageBox.Show("保存功能待实现", "提示");
        }

        private void OnExit(object sender, EventArgs e)
        {
            if (MessageBox.Show("确定要退出程序吗？", "确认",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                Application.Exit();
            }
        }

        private void OnMarketSearch(object sender, EventArgs e)
        {
            OpenChildForm("MarketSearch", () => new MarketSearchForm());
        }

        private void OnOrderManagement(object sender, EventArgs e)
        {
            OpenChildForm("OrderManagement", () => new OrderManagementForm());
        }

        private void OnPriceAnalysis(object sender, EventArgs e)
        {
            OpenChildForm("PriceAnalysis", () => new PriceAnalysisForm());
        }

        private void OnManufacturing(object sender, EventArgs e)
        {
            OpenChildForm("Manufacturing", () => new ManufacturingForm());
        }

        private void OnBlueprintManagement(object sender, EventArgs e)
        {
            OpenChildForm("BlueprintManagement", () => new BlueprintManagementForm());
        }

        private void OnMaterialCalculation(object sender, EventArgs e)
        {
            OpenChildForm("MaterialCalculation", () => new MaterialCalculationForm());
        }

        private void OnAssetsOverview(object sender, EventArgs e)
        {
            OpenChildForm("AssetsOverview", () => new AssetsOverviewForm());
        }

        private void OnInventoryManagement(object sender, EventArgs e)
        {
            OpenChildForm("InventoryManagement", () => new InventoryManagementForm());
        }

        private void OnSettings(object sender, EventArgs e)
        {
            OpenChildForm("Settings", () => new SettingsForm());
        }

        private void OnDataUpdate(object sender, EventArgs e)
        {
            OpenChildForm("DataUpdate", () => new DataUpdateForm());
        }

        private void OnHelp(object sender, EventArgs e)
        {
            System.Diagnostics.Process.Start("https://wiki.eveassistant.com");
        }

        private void OnCheckUpdate(object sender, EventArgs e)
        {
            MessageBox.Show("检查更新功能待实现", "提示");
        }

        private void OnAbout(object sender, EventArgs e)
        {
            MessageBox.Show(
                "EVE Assistant\n" +
                $"版本: {Application.ProductVersion}\n" +
                "作者: Your Name\n" +
                "Copyright © 2024",
                "关于",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );
        }
        #endregion

        #region Form Management
        private void OpenChildForm(string formKey, Func<Form> formFactory)
        {
            if (activeForm != null)
            {
                activeForm.Hide();
            }

            if (!formCache.ContainsKey(formKey))
            {
                formCache[formKey] = formFactory();
                Form childForm = formCache[formKey];
                childForm.TopLevel = false;
                childForm.FormBorderStyle = FormBorderStyle.None;
                childForm.Dock = DockStyle.Fill;
                mainPanel.Controls.Add(childForm);
            }

            activeForm = formCache[formKey];
            activeForm.Show();
            activeForm.BringToFront();
        }
        #endregion

        #region Theme
        private void ApplyTheme()
        {
            // 主窗体
            this.BackColor = Color.FromArgb(28, 28, 30);
            
            // 菜单栏
            mainMenuStrip.BackColor = Color.FromArgb(45, 45, 48);
            mainMenuStrip.ForeColor = Color.White;

            // 工具栏
            toolStrip.BackColor = Color.FromArgb(45, 45, 48);
            toolStrip.ForeColor = Color.White;

            // 状态栏
            statusStrip.BackColor = Color.FromArgb(45, 45, 48);
            statusStrip.ForeColor = Color.White;

            // 应用菜单样式
            foreach (ToolStripMenuItem item in mainMenuStrip.Items)
            {
                SetMenuItemStyle(item);
            }
        }

        private void SetMenuItemStyle(ToolStripMenuItem item)
        {
            item.BackColor = Color.FromArgb(45, 45, 48);
            item.ForeColor = Color.White;

            foreach (ToolStripItem subItem in item.DropDownItems)
            {
                if (subItem is ToolStripMenuItem)
                {
                    SetMenuItemStyle(subItem as ToolStripMenuItem);
                }
            }
        }
        #endregion

        #region Settings
        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            LoadUserSettings();
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            base.OnFormClosing(e);
            SaveUserSettings();
        }

        private void LoadUserSettings()
        {
            try
            {
                // 从配置文件加载设置
                if (Properties.Settings.Default.WindowState != FormWindowState.Minimized)
                {
                    this.WindowState = Properties.Settings.Default.WindowState;
                }
                if (this.WindowState == FormWindowState.Normal)
                {
                    this.Size = Properties.Settings.Default.WindowSize;
                    this.Location = Properties.Settings.Default.WindowLocation;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"加载配置失败: {ex.Message}", "错误",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void SaveUserSettings()
        {
            try
            {
                // 保存窗体状态
                Properties.Settings.Default.WindowState = this.WindowState;
                if (this.WindowState == FormWindowState.Normal)
                {
                    Properties.Settings.Default.WindowSize = this.Size;
                    Properties.Settings.Default.WindowLocation = this.Location;
                }
                Properties.Settings.Default.Save();
            }
            catch (Exception ex)
            {
                MessageBox.Show($"保存配置失败: {ex.Message}", "错误",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        #endregion
    }

    #region Custom Renderers
    public class CustomMenuRenderer : ToolStripProfessionalRenderer
    {
        public CustomMenuRenderer() : base(new CustomColorTable()) { }

        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e)
        {
            if (!e.Item.Selected)
                base.OnRenderMenuItemBackground(e);
            else
            {
                var rc = new Rectangle(Point.Empty, e.Item.Size);
                using (var brush = new SolidBrush(Color.FromArgb(63, 63, 70)))
                {
                    e.Graphics.FillRectangle(brush, rc);
                }
            }
        }
    }

    public class CustomColorTable : ProfessionalColorTable
    {
        public override Color MenuItemSelected
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemSelectedGradientBegin
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemSelectedGradientEnd
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemPressedGradientBegin
        {
            get { return Color.FromArgb(63, 63, 70); }
        }

        public override Color MenuItemPressedGradientEnd
        {
            get { return Color.FromArgb(63, 63, 70); }
        }
    }

    public class CustomToolStripRenderer : ToolStripProfessionalRenderer
    {
        public CustomToolStripRenderer() : base(new CustomColorTable()) { }

        protected override void OnRenderButtonBackground(ToolStripItemRenderEventArgs e)
        {
            if (!e.Item.Selected)
                base.OnRenderButtonBackground(e);
            else
            {
                var rc = new Rectangle(Point.Empty, e.Item.Size);
                using (var brush = new SolidBrush(Color.FromArgb(63, 63, 70)))
                {
                    e.Graphics.FillRectangle(brush, rc);
                }
            }
        }
    }
    #endregion
}
```

```xml
<?xml version="1.0" encoding="utf-8" ?>
<configuration>
    <configSections>
        <sectionGroup name="userSettings" type="System.Configuration.UserSettingsGroup, System, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089" >
            <section name="EVE_Assistant.Properties.Settings" type="System.Configuration.ClientSettingsSection, System, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089" allowExeDefinition="MachineToLocalUser" requirePermission="false" />
        </sectionGroup>
    </configSections>
    <startup> 
        <supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.7.2" />
    </startup>
    <userSettings>
        <EVE_Assistant.Properties.Settings>
            <setting name="WindowState" serializeAs="String">
                <value>Normal</value>
            </setting>
            <setting name="WindowSize" serializeAs="String">
                <value>1024, 768</value>
            </setting>
            <setting name="WindowLocation" serializeAs="String">
                <value>100, 100</value>
            </setting>
        </EVE_Assistant.Properties.Settings>
    </userSettings>
</configuration>
```

```csharp
namespace EVE_Assistant.Properties {
    internal sealed partial class Settings {
        public Settings() {
            // // 要添加事件处理程序以在设置更改时保存设置，请取消注释下面的行：
            // this.SettingChanging += this.SettingChangingEventHandler;
        }
        
        private void SettingChangingEventHandler(object sender, System.Configuration.SettingChangingEventArgs e) {
            // 在此处添加用于处理 SettingChangingEvent 事件的代码。
        }
    }
}
```

---

**User**

详细分析这个软甲的所有功能都是怎么实现的，包含哪些模考，每个模块都有什么功能

---

**Cursor**

让我通过分析源代码来详细说明这个软件的功能模块和实现方式。


根据代码分析，这是一个功能丰富的EVE Online游戏辅助工具，主要包含以下核心模块：

# 1. 数据管理模块

## 1.1 基础数据管理
- 静态数据管理（StaticsData）
- 蓝图数据管理（BluePrints）
- 星图数据管理（MapData）
- 区域标记管理（RegionMark）

## 1.2 用户数据管理
- 角色信息管理
- 技能数据管理
- 库存管理
- 订单管理
- 交易记录管理

# 2. 市场系统模块

## 2.1 市场查询功能
- 物品价格查询
- 市场订单查询
- 历史价格分析
- 交易量统计

## 2.2 订单管理功能
- 订单导入导出
- 订单状态追踪
- 订单成本计算
- 订单利润分析

## 2.3 价格分析功能
- 价格趋势分析
- 利润空间计算
- 市场热度分析
- 交易量分析

# 3. 制造系统模块

## 3.1 蓝图管理
- 蓝图信息管理
- 蓝图研究追踪
- 材料效率计算
- 时间效率计算

## 3.2 制造计算
- 材料需求计算
- 制造成本计算
- 制造时间计算
- 利润分析

## 3.3 生产计划
- 生产计划制定
- 材料清单生成
- 生产进度追踪
- 成本控制

# 4. 资产管理系统

## 4.1 库存管理
- 物品库存追踪
- 库存价值计算
- 库存变动记录
- 库存预警

## 4.2 资产统计
- 资产总值统计
- 资产分类统计
- 资产变动分析
- 收益分析

# 5. 行星开发系统

## 5.1 行星设施管理
- 行星资源显示
- 设施管理
- 产出计算
- 运输规划

## 5.2 行星仓库管理
- 仓库物品管理
- 资源追踪
- 运输管理
- 产出统计

# 6. 数据更新系统

## 6.1 市场数据更新
- 价格数据更新
- 订单数据更新
- 交易量更新
- 历史数据更新

## 6.2 静态数据更新
- 物品数据更新
- 蓝图数据更新
- 星图数据更新
- 区域数据更新

# 7. 工具类模块

## 7.1 计算工具
- 价格计算
- 成本计算
- 利润计算
- 效率计算

## 7.2 数据处理工具
- 数据导入导出
- 数据格式转换
- 数据验证
- 数据备份

# 8. 用户界面模块

## 8.1 主界面
- 菜单系统
- 工具栏
- 状态栏
- 导航系统

## 8.2 功能界面
- 市场查询界面
- 制造界面
- 资产管理界面
- 设置界面

# 9. 系统配置模块

## 9.1 用户设置
- 界面设置
- 数据更新设置
- 计算参数设置
- 显示选项设置

## 9.2 系统设置
- 数据库设置
- 网络设置
- 缓存设置
- 日志设置

# 10. 辅助功能模块

## 10.1 帮助系统
- 使用说明
- 功能说明
- 操作指南
- 常见问题

## 10.2 数据导出
- 报表生成
- 数据导出
- 图表生成
- 分析报告

这个软件采用了模块化的设计，各个功能模块之间相对独立但又相互关联，通过数据共享和事件驱动来实现功能整合。主要使用了以下技术：

1. 数据存储：使用SQLite数据库
2. 界面开发：Windows Forms
3. 数据处理：ADO.NET
4. 网络通信：HTTP请求
5. 多线程处理：BackgroundWorker
6. 数据缓存：内存缓存
7. 配置管理：XML配置文件

这个软件的设计非常专业，功能完整，适合EVE Online玩家进行市场交易、制造生产和资产管理。

---

**User**

我现在要做一个类似的软件，该怎么开始？

---

**Cursor**

我来为您制定一个循序渐进的开发计划：

# 第一阶段：基础框架搭建（2-3周）

## 1. 开发环境准备
1. 安装必要软件：
   - Visual Studio 2022 Community
   - .NET Framework SDK
   - SQLite数据库工具
   - Git版本控制

2. 创建项目结构：
```
EVE_Assistant/
├── src/
│   ├── Forms/          # 窗体文件
│   ├── Models/         # 数据模型
│   ├── Services/       # 业务逻辑
│   ├── Utils/          # 工具类
│   └── Resources/      # 资源文件
├── tests/              # 测试项目
└── docs/              # 文档
```

## 2. 数据库设计
1. 创建基础数据表：
```sql
-- 物品表
CREATE TABLE Items (
    ItemID INTEGER PRIMARY KEY,
    Name TEXT,
    Category TEXT,
    BasePrice DECIMAL
);

-- 市场订单表
CREATE TABLE MarketOrders (
    OrderID INTEGER PRIMARY KEY,
    ItemID INTEGER,
    Price DECIMAL,
    Volume INTEGER,
    Type TEXT,
    Created DATETIME
);

-- 库存表
CREATE TABLE Inventory (
    ItemID INTEGER,
    Quantity INTEGER,
    Location TEXT
);
```

## 3. 主窗体实现
1. 创建基础界面：
```csharp
public partial class MainForm : Form
{
    private MenuStrip mainMenu;
    private ToolStrip toolStrip;
    private StatusStrip statusStrip;
    private Panel mainPanel;

    public MainForm()
    {
        InitializeComponent();
        InitializeMainForm();
    }

    private void InitializeMainForm()
    {
        // 设置窗体属性
        this.Text = "EVE Assistant";
        this.WindowState = FormWindowState.Maximized;
        
        // 初始化菜单
        InitializeMenuStrip();
        
        // 初始化工具栏
        InitializeToolStrip();
        
        // 初始化主面板
        InitializeMainPanel();
        
        // 初始化状态栏
        InitializeStatusStrip();
    }
}
```

# 第二阶段：核心功能开发（4-6周）

## 1. 市场系统
1. 创建市场查询窗体：
```csharp
public class MarketSearchForm : Form
{
    private TextBox searchBox;
    private DataGridView resultGrid;
    private Button searchButton;

    public MarketSearchForm()
    {
        InitializeComponent();
        InitializeMarketSearch();
    }

    private void InitializeMarketSearch()
    {
        // 实现市场搜索功能
    }
}
```

2. 实现价格查询功能：
```csharp
public class MarketService
{
    public async Task<List<MarketOrder>> SearchOrders(string itemName)
    {
        // 实现订单查询逻辑
    }

    public async Task<decimal> GetAveragePrice(int itemId)
    {
        // 实现均价计算逻辑
    }
}
```

## 2. 制造系统
1. 创建制造计算器：
```csharp
public class ManufacturingCalculator
{
    public ManufacturingResult CalculateCost(Blueprint blueprint, int runs)
    {
        // 实现制造成本计算
    }

    public decimal CalculateProfit(ManufacturingResult result)
    {
        // 实现利润计算
    }
}
```

## 3. 资产管理系统
1. 创建库存管理界面：
```csharp
public class InventoryForm : Form
{
    private TreeView inventoryTree;
    private DataGridView inventoryGrid;

    public InventoryForm()
    {
        InitializeComponent();
        LoadInventory();
    }
}
```

# 第三阶段：数据管理（2-3周）

## 1. 数据服务层
```csharp
public class DataService
{
    private readonly string connectionString;

    public DataService(string connectionString)
    {
        this.connectionString = connectionString;
    }

    public async Task<List<Item>> GetItems()
    {
        // 实现数据查询
    }

    public async Task SaveOrder(MarketOrder order)
    {
        // 实现数据保存
    }
}
```

## 2.

```plaintext
EVE_Assistant/
├── src/
│   ├── Forms/          # 窗体文件
│   ├── Models/         # 数据模型
│   ├── Services/       # 业务逻辑
│   ├── Utils/          # 工具类
│   └── Resources/      # 资源文件
├── tests/              # 测试项目
└── docs/              # 文档
```

```sql
-- 物品表
CREATE TABLE Items (
    ItemID INTEGER PRIMARY KEY,
    Name TEXT,
    Category TEXT,
    BasePrice DECIMAL
);

-- 市场订单表
CREATE TABLE MarketOrders (
    OrderID INTEGER PRIMARY KEY,
    ItemID INTEGER,
    Price DECIMAL,
    Volume INTEGER,
    Type TEXT,
    Created DATETIME
);

-- 库存表
CREATE TABLE Inventory (
    ItemID INTEGER,
    Quantity INTEGER,
    Location TEXT
);
```

```csharp
public partial class MainForm : Form
{
    private MenuStrip mainMenu;
    private ToolStrip toolStrip;
    private StatusStrip statusStrip;
    private Panel mainPanel;

    public MainForm()
    {
        InitializeComponent();
        InitializeMainForm();
    }

    private void InitializeMainForm()
    {
        // 设置窗体属性
        this.Text = "EVE Assistant";
        this.WindowState = FormWindowState.Maximized;
        
        // 初始化菜单
        InitializeMenuStrip();
        
        // 初始化工具栏
        InitializeToolStrip();
        
        // 初始化主面板
        InitializeMainPanel();
        
        // 初始化状态栏
        InitializeStatusStrip();
    }
}
```

```csharp
public class MarketSearchForm : Form
{
    private TextBox searchBox;
    private DataGridView resultGrid;
    private Button searchButton;

    public MarketSearchForm()
    {
        InitializeComponent();
        InitializeMarketSearch();
    }

    private void InitializeMarketSearch()
    {
        // 实现市场搜索功能
    }
}
```

```csharp
public class MarketService
{
    public async Task<List<MarketOrder>> SearchOrders(string itemName)
    {
        // 实现订单查询逻辑
    }

    public async Task<decimal> GetAveragePrice(int itemId)
    {
        // 实现均价计算逻辑
    }
}
```

```csharp
public class ManufacturingCalculator
{
    public ManufacturingResult CalculateCost(Blueprint blueprint, int runs)
    {
        // 实现制造成本计算
    }

    public decimal CalculateProfit(ManufacturingResult result)
    {
        // 实现利润计算
    }
}
```

```csharp
public class InventoryForm : Form
{
    private TreeView inventoryTree;
    private DataGridView inventoryGrid;

    public InventoryForm()
    {
        InitializeComponent();
        LoadInventory();
    }
}
```

```csharp
public class DataService
{
    private readonly string connectionString;

    public DataService(string connectionString)
    {
        this.connectionString = connectionString;
    }

    public async Task<List<Item>> GetItems()
    {
        // 实现数据查询
    }

    public async Task SaveOrder(MarketOrder order)
    {
        // 实现数据保存
    }
}
```

---

**User**

继续

---

**Cursor**

好的，让我继续详细说明开发计划：

# 第三阶段：数据管理（续）

## 2. 数据更新系统
```csharp
public class DataUpdateService
{
    private readonly HttpClient httpClient;
    private readonly DataService dataService;

    public async Task UpdateMarketData()
    {
        try
        {
            // 1. 获取最新市场数据
            var marketData = await FetchMarketData();
            
            // 2. 更新本地数据库
            await dataService.UpdateMarketOrders(marketData);
            
            // 3. 记录更新日志
            LogUpdate("市场数据更新完成");
        }
        catch (Exception ex)
        {
            LogError("市场数据更新失败", ex);
        }
    }
}
```

## 3. 缓存管理
```csharp
public class CacheManager
{
    private static readonly Dictionary<string, object> cache = new Dictionary<string, object>();
    private static readonly TimeSpan defaultExpiration = TimeSpan.FromMinutes(30);

    public T GetOrSet<T>(string key, Func<T> getData)
    {
        if (cache.TryGetValue(key, out var cachedValue))
        {
            return (T)cachedValue;
        }

        var data = getData();
        cache[key] = data;
        return data;
    }
}
```

# 第四阶段：用户界面优化（2-3周）

## 1. 主题系统
```csharp
public class ThemeManager
{
    public static void ApplyTheme(Form form)
    {
        // 设置窗体主题
        form.BackColor = Color.FromArgb(28, 28, 30);
        form.ForeColor = Color.White;

        // 应用控件主题
        foreach (Control control in form.Controls)
        {
            ApplyControlTheme(control);
        }
    }

    private static void ApplyControlTheme(Control control)
    {
        // 为不同类型的控件应用主题
        switch (control)
        {
            case DataGridView dgv:
                ApplyDataGridViewTheme(dgv);
                break;
            case Button btn:
                ApplyButtonTheme(btn);
                break;
            // 其他控件类型...
        }
    }
}
```

## 2. 自定义控件
```csharp
public class CustomDataGridView : DataGridView
{
    public CustomDataGridView()
    {
        InitializeCustomGrid();
    }

    private void InitializeCustomGrid()
    {
        // 设置网格样式
        this.BackgroundColor = Color.FromArgb(45, 45, 48);
        this.ForeColor = Color.White;
        this.BorderStyle = BorderStyle.None;
        this.CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal;
        
        // 设置列样式
        this.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(37, 37, 38);
        this.ColumnHeadersDefaultCellStyle.ForeColor = Color.White;
        
        // 设置行样式
        this.RowHeadersVisible = false;
        this.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(51, 51, 55);
    }
}
```

# 第五阶段：功能扩展（3-4周）

## 1. 行星开发系统
```csharp
public class PlanetSystem
{
    public class PlanetFacility
    {
        public int FacilityId { get; set; }
        public string Name { get; set; }
        public decimal Output { get; set; }
        public decimal Efficiency { get; set; }
    }

    public class PlanetResource
    {
        public int ResourceId { get; set; }
        public string Name { get; set; }
        public decimal Amount { get; set; }
        public decimal ExtractionRate { get; set; }
    }

    public decimal CalculateOutput(PlanetFacility facility, PlanetResource resource)
    {
        return facility.Output * facility.Efficiency * resource.ExtractionRate;
    }
}
```

## 2. 制造规划系统
```csharp
public class ManufacturingPlanner
{
    public class ProductionPlan
    {
        public int BlueprintId { get; set; }
        public int Runs { get; set; }
        public DateTime StartTime { get; set; }
        public DateTime EndTime { get; set; }
        public List<MaterialRequirement> Materials { get; set; }
    }

    public class MaterialRequirement
    {
        public int ItemId { get; set; }
        public int Quantity { get; set; }
        public decimal Cost { get; set; }
    }

    public ProductionPlan CreatePlan(int blueprintId, int runs)
    {
        // 实现制造计划创建逻辑
    }
}
```

# 第六阶段：性能优化（2-3周）

## 1. 数据加载优化
```csharp
public class DataLoader
{
    private readonly SemaphoreSlim semaphore = new SemaphoreSlim(1, 1);
    private readonly CacheManager cacheManager;

    public async Task<T> LoadDataAsync<T>(string key, Func<Task<T>> loadFunction)
    {
        // 检查缓存
        var cachedData = cacheManager.GetOrSet(key, () => null);
        if (cachedData != null)
        {
            return (T)cachedData;
        }

        // 加载数据
        await semaphore.WaitAsync();
        try
        {
            var data = await loadFunction();
            cacheManager.Set(key, data);
            return data;
        }
        finally
        {
            semaphore.Release();
        }
    }
}
```

## 2. 界面响应优化
```csharp
public class UIOptimizer
{
    public static async Task UpdateUIAsync(Control control, Action updateAction)
    {
        if (control.InvokeRequired)
        {
            await Task.Run(() => control.Invoke(updateAction));
        }
        else
        {
            updateAction();
        }
    }
}
```

# 第七阶段：测试和部署（2-3周）

## 1. 单元测试
```csharp
[TestClass]
public class MarketServiceTests
{
    [TestMethod]
    public async Task SearchOrders_ValidItemName_ReturnsOrders()
    {
        // 准备测试数据
        var service = new MarketService();
        
        // 执行测试
        var result = await service.SearchOrders("Tritanium");
        
        // 验证结果
        Assert.IsNotNull(result);
        Assert.IsTrue(result.Count > 0);
    }
}
```

## 2. 部署准备
1. 创建安装程序
2. 准备用户文档
3. 创建更新系统

# 开发建议

1. **循序渐进**
   - 先实现基础功能
   - 逐步添加复杂功能
   - 持续优化和改进

2. **代码管理**
   - 使用Git进行版本控制
   - 定期提交代码
   - 保持代码整洁

3. **测试驱动**
   - 编写单元测试
   - 进行集成测试
   - 进行用户测试

4. **文档维护**
   - 编写技术文档
   - 编写用户手册
   - 记录开发日志

5. **性能考虑**
   - 优化数据加载
   - 减少内存使用
   - 提高响应速度

这个开发计划可以根据您的具体需求进行调整。建议先完成基础功能，然后逐步添加更复杂的功能。每个阶段完成后都要进行充分测试，确保软件的稳定性和可用性。

```csharp
public class DataUpdateService
{
    private readonly HttpClient httpClient;
    private readonly DataService dataService;

    public async Task UpdateMarketData()
    {
        try
        {
            // 1. 获取最新市场数据
            var marketData = await FetchMarketData();
            
            // 2. 更新本地数据库
            await dataService.UpdateMarketOrders(marketData);
            
            // 3. 记录更新日志
            LogUpdate("市场数据更新完成");
        }
        catch (Exception ex)
        {
            LogError("市场数据更新失败", ex);
        }
    }
}
```

```csharp
public class CacheManager
{
    private static readonly Dictionary<string, object> cache = new Dictionary<string, object>();
    private static readonly TimeSpan defaultExpiration = TimeSpan.FromMinutes(30);

    public T GetOrSet<T>(string key, Func<T> getData)
    {
        if (cache.TryGetValue(key, out var cachedValue))
        {
            return (T)cachedValue;
        }

        var data = getData();
        cache[key] = data;
        return data;
    }
}
```

```csharp
public class ThemeManager
{
    public static void ApplyTheme(Form form)
    {
        // 设置窗体主题
        form.BackColor = Color.FromArgb(28, 28, 30);
        form.ForeColor = Color.White;

        // 应用控件主题
        foreach (Control control in form.Controls)
        {
            ApplyControlTheme(control);
        }
    }

    private static void ApplyControlTheme(Control control)
    {
        // 为不同类型的控件应用主题
        switch (control)
        {
            case DataGridView dgv:
                ApplyDataGridViewTheme(dgv);
                break;
            case Button btn:
                ApplyButtonTheme(btn);
                break;
            // 其他控件类型...
        }
    }
}
```

```csharp
public class CustomDataGridView : DataGridView
{
    public CustomDataGridView()
    {
        InitializeCustomGrid();
    }

    private void InitializeCustomGrid()
    {
        // 设置网格样式
        this.BackgroundColor = Color.FromArgb(45, 45, 48);
        this.ForeColor = Color.White;
        this.BorderStyle = BorderStyle.None;
        this.CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal;
        
        // 设置列样式
        this.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(37, 37, 38);
        this.ColumnHeadersDefaultCellStyle.ForeColor = Color.White;
        
        // 设置行样式
        this.RowHeadersVisible = false;
        this.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(51, 51, 55);
    }
}
```

```csharp
public class PlanetSystem
{
    public class PlanetFacility
    {
        public int FacilityId { get; set; }
        public string Name { get; set; }
        public decimal Output { get; set; }
        public decimal Efficiency { get; set; }
    }

    public class PlanetResource
    {
        public int ResourceId { get; set; }
        public string Name { get; set; }
        public decimal Amount { get; set; }
        public decimal ExtractionRate { get; set; }
    }

    public decimal CalculateOutput(PlanetFacility facility, PlanetResource resource)
    {
        return facility.Output * facility.Efficiency * resource.ExtractionRate;
    }
}
```

```csharp
public class ManufacturingPlanner
{
    public class ProductionPlan
    {
        public int BlueprintId { get; set; }
        public int Runs { get; set; }
        public DateTime StartTime { get; set; }
        public DateTime EndTime { get; set; }
        public List<MaterialRequirement> Materials { get; set; }
    }

    public class MaterialRequirement
    {
        public int ItemId { get; set; }
        public int Quantity { get; set; }
        public decimal Cost { get; set; }
    }

    public ProductionPlan CreatePlan(int blueprintId, int runs)
    {
        // 实现制造计划创建逻辑
    }
}
```

```csharp
public class DataLoader
{
    private readonly SemaphoreSlim semaphore = new SemaphoreSlim(1, 1);
    private readonly CacheManager cacheManager;

    public async Task<T> LoadDataAsync<T>(string key, Func<Task<T>> loadFunction)
    {
        // 检查缓存
        var cachedData = cacheManager.GetOrSet(key, () => null);
        if (cachedData != null)
        {
            return (T)cachedData;
        }

        // 加载数据
        await semaphore.WaitAsync();
        try
        {
            var data = await loadFunction();
            cacheManager.Set(key, data);
            return data;
        }
        finally
        {
            semaphore.Release();
        }
    }
}
```

```csharp
public class UIOptimizer
{
    public static async Task UpdateUIAsync(Control control, Action updateAction)
    {
        if (control.InvokeRequired)
        {
            await Task.Run(() => control.Invoke(updateAction));
        }
        else
        {
            updateAction();
        }
    }
}
```

```csharp
[TestClass]
public class MarketServiceTests
{
    [TestMethod]
    public async Task SearchOrders_ValidItemName_ReturnsOrders()
    {
        // 准备测试数据
        var service = new MarketService();
        
        // 执行测试
        var result = await service.SearchOrders("Tritanium");
        
        // 验证结果
        Assert.IsNotNull(result);
        Assert.IsTrue(result.Count > 0);
    }
}
```

