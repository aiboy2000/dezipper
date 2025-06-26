# 批量解压缩工具 (Web UI & API版)

一个功能强大的批量解压缩工具，现在提供 Web UI 和 API 接口，支持嵌套解压、中文文件名处理和多种压缩格式。

## 🌟 特性

- **💻 Web UI**: 通过浏览器轻松操作，无需命令行。
- **🔌 API 驱动**: 所有核心功能通过 FastAPI 提供，方便集成和扩展。
- **🔄 嵌套解压**: 自动处理压缩包中的压缩包，支持无限层级嵌套。
- **🔤 中文支持**: 智能处理各种编码的中文/日文/韩文文件名。
- **📦 多格式支持**: ZIP、RAR、7Z、TAR、TAR.GZ、TAR.BZ2、TAR.XZ。
- **📄 扁平化提取**: 可选择只提取文件，忽略文件夹结构。
- **🛡️ 安全备份**: 自动创建备份，防止数据丢失。
- **📊 详细统计与日志**: UI实时显示处理进度和详细日志，同时日志文件也保存在工作目录的 `batch_extractor_logs` 子目录下。

## 📁 文件结构

```
batch_extractor/
├── api.py          # FastAPI 应用主程序 (包含API路由和核心逻辑)
├── config.py       # 配置常量
├── utils.py        # 工具函数
├── extractors.py   # 解压器模块
├── static/         # 存放 Web UI 的静态文件 (HTML, CSS, JS)
│   └── index.html
├── requirements.txt # Python 依赖包列表
└── README.md       # 使用说明
```

## 🚀 安装与启动

1.  **克隆仓库** (如果尚未克隆):
    ```bash
    git clone <repository_url>
    cd batch_extractor
    ```

2.  **安装依赖**:
    确保你的环境中有 Python 3.7+。然后安装必要的库：
    ```bash
    pip install -r requirements.txt
    ```
    这将安装 `fastapi`, `uvicorn`, 以及可选的 `rarfile` 和 `py7zr` (用于 RAR 和 7Z 支持)。

3.  **启动 API 服务器**:
    ```bash
    python api.py
    ```
    服务器默认会在 `http://localhost:8000` 启动。

## 📖 使用方法

### Web UI
1.  启动 API 服务器后，在浏览器中打开 `http://localhost:8000/`。
2.  在 "Target Directory" 输入框中，填入包含压缩文件（或嵌套压缩文件）的文件夹的 **绝对路径**。
3.  根据需要选择以下选项:
    *   **Create Backup**: 是否在处理前创建目标目录的备份。 (默认为勾选)
    *   **Delete Original Archive After Extraction**: 成功解压后是否删除原压缩文件。(默认为勾选)
    *   **Preserve Directory Structure**: 解压时是否保持压缩包内的目录结构。 (默认为勾选)
        *   如果取消勾选，解压后的文件会直接放在以压缩包名命名的文件夹下（位于工作目录）。
    *   **Extract Flat (Ignore Folders, Extract Files Only)**: 是否将所有文件（无论原先在哪个子文件夹）直接提取到目标路径，忽略所有内部文件夹结构。(默认为不勾选)
4.  点击 "Start Extraction" 按钮。
5.  处理过程中的日志和最终统计信息会显示在 "Results"区域。

### API (可选)
核心解压功能通过 `/extract` POST 端点提供。

**请求 (`POST /extract`)**:
*   **Body (JSON)**:
    ```json
    {
        "directory": "/path/to/your/archives", // (必需) 目标目录的绝对路径
        "create_backup": true,                 // (可选, 默认 true)
        "delete_original": true,               // (可选, 默认 true)
        "preserve_structure": true,            // (可选, 默认 true)
        "extract_flat": false                  // (可选, 默认 false)
    }
    ```

**响应 (`200 OK`)**:
*   **Body (JSON)**:
    ```json
    {
        "success": true,
        "message": "Extraction process completed.",
        "logs": [
            "[INFO] Batch Extractor starting...",
            // ... 更多日志条目
        ],
        "stats": {
            "found": 5,
            "processed": 5,
            "success": 5,
            "error": 0,
            "total_size": 102400, // 示例: 字节数
            "freed_size": 51200,  // 示例: 字节数
            "extracted_files": 10
        }
    }
    ```
