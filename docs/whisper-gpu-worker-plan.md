# Whisper GPU分离 - WebSocket Worker 方案设计文档

> **创建日期**: 2026-01-21
> **状态**: 设计阶段
> **目标**: 将Whisper转录任务分离到GPU机器，Worker通过WebSocket反向连接到Backend

---

## 一、背景

### 当前问题
- Whisper转录需要在Backend服务器上运行，占用GPU资源
- 需要将GPU密集型任务分离到独立的GPU机器上
- GPU机器可能位于NAT后，无法被Backend主动连接

### 解决方案
- **通信方式**: WebSocket (Worker反向连接)
- **文件传输**: HTTP预签名URL
- **部署模式**: 单Worker，支持容错重连
- **鉴权机制**: Token-based认证

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           主 Backend (无GPU)                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │  WebSocket Server                                                        │   │
│  │  Endpoint: ws://backend:8000/ws/worker                                  │   │
│  │                                                                          │   │
│  │  消息协议:                                                               │ │
│  │  ┌────────────────────────────────────────────────────────────────────┐ │   │
│  │  │ Client → Server:                                                  │ │   │
│  │  │   {"type": "register", "token": "xxx", "worker_id": "gpu-01"}     │ │   │
│  │  │   {"type": "heartbeat"}                                           │ │   │
│  │  │   {"type": "job_complete", "job_id": "...", "result": {...}}      │ │   │
│  │  │   {"type": "job_progress", "job_id": "...", "progress": 45}      │ │   │
│  │  │   {"type": "job_failed", "job_id": "...", "error": "..."}        │ │   │
│  │  │                                                                  │ │   │
│  │  │ Server → Client:                                                  │ │   │
│  │  │   {"type": "registered", "worker_id": "gpu-01"}                  │ │   │
│  │  │   {"type": "job_assigned", "job_id": "...", "audio_url": "..."}  │ │   │
│  │  │   {"type": "heartbeat_ack"}                                      │ │   │
│  │  │   {"type": "error", "message": "..."}                            │ │   │
│  │  └────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                    ↕ WebSocket 连接                             │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    ↕ 反向连接 (Worker主动)
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        GPU Worker (任意机器)                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │  WhisperWorkerClient                                                     │   │
│  │                                                                          │   │
│  │  1. 连接 WebSocket (带token鉴权)                                         │   │
│  │  2. 发送 register 消息                                                   │   │
│  │  3. 接收 job_assigned → 下载音频 (HTTP预签名URL)                         │   │
│  │  4. 执行 Whisper 转录                                                    │   │
│  │  5. 发送结果 → 请求下一个任务                                            │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、通信协议设计

### 3.1 WebSocket消息类型

```python
# Client → Server 消息

{
    "type": "register",
    "token": "prod_token_xxx",
    "worker_id": "gpu-01",
    "capabilities": {
        "model": "base",
        "device": "cuda",
        "fp16": false
    }
}

{
    "type": "heartbeat"
}

{
    "type": "job_complete",
    "job_id": "uuid",
    "result": {
        "segments": [...],
        "language": "ja",
        "language_probs": {...}
    }
}

{
    "type": "job_progress",
    "job_id": "uuid",
    "progress": 45,
    "message": "Transcribing... (45%)"
}

{
    "type": "job_failed",
    "job_id": "uuid",
    "error": "Transcription failed: ..."
}


# Server → Client 消息

{
    "type": "registered",
    "worker_id": "gpu-01",
    "server_time": 1737456000.0
}

{
    "type": "job_assigned",
    "job_id": "uuid",
    "audio_url": "https://backend/temp/audio/xxx.wav?signature=...",
    "audio_size": 12345678,
    "options": {
        "language": "ja",
        "model_size": "base",
        "fp16": false
    }
}

{
    "type": "heartbeat_ack",
    "server_time": 1737456000.0
}

{
    "type": "error",
    "code": "INVALID_TOKEN",
    "message": "Invalid worker token"
}
```

### 3.2 数据模型

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime

class JobStatus(str, Enum):
    PENDING = "pending"      # 等待分配
    ASSIGNED = "assigned"    # 已分配给worker
    PROCESSING = "processing" # worker正在处理
    COMPLETED = "completed"   # 完成
    FAILED = "failed"        # 失败

class WorkerStatus(str, Enum):
    OFFLINE = "offline"
    IDLE = "idle"           # 已连接，空闲
    BUSY = "busy"           # 已连接，处理中

