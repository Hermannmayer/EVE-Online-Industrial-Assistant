# services.workers.__init__

> 源文件 `services/workers/__init__.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

向后兼容 shim — 下载器已迁移到 services/importers。

保留旧导入路径（services.workers.getprices 等）与测试 patch 语义：
sys.modules 别名 + 父包属性都指向 services.importers 下的同名真实模块。

_（此模块无可公开的类或函数）_
