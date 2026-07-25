from __future__ import annotations

import re
from typing import Any


SUBTITLE_PRESETS = {
    "compact": {"caption_font_size": 44, "center_font_size": 50, "headline_font_size": 54},
    "standard": {"caption_font_size": 52, "center_font_size": 58, "headline_font_size": 60},
    "large": {"caption_font_size": 62, "center_font_size": 68, "headline_font_size": 72},
}


def _ass_header(*, preset: str, safe_bottom_px: int) -> str:
    sizes = SUBTITLE_PRESETS[preset]
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Noto Sans CJK SC,{sizes['caption_font_size']},&H00FFFFFF,&H00FFFFFF,&H00202020,&H90000000,0,0,0,0,100,100,0,0,1,3,0,2,72,72,{safe_bottom_px},1
Style: CaptionCenter,Noto Sans CJK SC,{sizes['center_font_size']},&H00FFFFFF,&H00FFFFFF,&H00202020,&H90000000,-1,0,0,0,100,100,0,0,1,3,0,5,96,96,0,1
Style: Headline,Noto Sans CJK SC,{sizes['headline_font_size']},&H00FFFFFF,&H00FFFFFF,&H00181030,&HC0181030,-1,0,0,0,100,100,0,0,3,2,0,8,90,90,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


ASS_HEADER = _ass_header(preset="standard", safe_bottom_px=160)


