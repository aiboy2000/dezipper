# 批量解压缩工具

一个功能强大的批量解压缩工具，支持嵌套解压、中文文件名处理和多种压缩格式。

## 🌟 特性

- **🔄 嵌套解压**: 自动处理压缩包中的压缩包，支持无限层级嵌套
- **🔤 中文支持**: 智能处理各种编码的中文/日文/韩文文件名
- **📦 多格式支持**: ZIP、RAR、7Z、TAR、TAR.GZ、TAR.BZ2、TAR.XZ
- **📄 扁平化提取**: 可选择只提取文件，忽略文件夹结构
- **🛡️ 安全备份**: 自动创建备份，防止数据丢失
- **📊 详细统计**: 实时显示处理进度和详细日志

## 📁 文件结构

```
batch_extractor/
├── main.py         # 主程序入口
├── config.py       # 配置常量
├── utils.py        # 工具函数
├── extractors.py   # 解压器模块
└── README.md       # 使用说明
```

## 🚀 安装依赖

### 基础依赖
```bash
# Python 3.6+ 自带的标准库已足够处理 ZIP 和 TAR 格式
```

### 可选依赖
```bash
# RAR 支持
pip install rarfile

# 7Z 支持  
pip install py7zr
```

## 📖 使用方法

### 基本用法
```bash
# 标准模式（创建备份，删除原文件，保持结构）
python main.py /path/to/your/folder

# 扁平化提取（只要文件，不要文件夹）
python main.py /path/to/your/folder --extract-flat

# 不创建备份
python main.py /path/to/your/folder --no-backup

# 保留原压缩文件
python main.py /path/to/your/folder --keep-original

# 不保持目录结构
python main.py /path/to/your/folder --flat-structure
```

### 组合使用
```bash
# 扁平化提取 + 不创建备份 + 保留原文件
python main.py /path/to/folder --extract-flat --no-backup --keep-original
```

### 参数说明
- `directory`: 要处理的目录路径（必需）
- `--no-backup`: 不创建备份副本
- `--keep-original`: 保留原压缩文件（不删除）
- `--flat-structure`: 不保持原有目录结构
- `--extract-flat`: 扁平化提取，只提取文件内容，忽略文件夹结构

## 🔧 工作流程

1. **📋 创建备份**: 复制整个工作目录作为备份
2. **🔍 扫描文件**: 递归扫描所有支持的压缩文件
3. **🔄 多轮解压**: 循环解压，直到没有新的压缩文件产生
4. **🗑️ 清理文件**: 可选删除已成功解压的原压缩文件
5. **📊 统计报告**: 输出详细的处理统计信息

## 📝 处理示例

### 标准模式效果
```
原始结构:                   处理后:
project.zip                project/
├─ docs/                   ├─ docs/
│  ├─ readme.txt          │  ├─ readme.txt
│  └─ nested.rar          │  ├─ manual.pdf (from nested.rar)
├─ src/                    │  └─ guide.doc (from nested.rar)  
│  └─ main.py             ├─ src/
└─ config.json            │  └─ main.py
                           └─ config.json
```

### 扁平化模式效果
```
原始结构:                   扁平化后:
project.zip                直接提取到目标目录:
├─ docs/                   ├─ readme.txt
│  ├─ readme.txt          ├─ manual.pdf
│  └─ nested.rar          ├─ guide.doc
├─ src/                    ├─ main.py
│  └─ main.py             └─ config.json
└─ config.json
```

## 🛡️ 安全特性

- **路径安全**: 防止路径遍历攻击
- **编码处理**: 智能处理多种字符编码
- **错误恢复**: 单个文件失败不影响整体处理
- **备份机制**: 自动创建带时间戳的备份
- **冲突处理**: 自动处理文件名冲突

## 📊 支持格式

| 格式 | 扩展名 | 依赖要求 | 密码支持 |
|------|--------|----------|----------|
| ZIP | .zip | 内置 | 检测 |
| RAR | .rar | rarfile | 检测 |
| 7-Zip | .7z | py7zr | 检测 |
| TAR | .tar | 内置 | - |
| TAR.GZ | .tar.gz, .tgz | 内置 | - |
| TAR.BZ2 | .tar.bz2, .tbz2 | 内置 | - |
| TAR.XZ | .tar.xz, .txz | 内置 | - |

## 🔍 日志说明

工具会生成详细的处理日志，包括：
- 每个压缩文件的发现和处理状态
- 文件大小和解压路径信息
- 成功/失败统计
- 错误原因详细说明
- 处理时间和释放空间统计

日志同时输出到控制台和日志文件（`batch_extractor_YYYYMMDD_HHMMSS.log`）。

## ⚠️ 注意事项

1. **备份重要性**: 首次使用建议保留备份选项
2. **磁盘空间**: 确保有足够空间进行解压操作
3. **权限要求**: 确保对目标目录有读写权限
4. **密码保护**: 无法处理密码保护的压缩文件
5. **嵌套深度**: 理论上支持无限层级，但受系统限制

## 🐛 故障排除

### 常见问题
1. **RAR文件无法解压**: 安装 `pip install rarfile`
2. **7Z文件无法解压**: 安装 `pip install py7zr`
3. **编码错误**: 工具会自动尝试多种编码
4. **权限不足**: 确保对目录有完整的读写权限

### 获取帮助
```bash
python main.py --help
```

## 📄 许可证

MIT License - 可自由使用和修改。