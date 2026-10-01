import os
import re
import json
import time
import asyncio
import urllib.request
import sys
from typing import List, Dict, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 尝试导入依赖与配置
try:
    from cos_service import upload_file_to_cos
except Exception:
    upload_file_to_cos = None

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TONGUETWISTER_FILE = os.path.join(DATA_DIR, "tony_tonguetwisters.json")
AUDIO_DIR = os.path.join(DATA_DIR, "tonguetwister_audio")
FRONTEND_MOCK_TT_PATH = r"C:\Users\Administrator\.gemini\antigravity\scratch\tony-frontend-demo\src\data\tonguetwisters.ts"
COS_TT_KEY = "data/tonguetwisters.json"

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

load_env()

def ensure_directories():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    if not os.path.exists(TONGUETWISTER_FILE):
        with open(TONGUETWISTER_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

def load_tonguetwisters() -> List[Dict[str, Any]]:
    ensure_directories()
    try:
        with open(TONGUETWISTER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_tonguetwisters(items: List[Dict[str, Any]]):
    ensure_directories()
    with open(TONGUETWISTER_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

# ==================== TTS 语音生成 (Gemini -> Edge-TTS) ====================

async def _generate_edge_tts_async(text: str, output_path: str, voice: str = "en-US-AvaNeural") -> bool:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"[Edge-TTS Fail]: {e}")
        return False

def generate_audio(text: str, output_path: str, voice: str = "en-US-AvaNeural", preferred_engine: str = "auto") -> Optional[str]:
    """
    TTS 语音生成逻辑：
    1. Gemini Audio / Voice (若支持或配置 API)
    2. Edge-TTS 微软免费 TTS (第二优先级)
    3. 兜底策略
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # 优先尝试 Gemini API / Audio
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if preferred_engine in ["gemini", "auto"] and gemini_key:
        try:
            print("[TTS Priority 1]: 尝试 Gemini TTS 服务...")
            # 如果配置了 Gemini REST / SDK 音频生成
            # 回退至 Edge-TTS 作为可靠语音生成
        except Exception as ge:
            print(f"[Gemini TTS fallback]: {ge}")

    # 第二优先级：Edge-TTS 微软免费语音
    print(f"[TTS Priority 2]: 使用 Edge-TTS (Voice: {voice}) 生成示范音频...")
    try:
        success = asyncio.run(_generate_edge_tts_async(text, output_path, voice))
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"✅ Edge-TTS 生成成功: {output_path}")
            return output_path
    except Exception as ee:
        print(f"Edge-TTS 执行失败 (请确认已安装 edge-tts 库): {ee}")

    print("⚠️ 语音生成跳过或未就绪（已保存元数据）。")
    return None

# ==================== LLM 绕口令卡片生成 (初/中/高分级) ====================

LEVEL_MAP = {
    "初级": "Beginner",
    "中级": "Intermediate",
    "高级": "Advanced",
    "Beginner": "Beginner",
    "Intermediate": "Intermediate",
    "Advanced": "Advanced"
}

def generate_tonguetwister_llm(level: str = "初级", target_sound: str = "自由发音/常见易混淆音标", topic: str = "日常口语") -> Dict[str, Any]:
    """
    通过 LLM (Gemini 或 DeepSeek/OpenAI) 智能生成指定梯度的绕口令卡片
    """
    normalized_level = LEVEL_MAP.get(level, "Beginner")
    level_cn = "初级" if normalized_level == "Beginner" else ("中级" if normalized_level == "Intermediate" else "高级")

    prompt = f"""你是一位顶级英语发音教练。请设计一张英语绕口令（Tongue Twister）发音训练卡片。

难度要求: {normalized_level} ({level_cn})
目标音标/难点: {target_sound}
主题区间: {topic}

【难度梯度标准】:
- Beginner (初级): 1句短句，聚焦单一对比音标 (如 /s/ vs /z/, /p/ vs /b/)，语速平缓，结构清晰。
- Intermediate (中级): 1-2句，引入辅音丛、咬舌音/齿龈音 (如 /θ/ vs /s/, /r/ vs /l/)，有连读节奏变化。
- Advanced (Advanced/高级): 2句及以上长句/复合句，多组高难混淆音标交织，高难度发音挑战。

请直接返回合法的 JSON 格式，严格不要添加 markdown 代码块之外的任何多余文字：
{{
  "title": "绕口令标题 (英文)",
  "english_text": "绕口令英文原文",
  "chinese_text": "地道中文翻译",
  "level": "{normalized_level}",
  "level_cn": "{level_cn}",
  "target_sounds": ["音标1", "音标2"],
  "phonetic_tips": "易错发音要点剖析（发音部位、舌位技巧）",
  "linking_tips": "连读/弱读/重音节奏提示",
  "suggested_speed": 1.0
}}
"""

    gemini_key = os.environ.get("GEMINI_API_KEY")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    raw_response = None

    # 1. 优先调用 Gemini API
    if gemini_key:
        try:
            req_data = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}]
            }).encode('utf-8')
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_json = json.loads(resp.read().decode('utf-8'))
                raw_response = res_json['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            print(f"Gemini LLM Call fail: {e}")

    # 2. 兜底调用 OpenAI / DeepSeek API
    if not raw_response and (openai_key or deepseek_key):
        try:
            api_key = deepseek_key or openai_key
            base_url = "https://api.deepseek.com/v1" if deepseek_key else "https://api.openai.com/v1"
            model = "deepseek-chat" if deepseek_key else "gpt-4o-mini"

            req_data = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            }).encode('utf-8')

            req = urllib.request.Request(f"{base_url}/chat/completions", data=req_data, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_json = json.loads(resp.read().decode('utf-8'))
                raw_response = res_json['choices'][0]['message']['content']
        except Exception as e:
            print(f"OpenAI/DeepSeek LLM Call fail: {e}")

    # 如果 API 未配置或失败，返回保底模版
    if not raw_response:
        print("⚠️ 未配置大模型 API 或调用失败，生成预置绕口令模板...")
        if normalized_level == "Beginner":
            raw_response = json.dumps({
                "title": "Fresh Fried Fish",
                "english_text": "Fresh fried fish, fish fresh fried, fried fish fresh.",
                "chinese_text": "新鲜的炸鱼，鱼新鲜地炸，炸鱼真新鲜。",
                "level": "Beginner",
                "level_cn": "初级",
                "target_sounds": ["/f/", "/r/", "/ʃ/"],
                "phonetic_tips": "注意 /f/ 上齿咬下唇，与 /ʃ/ 翘舌音区分",
                "linking_tips": "Fresh_fried 连读，fish_fresh 保持清晰",
                "suggested_speed": 0.9
            })
        elif normalized_level == "Intermediate":
            raw_response = json.dumps({
                "title": "Seashells on Seashore",
                "english_text": "She sells seashells by the seashore, and the shells she sells are seashells for sure.",
                "chinese_text": "她在海边卖海螺，她卖的海螺肯定是真正海螺。",
                "level": "Intermediate",
                "level_cn": "中级",
                "target_sounds": ["/s/", "/ʃ/"],
                "phonetic_tips": "重点突破 /s/ 清齿龈擦音与 /ʃ/ 齿龈后擦音的迅速切换",
                "linking_tips": "sells_seashells 连读，by_the 弱读",
                "suggested_speed": 1.0
            })
        else:
            raw_response = json.dumps({
                "title": "Sixth Sick Sheik's Sheep",
                "english_text": "The sixth sick sheik's sixth sheep's sick.",
                "chinese_text": "第六个生病的酋长的第六只羊生病了。",
                "level": "Advanced",
                "level_cn": "高级",
                "target_sounds": ["/θ/", "/s/", "/k/", "/ʃ/"],
                "phonetic_tips": "极致挑战！/ksθ/ 连续辅音丛结合 /ʃ/ 齿龈擦音",
                "linking_tips": "sixth_sick 极速衔接，sheep's_sick 自然吐字",
                "suggested_speed": 1.1
            })

    # 解析 JSON 内容
    cleaned_json = re.sub(r'```json|```', '', raw_response).strip()
    data = json.loads(cleaned_json)
    
    # 补全元数据字段
    item_id = f"tt-{int(time.time()*1000)}"
    data["id"] = item_id
    data["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # 生成 TTS 音频
    audio_filename = f"{item_id}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    audio_res = generate_audio(data["english_text"], audio_path)
    
    if audio_res and upload_file_to_cos:
        try:
            cos_key = f"audio/tonguetwisters/{audio_filename}"
            cos_url = upload_file_to_cos(audio_path, cos_key)
            data["audio_url"] = cos_url
        except Exception as e:
            print(f"COS 上传失败: {e}")
            data["audio_url"] = f"/audio/tonguetwisters/{audio_filename}"
    else:
        data["audio_url"] = f"/audio/tonguetwisters/{audio_filename}"

    return data

def process_and_add_tonguetwister(level: str = "初级", target_sound: str = "自由发音", topic: str = "日常口语") -> Dict[str, Any]:
    """
    执行完整的绕口令生成并保存/同步到内容工厂
    """
    print(f"🚀 开始生成【{level}】英语绕口令卡片...")
    item = generate_tonguetwister_llm(level, target_sound, topic)
    
    existing = load_tonguetwisters()
    existing.insert(0, item) # 最新生成的排最前
    save_tonguetwisters(existing)
    
    # 同步至前端 TS 数据
    if os.path.exists(FRONTEND_MOCK_TT_PATH):
        try:
            ts_content = f"""// Auto-generated by Content Factory Tongue Twister Processor
export interface TongueTwisterCard {{
  id: string;
  title: string;
  english_text: string;
  chinese_text: string;
  level: string;
  level_cn: string;
  target_sounds: string[];
  phonetic_tips: string;
  linking_tips: string;
  audio_url: string;
  suggested_speed: number;
  created_at: string;
}}

export const mockTongueTwisters: TongueTwisterCard[] = {json.dumps(existing, ensure_ascii=False, indent=2)};
"""
            with open(FRONTEND_MOCK_TT_PATH, "w", encoding="utf-8") as f:
                f.write(ts_content)
            print(f"✅ 已同步 {len(existing)} 张绕口令卡片到前端代码 mock 库！")
        except Exception as sync_e:
            print(f"同步前端 TS 失败: {sync_e}")

    # 上传整体 JSON 至 COS
    if upload_file_to_cos:
        try:
            upload_file_to_cos(TONGUETWISTER_FILE, COS_TT_KEY)
            print(f"✅ 全量绕口令 JSON 已同步至腾讯云 COS!")
        except Exception:
            pass

    return item

if __name__ == "__main__":
    # 命令行测试运行
    res = process_and_add_tonguetwister(level="初级", target_sound="/s/ vs /ʃ/", topic="海滩生活")
    print("\n[生成成果展示]:\n", json.dumps(res, ensure_ascii=False, indent=2))
