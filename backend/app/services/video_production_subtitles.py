from __future__ import annotations

import re
from typing import Any


SUBTITLE_PRESETS = {
    "compact": {"caption_font_size": 44, "center_font_size": 50, "headline_font_size": 54},
    "standard": {"caption_font_size": 52, "center_font_size": 58, "headline_font_size": 60},
    "large": {"caption_font_size": 62, "center_font_size": 68, "headline_font_size": 72},
}


def evaluate_subtitle_quality(
    shot_list: dict[str, Any],
    subtitle_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Validate deterministic subtitle evidence before release-quality evaluation.

    This is intentionally a manifest-level check.  It proves that the frozen ASS
    event plan is structurally readable and traces every required ScriptBlock; it
    does not claim pixel-level OCR or audio forced-alignment verification.
    """

    events = [event for event in subtitle_manifest.get("events") or [] if isinstance(event, dict)]
    shots_by_index = {
        _as_int(shot.get("shot_index")): shot
        for shot in shot_list.get("shots") or []
        if isinstance(shot, dict) and _as_int(shot.get("shot_index")) is not None
    }
    issues: list[dict[str, Any]] = []

    def issue(code: str, **details: Any) -> None:
        issues.append({"code": code, **details})

    safe_margins = subtitle_manifest.get("safe_margins")
    resolution = subtitle_manifest.get("play_resolution")
    safe_area = (
        isinstance(safe_margins, dict)
        and isinstance(resolution, dict)
        and _as_int(resolution.get("width")) == 1080
        and _as_int(resolution.get("height")) == 1920
        and (_as_int(safe_margins.get("left")) or 0) >= 72
        and (_as_int(safe_margins.get("right")) or 0) >= 72
        and 80 <= (_as_int(safe_margins.get("bottom")) or 0) <= 360
        and 120 <= (_as_int(safe_margins.get("headline_top")) or 0) <= 360
    )
    if not safe_area:
        issue("subtitle_safe_area_invalid")

    manifest_consistent = (
        _as_int(subtitle_manifest.get("event_count")) == len(events)
        and _as_int(subtitle_manifest.get("caption_event_count"))
        == sum(event.get("kind") == "caption" for event in events)
    )
    if not manifest_consistent:
        issue("subtitle_manifest_event_count_mismatch")

    event_ranges_valid = True
    line_layout_valid = True
    readable_durations_valid = True
    covered_blocks: set[str] = set()
    for event_index, event in enumerate(events):
        kind = str(event.get("kind") or "")
        shot_index = _as_int(event.get("shot_index"))
        start = _as_float(event.get("start_seconds"))
        end = _as_float(event.get("end_seconds"))
        shot = shots_by_index.get(shot_index)
        if (
            kind not in {"caption", "headline"}
            or shot is None
            or start is None
            or end is None
            or end <= start
        ):
            event_ranges_valid = False
            issue("subtitle_event_timing_invalid", event_index=event_index, shot_index=shot_index)
            continue
        shot_start = _as_float(shot.get("start_seconds"))
        shot_end = _as_float(shot.get("end_seconds"))
        if (
            shot_start is None
            or shot_end is None
            or start < shot_start - 0.001
            or end > shot_end + 0.001
        ):
            event_ranges_valid = False
            issue("subtitle_event_outside_shot", event_index=event_index, shot_index=shot_index)

        lines = str(event.get("text") or "").splitlines()
        maximum = 19 if kind == "caption" else 16
        if not lines or len(lines) > 2 or any(len(line) > maximum for line in lines):
            line_layout_valid = False
            issue("subtitle_line_layout_invalid", event_index=event_index, shot_index=shot_index)

        if kind != "caption":
            continue
        source_text = str(event.get("source_text") or "").strip()
        if not source_text or end - start + 0.001 < _minimum_readable_seconds(source_text):
            readable_durations_valid = False
            issue(
                "subtitle_caption_too_short",
                event_index=event_index,
                shot_index=shot_index,
                duration_seconds=round(end - start, 3),
                minimum_seconds=_minimum_readable_seconds(source_text),
            )
        covered_blocks.update(
            str(code).strip()
            for code in event.get("source_script_block_codes") or []
            if str(code).strip()
        )

    required_blocks = {
        str(code).strip()
        for shot in shots_by_index.values()
        if str(shot.get("narration") or shot.get("subtitle_text") or "").strip()
        for code in shot.get("source_script_block_codes") or []
        if str(code).strip()
    }
    missing_blocks = sorted(required_blocks - covered_blocks)
    if missing_blocks:
        issue("required_script_blocks_missing_from_subtitles", script_block_codes=missing_blocks)

    text_complete = bool(subtitle_manifest.get("text_complete")) and not int(
        subtitle_manifest.get("truncated_event_count") or 0
    )
    if not text_complete:
        issue("subtitle_text_incomplete")

    checks = {
        "subtitle_text_complete": text_complete,
        "subtitle_safe_area": safe_area,
        "subtitle_manifest_consistent": manifest_consistent,
        "subtitle_event_ranges": event_ranges_valid,
        "subtitle_line_layout": line_layout_valid,
        "subtitle_readable_duration": readable_durations_valid,
        "required_script_blocks_covered": not missing_blocks,
    }
    return {
        "schema_version": "subtitle-quality-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "safe_margins": safe_margins if isinstance(safe_margins, dict) else {},
        "event_count": len(events),
        "required_script_block_codes": sorted(required_blocks),
        "covered_script_block_codes": sorted(covered_blocks),
        "missing_script_block_codes": missing_blocks,
        "issues": issues,
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
        source_shot_code = str(shot.get("source_shot_code") or "").strip()
        source_script_block_codes = list(
            dict.fromkeys(
                str(code).strip()
                for code in shot.get("source_script_block_codes") or []
                if str(code).strip()
            )
        )
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
                "source_shot_code": source_shot_code,
                "source_script_block_codes": source_script_block_codes,
                "timing_source": "text_weight_estimate_v1",
                "word_timing": _word_timing(caption, cursor, end),
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
                    "source_shot_code": source_shot_code,
                    "source_script_block_codes": source_script_block_codes,
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
        "word_timing_source": "text_weight_estimate_v1",
        "word_timing_count": sum(
            len(event.get("word_timing") or [])
            for event in events
            if event["kind"] == "caption"
        ),
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
    sentences = [
        part.strip()
        for part in re.findall(r".+?(?:[。！？!?；;]+|$)", text, flags=re.DOTALL)
        if part.strip()
    ]
    chunks: list[str] = []
    for sentence in sentences or [text]:
        clauses = [
            part
            for part in re.findall(r".+?(?:[，、：]+|$)", sentence, flags=re.DOTALL)
            if part
        ]
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


def _minimum_readable_seconds(text: str) -> float:
    """Use a conservative deterministic lower bound, capped for short-video captions."""

    return round(min(3.0, max(0.7, _text_weight(text) / 6.0)), 3)


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in {float("inf"), float("-inf")} else None


def _word_timing(text: str, start_seconds: float, end_seconds: float) -> list[dict[str, float | str]]:
    tokens = re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+|[^\s]", text)
    if not tokens or end_seconds <= start_seconds:
        return []
    weights = [_text_weight(token) for token in tokens]
    total_weight = sum(weights) or 1.0
    cursor = start_seconds
    timing: list[dict[str, float | str]] = []
    for index, (token, weight) in enumerate(zip(tokens, weights, strict=True)):
        end = (
            end_seconds
            if index == len(tokens) - 1
            else cursor + (end_seconds - start_seconds) * weight / total_weight
        )
        timing.append(
            {
                "text": token,
                "start_seconds": round(cursor, 6),
                "end_seconds": round(end, 6),
            }
        )
        cursor = end
    return timing


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _dialogue_line(start: float, end: float, style: str, text: str, *, layer: int = 0) -> str:
    return f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},{style},,0,0,0,,{text}"
