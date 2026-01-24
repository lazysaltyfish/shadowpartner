# ShadowPartner (影子跟读)

## 项目简介

ShadowPartner 是一款面向日语学习者的渐进式 Web 应用（PWA），可处理 YouTube 视频和本地上传文件，生成带词级时间戳、假名注音和中文翻译的交互式字幕。

### 核心功能
- **视频处理**：自动下载和处理 YouTube 视频或本地文件
- **语音识别**：使用 OpenAI Whisper 进行准确的日语转录，带词级时间戳
- **GPU Worker (NEW)**: 支持 GPU Worker 通过 WebSocket 连接进行加速转录，自动回退到本地处理
- **日语NLP**：使用 MeCab 进行形态学分析，自动生成假名注音
- **翻译**：通过 Google Gemini API 进行批量翻译
- **交互式播放**：词级高亮、点击跳转功能

## 技术栈

### 后端
- **框架**：FastAPI (Python 3.11+) + Uvicorn
- **数据库**：SQLite + SQLModel（支持轻松迁移到 PostgreSQL）
- **核心库**：
  - `openai-whisper`（转录）
  - `google-genai`（翻译）
  - `mecab-python3` + `unidic-lite`（日语NLP）
  - `yt-dlp`（YouTube下载）
  - `tenacity`（重试/退避）
  - `slowapi` + `limits`（速率限制）
  - `sqlmodel` + `sqlalchemy`（数据库ORM）
  - `python-magic`（文件类型检测）

### 前端
- **框架**：Vue 3 + Tailwind CSS（CDN方式）
- **视频播放器**：ArtPlayer（本地上传）+ YouTube IFrame API
- **测试**：Playwright（E2E测试）

### 开发工具
- **格式化/检查**：Ruff
- **类型检查**：Pyright
- **包管理**：uv

## 项目结构

```
shadowpartner/
├── backend/
│   ├── main.py                    # FastAPI 应用工厂
│   ├── lifecycle.py               # 启动/关闭钩子
│   ├── middleware.py              # 请求日志 + CORS
│   ├── rate_limiter.py            # 速率限制单例
│   ├── routes.py                  # API 端点
│   ├── admin_routes.py            # 管理端点
│   ├── session_manager.py         # 会话管理
│   ├── processing.py              # 视频处理流水线
│   ├── uploads.py                 # 上传处理
│   ├── models.py                  # Pydantic 模型
│   ├── state.py                   # 内存状态
│   ├── settings.py                # 环境配置
│   ├── validators.py              # 文件验证
│   ├── services_registry.py       # 服务初始化
│   ├── db/                        # 数据库模块
│   │   ├── engine.py              # 数据库引擎
│   │   ├── models.py              # SQLModel 模型
│   │   └── crud.py                # CRUD 操作
│   ├── services/                  # 业务逻辑
│   │   ├── downloader.py          # YouTube/文件下载
│   │   ├── transcriber.py         # Whisper 转录
│   │   ├── analyzer.py            # 日语 NLP
│   │   ├── aligner.py             # 时间戳对齐
│   │   ├── translator.py          # Gemini 翻译
│   │   ├── subtitle_linearizer.py # 字幕去重
│   │   ├── video_utils.py         # 视频工具
│   │   └── storage/               # 存储抽象层
│   │       ├── base.py            # 基础存储类
│   │       └── local.py           # 本地存储实现
│   ├── utils/                     # 工具函数
│   │   ├── logger.py              # 日志
│   │   ├── path_setup.py          # PATH 设置
│   │   ├── resilience.py          # 重试辅助
│   │   └── task_manager.py        # 异步任务辅助
│   ├── tests/                     # 单元测试
│   ├── workers/                   # GPU Worker 服务端 (NEW)
│   │   ├── models.py              # Worker 数据模型
│   │   ├── job_queue.py           # 任务队列
│   │   ├── storage_bridge.py      # 预签名 URL 生成
│   │   └── manager.py             # Worker 管理器
│   └── data/                      # 持久化数据（git忽略）
│       ├── shadow.db              # SQLite 数据库
│       └── storage/               # 文件存储
├── worker/                       # GPU Worker 客户端 (NEW)
│   ├── main.py                    # Worker 入口
│   ├── client.py                  # WebSocket 客户端
│   ├── transcriber.py             # Whisper 包装器
│   ├── downloader.py              # 音频下载器
│   ├── config.py                  # 配置加载
│   ├── pyproject.toml             # Worker 依赖 (uv)
│   └── requirements.txt           # 旧版依赖快照（可选）
├── frontend/
│   ├── index.html                 # 主页面
│   ├── js/
│   │   ├── app.js                 # Vue 3 应用
│   │   ├── router.js              # 哈希路由
│   │   ├── api.js                 # API 客户端
│   │   ├── player.js              # 统一播放器
│   │   ├── subtitles.js           # 字幕渲染
│   │   └── mock.js                # 模拟数据
│   ├── css/style.css              # 自定义样式
│   ├── service-worker.js          # PWA 离线支持
│   └── tests/                     # Playwright 测试
├── pyproject.toml                 # 后端依赖
└── package.json                   # 前端依赖
```