**错误响应 (例如 `400 Bad Request`, `500 Internal Server Error`)**:
*   **Body (JSON)**:
    ```json
    {
        "detail": "Error message explaining the issue."
    }
    ```

## 🔧 工作流程 (与原版类似，通过API执行)

1.  **(可选) 创建备份**: 如果启用，复制整个工作目录作为备份。
2.  **🔍 扫描文件**: 递归扫描所有支持的压缩文件。
3.  **🔄 多轮解压**: 循环解压，直到没有新的压缩文件产生 (处理嵌套压缩包)。
4.  **🗑️ 清理文件**: (可选) 删除已成功解压的原压缩文件。
5.  **📊 统计报告**: 返回详细的处理统计信息和日志。

## 📊 支持格式 (依赖安装情况)

| 格式    | 扩展名                | 依赖要求  | 密码支持 |
| :------ | :-------------------- | :-------- | :------- |
| ZIP     | .zip                  | 内置      | 检测     |
| RAR     | .rar                  | `rarfile` | 检测     |
| 7-Zip   | .7z                   | `py7zr`   | 检测     |
| TAR     | .tar                  | 内置      | -        |
| TAR.GZ  | .tar.gz, .tgz         | 内置      | -        |
| TAR.BZ2 | .tar.bz2, .tbz2       | 内置      | -        |
| TAR.XZ  | .tar.xz, .txz         | 内置      | -        |

*密码保护的压缩文件：工具会检测到密码并跳过解压，不会尝试破解。*

## 🔍 日志说明

-   **Web UI**: 日志实时显示在结果区域。
-   **API 响应**: `logs` 字段包含详细日志列表。
-   **文件日志**: 更持久的日志保存在处理目录下的 `batch_extractor_logs/batch_extractor_<request_id>_<timestamp>.log` 文件中。`request_id` 是为了区分并发API请求（尽管当前版本主要面向单用户UI操作）。

## ⚠️ 注意事项

1.  **路径**: UI中请输入目标文件夹的**绝对路径**。
2.  **备份重要性**: 首次使用或处理重要数据时，强烈建议保留 "Create Backup" 选项。
3.  **磁盘空间**: 确保有足够空间进行解压操作，特别是对于大型或多层嵌套的压缩包。
4.  **权限要求**: 确保运行 `python api.py` 的用户对指定的目标目录有读写权限，以及对日志存储目录（目标目录下的 `batch_extractor_logs`）的创建和写入权限。
5.  **密码保护**: 工具无法处理受密码保护的压缩文件；它们会被跳过。
6.  **嵌套深度**: 理论上支持无限层级嵌套，但受系统资源和 `MAX_PROCESSING_ROUNDS` (在 `config.py` 中定义) 的限制。

## 🐛 故障排除

### 常见问题
1.  **RAR/7Z文件无法解压**:
    *   确保已通过 `pip install -r requirements.txt` 安装 `rarfile` 和 `py7zr`。
    *   对于RAR，系统可能还需要 `unrar` 命令行工具。如果 `rarfile` 库报告找不到 `unrar` (或类似错误)，请根据您的操作系统安装它。
2.  **编码错误**: 工具会自动尝试多种常见编码。如果仍有问题，可能遇到了非常罕见的编码或损坏的文件名。
3.  **权限不足**: 检查程序对目标目录和日志目录的读写权限。
4.  **UI没有反应/按钮点击无效**:
    *   确保API服务器 (`python api.py`) 正在运行且没有错误。
    *   打开浏览器开发者工具 (通常按 F12)，查看控制台是否有 JavaScript 错误或网络请求失败信息。
5.  **"Directory not found" 或 "Path is not a directory"**:
    *   确认在UI中输入的是文件夹的**绝对路径**，并且该路径确实存在。

### 获取帮助
-   查看API服务器的控制台输出获取详细错误信息。
-   检查 `batch_extractor_logs` 目录下的日志文件。

## 📄 许可证

MIT License - 可自由使用和修改。