# ShadowPartner - 视频影子跟读 App (MVP) 开发计划

## 1. 项目概述
构建一个支持 PWA 的视频影子跟读应用。用户输入 YouTube 视频链接，App 自动生成带注音的日语字幕和中文翻译。核心特色是支持日语的“词级别”高亮和假名注音，辅助用户进行跟读练习。

## 2. 技术栈
*   **后端**: Python 3.10+
    *   **框架**: FastAPI (高性能 Web 框架)
    *   **视频/音频处理**: `yt-dlp` (下载 YouTube 音频), `ffmpeg` (音频处理)
    *   **AI/语音识别**: `openai-whisper` (语音转文字，提取时间戳)
    *   **日语处理**: `mecab-python3` (分词), `unidic-lite` (词典)
    *   **翻译**: 待定 (可使用免费翻译库如 `googletrans` 或集成 LLM API)
*   **前端**: Vue.js 3
    *   **构建工具**: Vite
    *   **语言**: JavaScript / TypeScript (推荐 TypeScript 以保证数据结构清晰)
    *   **UI 框架**: Tailwind CSS (轻量级，便于定制) 或 Element Plus (组件丰富) - *建议 MVP 使用原生 CSS 或 Tailwind 以保持简单*
    *   **PWA**: Vite PWA Plugin
    *   **视频播放**: `youtube-iframe-api`
*   **部署**: Docker (可选，便于环境统一)

## 3. 核心功能 (MVP)
1.  **视频输入**: 支持输入 YouTube 视频 URL。
2.  **自动处理**:
    *   提取音频。
    *   Whisper 识别生成日语字幕（带词级别时间戳）。
    *   MeCab 对日语字幕进行分词和注音。
    *   **关键**: 将 Whisper 的时间戳与 MeCab 的分词结果对齐。
    *   生成中文翻译（整句）。
3.  **跟读界面**:
    *   播放 YouTube 视频。
    *   **日文栏**: 显示日语汉字 + 假名注音 (`<ruby>` 标签)。播放时，当前发音的**单词**高亮显示。
    *   **中文栏**: 显示对应的中文翻译（无需高亮）。
4.  **PWA**: 支持安装到桌面/手机。

## 4. 数据结构设计 (API 契约)

后端 `/api/process` 返回的 JSON 结构示例：

```json
{
  "video_id": "dQw4w9WgXcQ",
  "title": "Sample Japanese Video",
  "segments": [
    {
      "start": 0.0,
      "end": 2.5,
      "translation": "今天天气很好。", // 中文翻译
      "words": [
        {
          "text": "今日",      // 原始文本 (MeCab 分词结果)
          "reading": "きょう", // 平假名读音 (MeCab 结果)
          "start": 0.0,       // 开始时间 (Whisper 对齐后)
          "end": 0.8          // 结束时间 (Whisper 对齐后)
        },
        {
          "text": "は",
          "reading": "は",
          "start": 0.8,
          "end": 1.0
        },
        {
          "text": "いい",
          "reading": "いい",
          "start": 1.0,
          "end": 1.5
        },
        {
          "text": "天気",
          "reading": "てんき",
          "start": 1.5,
          "end": 2.5
        }
      ]
    }
    // ... 更多句子
  ]
}
```

## 5. 开发步骤 (Step-by-Step)

### Phase 1: 基础架构搭建
- [ ] **1.1 后端环境**: 初始化 FastAPI 项目，安装 `fastapi`, `uvicorn`, `yt-dlp`, `openai-whisper`, `mecab-python3`, `unidic-lite`.
- [ ] **1.2 前端环境**: 使用 `npm create vue@latest` 初始化 Vue 3 项目，安装 `vite-plugin-pwa`.

### Phase 2: 后端核心逻辑 (The "Hard" Part)
- [ ] **2.1 音频获取**: 实现 `VideoDownloader` 类，封装 `yt-dlp`，输入 URL，输出音频文件路径。
- [ ] **2.2 基础听写**: 实现 `Transcriber` 类，封装 `whisper`，输出原始的 segment 和 word_timestamps。
- [ ] **2.3 日语分析**: 实现 `JapaneseAnalyzer` 类，封装 `MeCab`，输入文本，输出分词和读音列表。
- [ ] **2.4 对齐算法 (核心)**: 实现 `Aligner` 逻辑。
    -   输入: Whisper 的词列表 (带时间) + MeCab 的词列表 (带读音)。
    -   逻辑: 基于字符长度或字符匹配，将 Whisper 的时间分配给 MeCab 的词。
    -   输出: 符合 API 契约的 `words` 列表。
- [ ] **2.5 翻译服务**: 实现简单的翻译功能 (日 -> 中)。
- [ ] **2.6 API 整合**: 创建 `/api/process` 端点，串联上述所有步骤，返回最终 JSON。

### Phase 3: 前端界面开发
- [ ] **3.1 基础 UI**: 创建输入框、加载状态、视频播放器容器。
- [ ] **3.2 播放器集成**: 封装 `YouTubePlayer` 组件，支持 `seekTo`, `play`, `pause` 以及 `timeupdate` 事件监听。
- [ ] **3.3 字幕渲染组件**:
    -   接收 `segments` 数据。
    -   遍历渲染：使用 `<ruby>` 标签展示 `<rb>{text}</rb><rt>{reading}</rt>`。
    -   中文翻译显示在下方。
- [ ] **3.4 同步高亮逻辑**:
    -   监听 `timeupdate` (频率可能不够，可使用 `requestAnimationFrame` 轮询 `player.getCurrentTime()`)。
    -   查找当前时间落在哪个 `word` 的 `[start, end]` 区间内。
    -   给该 `word` 对应的 DOM 元素添加 `.active` 类。
    -   实现自动滚动：确保当前高亮的句子始终在视野内。

### Phase 4: PWA 与 优化
- [ ] **4.1 PWA 配置**: 配置 `manifest.json` (图标、名称、主题色)，确保 Chrome 可识别并提示安装。
- [ ] **4.2 体验优化**: 添加错误处理 (如无效链接、处理超时)，加载动画。

## 6. 后续改进 (Post-MVP)
- [ ] 支持更多语言对。
- [ ] 用户账户系统 (保存学习记录)。
- [ ] 单词本功能 (点击单词加入生词本)。
- [ ] 麦克风录音与波形对比 (真正的 Shadowing 评分)。
