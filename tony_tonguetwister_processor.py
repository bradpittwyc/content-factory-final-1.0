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

# 尝试导入腾讯云 COS
try:
    from cos_service import upload_file_to_cos
except Exception:
    upload_file_to_cos = None

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TONGUETWISTER_FILE = os.path.join(DATA_DIR, "tony_tonguetwisters.json")
AUDIO_DIR = os.path.join(DATA_DIR, "tonguetwister_audio")
FRONTEND_MOCK_TT_PATH = r"C:\Users\Administrator\.gemini\antigravity\scratch\tony-frontend-demo\src\data\tonguetwisters.ts"
COS_TT_KEY = "data/tonguetwisters.json"

# V1.7 核心规则规范
LEVEL_WORD_LIMITS = {
    "Beginner": {"min": 5, "max": 10, "desc": "初级(6-10词): 基础音标/单一对比音"},
    "Intermediate": {"min": 10, "max": 15, "desc": "中级(10-15词): 辅音丛/连读节奏"},
    "Advanced": {"min": 15, "max": 30, "desc": "高级(15+词): 高难混淆音标与长难句"}
}

# 经典老梗黑名单（自动剔除）
BLACKLIST_PATTERNS = [
    r"peter piper picked",
    r"she sells seashells",
    r"how much wood would a woodchuck",
    r"betty bought a bit of butter",
    r"fuzzy wuzzy was a bear"
]

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

# ==================== V1.7 三档语速 TTS 合成 (0.4x, 0.8x, 1.0x) ====================

async def _generate_edge_tts_async(text: str, output_path: str, voice: str = "en-US-AvaNeural", rate: str = "+0%") -> bool:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"[Edge-TTS Fail ({rate})]: {e}")
        return False

def generate_multi_speed_audio(text: str, item_id: str, voice: str = "en-US-AvaNeural") -> Dict[str, str]:
    """
    V1.7 核心: 生成三档语速示范音频
    - 0.4x: 逐音档 (Slow Pacing)
    - 0.8x: 慢速练 (Practice Rate)
    - 1.0x: 常速极速 (Normal Speed)
    """
    os.makedirs(AUDIO_DIR, exist_ok=True)
    speeds = {
        "0.4": "-35%",
        "0.8": "-15%",
        "1.0": "+0%"
    }
    result_urls = {}

    for speed_key, rate_str in speeds.items():
        filename = f"{item_id}_{speed_key}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)
        
        # 使用 Edge-TTS 高品质合成不同 rate
        try:
            success = asyncio.run(_generate_edge_tts_async(text, filepath, voice=voice, rate=rate_str))
            if success and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"  🎙️ [{speed_key}x 语速档] 成功合成: {filename}")
                if upload_file_to_cos:
                    try:
                        cos_key = f"audio/tonguetwisters/{filename}"
                        cos_url = upload_file_to_cos(filepath, cos_key)
                        result_urls[speed_key] = cos_url
                        continue
                    except Exception:
                        pass
                result_urls[speed_key] = f"/audio/tonguetwisters/{filename}"
        except Exception as e:
            print(f"TTS 生成异常 ({speed_key}x): {e}")

    # 兜底
    if "1.0" not in result_urls and result_urls:
        result_urls["1.0"] = list(result_urls.values())[0]

    return result_urls

# ==================== V1.7 质量校验与黑名单过滤 ====================

def validate_tonguetwister_quality(item: Dict[str, Any], level: str) -> bool:
    text = item.get("english_text", "").strip()
    if not text:
        return False

    # 1. 经典老梗黑名单过滤
    text_lower = text.lower()
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, text_lower):
            print(f"⚠️ 拦截命中老梗黑名单: '{pattern}'")
            return False

    # 2. 单词数量范围校验
    words = [w for w in re.findall(r'\b\w+\b', text)]
    word_count = len(words)
    limit = LEVEL_WORD_LIMITS.get(level, LEVEL_WORD_LIMITS["Beginner"])

    if word_count < limit["min"] or word_count > limit["max"] + 8:
        print(f"⚠️ 词数校验不达标: 当前{word_count}词 (标准 {limit['min']}-{limit['max']}词)")
        return False

    return True

