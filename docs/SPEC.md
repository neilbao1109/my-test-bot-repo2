# ClawFS v1 — 产品规格说明（PM 视角）

> 内容寻址文件系统（Content-Addressable FS）。SHA-256 去重，REST + CLI 双入口，同时服务人类与 agent。单机起步，目标可在 Azure 单 VM 部署。
>
> Repo: https://github.com/neilbao1109/my-test-bot-repo2.git

---

## 1. v1 范围（MoSCoW）

### MUST（v1 必须）
- M1. 内容寻址存储：所有写入按 SHA-256 计算 hash，相同内容自动去重（同 hash 只存一份）。
- M2. Blob CRUD（读 + 写 + 存在性检查），Blob 不可变（immutable）。
- M3. Ref（路径 → hash 映射）的 CRUD：PUT/GET/LIST/DELETE，路径形如 `/notes/2026/foo.md`。
- M4. CLI（`clawfs`）覆盖 Blob/Ref 的全部基础操作，支持 stdin/stdout pipe。
- M5. REST API（JSON over HTTP）+ OpenAPI 描述文件。
- M6. 简单鉴权：Bearer Token（单用户/单租户即可，token 通过环境变量配置）。
- M7. 本地单机部署（SQLite + 本地文件系统作为 blob store），一条命令起服务。
- M8. 引用计数 + 显式 GC：`DELETE /refs/{path}` 解绑后，无引用 blob 由 GC 回收。
- M9. 分享 token：为单个 ref 生成只读、可过期的 share URL（无需登录可访问）。
- M10. 基础可观测性：结构化日志、`/healthz`、`/metrics`（Prometheus 文本格式）。

### SHOULD（尽量做，可推迟一个迭代）
- S1. Azure 部署一键脚本（单 VM + Managed Disk，可选 Azure Blob 作为 backend）。
- S2. 多用户 + 简单 ACL（per-ref owner，share token 已覆盖只读分享场景）。
- S3. Blob 流式上传/下载（>100MB 文件不进内存）。
- S4. CLI 配置文件（`~/.clawfs/config.toml`）+ profile 切换。
- S5. 内容类型嗅探（写入时记录 MIME，读时回填 `Content-Type`）。
- S6. Web UI（最小化：登录、ref 浏览、上传、生成 share）。
- S7. Pluggable backend 抽象：local FS / Azure Blob / S3 同接口。

### WON'T（v1 明确不做）
- W1. 多机分布式 / 一致性哈希环 / 副本同步。
- W2. 端到端加密、客户端加密 KMS 集成。
- W3. 复杂权限模型（组、角色、继承 ACL）。
- W4. Blob 内容差分（delta / chunking / rsync 风格）。v1 整文件去重即可。
- W5. 版本树 / 分支 / merge（Ref 只保留当前 hash，不留历史链）。
- W6. 全文检索、向量索引、agent memory 高级语义层。
- W7. Webhook / 事件总线 / pub-sub。

---

## 2. REST API 设计

约定：
- Base URL: `/v1`
- 鉴权：`Authorization: Bearer <token>`（除 `GET /shares/{token}` 与 `GET /healthz`）
- 错误统一格式：`{"error": {"code": "string", "message": "string"}}`
- Hash 表示：小写 hex SHA-256（64 字符）

### 2.1 `POST /v1/blobs` — 写入 blob
**Method / Path:** `POST /v1/blobs`

请求：
- Header: `Content-Type: application/octet-stream`
- Body: 文件原始字节（也支持 `multipart/form-data` 字段名 `file`）

响应 `201 Created`（新建）或 `200 OK`（已存在，去重命中）：
```json
{
  "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "size": 1234,
  "deduped": true,
  "created_at": "2026-04-29T00:00:00Z"
}
```

### 2.2 `GET /v1/blobs/{hash}` — 按 hash 读
**Method / Path:** `GET /v1/blobs/{hash}`

请求：无 body。可选 `Range` header（范围请求）。

响应 `200 OK`：原始字节，附 header
- `Content-Type: application/octet-stream`（或嗅探到的 MIME）
- `Content-Length: <bytes>`
- `ETag: "<hash>"`

错误响应 `404 Not Found`：
```json
{ "error": { "code": "blob_not_found", "message": "no blob with given hash" } }
```

### 2.3 `PUT /v1/refs/{path}` — 路径绑定到 hash
**Method / Path:** `PUT /v1/refs/notes/2026/foo.md`（path 为 URL-encoded 多级路径）

请求：
```json
{
  "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "content_type": "text/markdown",
  "metadata": { "tag": "draft" }
}
```

响应 `200 OK`（更新）或 `201 Created`（新建）：
```json
{
  "path": "/notes/2026/foo.md",
  "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "content_type": "text/markdown",
  "size": 1234,
  "updated_at": "2026-04-29T00:00:00Z"
}
```

### 2.4 `GET /v1/refs/{path}` — 按路径读
**Method / Path:** `GET /v1/refs/notes/2026/foo.md`

查询参数：
- `meta=1`（默认 0）：只返回元数据 JSON，不返回 blob 内容

