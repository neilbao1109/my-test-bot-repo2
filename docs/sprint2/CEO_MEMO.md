# ClawFS Sprint 2 — CEO 战略备忘

## 1. 北极星指标
**2 周内：3 个外部 agent 通过我们的 SDK 完成端到端"上传→检索→引用"闭环，累计 1000 次成功调用，P95 延迟 < 800ms。**

## 2. 三个必达里程碑
- **M1：多租户 + API Key 鉴权上线。** v1 是单机裸奔，没有租户隔离就没人敢接。这是 agent ecosystem 的入场券。
- **M2：把 Azure stub 换成真 Blob + 后台异步 ingest（Celery/RQ）。** 同步上传是性能天花板，异步化才能撑并发；同时验证 Bicep 在真环境跑通。
- **M3：发布 Python SDK + OpenAPI spec + 一个 60 秒 quickstart。** Agent 接入摩擦全在第一分钟，文档即产品。

## 3. 取舍
- **该花精力：** 检索质量（embedding + 简单 rerank），让"返回的 chunk 真的有用"。这是留存的根因。
- **该砍掉：** Web UI / Dashboard。本 Sprint 只给 API 和 CLI，不做前端，避免分散火力。

## 4. Agent ecosystem 策略
把 ClawFS 定位成"agent 的外置长期记忆 + 文件系统"，而非又一个向量库。提供 OpenAI/Anthropic tool-schema 即插即用、零配置的 Python/TS SDK、慷慨的免费额度（10GB / 100k 调用）、以及 MCP server 适配。让开发者 5 分钟跑通 demo，文档里直接给 LangChain/AutoGen/Claude Code 的接入片段——降低决策成本，比卖功能更重要。

## 5. 风险清单
- **R1：检索质量不达标，agent 接了又弃。** 缓解：M3 前建 eval 集（50 个 QA），守住 recall@5 ≥ 0.8 的红线。
- **R2：Azure 成本失控（embedding + Blob 流量）。** 缓解：每租户配额 + 成本看板 + embedding 本地缓存去重。
- **R3：安全事故（key 泄漏、跨租户读越权）。** 缓解：所有查询强制带 tenant_id 过滤、加集成测试覆盖、key 哈希存储 + 轮换接口。
