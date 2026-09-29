# -*- coding: utf-8 -*-
"""
YouTube Downloader 增强引擎：
1. 关键词自动频道内容归类 (科技&AI / 个人成长 / 健康科学 / 商业财经 / 人文历史 / 娱乐生活)
2. 本地 FFmpeg 极速抽轨导出同名 MP3 (免二次下载)
3. 中英双语字幕 (.zh-en.srt / .zh-en.ass)
4. 中英对照 Word 学习文档生成 (.学习文档.docx)
5. OpenAI / DeepSeek 兼容翻译接口对接
"""

import os
import re
import json
import subprocess
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

CATEGORIES = [
    {
        "id": "tech",
        "name": "科技 & AI",
        "icon": "🤖",
        "color": "#06b6d4",
        "keywords": [
            "ai", "a.i.", "artificial intelligence", "gpt", "chatgpt", "llm", "model", "neural",
            "machine learning", "deep learning", "agent", "agentic", "api", "code", "coding",
            "programming", "developer", "software", "engineer", "python", "javascript", "rust",
            "linux", "open source", "robot", "robotics", "automation", "computer", "chip", "gpu",
            "nvidia", "apple", "google", "microsoft", "openai", "tech", "technology", "quantum",
            "metaverse", "crypto", "blockchain", "gadget", "unboxing", "review"
        ]
    },
    {
        "id": "growth",
        "name": "个人成长",
        "icon": "🌱",
        "color": "#10b981",
        "keywords": [
            "motivat", "habit", "mindset", "discipline", "confidence", "self", "goal", "productiv",
            "procrastinat", "focus", "routine", "morning", "journal", "gratitude", "anxiety",
            "stress", "burnout", "therapy", "healing", "relationship", "love", "success", "fail",
            "change your life", "transform", "improve", "growth", "stoic", "philosophy", "advice"
        ]
    },
    {
        "id": "health",
        "name": "健康 & 科学",
        "icon": "🧬",
        "color": "#3b82f6",
        "keywords": [
            "health", "doctor", "medical", "medicine", "sleep", "diet", "nutrition", "exercise",
            "workout", "fitness", "muscle", "weight", "metabolis", "hormone", "brain", "neuro",
            "dopamine", "longevity", "aging", "science", "scientist", "physics", "chemistry",
            "biology", "space", "nasa", "nature", "huberman", "fasting"
        ]
    },
    {
        "id": "business",
        "name": "商业 & 财经",
        "icon": "📈",
        "color": "#f59e0b",
        "keywords": [
            "business", "money", "finance", "financial", "invest", "stock", "market", "economy",
            "entrepreneur", "founder", "ceo", "company", "revenue", "profit", "sales", "marketing",
            "brand", "ecommerce", "real estate", "tax", "wealth", "rich", "millionaire", "career",
            "startup", "strategy", "bitcoin", "trading", "passive income"
        ]
    },
    {
        "id": "knowledge",
        "name": "人文 & 历史",
        "icon": "📚",
        "color": "#8b5cf6",
        "keywords": [
            "history", "historical", "war", "empire", "civilization", "politics", "president",
            "government", "law", "philosophy", "culture", "literature", "book", "author", "writing",
            "language", "education", "lecture", "documentary", "explained", "story of", "interview", "podcast"
        ]
    },
    {
        "id": "life",
        "name": "娱乐 & 生活",
        "icon": "🍿",
        "color": "#ec4899",
        "keywords": [
            "funny", "comedy", "prank", "challenge", "reaction", "vlog", "game", "gaming", "minecraft",
            "music", "song", "food", "cooking", "travel", "movie", "entertainment", "mrbeast", "lego"
        ]
    }
]

def classify_channel_by_titles(titles: List[str]) -> Dict[str, Any]:
    """根据视频标题集合对频道进行领域自动归类"""
    if not titles:
        return {"id": "tech", "name": "科技 & AI", "icon": "🤖", "color": "#06b6d4"}
    
    scores = {c["id"]: 0 for c in CATEGORIES}
    combined_text = " ".join(titles).lower()
    
    for cat in CATEGORIES:
        for kw in cat["keywords"]:
            if kw in combined_text:
                scores[cat["id"]] += combined_text.count(kw)
    
    best_id = max(scores, key=scores.get)
    if scores[best_id] == 0:
        return {"id": "knowledge", "name": "综合频道", "icon": "✨", "color": "#06b6d4"}
    
    for cat in CATEGORIES:
        if cat["id"] == best_id:
            return cat
    return CATEGORIES[0]