@dataclass
class TranscribeJob:
    job_id: str
    task_id: str                    # 关联的原始task_id
    audio_path: str                 # 本地音频路径
    audio_url: str                  # 预签名URL
    status: JobStatus
    worker_id: Optional[str] = None # 当前处理的worker
    assigned_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    timeout_at: Optional[datetime] = None  # 超时时间
    retry_count: int = 0            # 重试次数
    max_retries: int = 2            # 最大重试次数
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@dataclass
class WorkerInfo:
    worker_id: str
    status: WorkerStatus
    connected_at: datetime
    last_heartbeat: datetime
    current_job_id: Optional[str] = None
    capabilities: Dict[str, Any] = None
    ws_connection: Optional[Any] = None  # WebSocket连接
```

---

## 四、容错与重连设计

### 4.1 状态机

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Worker 状态机                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│    [未连接] ──register──→ [已注册] ──job_assigned──→ [处理中]                    │
│        ↑                      ↓                       ↓                          │
│        │                  [空闲]                    ├──job_complete──→ [空闲]    │
│        │                      ↑                       ├──job_failed──→ [空闲]     │
│        └──────reconnect────────┴───────────────────────┘                         │
│                                                                                 │
│    心跳机制:                                                                     │
│    - Worker 每 15 秒发送心跳                                                    │
│    - Backend 30 秒无心跳 → 标记离线                                             │
│    - 离线 Worker 的任务自动重新入队                                              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Worker端重连逻辑

```python
class WhisperWorkerClient:
    def __init__(self, backend_url: str, token: str, worker_id: str):
        self.backend_url = backend_url
        self.token = token
        self.worker_id = worker_id
        self.reconnect_delay = 1  # 初始1秒
        self.max_reconnect_delay = 30
        self.current_job = None   # 当前正在处理的任务
        self.ws = None

    async def connect(self):
        while True:
            try:
                logger.info(f"连接到 {self.backend_url}...")
                self.ws = await websockets.connect(self.backend_url)

                # 注册
                await self.register()

                # 连接成功，重置重连延迟
                self.reconnect_delay = 1
                logger.info("连接成功")

                # 进入消息循环
                await self.message_loop()

            except Exception as e:
                logger.warning(f"连接断开: {e}, {self.reconnect_delay}秒后重连...")
                # 如果正在处理任务，标记为失败
                if self.current_job:
                    await self.abort_current_job()

                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)

    async def register(self):
        await self.ws.send_json({
            "type": "register",
            "token": self.token,
            "worker_id": self.worker_id,
            "capabilities": self.get_capabilities()
        })

        response = await self.ws.recv_json()
        if response["type"] == "registered":
            logger.info(f"注册成功: {response['worker_id']}")
        elif response["type"] == "error":
            raise Exception(f"注册失败: {response['message']}")

    async def message_loop(self):
        heartbeat_task = asyncio.create_task(self.send_heartbeat())

        try:
            async for message in self.ws:
                data = json.loads(message)

                if data["type"] == "job_assigned":
                    await self.handle_job_assigned(data)
                elif data["type"] == "heartbeat_ack":
                    logger.debug("心跳确认")
                elif data["type"] == "error":
                    logger.error(f"服务端错误: {data['message']}")

        finally:
            heartbeat_task.cancel()

    async def send_heartbeat(self):
        while True:
            await asyncio.sleep(15)
            if self.ws and not self.ws.closed:
                await self.ws.send_json({"type": "heartbeat"})
```

### 4.3 任务超时与重试

```python
# Backend端

class JobQueue:
    def __init__(self):
        self.jobs: Dict[str, TranscribeJob] = {}
        self.pending_queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_jobs: Dict[str, str] = {}  # worker_id -> job_id

    async def assign_job(self, worker_id: str) -> Optional[str]:
        """为Worker分配一个任务"""
        if self.pending_queue.empty():
            return None

        job_id = await self.pending_queue.get()
        job = self.jobs.get(job_id)

        if job and job.status == JobStatus.PENDING:
            job.status = JobStatus.ASSIGNED
            job.worker_id = worker_id
            job.assigned_at = datetime.now()
            job.timeout_at = datetime.now() + timedelta(seconds=600)  # 10分钟超时
            self.worker_jobs[worker_id] = job_id
            return job_id

        return None

    async def check_timeouts(self):
        """检查超时任务"""
        now = datetime.now()
        for job_id, job in list(self.jobs.items()):
            if job.status == JobStatus.ASSIGNED and job.timeout_at and now > job.timeout_at:
                logger.warning(f"任务超时: {job_id}")
                await self.retry_job(job_id)

    async def retry_job(self, job_id: str):
        """重试任务"""
        job = self.jobs.get(job_id)
        if not job:
            return

        # 清除worker关联
        if job.worker_id in self.worker_jobs:
            del self.worker_jobs[job.worker_id]

        job.retry_count += 1
        if job.retry_count > job.max_retries:
            job.status = JobStatus.FAILED
            job.error = "Max retries exceeded"
        else:
            job.status = JobStatus.PENDING
            job.worker_id = None
            job.assigned_at = None
            job.timeout_at = None
            await self.pending_queue.put(job_id)
