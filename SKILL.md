---
name: c-cpp-code-checker
description: Use when writing or modifying C/C++ code (auto-trigger after .c/.cpp/.h/.hpp changes), or when user requests static code quality comparison between C/C++ files or folders
---

# C/C++ Code Checker

## Overview
使用 clang-tidy + cppcheck 纯静态分析 C/C++ 代码，生成 HTML 对比报告（含分类问题列表、评分、AI 对比分析）。

## When to Use
- 手动触发：用户明确要求检查或对比 C/C++ 文件

## Quick Reference
| 命令 | 用途 |
|------|------|
| `python skills/c-cpp-code-checker/setup.py` | 首次或更新时下载工具 |
| `python skills/c-cpp-code-checker/checker.py file.cpp` | 单文件检查 |
| `python skills/c-cpp-code-checker/checker.py a.cpp b.cpp` | 双文件对比 |
| `python skills/c-cpp-code-checker/checker.py src/` | 目录批量检查 |
| `python skills/c-cpp-code-checker/checker.py dir1/ dir2/` | 两个文件夹对比 |

## Workflow
1. **Setup（首次）**: `python skills/c-cpp-code-checker/setup.py` 下载 cppcheck + clang-tidy 到 `download/` 目录。若 `download/` 下已存在对应工具则跳过下载。
2. **Check**: `python skills/c-cpp-code-checker/checker.py <file(s) or dir(s)>` 运行分析。**运行前须确保至少一种工具已安装**；若 `download/` 下无任何工具，须先执行 `setup.py`。
3. **Report**: 自动生成 HTML 报告并在浏览器中打开
4. **AI Analysis（对比模式）**: 双文件或两文件夹对比后，读取 JSON 结果，分析差异并写入 HTML

## Scoring
| 严重度 | 扣分 |
|--------|------|
| Error | -3分/条 |
| Warning | -2分/条 |
| Style | -1分/条 |
满分100分，最低0分。

## Issue Categories
内存泄漏、空指针、缓冲区溢出、未初始化变量、资源泄漏、类型安全、代码风格、未定义行为、逻辑错误、其他

## Output
- HTML 报告（自动浏览器打开）
- JSON 中间结果（双文件或两文件夹对比时供 AI 分析）
