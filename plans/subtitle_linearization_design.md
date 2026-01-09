# 滚动字幕线性化算法设计 (Subtitle Linearization Design)

## 1. 问题分析

### 背景
自动生成的字幕（特别是直播流或某些 ASR 系统输出）通常采用“滚动”或“累积”模式。在这种模式下，为了给观众提供上下文，当前的字幕块往往包含前一个字幕块的文本内容。

### 观察到的模式
根据输入示例：
*   **Segment 1**: `A` (时间 $T_1$)
*   **Segment 2**: `A + B` (时间 $T_2$)
*   **Segment 3**: `B + C` (时间 $T_3$)

这种模式表明：
1.  **后缀重叠 (Suffix Overlap)**：$Text_{i-1}$ 的末尾部分与 $Text_{i}$ 的开头部分重复。
2.  **信息增量 (Information Increment)**：$Text_{i}$ 相对于 $Text_{i-1}$ 的新增内容（即 $B$ 相对于 $A+B$，或 $C$ 相对于 $B+C$）是该时间段 $T_i$ 内实际发生的对话内容。
3.  **时间轴归属**：由于 $A$ 已经在 $T_1$ 展示过，且 $A+B$ 在 $T_2$ 展示，可以推断 $B$ 的内容主要对应 $T_2$ 的时间段。

### 目标
从每个字幕块中剥离掉“继承”自上一块的重叠内容，只保留“新增”内容，并将其与当前时间戳关联。

---

## 2. 算法逻辑

### 核心思想
遍历字幕列表，对于每一个字幕块 $S_i$，将其文本与前一个字幕块 $S_{i-1}$ 的文本进行比较，寻找 $S_{i-1}$ 的**最长后缀**与 $S_i$ 的**最长前缀**之间的匹配。

### 算法步骤 (Pseudocode)

```python
def linearize_subtitles(subtitles):
    """
    Input: List of objects {start, end, text}
    Output: List of objects {start, end, text} (linearized)
    """
    linearized = []
    if not subtitles:
        return linearized

    # 1. 初始化
    # 第一个字幕默认认为是全新的
    linearized.append(subtitles[0])
    
    # 维持一个"前文缓冲区"，用于和下一句比较
    # 注意：有时候滚动的窗口可能比上一句更长或更短，
    # 严谨的做法是拿"原始的上一句全文"来做重叠检测。
    prev_text_raw = subtitles[0].text

    for i in range(1, len(subtitles)):
        curr = subtitles[i]
        curr_text_raw = curr.text
        
        # 2. 寻找重叠 (Find Overlap)
        # 目标：找到 prev_text_raw 的后缀 与 curr_text_raw 的前缀 的最大匹配
        overlap_len = find_longest_overlap(prev_text_raw, curr_text_raw)
        
        # 3. 提取新增内容 (Extract New Content)
        # 只有在重叠长度之后的才是新内容
        new_content = curr_text_raw[overlap_len:].strip()
        
        # 4. 构建新字幕块
        if new_content:
            # 只有当有实质性新内容时才添加
            new_item = {
                "start": curr.start,
                "end": curr.end,
                "text": new_content
            }
            linearized.append(new_item)
        else:
            # 如果没有新内容（完全重复），可能需要考虑延长上一句的结束时间
            # 或者直接忽略（视具体需求而定，通常忽略即可）
            pass
            
        # 5. 更新上下文
        # 无论是否有新内容，当前的原始文本都将成为下一轮比较的"前文"
        prev_text_raw = curr_text_raw

    return linearized

def find_longest_overlap(s1, s2):
    """
    寻找 s1 的后缀与 s2 的前缀的最长公共部分。
    返回重叠部分的长度。
    """
    # 优化策略：
    # 从 s2 的最大可能长度开始尝试，递减长度
    # 这里的最大可能长度不能超过 s1 的长度
    max_len = min(len(s1), len(s2))
    
    # 阈值：为了避免错误匹配单个字符（如 'a'），可以设置最小匹配长度
    # 但对于英文单词间可能有空格，需谨慎。
    # 建议先进行简单的字符串匹配。
    
    for length in range(max_len, 0, -1):
        # 检查 s1 的最后 length 个字符 是否等于 s2 的前 length 个字符
        if s1.endswith(s2[:length]):
            return length
            
    return 0
```

---

## 3. 边界情况处理与优化

### 3.1 模糊匹配 (Fuzzy Matching)
由于 ASR 的不稳定性，滚动的文本可能发生微小变化（标点、大小写、个别错词）。
*   **策略**：在比较前先进行**标准化**（转小写、去除标点）。计算出重叠长度后，再映射回原始文本的长度进行切分。
*   **容错**：如果标准化后仍不完全匹配，可以计算 Levenshtein 距离。若相似度超过阈值（如 90%），则视为重叠。

### 3.2 完全包含 (Full Containment)
*   情况：$S_{i-1} = "Hello world"$, $S_i = "Hello world"`
*   处理：`new_content` 为空。算法将跳过输出，但会将 $S_i$ 设为新的 `prev_text_raw`。

### 3.3 包含关系反转 (Reversed Containment) - 较少见但可能
*   情况：$S_{i-1} = "Hello world my friend"$, $S_i = "world my friend"`
*   分析：这意味着字幕窗口在缩小，或者回滚。
*   处理：Overlap 检测会发现 $S_{i-1}$ 的后缀 "world my friend" 与 $S_i$ 的前缀（即全文）匹配。Overlap 长度等于 $S_i$ 长度。`new_content` 为空。正确。

### 3.4 极短重叠 (Short Overlap)
*   情况：$S_{i-1} = "... the"$, $S_i = "the ..."`
*   风险：仅仅匹配了单词 "the" 可能是巧合，而非滚动重叠。
*   处理：设置 **最小重叠阈值 (Minimum Overlap Threshold)**。例如，重叠长度必须 > 5 个字符，或者包含至少 2 个单词（除非重叠就是整个句子）。如果是 ASR 滚动字幕，重叠通常很长，因此可以设置较高的置信度。

### 3.5 时间间隙 (Time Gaps)
*   如果 $S_{i-1}$ 结束时间和 $S_i$ 开始时间相差很大（例如 > 2秒），即使文本有重叠，也可能是说话人重复了之前的话，而不是字幕滚动。
*   **策略**：如果 `start_time(current) - end_time(previous) > threshold`，则强制重置，不进行去重（认为是一句新的、独立的话）。

---

## 4. 验证方案

### 4.1 单元测试用例
构造以下测试数据进行验证：

1.  **标准滚动**：
    *   In: ["A", "A B", "B C"]
    *   Out: ["A", "B", "C"]
2.  **完全重复**：
    *   In: ["Hello", "Hello", "Hello World"]
    *   Out: ["Hello", "World"]
3.  **无重叠**：
    *   In: ["Hello", "World"]
    *   Out: ["Hello", "World"]
4.  **部分字符干扰（需模糊匹配）**：
    *   In: ["Hello world.", "hello world is great"]
    *   Out: ["Hello world.", "is great"] (注意处理标点差异)

### 4.2 视觉验证
将生成的线性字幕叠加回视频或生成 `.srt` 文件，人工阅读是否通顺，是否存在明显的断句重复（如 "Hello world world is great"）。