def build_ass_subtitles(
    shot_list: dict[str, Any],
    voice_manifest: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    subtitle_style = _subtitle_style(shot_list.get("subtitle_style"))
    events: list[dict[str, Any]] = []
    lines: list[str] = [
        _ass_header(
            preset=subtitle_style["preset"],
            safe_bottom_px=subtitle_style["safe_bottom_px"],
        ).rstrip("\n")
    ]
    incomplete_shot_indices: list[int] = []
    voice_by_shot = {
        int(segment["shot_index"]): segment
        for segment in (voice_manifest or {}).get("segments") or []
    }
    for shot in shot_list.get("shots") or []:
        shot_index = int(shot["shot_index"])
        shot_start = float(shot["start_seconds"])
        shot_end = float(shot["end_seconds"])
        narration = str(shot.get("subtitle_text") or shot.get("narration") or "")
        captions = _caption_chunks(narration, maximum=30)
        if _normalized_text("".join(captions)) != _normalized_text(narration):
            incomplete_shot_indices.append(shot_index)
        voice_segment = voice_by_shot.get(shot_index) or {}
        speech_duration = float(
            voice_segment.get("speech_duration_seconds")
            or voice_segment.get("target_duration_seconds")
            or (shot_end - shot_start)
        )
        caption_end = min(shot_end, shot_start + max(0.1, speech_duration))
        caption_position = str(shot.get("caption_position") or "bottom")
        if caption_position not in {"bottom", "center"}:
            raise ValueError("subtitle caption position is unsupported")
        caption_style = "CaptionCenter" if caption_position == "center" else "Caption"
        weights = [_text_weight(text) for text in captions]
        total_weight = sum(weights) or 1.0
        cursor = shot_start
        for index, (caption, weight) in enumerate(zip(captions, weights, strict=True)):
            end = (
                caption_end
                if index == len(captions) - 1
                else cursor + (caption_end - shot_start) * weight / total_weight
            )
            wrapped = _wrap_lines(caption, max_characters=19, max_lines=2)
            event = {
                "kind": "caption",
                "shot_index": shot_index,
                "start_seconds": round(cursor, 3),
                "end_seconds": round(end, 3),
                "text": wrapped.replace("\\N", "\n"),
                "source_text": caption,
                "caption_position": caption_position,
            }
            events.append(event)
            lines.append(_dialogue_line(cursor, end, caption_style, wrapped))
            cursor = end

        headline = str(shot.get("screen_text") or "").strip()
        if headline:
            headline_end = min(shot_end, shot_start + 3.5)
            wrapped_headline = _wrap_lines(headline, max_characters=16, max_lines=2)
            events.append(
                {
                    "kind": "headline",
                    "shot_index": shot_index,
                    "start_seconds": round(shot_start, 3),
                    "end_seconds": round(headline_end, 3),
                    "text": wrapped_headline.replace("\\N", "\n"),
                }
            )
            lines.append(_dialogue_line(shot_start, headline_end, "Headline", wrapped_headline, layer=1))
    return "\n".join(lines) + "\n", {
        "source": "deterministic_ass_v1",
        "event_count": len(events),
        "caption_event_count": sum(event["kind"] == "caption" for event in events),
        "headline_event_count": sum(event["kind"] == "headline" for event in events),
        "text_complete": not incomplete_shot_indices,
        "truncated_event_count": sum("…" in event["text"] for event in events),
        "incomplete_shot_indices": incomplete_shot_indices,
        "font": "Noto Sans CJK SC",
        "play_resolution": {"width": 1080, "height": 1920},
        "subtitle_style": subtitle_style,
        "safe_margins": {"left": 72, "right": 72, "bottom": subtitle_style["safe_bottom_px"], "headline_top": 220},
        "caption_position_counts": {
            "bottom": sum(event.get("caption_position") == "bottom" for event in events),
            "center": sum(event.get("caption_position") == "center" for event in events),
        },
        "events": events,
    }


def _subtitle_style(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"preset": "standard", "safe_bottom_px": 160}
    preset = str(value.get("preset") or "standard")
    safe_bottom_px = value.get("safe_bottom_px", 160)
    if (
        preset not in SUBTITLE_PRESETS
        or not isinstance(safe_bottom_px, int)
        or isinstance(safe_bottom_px, bool)
        or not 80 <= safe_bottom_px <= 360
    ):
        raise ValueError("subtitle style is unsupported")
    return {"preset": preset, "safe_bottom_px": safe_bottom_px}


def _caption_chunks(text: str, *, maximum: int) -> list[str]:
    sentences = [part.strip() for part in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", text) if part.strip()]
    chunks: list[str] = []
    for sentence in sentences or [text]:
        clauses = [part for part in re.findall(r"[^，、：]+[，、：]?", sentence) if part]
        current = ""
        for clause in clauses or [sentence]:
            if current and len(current) + len(clause) > maximum:
                chunks.append(current.strip())
                current = ""
            remaining = clause
            while len(remaining) > maximum:
                split_at = _preferred_split(remaining, maximum)
                prefix = remaining[:split_at]
                if current:
                    chunks.append((current + prefix).strip())
                    current = ""
                else:
                    chunks.append(prefix.strip())
                remaining = remaining[split_at:]
            current += remaining
        if current:
            chunks.append(current.strip())
    return chunks or [""]


def _preferred_split(text: str, maximum: int) -> int:
    window = text[:maximum]
    positions = [window.rfind(mark) + 1 for mark in "，、：" if window.rfind(mark) >= maximum // 2]
    return max(positions) if positions else maximum


def _wrap_lines(text: str, *, max_characters: int, max_lines: int) -> str:
    clean = _escape_ass(text.replace("\n", " ").strip())
    if len(clean) <= max_characters:
        return clean
    if len(clean) > max_characters * max_lines:
        raise ValueError("subtitle text exceeds the configured line capacity")
    lower = max(1, len(clean) - max_characters)
    upper = min(max_characters, len(clean) - 1)
    target = len(clean) / 2
    candidates = [
        index
        for index in range(lower, upper + 1)
        if clean[index - 1] in "，、：；。！？!?· "
    ]
    split_at = min(candidates or range(lower, upper + 1), key=lambda index: abs(index - target))
    first = clean[:split_at].rstrip()
    second = clean[split_at:].lstrip()
    lines = [first, second]
    return "\\N".join(lines)


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _escape_ass(text: str) -> str:
    return text.replace("\\", "／").replace("{", "（").replace("}", "）")


def _text_weight(text: str) -> float:
    chinese = len(re.findall(r"[\u3400-\u9fff]", text))
    ascii_characters = len(re.findall(r"[A-Za-z0-9]", text))
    return max(1.0, chinese + ascii_characters * 0.5)


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _dialogue_line(start: float, end: float, style: str, text: str, *, layer: int = 0) -> str:
    return f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},{style},,0,0,0,,{text}"