默认响应 `200 OK`：直接返回 blob 字节流（等价于解析后 redirect 到 blob，但内联返回更适合 agent）。
- Header: `X-ClawFS-Hash: <hash>`, `Content-Type: <stored>`, `ETag: "<hash>"`

`?meta=1` 响应：
```json
{
  "path": "/notes/2026/foo.md",
  "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "size": 1234,
  "content_type": "text/markdown",
  "metadata": { "tag": "draft" },
  "created_at": "2026-04-28T22:00:00Z",
  "updated_at": "2026-04-29T00:00:00Z"
}
```

### 2.5 `GET /v1/refs` — 列举
**Method / Path:** `GET /v1/refs?prefix=/notes/&limit=100&cursor=<opaque>`

响应 `200 OK`：
```json
{
  "items": [
    {
      "path": "/notes/2026/foo.md",
      "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "size": 1234,
      "content_type": "text/markdown",
      "updated_at": "2026-04-29T00:00:00Z"
    }
  ],
  "next_cursor": null
}
```

### 2.6 `DELETE /v1/refs/{path}` — 删除（含 GC 语义）
**Method / Path:** `DELETE /v1/refs/notes/2026/foo.md`

查询参数：
- `gc=sync`（默认 `async`）：同步触发 blob GC；否则只解绑，blob 由后台 GC 异步回收。

行为：
1. 删除 ref 行。
2. 对该 ref 原指向的 blob 引用计数 -1。
3. 引用计数归零、且无活跃 share 指向 → blob 标记为可回收。

响应 `200 OK`：
```json
{
  "path": "/notes/2026/foo.md",
  "deleted": true,
  "blob_freed": true,
  "freed_bytes": 1234
}
```

### 2.7 `POST /v1/shares` — 创建分享 token
**Method / Path:** `POST /v1/shares`

请求：
```json
{
  "path": "/notes/2026/foo.md",
  "expires_at": "2026-05-29T00:00:00Z",
  "max_downloads": 100
}
```

响应 `201 Created`：
```json
{
  "token": "shr_8f3a2c1d9b4e7a06",
  "url": "https://clawfs.example.com/v1/shares/shr_8f3a2c1d9b4e7a06",
  "path": "/notes/2026/foo.md",
  "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "expires_at": "2026-05-29T00:00:00Z",
  "max_downloads": 100,
  "created_at": "2026-04-29T00:00:00Z"
}
```

### 2.8 `GET /v1/shares/{token}` — 通过 token 访问（无需登录）
**Method / Path:** `GET /v1/shares/shr_8f3a2c1d9b4e7a06`

响应 `200 OK`：返回 blob 字节流（snapshot 语义：绑定到创建时的 hash，后续 ref 改动不影响 share 内容）。
- Header: `Content-Type`, `Content-Disposition: inline; filename="foo.md"`, `ETag: "<hash>"`

错误：`410 Gone`（过期或额度耗尽）
```json
{ "error": { "code": "share_expired", "message": "share token is no longer valid" } }
```

---

## 3. CLI 设计（git 风格）

二进制名：`clawfs`。子命令风格 `clawfs <verb> [args]`。所有命令支持 `--server`、`--token`、`--json`。

| # | 命令 | 说明 |
|---|------|------|
| 1 | `clawfs put <file>` | 上传文件，输出 hash。`-` 表示 stdin。 |
| 2 | `clawfs get <hash> [-o file]` | 按 hash 拉取，默认写 stdout。 |
| 3 | `clawfs link <path> <hash>` | 把 ref path 绑到 hash（PUT /refs）。 |
| 4 | `clawfs cat <path>` | 按 ref path 读取内容到 stdout。 |
| 5 | `clawfs ls [prefix]` | 列举 ref，支持 `--long`、`--limit`。 |
| 6 | `clawfs rm <path> [--gc]` | 删除 ref，`--gc` 同步触发 blob 回收。 |
| 7 | `clawfs share <path> [--ttl 7d] [--max 100]` | 创建 share token，输出 URL。 |
| 8 | `clawfs cp <localfile> <path>` | 组合操作：`put` + `link`，最常用。 |
| 9 | `clawfs stat <path>` | 显示 ref 元数据（hash/size/type/updated_at）。 |
| 10 | `clawfs gc [--dry-run]` | 手动触发后台 GC，列出回收的 blob 与字节数。 |

辅助：
- `clawfs login --server https://... --token ...` 写入 `~/.clawfs/config.toml`
- `clawfs version` / `clawfs help [cmd]`

---

## 4. 数据模型

存储引擎：v1 SQLite（单文件 `clawfs.db`）+ 本地 blob 目录 `blobs/<hh>/<hash>`（按前 2 位 hex 分桶）。

