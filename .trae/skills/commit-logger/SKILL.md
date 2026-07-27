---
name: "commit-logger"
description: "当用户提交代码时自动更新 CHANGELOG.md、.gitignore 和 README.md。当用户提到 'commit'、'提交代码'、'push' 等相关词汇时触发。"
---

# Commit Logger（代码提交日志）

此技能在用户提交代码时自动更新 `CHANGELOG.md`、`.gitignore` 和 `README.md`。

## 触发条件

**当以下情况发生时，必须触发此技能：**
- 用户提到 "commit" 或 "提交代码"
- 用户提到 "push" 或 "推送代码"
- 用户要求 "更新changelog" 或 "更新readme"
- 用户即将进行代码提交

## 执行步骤

### 步骤 1：收集变更信息

询问用户以下信息：
- 提交信息（或从变更中生成）
- 变更类型：`feat`（新功能）、`fix`（修复）、`docs`（文档）、`refactor`（重构）、`chore`（维护）
- 变更描述
- 修改的相关文件

### 步骤 2：更新 CHANGELOG.md

在 `CHANGELOG.md` 顶部添加新条目，格式如下：

```markdown
## [未发布]

### <类型>
- <描述>
- 相关文件：<文件列表>
```

### 步骤 3：更新 .gitignore

更新 `.gitignore` 文件，确保新文件被正确忽略：
- 添加新的构建产物或生成文件
- 添加包含敏感数据的新配置文件
- 添加不应该提交的新目录

### 步骤 4：更新 README.md

精简更新 README.md：
- 如果添加了新功能，更新"功能"部分
- 如果添加/删除了文件，更新"项目结构"部分
- 保持其他部分简洁
- 删除冗余内容

### 步骤 5：显示更新摘要

向用户展示更新的内容摘要。

## CHANGELOG.md 格式

```markdown
# 变更日志

本项目的所有重要变更都会记录在此文件中。

## [未发布]

### feat（新功能）
- 新功能描述

### fix（修复）
- 修复描述

### docs（文档）
- 文档更新

### refactor（重构）
- 代码重构变更

### chore（维护）
- 维护任务

## [1.0.0] - YYYY-MM-DD

### 初始版本
- 项目第一个版本
```

## README.md 指南

保持 README.md 简洁：
- 标题和简要描述
- 功能特性（项目符号）
- 技术栈（表格或列表）
- 快速开始（分步说明）
- 项目结构（树形格式）
- API/使用说明（如需要）

删除不必要的内容：
- 过长的描述
- 重复信息
- 实现细节
- 临时注释

## 示例

当用户说"提交代码：修复了Jitsi连接问题"时，触发此技能：

1. 询问详情（如需要）
2. 更新 CHANGELOG.md：
   ```markdown
   ## [未发布]
   
   ### fix（修复）
   - 修复 Jitsi 连接问题
   - 相关文件：frontend/src/config.ts, frontend/src/hooks/useJitsiApi.ts
   ```

3. 更新 .gitignore（如需要）

4. 更新 README.md（如涉及功能变更）

5. 显示更新摘要