```

---

## 五、Whisper进度实现方案

由于 `openai-whisper` 不支持原生进度回调，采用**分段预估**方案：

### 5.1 进度报告器

```python
class ProgressReporter:
    """Whisper转录进度报告器"""

    def __init__(self, ws, job_id: str, total_duration: float):
        self.ws = ws
        self.job_id = job_id
        self.total_duration = total_duration
        self.start_time = None
        self.last_report = 0
        self.last_report_time = 0
        # 历史平均处理速度: 秒/音频秒
        self.processing_rate = 0.15  # 初始估算 (GPU大概快6-7倍实时)
        self.lock = asyncio.Lock()

    async def start(self):
        self.start_time = time.time()
        self.last_report_time = time.time()
        await self._send_progress(0, "Loading model...")

    async def phase(self, phase: str, progress: int):
        """报告阶段进度"""
        messages = {
            "loading": "Loading model...",
            "preload": "Preprocessing audio...",
            "transcribing": "Transcribing...",
            "postprocess": "Post-processing..."
        }
        await self._send_progress(progress, messages.get(phase, phase))

    async def update(self, message: str = None):
        """更新进度 (定期调用)"""
        if not self.start_time:
            return

        async with self.lock:
            elapsed = time.time() - self.start_time
            # 基于处理时长和预估速度计算进度
            estimated_total = self.total_duration * self.processing_rate
            progress = min(int(elapsed / estimated_total * 100), 95)  # 最高95%

            # 每5秒或进度变化10%时报告
            now = time.time()
            if progress - self.last_report >= 10 or now - self.last_report_time >= 5:
                await self._send_progress(progress, message or "Transcribing...")
                self.last_report = progress
                self.last_report_time = now

    async def complete(self):
        """标记完成"""
        await self._send_progress(100, "Complete")
        # 更新处理速度用于下次估算
        if self.start_time:
            elapsed = time.time() - self.start_time
            if self.total_duration > 0:
                self.processing_rate = elapsed / self.total_duration

    async def _send_progress(self, progress: int, message: str):
        try:
            await self.ws.send_json({
                "type": "job_progress",
                "job_id": self.job_id,
                "progress": progress,
                "message": message
            })
        except Exception as e:
            logger.warning(f"发送进度失败: {e}")
```

### 5.2 转录封装

```python
async def transcribe_with_progress(
    model,
    audio_path: str,
    ws,
    job_id: str,
    language: str = "ja"
):
    """带进度报告的转录"""
    # 获取音频时长用于进度估算
    import ffmpeg
    probe = ffmpeg.probe(audio_path)
    duration = float(probe['format']['duration'])

    reporter = ProgressReporter(ws, job_id, duration)

    try:
        await reporter.start()
        await reporter.phase("preload", 5)

        # 在单独线程执行Whisper
        loop = asyncio.get_event_loop()

        # 启动进度更新任务
        progress_task = asyncio.create_task(reporter.update())

        try:
            result = await loop.run_in_executor(
                None,
                lambda: model.transcribe(
                    audio_path,
                    language=language,
                    word_timestamps=True
                )
            )
        finally:
            progress_task.cancel()

        await reporter.phase("postprocess", 95)
        await reporter.complete()

        return result

    except Exception as e:
        await ws.send_json({
            "type": "job_failed",
            "job_id": job_id,
            "error": str(e)
        })
        raise
```

---

## 六、文件传输方案

### 6.1 预签名URL生成

```python
# backend/workers/storage_bridge.py

from datetime import datetime, timedelta
from services.storage.base import BaseStorage
import secrets