## 功能特性

1. **双视频输入**：YouTube 链接或本地文件上传（支持拖拽）
2. **词级时间戳**：Whisper 转录带每个词的时间戳
3. **GPU Worker 支持**：GPU Worker 通过 WebSocket 连接加速转录
4. **假名注音**：使用 MeCab 自动生成日语读音
5. **中文翻译**：通过 Google Gemini API 进行批量翻译
6. **用户字幕支持**：上传 SRT 文件与 AI 时间戳对齐
7. **交互式播放**：点击任意单词跳转到该位置
8. **PWA 支持**：可安装，支持离线使用
9. **管理面板**：管理用户、资产和字幕轨道
10. **速率限制**：可配置的 API 速率限制
11. **会话管理**：匿名上传会话，支持 TTL 和限制

## 环境准备

- **Python 3.11+**
- **FFmpeg**（音视频处理）
- **uv**（Python 包管理器，推荐）
- **Google Gemini API Key**（用于翻译）

### FFmpeg 安装

**Windows**：从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载，解压并将 `bin` 目录添加到系统 PATH。

**Linux**：
```bash
sudo apt install ffmpeg
# 或使用提供的脚本：
cd backend && python setup_ffmpeg.py
```

**macOS**：
```bash
brew install ffmpeg
```

## 安装步骤

### 1. 安装后端依赖

```bash
cd backend
uv sync
```

### 2. 配置环境变量

在 `backend` 目录创建 `.env` 文件：

```bash
cp .env.example .env
# 编辑 .env 文件
```

必需变量：
- `GEMINI_API_KEY` - Google Gemini API Key

可选变量：
- `WHISPER_MODEL_SIZE` - Whisper 模型大小（tiny/base/small/medium/large，默认：base）
- `WHISPER_DEVICE` - GPU/CPU 选择（cuda/cpu/None 自动）
- `ADMIN_USERNAME` - 管理面板用户名
- `ADMIN_PASSWORD` - 管理面板密码