def extract_mp3_from_video(video_path: str, mp3_path: str) -> bool:
    """利用本地 FFmpeg 极速将 mp4 音频轨直接抽轨另存为同名 MP3 (免二次下载)"""
    if not os.path.exists(video_path):
        return False
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "2",
            mp3_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        return res.returncode == 0 and os.path.exists(mp3_path)
    except Exception as e:
        print(f"FFmpeg extract mp3 error: {e}")
        return False

# ==============================================================================
# ASS 双语字幕样式生成器 (黄色/青色英文 + 纯白中文，带黑边与微距阴影)
# ==============================================================================
def create_ass_bilingual_subtitle(cues: List[Dict[str, str]], ass_path: str, title: str = "YouTube Video"):
    """
    生成标准高级双语 ASS 特效字幕：
    - 中文：纯白加粗，底部居中，字号适当
    - 英文：浅黄色/青色，紧贴中文上方或下方，字号略小
    - 完美适配 PotPlayer, VLC, mpv
    """
    header = f"""[Script Info]
Title: {title} - Bilingual Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ZhMain,Microsoft YaHei,52,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3.0,1.5,2,40,40,45,1
Style: EnSub,Arial,34,&H0050E6FF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2.2,1.2,2,40,40,15,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for c in cues:
        start = c.get("start", "00:00:00.00")
        end = c.get("end", "00:00:05.00")
        en = c.get("en", "").replace("\n", " ").strip()
        zh = c.get("zh", "").replace("\n", " ").strip()
        
        # 转换为 ASS 时间戳格式 H:MM:SS.cc
        def to_ass_time(t_str):
            t_str = t_str.replace(",", ".")
            m = re.match(r"(\d+):(\d+):(\d+\.?\d*)", t_str)
            if m:
                h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return f"{h}:{mi:02d}:{s:05.2f}"
            return "0:00:00.00"
            
        ass_start = to_ass_time(start)
        ass_end = to_ass_time(end)
        
        # 中文行在上，英文在下（或者合成双行）
        text = f"{zh}\\N{{\\rEnSub}}{en}"
        events.append(f"Dialogue: 0,{ass_start},{ass_end},ZhMain,,0,0,0,,{text}")
        
    try:
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(events) + "\n")
        return True
    except Exception as e:
        print(f"Failed to write ASS file: {e}")
        return False

def create_srt_bilingual_subtitle(cues: List[Dict[str, str]], srt_path: str):
    """生成双语 SRT 字幕"""
    lines = []
    for idx, c in enumerate(cues, 1):
        start = c.get("start", "00:00:00,000").replace(".", ",")
        end = c.get("end", "00:00:05,000").replace(".", ",")
        en = c.get("en", "").strip()
        zh = c.get("zh", "").strip()
        
        lines.append(f"{idx}\n{start} --> {end}\n{zh}\n{en}\n")
    try:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return True
    except Exception as e:
        print(f"Failed to write SRT file: {e}")
        return False

# ==============================================================================
# 中英对照 Word 学习文档 (.docx) 高保真生成器
# ==============================================================================
def set_cell_background(cell, fill_hex):
    """给表格单元格设置背景颜色"""
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def generate_study_document(
    video_title: str,
    channel_name: str,
    video_url: str,
    duration: str,
    cues: List[Dict[str, str]],
    docx_path: str,
    vocab_list: Optional[List[Dict[str, str]]] = None,
    api_model: str = "DeepSeek AI"
) -> bool:
    """
    生成高规格「中英对照精读学习文档」Word (.docx)
    包含：
    1. 标题与头部元数据 (博主, 时长, 链接, 模型)
    2. 逐段对照精读区 (带时间码、英文原句、地道中文、核心语法与难句点拨)
    3. 附录一：纯英文复读跟读区 (无中文干扰，便于口语复述与听力磨耳朵)
    4. 附录二：核心高频词汇总表 (带音标、词性、中文释义与出现语境)
    """
    doc = docx.Document()

    # 页面边距设置为精巧型 1.8cm
    for section in doc.sections:
        section.top_margin = Inches(0.7)
        section.bottom_margin = Inches(0.7)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # 1. 主标题
    title_p = doc.add_paragraph()
    title_run = title_p.add_run(video_title)
    title_run.font.name = "Microsoft YaHei"
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(17, 24, 39)
    title_p.paragraph_format.space_after = Pt(4)

    # 副标题/导言
    sub_p = doc.add_paragraph()
    sub_run = sub_p.add_run("YouTube 视频原生字幕逐段中英精读对照与生词剖析 • 伴随学习手册")
    sub_run.font.name = "Microsoft YaHei"
    sub_run.font.size = Pt(10.5)
    sub_run.font.color.rgb = RGBColor(107, 114, 128)
    sub_p.paragraph_format.space_after = Pt(12)

    # 元信息卡片表格
    meta_table = doc.add_table(rows=2, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_data = [
        [("博主频道", channel_name), ("视频时长", duration), ("识别分类", "YouTube 精品内容"), ("处理引擎", api_model)],
        [("视频链接", video_url), ("文档用途", "听力复读/精读对照"), ("字幕模式", "中英双轨原生对齐"), ("导出格式", "Word 专业排版")]
    ]
    for r_idx, row in enumerate(meta_data):
        for c_idx, (label, val) in enumerate(row):
            cell = meta_table.cell(r_idx, c_idx)
            set_cell_background(cell, "F3F4F6")
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_after = Pt(2)
            cp.paragraph_format.space_before = Pt(2)
            lr = cp.add_run(f"{label}: ")
            lr.font.name = "Microsoft YaHei"
            lr.font.size = Pt(9)
            lr.font.bold = True
            lr.font.color.rgb = RGBColor(75, 85, 99)
            vr = cp.add_run(val)
            vr.font.name = "Microsoft YaHei"
            vr.font.size = Pt(9)
            vr.font.color.rgb = RGBColor(17, 24, 39)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # 2. 正文：逐段精读
    h1 = doc.add_paragraph()
    h1_run = h1.add_run("📖 一、 逐段中英双语精读对照")
    h1_run.font.name = "Microsoft YaHei"
    h1_run.font.size = Pt(14)
    h1_run.font.bold = True
    h1_run.font.color.rgb = RGBColor(30, 58, 138) # Deep Blue
    h1.paragraph_format.space_before = Pt(12)
    h1.paragraph_format.space_after = Pt(6)

    # 遍历字幕分段
    for idx, cue in enumerate(cues, 1):
        timecode = cue.get("start", "00:00:00")
        en_text = cue.get("en", "")
        zh_text = cue.get("zh", "")
        note = cue.get("note", "")

        # 段落容器
        sec_p = doc.add_paragraph()
        sec_p.paragraph_format.space_before = Pt(6)
        sec_p.paragraph_format.space_after = Pt(2)

        # 时间码徽章
        tc_run = sec_p.add_run(f"[{timecode}] ")
        tc_run.font.name = "Consolas"
        tc_run.font.size = Pt(9.5)
        tc_run.font.bold = True
        tc_run.font.color.rgb = RGBColor(220, 38, 38) # Red accent

        # 序号
        num_run = sec_p.add_run(f"第 {idx} 节\n")
        num_run.font.name = "Microsoft YaHei"
        num_run.font.size = Pt(9.5)
        num_run.font.color.rgb = RGBColor(107, 114, 128)

        # 英文段落
        en_p = doc.add_paragraph()
        en_run = en_p.add_run(en_text)
        en_run.font.name = "Calibri"
        en_run.font.size = Pt(11)
        en_run.font.bold = True
        en_run.font.color.rgb = RGBColor(31, 41, 55)
        en_p.paragraph_format.space_after = Pt(2)
        en_p.paragraph_format.left_indent = Inches(0.15)

        # 中文翻译段落
        zh_p = doc.add_paragraph()
        zh_run = zh_p.add_run(zh_text)
        zh_run.font.name = "Microsoft YaHei"
        zh_run.font.size = Pt(10.5)
        zh_run.font.color.rgb = RGBColor(75, 85, 99)
        zh_p.paragraph_format.space_after = Pt(4)
        zh_p.paragraph_format.left_indent = Inches(0.15)

        # 若有语法/解析点拨，加入提示框样式
        if note:
            note_p = doc.add_paragraph()
            note_run = note_p.add_run(f"💡 点拨：{note}")
            note_run.font.name = "Microsoft YaHei"
            note_run.font.size = Pt(9)
            note_run.font.italic = True
            note_run.font.color.rgb = RGBColor(5, 150, 105) # Green
            note_p.paragraph_format.left_indent = Inches(0.2)
            note_p.paragraph_format.space_after = Pt(6)

    # 3. 附录一：纯英文复读区
    doc.add_page_break()
    h2 = doc.add_paragraph()
    h2_run = h2.add_run("🎧 附录一 · 纯英文无干扰复读跟读区")
    h2_run.font.name = "Microsoft YaHei"
    h2_run.font.size = Pt(14)
    h2_run.font.bold = True
    h2_run.font.color.rgb = RGBColor(30, 58, 138)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(6)

    pure_intro = doc.add_paragraph()
    pure_intro_run = pure_intro.add_run("提示：本部分剔除了所有中文干扰，排版紧凑，专为结合原声视频/MP3进行影子跟读（Shadowing）与听写自测使用。")
    pure_intro_run.font.name = "Microsoft YaHei"
    pure_intro_run.font.size = Pt(9.5)
    pure_intro_run.font.color.rgb = RGBColor(107, 114, 128)
    pure_intro.paragraph_format.space_after = Pt(10)

    for cue in cues:
        p_en = doc.add_paragraph()
        tc = p_en.add_run(f"[{cue.get('start', '00:00')}] ")
        tc.font.name = "Consolas"
        tc.font.size = Pt(9)
        tc.font.color.rgb = RGBColor(156, 163, 175)
        
        t = p_en.add_run(cue.get("en", ""))
        t.font.name = "Calibri"
        t.font.size = Pt(10.5)
        t.font.color.rgb = RGBColor(31, 41, 55)
        p_en.paragraph_format.space_after = Pt(3)

    # 4. 附录二：词汇总表
    if vocab_list:
        doc.add_page_break()
        h3 = doc.add_paragraph()
        h3_run = h3.add_run("📝 附录二 · 重点词汇与专业表达总表")
        h3_run.font.name = "Microsoft YaHei"
        h3_run.font.size = Pt(14)
        h3_run.font.bold = True
        h3_run.font.color.rgb = RGBColor(30, 58, 138)
        h3.paragraph_format.space_before = Pt(12)
        h3.paragraph_format.space_after = Pt(8)

        v_table = doc.add_table(rows=1, cols=4)
        v_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        headers = ["单词 / 短语", "音标与词性", "中文释义", "视频原句 / 语境例句"]
        hdr_cells = v_table.rows[0].cells
        for i, head in enumerate(headers):
            hdr_cells[i].text = head
            set_cell_background(hdr_cells[i], "E5E7EB")
            p = hdr_cells[i].paragraphs[0]
            p.runs[0].font.name = "Microsoft YaHei"
            p.runs[0].font.size = Pt(9.5)
            p.runs[0].font.bold = True
            p.runs[0].font.color.rgb = RGBColor(17, 24, 39)

        for v in vocab_list:
            row_cells = v_table.add_row().cells
            vals = [v.get("word", ""), v.get("pos", ""), v.get("mean", ""), v.get("example", "")]
            for j, val in enumerate(vals):
                row_cells[j].text = val
                p = row_cells[j].paragraphs[0]
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                if p.runs:
                    p.runs[0].font.name = "Microsoft YaHei" if j != 0 else "Calibri"
                    p.runs[0].font.size = Pt(9)
                    if j == 0:
                        p.runs[0].font.bold = True

    try:
        doc.save(docx_path)
        return True
    except Exception as e:
        print(f"Failed to save docx: {e}")
        return False