### 4.1 `blobs`
| 字段 | 类型 | 说明 |
|------|------|------|
| `hash` | TEXT PK (64) | SHA-256 hex |
| `size` | INTEGER | 字节数 |
| `storage_path` | TEXT | 本地路径或 backend key |
| `content_type` | TEXT NULL | 首次写入嗅探/声明的 MIME |
| `ref_count` | INTEGER NOT NULL DEFAULT 0 | 被 ref 引用次数 |
| `share_count` | INTEGER NOT NULL DEFAULT 0 | 被活跃 share 引用次数 |
| `created_at` | DATETIME | 首次入库时间 |
| `last_access_at` | DATETIME | 最近一次读 |

GC 条件：`ref_count = 0 AND share_count = 0`。

### 4.2 `refs`
| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | TEXT PK | 规范化后的绝对路径，如 `/notes/2026/foo.md` |
| `hash` | TEXT FK → blobs.hash | 当前指向 |
| `content_type` | TEXT NULL | 该 ref 声明的 MIME（覆盖 blob 默认） |
| `metadata` | TEXT (JSON) | 用户自定义键值 |
| `owner` | TEXT | v1 单租户固定值，预留 |
| `created_at` | DATETIME | |
| `updated_at` | DATETIME | |

索引：`idx_refs_prefix (path)`（用于 `?prefix=` 列举）。

### 4.3 `shares`
| 字段 | 类型 | 说明 |
|------|------|------|
| `token` | TEXT PK | `shr_` 前缀 + 16 hex 随机 |
| `path` | TEXT | 创建时 ref 路径（仅记录） |
| `hash` | TEXT FK → blobs.hash | snapshot 到创建时的 hash |
| `expires_at` | DATETIME NULL | 过期时间 |
| `max_downloads` | INTEGER NULL | 下载次数上限，NULL 表示不限 |
| `download_count` | INTEGER NOT NULL DEFAULT 0 | 已使用次数 |
| `created_by` | TEXT | 创建者 token id |
| `created_at` | DATETIME | |

失效条件：`expires_at < now()` 或 `download_count >= max_downloads`。失效时 `share_count` 自动 -1。

---

## 5. Milestone

### M1 — Core CAS（2 周）
目标：单机能跑起 blob 读写 + ref 绑定。
1. 项目脚手架（语言/框架确定，CI lint+test 跑通）。
2. SQLite schema migration 工具 + `blobs` / `refs` 表落地。
3. `POST /v1/blobs` + `GET /v1/blobs/{hash}`，含 SHA-256 校验与去重。
4. `PUT/GET /v1/refs/{path}`，含路径规范化与基础校验。
5. `clawfs put / get / link / cat` 四条 CLI 跑通端到端。

### M2 — Lifecycle & Sharing（2 周）
目标：删除/GC/share 三件套，agent 可安全长期使用。
1. `GET /v1/refs` 列举 + cursor 分页。
2. `DELETE /v1/refs/{path}` + 引用计数维护 + 后台 GC worker。
3. `POST /v1/shares` + `GET /v1/shares/{token}`（含过期/限额）。
4. CLI：`ls / rm / share / stat / gc / cp` 全部上线。
5. Bearer token 鉴权 + 错误码统一。

### M3 — Ops & Deploy（1.5 周）
目标：能在 Azure 单 VM 部署并被监控。
1. `/healthz` + `/metrics`（Prometheus 文本格式：请求量、blob 总数/字节、GC 回收量）。
2. 结构化日志（JSON，含 request_id）+ 访问日志中间件。
3. OpenAPI 3.1 spec 自动生成 + 在线 `/docs`。
4. Azure 部署脚本（cloud-init / bicep 二选一），单 VM + Managed Disk。
5. 端到端集成测试套件 + 简易压测脚本（10k blob 写入、去重命中率断言）。

---

## 6. 验收标准（v1 上线门槛）

上线必须 5 条全部通过，每条都有可自动化的测试：

1. **去重正确性**：同一文件连续 `POST /v1/blobs` 100 次 → 数据库 `blobs` 行数 +1，`storage_path` 文件唯一；返回 hash 全部一致且与 `sha256sum` 本地计算结果相等。
2. **路径↔内容一致性**：`PUT /v1/refs/x` 后 `GET /v1/refs/x` 返回的字节流 SHA-256 必须等于 PUT 时提交的 hash；`X-ClawFS-Hash` header 与 body 哈希一致。
3. **GC 正确性**：创建 N=50 个 ref 指向 K=10 个 blob，逐个 `DELETE /v1/refs/...?gc=sync`；最后一个引用删除后该 blob 文件从磁盘消失，`ref_count=0`，`/metrics` 中 `clawfs_gc_freed_bytes_total` 增量等于 blob 实际大小之和。
4. **Share 安全语义**：share token 在 `expires_at` 之后请求返回 `410 Gone`；`max_downloads` 用尽后返回 `410`；未鉴权请求 `/v1/refs/*` 返回 `401`，但 `/v1/shares/<valid_token>` 无需 token 即可 200。
5. **可部署性**：在干净 Azure Ubuntu VM 上执行部署脚本 ≤10 分钟内 `clawfs --server https://<vm>/ put README.md && clawfs cat /README.md` 端到端成功；`/healthz` 返回 200；`/metrics` 暴露至少 5 个 `clawfs_*` 指标。