完整变量列表见[环境变量](#环境变量)部分。

### 3. 安装前端依赖（用于测试）

```bash
cd frontend
npm install
```

## 运行应用

### 启动后端

```bash
cd backend
export GEMINI_API_KEY="your_api_key"
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**可选参数**：
- `--no-rate-limit` - 禁用速率限制（测试时有用）
- `--host` - 绑定地址（默认：0.0.0.0）
- `--port` - 端口（默认：8000）
- `--reload` - 代码更改时自动重载

### 启动 GPU Worker（可选）

GPU Worker 可以加速转录处理，后端需要 worker 在线才能处理任务。

```bash
cd worker
cp .env.example .env
# 编辑 .env 文件配置后端地址和 Worker 凭证
pip install uv
uv sync --no-dev
uv run python main.py
```

**Worker 配置 (.env)**:
```bash
BACKEND_WS_URL=ws://localhost:8001/ws/worker
WORKER_TOKEN=your_secret_token
WORKER_ID=gpu-worker-1
WHISPER_MODEL_SIZE=base
WHISPER_DEVICE=cuda
WHISPER_FP16=true
AUDIO_CACHE_DIR=./cache
MAX_CACHE_SIZE_GB=10
```

### 启动前端

```bash
cd frontend
python3 -m http.server 3000
```

或使用 uv 从 backend 目录启动：
```bash
cd backend
uv run python -m http.server --directory ../frontend 3000
```

### 访问地址

- **主应用**：http://localhost:3000
- **API**：http://localhost:8000
- **管理面板**：http://localhost:3000/#/admin（需要 ADMIN_USERNAME/PASSWORD）

## 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `GEMINI_API_KEY` | Google Gemini API Key（翻译用） | 必需 |
| `GEMINI_MODEL_ID` | Gemini 模型 ID | `gemini-3-flash-preview` |
| `DATABASE_URL` | 数据库连接字符串 | `sqlite:///./data/shadow.db` |
| `STORAGE_ROOT_DIR` | 文件存储根目录 | `data/storage` |
| `WHISPER_MODEL_SIZE` | Whisper 模型大小 | `base` |
| `WHISPER_DEVICE` | GPU/CPU 设备（cuda/cpu/None） | `None`（自动） |
| `WHISPER_FP16` | 使用半精度推理 | `false` |
| `WHISPER_CONDITION_ON_PREVIOUS_TEXT` | 基于前文条件推理 | `false` |
| `WHISPER_HALLUCINATION_SILENCE_THRESHOLD` | 跳过幻觉静音（秒） | `None` |
| `TRANSLATE_BATCH_CHUNK_SIZE` | 翻译批次大小 | `50` |
| `SUBTITLE_SIMILARITY_THRESHOLD` | 用户字幕相似度阈值 | `0.1` |
| `HTTP_PROXY` / `HTTPS_PROXY` | YouTube 下载代理设置 | `None` |
| `UPLOAD_SESSION_TTL_SECONDS` | 分块上传会话 TTL | `600` |
| `UPLOAD_SESSION_SWEEP_SECONDS` | 上传清理间隔 | `60` |
| `AUTH_SESSION_TTL_SECONDS` | 认证会话 TTL（秒） | `3600` |
| `AUTH_SESSION_MAX_UPLOADS` | 每会话最大上传数 | `5` |
| `AUTH_SESSION_MAX_TOTAL_SIZE` | 每会话最大上传大小（字节） | `524288000` (500MB) |
| `RATE_LIMIT_ENABLED` | 启用速率限制 | `true` |
| `RATE_LIMIT_DEFAULT_REQUESTS_PER_MINUTE` | 默认速率限制 | `60` |
| `RATE_LIMIT_HEALTH_CHECK_PER_MINUTE` | 健康检查速率限制 | `120` |
| `RATE_LIMIT_STATUS_PER_MINUTE` | 状态轮询速率限制 | `120` |
| `RATE_LIMIT_UPLOAD_PER_MINUTE` | 上传速率限制 | `5` |
| `RATE_LIMIT_PROCESS_PER_MINUTE` | 处理端点速率限制 | `5` |
| `ADMIN_USERNAME` | 管理面板用户名 | `None` |
| `ADMIN_PASSWORD` | 管理面板密码 | `None` |
| `WORKER_WS_PORT` | Worker WebSocket 端口 | `8001` |
| `WORKER_API_TOKENS` | Worker 认证令牌 JSON | `{}` |
| `WORKER_HEARTBEAT_INTERVAL` | 心跳检查间隔（秒） | `15` |
| `WORKER_HEARTBEAT_TIMEOUT` | 心跳超时（秒） | `30` |
| `WORKER_JOB_TIMEOUT` | 任务超时（秒） | `600` |
| `WORKER_TEMP_DIR` | Worker 临时文件目录 | `/tmp/shadowpartner_worker` |
| `WORKER_TRANSCRIBE_RETRY_ATTEMPTS` | 转录重试次数 | `2` |
| `BACKEND_BASE_URL` | Worker 后端 URL | `http://localhost:8000` |

## API 端点

### 认证
- `POST /api/session` - 创建匿名上传会话

### 视频处理
- `POST /api/process` - 处理 YouTube 链接（异步）
- `GET /api/status/{task_id}` - 获取任务状态

### 文件上传
- `POST /api/upload` - 简单上传（小文件）
- `POST /api/upload/init` - 初始化分块上传
- `POST /api/upload/chunk` - 上传文件块
- `POST /api/upload/subtitle` - 为分块上传会话上传字幕
- `POST /api/upload/complete` - 完成分块上传

### 资源访问
- `GET /api/assets/{asset_id}` - 获取资源或资源列表
- `GET /api/assets/{asset_id}/stream` - 流式传输上传的视频

### 健康检查
- `GET /` - API 心跳
- `GET /health` - 综合健康检查

### 管理接口（需要 `X-Admin-Session-Id` 头）
- `POST /api/admin/login` - 管理员登录
- `POST /api/admin/logout` - 管理员登出
- `GET /api/admin/users` - 列出用户
- `DELETE /api/admin/users/{user_id}` - 删除用户
- `GET /api/admin/assets` - 列出资源
- `DELETE /api/admin/assets/{asset_id}` - 删除资源
- `GET /api/admin/subtitle-tracks` - 列出字幕轨道
- `DELETE /api/admin/subtitle-tracks/{track_id}` - 删除字幕轨道

## 处理流水线

### 标准流水线（无用户字幕）
```
输入（YouTube 链接或文件）
  → 检查缓存（SubtitleTrack 数据库）
  → [缓存命中] 返回缓存结果
  → [缓存未命中] 下载音视频
  → 转录（优先使用 GPU Worker，自动回退本地）
  → 日语形态学分析 + 假名注音
  → 批量翻译成中文
  → 保存到数据库
  → 返回带交互单词的片段
```

### 带用户字幕的流水线
```
输入（文件 + 用户 SRT）
  → 检查缓存
  → [缓存未命中] Whisper 转录获取时间戳参考
  → 加载用户字幕
  → 去重滚动字幕
  → 检查与 AI 字幕的相似度
  → 对齐和校准时间戳
  → 日语分析 + 假名注音
  → 批量翻译成中文
  → 保存到数据库
  → 返回片段（仅片段级，无词级）
```

## 测试

### 后端测试

```bash
cd backend
uv run pytest tests/
```

### 前端测试（Playwright）

```bash
cd frontend
npm test              # 运行所有测试（无头模式）
npm run test:headed   # 显示浏览器运行
npm run test:ui       # 使用 Playwright UI 运行
```

**注意**：前端测试需要同时运行前端（端口 3000）和后端（端口 8000）服务器。如果未运行，Playwright 配置会自动启动它们。

## 开发

### 代码格式化和质量检查

```bash
cd backend
uv run ruff check --fix .   # 检查并修复 linting
uv run ruff format .        # 格式化代码
uv run pyright              # 类型检查
```

### 架构说明

项目遵循模块化架构：
- **Routes**：带端点级速率限制的 API 端点
- **Services**：业务逻辑（下载、转录、翻译等）
- **Database**：SQLModel ORM + SQLite（可轻松迁移到 PostgreSQL）
- **Storage**：本地和未来云存储的抽象层

### 前端开发

前端使用：
- **Vue 3** 构建响应式 UI
- **Tailwind CSS**（CDN）进行样式设计
- **基于哈希的路由**实现 SPA 导航
- **统一播放器接口**支持 YouTube 和本地上传

## 许可证

MIT License