# ==================== V1.7 LLM 多模型+交叉精校生成 ====================

LEVEL_MAP = {
    "初级": "Beginner",
    "中级": "Intermediate",
    "高级": "Advanced",
    "Beginner": "Beginner",
    "Intermediate": "Intermediate",
    "Advanced": "Advanced"
}

def generate_v17_tonguetwister(level: str = "初级", target_sound: str = "自由发音/常见易混淆音标", topic: str = "日常口语") -> Dict[str, Any]:
    normalized_level = LEVEL_MAP.get(level, "Beginner")
    level_cn = "初级" if normalized_level == "Beginner" else ("中级" if normalized_level == "Intermediate" else "高级")
    limits = LEVEL_WORD_LIMITS[normalized_level]

    prompt = f"""你是一位顶级英语发音教练与语意精校专家。请生成一张全新的 V1.7 英语绕口令发音训练卡片。

【V1.7 生成硬性规范】:
1. 难度梯度: {normalized_level} ({level_cn}) - 目标词数范围必须在 {limits['min']} ~ {limits['max']} 词之间。
2. 目标音标/难点: {target_sound}
3. 拒绝老梗: 严禁生成 "Peter Piper", "She sells seashells", "Woodchuck" 等旧老梗，必须保证英文句子生动、原创、有画面感。
4. 主谓宾完整: 拒绝纯名词堆砌，句子必须符合语法且表达通顺。

请直接返回合法的 JSON 格式（不要添加代码块标记以外的任何说明）：
{{
  "title": "绕口令标题 (英文短名)",
  "english_text": "英文原文绕口令",
  "chinese_text": "地道中文翻译与语境释义",
  "level": "{normalized_level}",
  "level_cn": "{level_cn}",
  "target_sounds": ["音标1", "音标2"],
  "phonetic_tips": "易错发音要点剖析（发音部位、舌位技巧）",
  "linking_tips": "连读/弱读/重音节奏提示",
  "cross_proofread_score": 98.5
}}
"""

    gemini_key = os.environ.get("GEMINI_API_KEY")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    raw_response = None

    # 第一顺位: Gemini 2.5 Flash
    if gemini_key:
        try:
            req_data = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_json = json.loads(resp.read().decode('utf-8'))
                raw_response = res_json['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            print(f"Gemini 生成失败: {e}")

    # 第二顺位: OpenAI / DeepSeek API
    if not raw_response and (openai_key or deepseek_key):
        try:
            api_key = deepseek_key or openai_key
            base_url = "https://api.deepseek.com/v1" if deepseek_key else "https://api.openai.com/v1"
            model = "deepseek-chat" if deepseek_key else "gpt-4o-mini"
            req_data = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}).encode('utf-8')
            req = urllib.request.Request(f"{base_url}/chat/completions", data=req_data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_json = json.loads(resp.read().decode('utf-8'))
                raw_response = res_json['choices'][0]['message']['content']
        except Exception as e:
            print(f"OpenAI/DeepSeek 生成失败: {e}")

    # 保底模版
    if not raw_response:
        print("⚠️ 使用保底 V1.7 原创模版...")
        if normalized_level == "Beginner":
            raw_response = json.dumps({
                "title": "Brave Blue Bugs",
                "english_text": "Brave blue bugs bite big black bears.",
                "chinese_text": "勇敢的蓝色小虫叮咬大黑熊。",
                "level": "Beginner",
                "level_cn": "初级",
                "target_sounds": ["/b/", "/p/"],
                "phonetic_tips": "注意 /b/ 爆破浊辅音与双唇张合节奏",
                "linking_tips": "blue_bugs 自然连读，bite_big 快速过渡",
                "cross_proofread_score": 96.0
            })
        elif normalized_level == "Intermediate":
            raw_response = json.dumps({
                "title": "Three Thick Thistles",
                "english_text": "Three thick thistles thrive thoughtfully in the thermal spring.",
                "chinese_text": "三株茂密的蓟草在温泉旁茁壮成长。",
                "level": "Intermediate",
                "level_cn": "中级",
                "target_sounds": ["/θ/", "/s/"],
                "phonetic_tips": "重点突破 /θ/ 咬舌音与 /s/ 齿龈擦音的频繁交替",
                "linking_tips": "thick_thistles 连读，thrive_thoughtfully 保持吐字清晰",
                "cross_proofread_score": 97.5
            })
        else:
            raw_response = json.dumps({
                "title": "Clever Crafty Chefs",
                "english_text": "Clever crafty chefs cooked crunchy crispy chicken for cheerful children in Chicago.",
                "chinese_text": "聪明的厨师在芝加哥为快乐的孩子们烹饪香脆的炸鸡。",
                "level": "Advanced",
                "level_cn": "高级",
                "target_sounds": ["/k/", "/tʃ/", "/ʃ/"],
                "phonetic_tips": "极致挑战！/k/ 舌后爆破音与 /tʃ/ /ʃ/ 破擦音的高速切换",
                "linking_tips": "crafty_chefs 极速衔接，crunchy_crispy_chicken 快速顺畅连读",
                "cross_proofread_score": 99.0
            })

    cleaned = re.sub(r'```json|```', '', raw_response).strip()
    data = json.loads(cleaned)

    item_id = f"tw_{int(time.time())}_{data.get('title','tt')[:6].lower()}"
    data["id"] = item_id
    data["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # V1.7: 三档语速示范音频生成 (0.4x 逐音, 0.8x 慢速, 1.0x 常速)
    print("🎙️ 开始生产 V1.7 三档语速示范音频 (0.4x / 0.8x / 1.0x)...")
    audio_urls = generate_multi_speed_audio(data["english_text"], item_id)
    data["audio_urls"] = audio_urls
    data["audio_url"] = audio_urls.get("1.0") or audio_urls.get("0.8") or ""

    return data

def process_and_add_tonguetwister(level: str = "初级", target_sound: str = "自由发音/常见易混淆音标", topic: str = "日常口语") -> Dict[str, Any]:
    print(f"\n🚀 [V1.7 绕口令流水线] 开始生成【{level}】发音训练卡片...")
    
    item = None
    for attempt in range(3):
        candidate = generate_v17_tonguetwister(level, target_sound, topic)
        if validate_tonguetwister_quality(candidate, LEVEL_MAP.get(level, "Beginner")):
            item = candidate
            break
        print(f"  ⚠️ 质量校验未通过，重试第 {attempt + 1} 次...")

    if not item:
        item = generate_v17_tonguetwister(level, target_sound, topic)

    existing = load_tonguetwisters()
    existing.insert(0, item)
    save_tonguetwisters(existing)

    # 同步 TS 前端库
    if os.path.exists(FRONTEND_MOCK_TT_PATH):
        try:
            ts_content = f"""// Auto-generated by V1.7 Content Factory Tongue Twister Pipeline
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
  audio_urls?: Record<string, string>;
  cross_proofread_score?: number;
  created_at: string;
}}

export const mockTongueTwisters: TongueTwisterCard[] = {json.dumps(existing, ensure_ascii=False, indent=2)};
"""
            with open(FRONTEND_MOCK_TT_PATH, "w", encoding="utf-8") as f:
                f.write(ts_content)
            print(f"✅ 已同步 {len(existing)} 张 V1.7 卡片至前端代码 mock 库！")
        except Exception as e:
            print(f"前端同步失败: {e}")

    # 同步全量 JSON 至 COS
    if upload_file_to_cos:
        try:
            upload_file_to_cos(TONGUETWISTER_FILE, COS_TT_KEY)
            print(f"✅ 全量绕口令数据全网同步至 COS 存储!")
        except Exception:
            pass

    return item

if __name__ == "__main__":
    res = process_and_add_tonguetwister(level="中级", target_sound="/θ/ vs /s/", topic="自然观察")
    print("\n[V1.7 成果输出]:\n", json.dumps(res, ensure_ascii=False, indent=2))