class StorageBridge:
    """存储桥接 - 为Worker生成临时访问URL"""

    def __init__(self, storage: BaseStorage, backend_base_url: str):
        self.storage = storage
        self.backend_base_url = backend_base_url
        self.signatures = {}  # {path: (signature, expires_at)}

    async def get_presigned_url(self, file_path: str, ttl_seconds: int = 3600) -> str:
        """生成预签名URL"""
        signature = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

        self.signatures[file_path] = (signature, expires_at)

        return f"{self.backend_base_url}/api/internal/temp-file?path={file_path}&sig={signature}"

    def validate_signature(self, file_path: str, signature: str) -> bool:
        """验证签名"""
        if file_path not in self.signatures:
            return False

        stored_signature, expires_at = self.signatures[file_path]

        if datetime.now() > expires_at:
            del self.signatures[file_path]
            return False

        return secrets.compare_digest(signature, stored_signature)
```

### 6.2 临时文件下载端点

```python
# backend/routers/internal.py (新增)

from fastapi import APIRouter, HTTPException, Response
from workers.storage_bridge import storage_bridge

router = APIRouter(prefix="/api/internal", tags=["internal"])

@router.get("/temp-file")
async def get_temp_file(path: str, sig: str):
    """通过预签名URL获取临时文件"""
    if not storage_bridge.validate_signature(path, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired signature")

    # 从storage读取文件
    try:
        file_data = await storage.get(path)
        return Response(content=file_data, media_type="audio/wav")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
```

### 6.3 Worker下载流程

```python
# Worker端

async def download_audio(url: str, dest_path: str):
    """下载音频文件"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"下载失败: {resp.status}")

            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0

            with open(dest_path, 'wb') as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    # 可选: 报告下载进度

            logger.info(f"下载完成: {dest_path} ({downloaded} bytes)")
```

---

## 七、文件结构

### Backend侧

```
backend/
├── workers/                          # 新模块
│   ├── __init__.py
│   ├── manager.py                    # WebSocket服务端，Worker管理
│   ├── job_queue.py                  # 转录任务队列
│   ├── storage_bridge.py             # 预签名URL生成
│   └── models.py                     # Worker相关数据模型
│
├── routers/
│   ├── workers.py                    # 新增: WebSocket路由
│   └── internal.py                   # 新增: 内部API (临时文件下载)
│
├── processing.py                     # 修改: 集成worker转录
│
├── state.py                          # 修改: 添加worker状态
│
├── services_registry.py              # 修改: 初始化worker manager
│
└── settings.py                       # 修改: 添加worker配置
    # 新增配置项:
    # WORKER_WS_PORT: WebSocket端口 (默认8000)
    # WORKER_API_TOKENS: Worker认证token字典
    # WORKER_HEARTBEAT_INTERVAL: 心跳间隔 (默认15秒)
    # WORKER_HEARTBEAT_TIMEOUT: 心跳超时 (默认30秒)
    # WORKER_JOB_TIMEOUT: 任务超时 (默认600秒)
```

### Worker侧 (独立项目)

```
worker/                               # 新独立项目
├── main.py                           # Worker入口
├── client.py                         # WebSocket客户端
├── transcriber.py                    # Whisper封装
├── downloader.py                     # 音频下载
├── config.py                         # 配置加载
├── requirements.txt                  # 依赖
└── README.md                         # 使用说明
```

---

## 八、processing.py 修改点

```python
# processing.py - 修改后的转录调用

async def process_audio_task(...):
    # ... 前面的代码不变 (下载、缓存检查等) ...

    # 2. Transcribe (优先使用Worker)
    gen_result = None

    # 检查是否有可用的Worker
    if workers_manager.has_active_worker():
        update_task(task_id, TaskStatus.PROCESSING, 10, "Queued for transcription...")

        try:
            gen_result = await workers_manager.submit_transcribe_job(
                file_path=file_path,
                language="ja",
                task_id=task_id,
                timeout=600,  # 10分钟超时
            )
            transcribe_time = ...  # 从worker返回结果中获取

        except asyncio.TimeoutError:
            logger.warning(f"Task {task_id}: Worker transcription timeout, falling back to local")
            # 回退到本地转录
            ...
        except Exception as e:
            logger.error(f"Task {task_id}: Worker transcription failed: {e}")
            # 回退到本地转录
            ...
    else:
        # 使用本地转录
        update_task(task_id, TaskStatus.PROCESSING, 10, "Transcribing locally...")

        if services.whisper_lock:
            async with services.whisper_lock:
                gen_result = await run_cpu_bound(
                    services.transcriber.transcribe,
                    file_path,
                    language="ja",
                )
        else:
            gen_result = await run_cpu_bound(
                services.transcriber.transcribe,
                file_path,
                language="ja",
            )

    # ... 后续处理不变 (analysis, translation, save等) ...
```

---

## 九、环境变量配置

### Backend侧

```bash
# .env

# Worker配置
WORKER_WS_PORT=8000                                    # WebSocket监听端口
WORKER_API_TOKENS={"gpu-main":"token_xxx"}             # Worker认证token
WORKER_HEARTBEAT_INTERVAL=15                           # 心跳间隔(秒)
WORKER_HEARTBEAT_TIMEOUT=30                            # 心跳超时(秒)
WORKER_JOB_TIMEOUT=600                                # 任务超时(秒)

# 预签名URL
BACKEND_BASE_URL=https://your-backend.com             # 用于生成预签名URL
TEMP_FILE_TTL=3600                                    # 临时文件URL有效期(秒)
```

### Worker侧

```bash
# worker/.env

BACKEND_WS_URL=ws://your-backend.com:8000/ws/worker   # Backend WebSocket地址
WORKER_TOKEN=token_xxx                                # 认证token
WORKER_ID=gpu-01                                      # Worker标识

# Whisper配置
WHISPER_MODEL_SIZE=base                               # 模型大小
WHISPER_DEVICE=cuda                                   # 设备
WHISPER_FP16=false                                    # FP16精度

# 本地缓存
AUDIO_CACHE_DIR=./cache/audio                         # 音频缓存目录
MAX_CACHE_SIZE_GB=10                                  # 最大缓存大小
```

---

## 十、实现步骤

### Phase 1: Worker框架 (最简可用)
1. 创建 `backend/workers/` 模块
2. 实现WebSocket server和register handler
3. 实现基本的任务队列 (pending_queue)
4. 添加token鉴权

**验收标准**: Worker可以连接并注册，Backend可以分配任务

### Phase 2: Worker客户端
1. 创建独立 `worker/` 项目
2. 实现WebSocket连接和重连逻辑
3. 实现音频下载 (HTTP)
4. 实现Whisper调用封装

**验收标准**: Worker可以接收任务，下载音频，执行转录

### Phase 3: 集成
1. 修改 `processing.py` 集成worker调用
2. 添加任务状态追踪 (JobStatus)
3. 实现进度报告转发到TaskInfo

**验收标准**: Backend可以通过Worker完成转录任务

### Phase 4: 完善与容错
1. 添加任务超时重试机制
2. 添加心跳和离线检测
3. 添加Worker离线时的任务重新分配
4. 添加监控和日志

**验收标准**: Worker断线重连后任务可以继续处理

---

## 十一、监控与日志

### 关键监控指标

```python
# /health 端点新增字段

{
    "status": "healthy",
    "services": {...},
    "workers": {
        "connected": 1,
        "idle": 1,
        "busy": 0,
        "workers": [
            {
                "worker_id": "gpu-01",
                "status": "idle",
                "connected_at": "2026-01-21T10:00:00Z",
                "last_heartbeat": "2026-01-21T10:15:30Z",
                "jobs_completed": 42,
                "jobs_failed": 0
            }
        ]
    },
    "transcribe_jobs": {
        "pending": 0,
        "assigned": 0,
        "processing": 0
    }
}
```

### 日志格式

```
[WorkerManager] Worker registered: gpu-01
[WorkerManager] Job assigned: job_123 -> worker gpu-01
[WorkerManager] Job progress: job_123 (45%)
[WorkerManager] Job complete: job_123 (12.5s)
[WorkerManager] Heartbeat timeout: gpu-01, marking offline
[WorkerManager] Job reassigned: job_124 -> gpu-01 (retry 1)
```

---

## 十二、安全性考虑

1. **Token认证**: 所有Worker必须提供有效token才能注册
2. **预签名URL**: 临时文件URL有时效性和签名验证
3. **输入验证**: Worker发送的所有数据需要验证
4. **资源限制**:
   - 单个Worker最大并发任务数 (1)
   - 任务队列最大长度
   - 文件大小限制 (复用现有500MB限制)

---

## 十三、待讨论问题

1. **预签名URL实现**: 用现有的storage抽象还是新增独立API？
2. **多Worker负载均衡**: 当前方案单Worker，是否需要为未来预留多Worker能力？
3. **模型缓存**: Worker是否需要支持多模型热切换？
4. **进度粒度**: 当前的估算进度是否满足需求，还是需要更精确的进度？
5. **故障恢复**: Worker崩溃时，正在处理的任务如何恢复？

---

## 十四、参考资料

- [websockets库文档](https://websockets.readthedocs.io/)
- [openai-whisper文档](https://github.com/openai/whisper)
- [FastAPI WebSocket文档](https://fastapi.tiangolo.com/advanced/websockets/)
