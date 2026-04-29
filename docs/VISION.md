# ClawFS — Product Vision (CEO)

## 1. Vision
**为人类与 AI agent 共建的内容寻址文件系统——一次写入，永不重复，全局可寻。**

## 2. Differentiation
- **vs S3** — 原生 hash 寻址 + 自动去重，无需上层管理 key/版本；agent 友好的细粒度 share。
- **vs Dropbox** — 面向程序而非人，CLI/API 一等公民，无 GUI 同步焦虑；hash 即身份。
- **vs Git** — 可 update/delete + share 权限模型，不强制 commit/branch 心智；为大文件优化。

## 3. Target Users
- **人类开发者**：复用、分享、不重复的素材库（数据集、模型权重、媒体资产）。
- **AI agent**：稳定可寻址的"工作记忆"——产物 hash 化后被其他 agent 直接引用。

## 4. Success Metrics (3 months post v1)
1. 去重率 ≥ 40%
2. agent 集成 ≥ 5 个
3. p95 read 延迟 < 50ms（缓存命中），< 500ms（冷读）

## 5. v1 Non-Goals
- ❌ 分布式一致性
- ❌ 端到端加密
- ❌ GUI 客户端
- ❌ 版本历史 UI
- ❌ 权限组/团队管理

## 6. Deployment Decision: **单机优先（v1）**
v1 验证 PMF，单机 docker run 一行起。Azure 部署留给 v2 作为商业化入口。
