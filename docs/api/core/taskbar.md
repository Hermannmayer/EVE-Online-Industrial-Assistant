# core.taskbar

> 源文件 `core/taskbar.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

Windows 任务栏身份 —— 让窗口与任务栏图标归到本应用自己名下。

Windows 按 **AppUserModelID** 归并任务栏按钮并决定取哪个图标。不显式设置时，
源码运行（python.exe 宿主）的任务栏按钮会显示 Python 的图标、并和其它 Python
程序并成一组；显式设置后与打包后的 exe 表现一致。

⚠️ 这个 id **一旦发布就不能改**：它是任务栏固定（pin）、快捷方式与跳转列表的
关联键，改了会让用户已固定的按钮失效。与 `Main.py` 的 setOrganizationName /
setApplicationName 是同一套语义。

仅 Windows 生效，失败静默 —— 纯外观层的事，不该影响启动。

## 函数

### `set_app_user_model_id`

```python
def set_app_user_model_id(app_id: str=APP_USER_MODEL_ID) -> bool
```

设置当前进程的 AppUserModelID，返回是否设置成功（非 Windows 恒 False）。

定义行：`23`
