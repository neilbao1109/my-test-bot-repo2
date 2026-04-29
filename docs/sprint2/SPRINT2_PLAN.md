# ClawFS Sprint 2 计划（v2，2 周）

PM: Agent008 · 起止：2026-04-29 → 2026-05-13 · 输入：[v1 SPEC](https://github.com/neilbao1109/my-test-bot-repo2/blob/main/docs/SPEC.md)

> Sprint 1（v1）交付了单机 CAS：blob/ref CRUD、share token、本地 SQLite + 本地 FS、Bearer token、/healthz、/metrics、CLI。
> Sprint 2 的主线：**让 v1 真的能在云上跑起来，并让 agent 一行代码用上它**。

---

## 1. Sprint 2 范围（2 周）

### MUST（5 项，本 sprint 上线门槛）

| # | 项目 | 理由 | 估时 |
|---|---|---|---|
| **A** | **Azure Blob Storage backend 真实现**（替换 v1 的 local FS / stub） | v1 的 SHOULD-S7 已经预留了 pluggable backend；不上云存储后面所有部署都没意义 | 4d |
| **B** | **GitHub Actions CI**（lint + unit test + integration test + docker build & push 到 GHCR） | 阻塞所有后续协作和部署；最便宜的杠杆 | 1.5d |
| **C** | **真部署到 Azure Container Apps + e2e 验证** | 替代 v1 的"单 VM cloud-init 脚本"，云原生路径，自动扩缩 | 3d |
| **D** | **Python agent SDK（`clawfs-py`）** | 真实用户是 agent。`fs.put(b"...")` / `fs.get(path)` 一行调用 = 采纳关键 | 2.5d |
| **E** | **结构化日志 + 监控强化**（request_id 贯穿、`/healthz` 增加依赖检查、`/metrics` 加 backend latency 直方图） | 上云之后没有可观测性 = 盲飞 | 1.5d |

合计 ~12.5 人日，留 1.5 天 buffer。

### SHOULD（不阻塞 Sprint 2 收尾，做完是惊喜）

- **API token 列表 + 撤销**（替换 v1 单 env-var token；DB 表 + `POST/DELETE /v1/admin/tokens`）
- **per-share 过期收紧**：v1 已有 `expires_at`，补 `revoke` 接口和后台清理 worker
- **Dockerfile 多阶段构建优化**（image < 80MB）

### WON'T（明确推迟到 Sprint 3）

- ❌ **大文件分块上传** —— 设计成本高（resumable session、并发分片合并、SHA-256 流式聚合），单独立 sprint
- ❌ Web UI / 多租户 ACL / 全文检索（继承 v1 WON'T）
- ❌ S3 backend（先把 Azure Blob 一条路径打通）

---

## 2. API 增量（v1 → v2）

Base URL 升级 `/v2`，`/v1` 保持向后兼容。新增/变更如下：

### 2.1 NEW · `GET /v2/healthz`（增强）

v1 只返回 `200 OK`。v2 返回依赖检查：

```json
{
  "status": "ok",
  "version": "0.2.0",
  "checks": {
    "db": { "ok": true, "latency_ms": 3 },
    "blob_backend": { "ok": true, "type": "azure_blob", "latency_ms": 12 }
  },
  "uptime_s": 3821
}
```

任一 `checks.*.ok=false` → 整体 `status="degraded"` 且 HTTP 503。

### 2.2 NEW · `POST /v2/admin/tokens`（SHOULD）

```json
// req
{ "label": "ci-bot", "expires_at": "2026-07-01T00:00:00Z", "scopes": ["read","write"] }
// resp 201
{ "token_id": "tk_9f3a", "token": "clw_live_xxxxx", "label": "ci-bot",
  "scopes": ["read","write"], "expires_at": "2026-07-01T00:00:00Z" }
```

伴随 `GET /v2/admin/tokens`（列出，不返回明文）、`DELETE /v2/admin/tokens/{id}`。

### 2.3 NEW · `DELETE /v2/shares/{token}`

显式撤销分享（v1 只能等过期）。

```json
{ "token": "shr_8f3a2c1d9b4e7a06", "revoked": true, "revoked_at": "2026-05-10T..." }
```

### 2.4 CHANGED · `POST /v1/blobs` 响应增字段

为 SDK 友好，新增 `etag` 和 `backend`：

```json
{
  "hash": "e3b0...b855",
  "size": 1234,
  "deduped": true,
  "etag": "\"e3b0...b855\"",
  "backend": "azure_blob",
  "created_at": "2026-04-29T..."
}
```

兼容性：纯加字段，老客户端忽略即可。

### 2.5 NEW metrics（`/metrics`）

- `clawfs_backend_op_duration_seconds{op="put|get|delete",backend="azure_blob"}` (histogram)
- `clawfs_backend_errors_total{op,backend,code}`
- `clawfs_share_active_total` (gauge)

---

## 3. 数据模型变更

迁移文件命名：`migrations/0002_*.sql`（v1 是 0001）。

### 3.1 `blobs` 表新增字段

```sql
ALTER TABLE blobs ADD COLUMN backend TEXT NOT NULL DEFAULT 'local_fs';
-- v1 行回填为 'local_fs'，新写入按配置写 'azure_blob'
ALTER TABLE blobs ADD COLUMN etag TEXT NULL;
-- Azure Blob 返回的 ETag，用于幂等校验
```

`storage_path` 语义扩展：当 `backend='azure_blob'` 时存 container-relative key（如 `ab/cd/ef..hash`）。

### 3.2 NEW 表 `api_tokens`（SHOULD）

```sql
CREATE TABLE api_tokens (
  token_id     TEXT PRIMARY KEY,        -- tk_xxxx
  token_hash   TEXT NOT NULL UNIQUE,    -- SHA-256(token明文)，明文不入库
  label        TEXT NOT NULL,
  scopes       TEXT NOT NULL,           -- JSON array: ["read","write","admin"]
  expires_at   DATETIME NULL,
  created_at   DATETIME NOT NULL,
  last_used_at DATETIME NULL,
  revoked_at   DATETIME NULL
);
CREATE INDEX idx_api_tokens_hash ON api_tokens(token_hash) WHERE revoked_at IS NULL;
```

启动时若表为空，自动 seed 一个来自 `CLAWFS_BOOTSTRAP_TOKEN` env 的 admin token（兼容 v1 部署）。

### 3.3 `shares` 表增字段

```sql
ALTER TABLE shares ADD COLUMN revoked_at DATETIME NULL;
-- 失效条件 OR 增一条：revoked_at IS NOT NULL
```

### 3.4 迁移策略

- 单向 forward-only，工具沿用 v1 的 `clawfs migrate`。
- 上线前在 staging 跑 dry-run 输出 diff。
- 老 backend='local_fs' 的 blob **不做** 数据搬迁，由后台 `migrate-blobs` 一次性脚本（非本 sprint 范围）后续异步搬。v2 服务同时支持读两种 backend。

---

## 4. 验收标准（v2 上线门槛，5 条全过）

每条都有自动化测试，跑在 GitHub Actions 上。

1. **Azure Blob backend 等价性**：以 `BLOB_BACKEND=azure_blob` 运行 v1 验收标准 #1（去重）和 #2（路径↔内容一致性）测试套件，**100% 通过**；blob 实际落到 Azure Storage container（用 `az storage blob list` 校验对象数与 DB `blobs` 行数相等）。

2. **CI 红绿可信**：`main` 分支每次 push 触发流水线 ≤ 8 分钟跑完 lint + 单测 + 集测（against Azurite）+ docker build + push GHCR；任何一步失败 → PR 不可 merge（required check）。流水线连续 10 次绿色后才允许标 `v0.2.0`。

3. **Container Apps e2e**：从干净的 Azure 订阅，跑 `make deploy-aca` 在 ≤ 15 分钟内拉起一套（Container Apps + Storage Account + 托管身份）。随后远程执行 `clawfs cp ./README.md /readme && clawfs cat /readme` 字节级一致；`/healthz` 返回 `status=ok` 且 `checks.blob_backend.type=azure_blob`。

4. **Python SDK 可用性**：`pip install clawfs` 后，以下脚本零额外配置（除 `CLAWFS_URL` + `CLAWFS_TOKEN`）跑通：

   ```python
   from clawfs import Client
   fs = Client.from_env()
   h = fs.put(b"hello agent")              # 返回 hash
   fs.link("/agent/notes/hi.txt", h)
   assert fs.get("/agent/notes/hi.txt") == b"hello agent"
   url = fs.share("/agent/notes/hi.txt", ttl="7d")
   ```

   覆盖率 ≥ 85%，发布到 TestPyPI，README 含 30 秒 quickstart。

5. **可观测性可信**：在 Container Apps 实例上跑 5 分钟混合负载（put/get/share），日志全部为单行 JSON 且每条含 `request_id`、`route`、`status`、`latency_ms`、`backend_op_ms`；`/metrics` 暴露 §2.5 的 3 个新指标且数值非零；故意把 storage account key 配错 → `/healthz` 在 ≤ 30s 内变 503 且日志出现 `blob_backend_unreachable` 事件。

---

## 5. 风险与依赖

| # | 风险 | 影响 | 概率 | 应对 |
|---|---|---|---|---|
| R1 | **Azure Container Apps 配额未审批 / 订阅 region 不支持** | C 项无法验收，MUST 项失败 | 中 | Day 1 立刻提工单申请配额；同步准备 fallback 路径：单 VM + docker-compose（沿用 v1 SHOULD-S1），保 e2e 不烂尾 |
| R2 | **Azure Blob 大量小对象的延迟/成本** 不可接受 | A/E 验收过但性能扎眼 | 中 | 早期就跑微基准（put 1KB×1000 / get 1KB×1000），如 p99>500ms 则启用本地 LRU cache（`/var/cache/clawfs`），仅缓存 GET hot path |
| R3 | **SDK 接口要稳定**，发出去再改成本高 | 影响 agent 用户信任 | 中 | Sprint 2 只发 `0.0.x` pre-release，README 明确"API may change before 0.1"；接口评审在 Day 3 前完成 |
| R4 | **CI 集成测试需要 Azurite**（不能用真 Azure 拉爆账单） | B 项流水线时间不可控 | 低 | 用 Azurite docker service container；真 Azure 只在 nightly job + 部署前 smoke test 跑 |
| R5 | **管理 token 的 bootstrap** 容易锁死自己 | 上线后无人能调用 admin API | 低 | `CLAWFS_BOOTSTRAP_TOKEN` env + 文档明确恢复路径；admin 接口加 rate limit |
| R6 | **数据迁移**：v1 既有 local_fs blob 何时搬到 Azure | 阻塞老用户升级 | 低 | 本 sprint **不做**搬迁；v2 服务同时读两种 backend；S3 sprint 出 `clawfs migrate-blobs` 工具 |
| R7 | **依赖：需要 Azure 订阅的 owner/contributor 角色 + Storage Account 创建权限** | C 完全阻塞 | — | Day 0 与 Neil 确认订阅 ID、可用 region（建议 `eastasia` 就近）、命名前缀 |

### 关键路径

```
Day 0    : Azure 订阅 / quota / region 确认（Neil）
Day 1-4  : A (Azure Blob backend) + B (CI) 并行
Day 3-5  : E (logs/metrics)
Day 5-8  : C (Container Apps deploy + e2e)
Day 6-9  : D (Python SDK)
Day 10   : 集成验收 + buffer + retro
```

---

_本文件由 PM (Agent008) 起草，待 Sprint 2 kickoff 与团队 review 后冻结。_
