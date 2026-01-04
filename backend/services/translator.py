import os
import google.generativeai as genai
from typing import List
import time

# Setup API Key from environment variable
API_KEY = os.environ.get("GEMINI_API_KEY")

if API_KEY:
    genai.configure(api_key=API_KEY)

class Translator:
    def __init__(self):
        self.model = None
        if API_KEY:
            self.model = genai.GenerativeModel('gemini-pro')
        self.available = bool(API_KEY)

    def translate(self, text: str, target_lang: str = "Chinese") -> str:
        if not self.available:
            return "[需要配置 GEMINI_API_KEY]"
        
        if not text.strip():
            return ""

        try:
            prompt = f"Translate the following Japanese text to {target_lang}. Only output the translation, no explanation:\n\n{text}"
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"Gemini translation error: {e}")
            return "[翻译失败]"
            
    def translate_batch(self, texts: List[str], target_lang: str = "Chinese") -> List[str]:
        """
        Translates a list of texts in one go to save time and quota.
        """
        if not self.available:
            return ["[需要配置 GEMINI_API_KEY]"] * len(texts)
            
        if not texts:
            return []
            
        # Process in chunks of 20 lines to avoid token limits or confusion
        CHUNK_SIZE = 20
        all_results = []
        
        for i in range(0, len(texts), CHUNK_SIZE):
            chunk = texts[i:i + CHUNK_SIZE]
            
            # Format:
            # 1. <text>
            # 2. <text>
            joined_text = "\n".join([f"{idx+1}. {t}" for idx, t in enumerate(chunk)])
            
            prompt = (
                f"Translate the following Japanese sentences to {target_lang} (Simplified Chinese). "
                f"Output strictly as a numbered list corresponding to the input numbers (e.g., '1. translation'). "
                f"Do not merge sentences. Maintain the original tone.\n\n{joined_text}"
            )
            
            try:
                # Add a small delay if processing multiple chunks to be nice to the API
                if i > 0: time.sleep(1)
                
                response = self.model.generate_content(prompt)
                response_text = response.text.strip()
                
                # Parse logic
                lines = response_text.split('\n')
                chunk_map = {}
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    # Look for "1. " pattern
                    parts = line.split('.', 1)
                    if len(parts) >= 2 and parts[0].strip().isdigit():
                        idx = int(parts[0].strip()) - 1
                        trans = parts[1].strip()
                        chunk_map[idx] = trans
                
                # Reconstruct chunk results
                for j in range(len(chunk)):
                    all_results.append(chunk_map.get(j, "[翻译缺失]"))
                    
            except Exception as e:
                print(f"Gemini batch translation error: {e}")
                # Fallback: append error messages for this chunk
                all_results.extend(["[翻译错误]"] * len(chunk))
                
        return all_results
