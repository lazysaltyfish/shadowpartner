# ShadowPartner 后端系统改进详细设计书 (v1.0)

## 1. 概要 (Overview)
本设计旨在将 ShadowPartner 从基于内存的临时处理系统迁移到基于持久化存储的生产级系统。核心目标是实现数据的持久化、处理结果的缓存复用，并构建一个支持未来多用户扩展的基础架构。

## 2. 架构设计原则 (Architecture Principles)

为了保证扩展性，系统将引入以下两个抽象层：

1.  **Repository Pattern (仓储模式)**:
    *   隔离业务逻辑与数据库实现。虽然目前使用 SQLite，但代码中通过 ORM (SQLModel/SQLAlchemy) 操作，未来迁移到 PostgreSQL 时仅需修改配置。
2.  **Storage Abstraction Layer (存储抽象层)**:
    *   定义统一的 `StorageProvider` 接口。
    *   目前实现 `LocalStorageProvider` (本地文件系统)。
    *   未来可无缝扩展为 `S3Provider` 或 `MinIOProvider` 而无需修改业务逻辑。

## 3. 详细设计 (Detailed Design)

### 3.1 数据模型设计 (Database Schema)

采用 `SQLModel` 定义模型，兼具 Pydantic 的验证能力和 SQLAlchemy 的 ORM 能力。

#### 3.1.1 User (用户)
支持“隐式”到“显式”的平滑过渡。

| 字段名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Yes | 主键 |
| `username` | String | No | 显式登录用 |
| `password_hash` | String | No | 显式登录用 |
| `is_admin` | Bool | Yes | **上传权限控制**。默认False |
| `created_at` | DateTime | Yes | |

#### 3.1.2 Asset (视频资产)
核心资源表。根据 `source_type` 决定是否存储实体文件。

| 字段名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Yes | 主键 |
| `type` | Enum | Yes | `YOUTUBE`, `UPLOAD` |
| `identifier` | String | Yes | YouTube ID 或 文件SHA256 (唯一索引) |
| `storage_path` | String | No | **仅 `UPLOAD` 类型有值**。存储视频实体文件。 |
| `meta` | JSON | No | 标题, 时长, 封面URL等 |
| `created_by` | UUID | Yes | FK -> User.id (上传者/触发者) |

#### 3.1.3 SubtitleTrack (字幕轨)
管理关联到 Asset 的所有文本资源。前端直接通过 `PROCESSED` 类型的 Track 获取数据。

| 字段名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Yes | 主键 |
| `asset_id` | UUID | Yes | FK -> Asset.id |
| `track_type` | Enum | Yes | `RAW` (纯文本/SRT), `PROCESSED` (成品JSON) |
| `source` | Enum | Yes | `USER_UPLOAD`, `AI_GENERATED` |
| `language` | String | Yes | ISO 639-1 (ja, zh, en) |
| `content` | JSON | Yes | **直接存储字幕内容** (JSON或SRT文本) |
| `is_default` | Bool | Yes | 是否作为默认显示字幕 |
| `created_at` | DateTime | Yes | |

### 3.2 存储层抽象 (Storage Abstraction)

在 `backend/services/storage/` 下定义接口。

**Interface: `BaseStorage`**
```python
class BaseStorage(ABC):
    @abstractmethod
    async def save(self, file_obj: BinaryIO, path: str) -> str: ...
    
    @abstractmethod
    async def get(self, path: str) -> BinaryIO: ...
    
    @abstractmethod
    async def delete(self, path: str) -> bool: ...
    
    @abstractmethod
    async def exists(self, path: str) -> bool: ...
```

**Implementation: `LocalStorage`**
*   Root Directory: `data/storage/`
*   Strategy: 使用 SHA256 前两位作为子目录 (e.g., `data/storage/a1/a1b2c3...mp4`) 以避免单目录文件过多。

### 3.3 目录结构变更 (Directory Structure)

```text
backend/
├── db/                     # [NEW] 数据库相关
│   ├── __init__.py
│   ├── engine.py           # 数据库连接 (SQLite setup)
│   ├── models.py           # SQLModel 定义 (User, Asset, Project)
│   └── crud.py             # 基础 CRUD 操作
├── services/
│   ├── storage/            # [NEW] 存储服务
│   │   ├── __init__.py
│   │   ├── base.py         # 抽象基类
│   │   └── local.py        # 本地文件系统实现
│   └── ... (existing services)
├── migrations/             # [NEW] Alembic 迁移脚本 (为未来做准备)
├── data/                   # [NEW] 持久化数据 (git ignored)
│   ├── shadow.db
│   └── storage/            # 实际文件存储
```

## 4. 业务逻辑变更点 (Key Logic Changes)

### 4.1 会话与用户 (Session & User)
*   **现状**: `X-Session-Id` header 对应内存中的 `AuthSession`。
*   **变更**:
    *   Middleware 或 Dependency 接收 `X-Session-Id`。
    *   在 DB 查找对应的 `User` (Role=GUEST)。
    *   如果 ID 不存在，**自动在 DB 创建一个新的 Guest User** 并返回新 ID。
    *   *扩展性*: 未来只需添加 `/api/login` 接口，验证成功后将该 Guest User 的 Role 更新为 USER，并填充 username/password。

### 4.2 上传流程 (Upload Flow)
1.  **Upload Start**: 计算文件 Hash (客户端算或后端流式算)。
2.  **Check Duplicate**: 查询 `Asset` 表是否存在该 Hash。
    *   **命中**: 直接关联现有的 `Asset.id`，实现“秒传”。
    *   **未命中**: 调用 `StorageService.save()` 写入磁盘，并在 `Asset` 表创建记录。
3.  **Create Project**: 创建 `Project` 记录，状态为 `PENDING`。

### 4.3 处理流程 (Process Flow)
1.  用户请求处理 (YouTube URL 或 Uploaded File)。
2.  检查 `Project` 表中是否已有 **相同 Asset ID** 且 **相同 Config** 且 **Status=COMPLETED** 的记录。
    *   **命中缓存**: 直接返回 `Project.result`。
    *   **未命中**: 
        *   创建新 `Project` (Status=PROCESSING)。
        *   触发后台 Task。
        *   Task 完成后更新 `Project` 的 result 和 status。

## 5. 执行计划 (Implementation Steps)

1.  **基础设施准备**:
    *   引入 `sqlmodel` 和 `alembic` 依赖。
    *   创建 `backend/db` 模块和 `backend/services/storage` 模块。
2.  **数据迁移**:
    *   定义 Models。
    *   配置 SQLite 引擎。
3.  **重构 Upload Service**:
    *   修改 `uploads.py` 使用 `StorageService` 和 `Asset` 表。
4.  **重构 Process Pipeline**:
    *   修改 `processing.py`，不再依赖内存 Task 字典，改为更新 DB 中的 `Project` 状态。
5.  **清理**:
    *   移除 `state.py` 中的大部分内存字典。
    *   移除 `temp/` 目录的重度依赖 (仅用于 ffmpeg 转码中间过程，不存源文件)。
