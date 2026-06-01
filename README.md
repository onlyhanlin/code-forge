# C/C++ Code Checker

基于 **cppcheck** + **clang-tidy** 的 C/C++ 代码静态分析工具，生成 HTML 对比报告。

## 功能

- 单文件 / 目录批量检查
- 双文件 / 双目录对比分析
- 内置空白/缩进检查
- 源码模式扫描（检测静态工具遗漏的风险模式）
- 自动化 HTML 报告（按分类、严重度分级、含源代码、评分）

## 快速开始

```bash
# 1. 安装分析工具（首次）
python setup.py

# 2. 检查代码
python checker.py file.cpp          # 单文件
python checker.py src/              # 目录
python checker.py a.cpp b.cpp       # 双文件对比
python checker.py dir1/ dir2/       # 双目录对比
```

## 工具链

| 工具 | 用途 |
|------|------|
| cppcheck | 内存泄漏、空指针、缓冲区溢出、未初始化变量 |
| clang-tidy | C++ Core Guidelines、性能、可读性、死代码 |
| whitespace | 缩进一致性、尾随空白、EOF 换行 |
| pattern-scan | 空指针解引用、use-after-free、除零等模式 |

## 评分规则

| 严重度 | 扣分 |
|--------|------|
| Error | -3 |
| Warning | -2 |
| Style | -1 |

满分 100，最低 0。

## 输出

- **HTML 报告**：自动浏览器打开，包含分类问题列表、源代码、评分
- **JSON 结果**：对比模式供 AI 进一步分析

## 问题分类

内存泄漏 · 空指针 · 缓冲区溢出 · 未初始化变量 · 资源泄漏 · 类型安全 · 代码风格 · 未定义行为 · 逻辑错误 · 其他

## 目录结构

```
├── checker.py        # 主检查脚本
├── setup.py          # 工具下载/安装
├── SKILL.md          # Reasonix 技能定义
├── test/
│   ├── 1/            # 测试用例 1（含故意缺陷）
│   └── 2/            # 测试用例 2（修复后对比）
└── download/         # 工具下载目录（gitignore）
```

## License

MIT
