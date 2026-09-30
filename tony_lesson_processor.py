import os
import re
import json
import time
import glob
import urllib.request
from typing import List, Dict, Any
import yt_dlp
from cos_service import upload_file_to_cos

LESSONS_FILE = os.path.join(os.path.dirname(__file__), "data", "tony_shadowing_lessons.json")

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

def ensure_lessons_file():
    os.makedirs(os.path.dirname(LESSONS_FILE), exist_ok=True)
    if not os.path.exists(LESSONS_FILE):
        with open(LESSONS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

def load_lessons() -> List[Dict[str, Any]]:
    ensure_lessons_file()
    try:
        with open(LESSONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_lessons(lessons: List[Dict[str, Any]]):
    ensure_lessons_file()
    with open(LESSONS_FILE, "w", encoding="utf-8") as f:
        json.dump(lessons, f, ensure_ascii=False, indent=2)

def process_subtitles_with_ai(subtitles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Dual-AI Pipeline:
    1. Proofread English subtitles for spoken accuracy (Gemini / DeepSeek)
    2. Translate English subtitles into natural spoken Chinese (DeepSeek)
    """
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if not deepseek_key or not subtitles:
        return subtitles

    sentences = [f"{i+1}. {s['en']}" for i, s in enumerate(subtitles)]
    prompt = (
        "You are an expert English linguist and translator for spoken English learning videos.\n"
        "Your job is two-fold:\n"
        "1. Proofread the English subtitle lines for accuracy, fixing typos or misheard words while keeping spoken phrasing natural.\n"
        "2. Translate each proofread line into accurate, natural, conversational Chinese.\n\n"
        "Return a JSON object with a single key 'items' containing an array of objects in order:\n"
        "{\"items\": [{\"en\": \"Proofread English 1\", \"cn\": \"中文翻译1\"}, {\"en\": \"Proofread English 2\", \"cn\": \"中文翻译2\"}]}\n\n"
        + "\n".join(sentences)
    )

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {deepseek_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional English editor and translator for language learners. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            items = parsed.get("items", [])
            if isinstance(items, list) and len(items) == len(subtitles):
                for i, item in enumerate(items):
                    if isinstance(item, dict):
                        subtitles[i]["en"] = item.get("en", subtitles[i]["en"])
                        subtitles[i]["cn"] = item.get("cn", "")
                print(f"AI successfully proofread & translated {len(subtitles)} subtitle lines!")
    except Exception as e:
        print(f"AI processing exception: {e}")
        
    return subtitles

def parse_vtt_subtitles(vtt_file: str) -> List[Dict[str, Any]]:
    """Parse WebVTT or SRT subtitle file into timestamped lines"""
    if not os.path.exists(vtt_file):
        return []
    
    subtitles = []
    with open(vtt_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        
    time_pattern = re.compile(r"(\d{2}:)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}:)?(\d{2}):(\d{2})[.,](\d{3})")
    
    current_sub = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.isdigit():
            continue
            
        match = time_pattern.search(line)
        if match:
            def to_sec(h, m, s, ms):
                hrs = int(h[:-1]) if h else 0
                return hrs * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
            
            start_sec = to_sec(match.group(1), match.group(2), match.group(3), match.group(4))
            end_sec = to_sec(match.group(5), match.group(6), match.group(7), match.group(8))
            
            current_sub = {"start": round(start_sec, 2), "end": round(end_sec, 2), "en": "", "cn": ""}
            subtitles.append(current_sub)
        elif current_sub and not line.startswith("<"):
            clean_text = re.sub(r"<[^>]+>", "", line).strip()
            if clean_text:
                if current_sub["en"]:
                    current_sub["en"] += " " + clean_text
                else:
                    current_sub["en"] = clean_text
                    
    filtered = [s for s in subtitles if s["en"]]
    return process_subtitles_with_ai(filtered)

def process_single_tiktok_video(url: str, output_dir: str = "downloads") -> Dict[str, Any]:
    """
    1. Downloads TikTok video + thumbnail + native subtitles
    2. Uploads video & thumbnail to COS under target path: videos/tiktok/{video_id}.mp4
    3. Proofreads English & translates into Chinese via AI
    """
    os.makedirs(output_dir, exist_ok=True)
    
    video_id_match = re.search(r"/video/(\d+)", url)
    video_id = video_id_match.group(1) if video_id_match else f"tt_{int(time.time() * 1000)}"
    
    out_prefix = os.path.join(output_dir, f"tiktok_{video_id}")
    outtmpl = f"{out_prefix}.%(ext)s"
    
    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bestvideo+bestaudio/best",
        "writethumbnail": True,
        "writeinfojson": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en.*", "en"],
        "skip_download": False,
        "quiet": True,
        "no_warnings": True
    }
    
    print(f"🎬 Downloading TikTok video: {url}")
    info = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        
    title = info.get("title") if info else f"TikTok Lesson {video_id}"
    duration = info.get("duration", 0) if info else 0
    
    mp4_files = glob.glob(f"{out_prefix}*.mp4") or glob.glob(f"{out_prefix}*.webm")
    jpg_files = glob.glob(f"{out_prefix}*.jpg") or glob.glob(f"{out_prefix}*.png") or glob.glob(f"{out_prefix}*.webp")
    sub_files = glob.glob(f"{out_prefix}*.vtt") or glob.glob(f"{out_prefix}*.srt")
    
    if not mp4_files:
        raise Exception(f"Failed to locate downloaded video for {url}")
        
    local_mp4 = mp4_files[0]
    local_jpg = jpg_files[0] if jpg_files else None
    local_sub = sub_files[0] if sub_files else None
    
    # Upload to COS under videos/tiktok/
    cos_mp4_key = f"videos/tiktok/{video_id}.mp4"
    cos_mp4_url = upload_file_to_cos(local_mp4, cos_mp4_key)
    
    cos_jpg_url = ""
    if local_jpg:
        ext = os.path.splitext(local_jpg)[1] or ".jpg"
        cos_jpg_key = f"videos/tiktok/{video_id}{ext}"
        cos_jpg_url = upload_file_to_cos(local_jpg, cos_jpg_key)
        
    # Parse Subtitles & Run AI Proofread + Translate
    subtitles = parse_vtt_subtitles(local_sub) if local_sub else []
    
    if not subtitles and duration > 0:
        subtitles = [{"start": 0.0, "end": float(duration), "en": title, "cn": ""}]
        subtitles = process_subtitles_with_ai(subtitles)
        
    lesson = {
        "id": f"tt_lesson_{video_id}",
        "video_id": video_id,
        "title": title,
        "source_url": url,
        "video_cos_url": cos_mp4_url,
        "cover_cos_url": cos_jpg_url,
        "duration": duration,
        "subtitles": subtitles,
        "subtitle_count": len(subtitles),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    return lesson

def process_batch_tiktok_lessons(urls: List[str]) -> List[Dict[str, Any]]:
    processed = []
    lessons = load_lessons()
    
    for url in urls:
        try:
            lesson = process_single_tiktok_video(url)
            idx = next((i for i, item in enumerate(lessons) if item["video_id"] == lesson["video_id"]), None)
            if idx is not None:
                lessons[idx] = lesson
            else:
                lessons.insert(0, lesson)
            processed.append(lesson)
        except Exception as e:
            print(f"Error processing TikTok video {url}: {e}")
            
    save_lessons(lessons)
    return processed
