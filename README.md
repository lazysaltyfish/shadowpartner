# ShadowPartner (影子跟读)

## 项目简介
这是一个支持 PWA 的视频影子跟读应用。它能自动为 YouTube 视频生成日语字幕（带假名注音和词级别高亮）以及中文翻译，帮助你进行跟读练习。

## 环境准备 (Prerequisites)

1.  **Python 3.10+**
2.  **FFmpeg**:
    *   **Windows**: 请下载 [FFmpeg](https://ffmpeg.org/download.html)，解压，并将 `bin` 目录添加到系统的 PATH 环境变量中。打开 PowerShell 输入 `ffmpeg -version` 确认安装成功。
    *   **Linux**: 项目包含自动安装脚本 (`backend/setup_ffmpeg.py`)，也可以使用 `sudo apt install ffmpeg`。
3.  **API Key**: 获取 Google Gemini API Key 用于翻译。

## 安装步骤 (Installation)

1.  **安装后端依赖**:
    进入 `backend` 目录：
    ```bash
    cd backend
    pip install -r requirements.txt
    # 或者如果你安装了 uv (推荐):
    uv sync
    ```

2.  **安装 FFmpeg (Linux Only)**:
    如果你的 Linux 系统没有 FFmpeg，运行此脚本自动下载静态构建版：
    ```bash
    python setup_ffmpeg.py
    ```

## 运行 (Running)

你需要打开两个终端窗口，分别启动后端和前端。

### 1. 启动后端 (Backend)

进入 `backend` 目录：

*   **Windows (PowerShell)**:
    ```powershell
    $env:GEMINI_API_KEY="你的_GEMINI_API_KEY"
    uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```
    *(如果没有 uv，使用 `python -m uvicorn main:app ...`)*

*   **Linux/Mac**:
    ```bash
    export GEMINI_API_KEY="你的_GEMINI_API_KEY"
    uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```

后端将在 `http://localhost:8000` 启动。

### 2. 启动前端 (Frontend)

你有两种方式启动前端服务器：

**方法 A: 使用系统 Python (如果已安装)**
```bash
cd frontend
python -m http.server 3000
# 或者 python3 -m http.server 3000
```

**方法 B: 使用 uv 环境 (推荐)**
如果你只安装了 uv，可以直接利用后端的环境来启动：
```bash
# 在 backend 目录下运行
cd backend
uv run python -m http.server --directory ../frontend 3000
```

启动后，打开浏览器访问 `http://localhost:3000`。

## 功能说明
*   **输入**: YouTube 视频链接 (例如 `https://www.youtube.com/watch?v=...`)。
*   **处理**: 后端会自动下载音频、使用 Whisper 识别、MeCab 分词注音、Gemini 翻译。
*   **跟读**:
    *   **日语栏**: 显示汉字和假名。播放时，当前朗读的单词会高亮显示。
    *   **翻译栏**: 显示中文翻译。
    *   **交互**: 点击任意单词，视频会跳转到该单词开始的时间。
