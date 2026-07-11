from __future__ import annotations

import re
from typing import Any

SOURCE = "jd_wine_livestream_script_rule_v1"
INSUFFICIENT_MATERIAL = "insufficient_verified_material_for_target_duration"

TIME_FORBIDDEN = (
    "早上好",
    "上午好",
    "中午好",
    "下午好",
    "晚上好",
    "今晚",
    "今夜",
    "今天",
    "明天",
    "后天",
    "本周",
    "下周",
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
    "星期",
    "凌晨",
    "周末",
    "下班后",
    "睡前",
    "本场结束",
    "感谢观看",
    "下次再见",
    "马上下播",
)
TIME_FORBIDDEN_PATTERNS = (
    r"\d{1,2}[:：]\d{2}",
    r"\d{1,2}点(?:钟|整|\d{1,2}分)?",
    r"\d{1,2}月\d{1,2}日",
    r"\d+(?:\.\d+)?\s*(?:小时|分钟|天)(?:后|内)",
    r"(?:稍后|一会儿|过会儿|随后).{0,8}(?:结束|恢复|下架|涨价|截止)",
    r"(?:倒计时|限时|限今日)",
)
CATALOG_SCOPE_FORBIDDEN = (
    "所有商品",
    "全部商品",
    "直播间就这几款",
    "把八款缩到两款",
    "直播间这八款",
    "直播间里的八款",
)
CATALOG_SCOPE_FORBIDDEN_PATTERNS = (
    r"(?:直播间|全场|本场)(?:内|里)?(?:一共|总共|共有|共|只有|就|有)?[零一二三四五六七八九十百两\d]+(?:款|个)(?:商品|产品|酒款|酒)?",
    r"[零一二三四五六七八九十百两\d]+(?:款|个)(?:商品|产品|酒款).{0,12}(?:全部|所有)",
)
INTERNAL_FORBIDDEN = (
    "参考资料显示",
    "待确认",
    "试读版",
    "正式直播前核验",
    "不作为承诺",
)
PROMOTION_SEMANTIC_PATTERNS = (
    r"优惠",
    r"赠品|赠送|赠礼",
    r"满减|立减|到手价|领券|优惠券|折扣",
    r"[零一二三四五六七八九十百两\d]+折",
    r"前[零一二三四五六七八九十百两\d]+名",
    r"限量|库存仅?",
)


class LivestreamScriptWriter:
    """Build a scope-safe first draft from structured, verified product facts.

    The writer deliberately refuses to stretch text to a requested duration. Its
    sections are also the authoritative input for scene planning and asset needs.
    """

    def generate(self, request: dict[str, Any]) -> dict[str, Any]:
        products = [dict(product) for product in request.get("products") or []]
        words_per_minute = int(request.get("words_per_minute") or 165)
        target_minutes = int(request.get("target_duration_minutes") or 30)
        sections = [self._opening_section(request, words_per_minute=words_per_minute)]
        dropped_unverified_claims: list[str] = []
        for index, product in enumerate(products, start=1):
            sections.append(
                self._product_section(
                    index,
                    product,
                    words_per_minute=words_per_minute,
                )
            )
            dropped_unverified_claims.extend(product.get("unverified_promotion_claims") or [])
        sections.append(
            self._loop_section(
                len(sections),
                request,
                first_product=products[0],
                words_per_minute=words_per_minute,
            )
        )
        dropped_unverified_claims = self._dedupe(dropped_unverified_claims)
        removed_unverified_claim_sentences = self._remove_unverified_claim_sentences(
            sections,
            claims=dropped_unverified_claims,
            words_per_minute=words_per_minute,
        )
        verified_promotion_claims = self._dedupe(
            [
                claim
                for product in products
                for claim in (product.get("verified_promotion_claims") or [])
            ]
        )
        removed_unverified_claim_sentences = self._dedupe(
            [
                *removed_unverified_claim_sentences,
                *self._remove_unowned_promotion_sentences(
                    sections,
                    verified_claims=verified_promotion_claims,
                    words_per_minute=words_per_minute,
                ),
            ]
        )
        removed_duplicate_sentences = self._dedupe_repeated_sentences(
            sections,
            words_per_minute=words_per_minute,
        )

        spoken_script = "\n\n".join(section["script"] for section in sections if section.get("script"))
        quality_report = self._quality_report(
            spoken_script,
            request=request,
            products=products,
            dropped_unverified_claims=dropped_unverified_claims,
            removed_unverified_claim_sentences=removed_unverified_claim_sentences,
            removed_duplicate_sentences=removed_duplicate_sentences,
            words_per_minute=words_per_minute,
            target_minutes=target_minutes,
        )
        global_review_reasons = list(quality_report["warnings"])
        review_reasons = list(global_review_reasons)
        for section in sections:
            section_reasons = self._dedupe(
                [*(section.get("review_reasons") or []), *global_review_reasons]
            )
            section["review_reasons"] = section_reasons
            section["manual_review"] = bool(section_reasons)
            review_reasons.extend(section_reasons)
        manual_review_required = any(section["manual_review"] for section in sections)

        scene_plan_payload = {
            "source": "generated_script_sections_v1",
            "scene_count": len(sections),
            "target_scene_count": len(sections),
            "manual_review_required": manual_review_required,
            "scenes": [
                {
                    "scene_index": section["section_index"],
                    "scene_name": section["scene_name"],
                    "scene_goal": section["scene_goal"],
                    "duration_seconds": section["duration_seconds"],
                    "script": section["script"],
                    "keywords": section["keywords"],
                    "manual_review": section["manual_review"],
                    "review_reasons": section["review_reasons"],
                }
                for section in sections
            ],
        }
        return {
            "source": SOURCE,
            "title": str(request.get("title") or "直播口播稿"),
            "platform": str(request.get("platform") or "京东"),
            "target_duration_minutes": target_minutes,
            "always_on_24h": bool(request.get("always_on_24h", True)),
            "catalog_total_verified": bool(request.get("catalog_total_verified", False)),
            "spoken_script": spoken_script,
            "section_count": len(sections),
            "sections": sections,
            "quality_report": quality_report,
            "scene_plan_payload": scene_plan_payload,
            "manual_review_required": manual_review_required,
            "review_reasons": self._dedupe(review_reasons),
        }

    def _opening_section(self, request: dict[str, Any], *, words_per_minute: int) -> dict[str, Any]:
        persona = str(request.get("host_persona") or "")
        if any(token in persona for token in ("直接", "判断", "利落")):
            script = (
                "选酒先把用途和口味说清楚。自己喝、宴请或送礼，选择标准不同，"
                "先把场景定下来，再看哪一种风格更合适；具体需求可以发在公屏上。"
            )
        else:
            script = (
                "正在看葡萄酒的朋友，可以把用途和口味发在公屏上。"
                "自己喝、宴请或送礼，选择标准不同，先把场景定下来，再看哪一种风格更合适。"
            )
        return self._section(
            section_index=0,
            section_type="opening",
            scene_name="循环入口",
            scene_goal="opening",
            script=script,
            keywords=["葡萄酒", "用途", "口味"],
            information_owner="opening:selection_context",
            words_per_minute=words_per_minute,
        )

    def _product_section(
        self,
        section_index: int,
        product: dict[str, Any],
        *,
        words_per_minute: int,
    ) -> dict[str, Any]:
        name = str(product.get("product_name") or "商品")
        positioning = str(product.get("positioning") or "产品特点")
        facts = self._dedupe(product.get("verified_facts") or [])
        tasting = self._dedupe(product.get("tasting_notes") or [])
        scenarios = self._dedupe(product.get("scenarios") or [])
        parts = [self._product_lead(section_index, name, positioning)]
        if facts:
            parts.append(self._as_sentences(facts))
        if tasting:
            parts.append(self._tasting_sentence(section_index, tasting))
        if scenarios:
            parts.append(self._scenario_sentence(section_index, scenarios))
        objection = str(product.get("objection_response") or "").strip()
        if objection:
            parts.append(self._ensure_sentence(objection))
        promotions = self._dedupe(product.get("verified_promotion_claims") or [])
        if promotions:
            parts.append(self._as_sentences(promotions))
        guidance = str(product.get("selection_guidance") or "").strip()
        if guidance:
            parts.append(self._ensure_sentence(guidance))
        else:
            parts.append(f"想继续比较{name}，可以点开商品页核对当前规格。")
        script = "".join(part for part in parts if part)
        review_reasons: list[str] = []
        if len(facts) < 2:
            review_reasons.append("insufficient_verified_product_facts")
        return self._section(
            section_index=section_index,
            section_type="product",
            scene_name=name,
            scene_goal="product_explanation",
            script=script,
            keywords=self._dedupe(
                [
                    name,
                    positioning,
                    *(product.get("asset_keywords") or []),
                    *facts,
                    *tasting,
                ]
            ),
            information_owner=f"product:{name}",
            words_per_minute=words_per_minute,
            product_name=name,
            product_code=product.get("product_code"),
            review_reasons=review_reasons,
        )

    def _loop_section(
        self,
        section_index: int,
        request: dict[str, Any],
        *,
        first_product: dict[str, Any],
        words_per_minute: int,
    ) -> dict[str, Any]:
        first_name = str(first_product.get("product_name") or "当前商品")
        if request.get("always_on_24h", True):
            script = f"需要继续比较时，可以把商品名和用途发在公屏上；想重新听选购逻辑，可以从{first_name}接着听。"
            scene_goal = "transition"
            section_type = "loop_reentry"
        else:
            script = "已经选好的朋友可以核对商品规格和收货信息。"
            scene_goal = "closing"
            section_type = "closing"
        if request.get("include_compliance_notice", True):
            script += "请适量饮酒，未成年人请勿饮酒，饮酒后不要驾车。"
        return self._section(
            section_index=section_index,
            section_type=section_type,
            scene_name="循环重入" if section_type == "loop_reentry" else "结束提醒",
            scene_goal=scene_goal,
            script=script,
            keywords=self._dedupe([first_name, "公屏", "适量饮酒"]),
            information_owner="loop:reentry_and_compliance",
            words_per_minute=words_per_minute,
        )

    def _quality_report(
        self,
        spoken_script: str,
        *,
        request: dict[str, Any],
        products: list[dict[str, Any]],
        dropped_unverified_claims: list[str],
        removed_unverified_claim_sentences: list[str],
        removed_duplicate_sentences: list[str],
        words_per_minute: int,
        target_minutes: int,
    ) -> dict[str, Any]:
        if request.get("always_on_24h", True):
            time_hits = [phrase for phrase in TIME_FORBIDDEN if phrase in spoken_script]
            time_hits.extend(
                match.group(0)
                for pattern in TIME_FORBIDDEN_PATTERNS
                for match in re.finditer(pattern, spoken_script)
            )
            time_hits = self._dedupe(time_hits)
        else:
            time_hits = []
        if request.get("catalog_total_verified", False):
            scope_hits = []
        else:
            scope_hits = [phrase for phrase in CATALOG_SCOPE_FORBIDDEN if phrase in spoken_script]
            scope_hits.extend(
                match.group(0)
                for pattern in CATALOG_SCOPE_FORBIDDEN_PATTERNS
                for match in re.finditer(pattern, spoken_script)
            )
            scope_hits = self._dedupe(scope_hits)
        internal_hits = [phrase for phrase in INTERNAL_FORBIDDEN if phrase in spoken_script]
        paragraphs = [self._normalize(paragraph) for paragraph in spoken_script.split("\n\n") if paragraph.strip()]
        duplicate_count = len(paragraphs) - len(set(paragraphs))
        duplicate_clause_count = self._duplicate_clause_count(spoken_script)
        chinese_character_count = len(re.findall(r"[\u4e00-\u9fff]", spoken_script))
        estimated_duration_seconds = max(1, round(chinese_character_count / words_per_minute * 60))
        target_duration_seconds = target_minutes * 60
        sufficient = estimated_duration_seconds >= target_duration_seconds
        warnings: list[str] = []
        if not sufficient:
            warnings.append(INSUFFICIENT_MATERIAL)
        if time_hits:
            warnings.append("time_dependent_spoken_language")
        if scope_hits:
            warnings.append("catalog_scope_assumption")
        if internal_hits:
            warnings.append("internal_review_language_in_spoken_script")
        if duplicate_count:
            warnings.append("duplicate_spoken_paragraphs")
        if duplicate_clause_count:
            warnings.append("duplicate_spoken_clauses")
        if removed_unverified_claim_sentences:
            warnings.append("unverified_promotion_claim_removed_from_spoken_content")
        if any(len(self._dedupe(product.get("verified_facts") or [])) < 2 for product in products):
            warnings.append("insufficient_verified_product_facts")
        return {
            "catalog_scope_safe": not scope_hits,
            "time_neutral": not time_hits,
            "padding_free": duplicate_count == 0 and duplicate_clause_count == 0,
            "fresh_draft_from_structured_sources": True,
            "duplicate_paragraph_count": duplicate_count,
            "forbidden_hits": self._dedupe([*time_hits, *scope_hits, *internal_hits]),
            "dropped_unverified_claims": dropped_unverified_claims,
            "removed_unverified_claim_sentences": removed_unverified_claim_sentences,
            "removed_duplicate_sentences": removed_duplicate_sentences,
            "chinese_character_count": chinese_character_count,
            "estimated_duration_seconds": estimated_duration_seconds,
            "target_duration_seconds": target_duration_seconds,
            "material_sufficiency_status": "sufficient" if sufficient else INSUFFICIENT_MATERIAL,
            "warnings": self._dedupe(warnings),
        }

    def _section(
        self,
        *,
        section_index: int,
        section_type: str,
        scene_name: str,
        scene_goal: str,
        script: str,
        keywords: list[str],
        information_owner: str,
        words_per_minute: int,
        product_name: str | None = None,
        product_code: str | None = None,
        review_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", script))
        reasons = self._dedupe(review_reasons or [])
        return {
            "section_index": section_index,
            "section_type": section_type,
            "scene_name": scene_name,
            "scene_goal": scene_goal,
            "product_name": product_name,
            "product_code": product_code,
            "duration_seconds": max(1, round(chinese_chars / words_per_minute * 60)),
            "script": script,
            "keywords": keywords,
            "information_owner": information_owner,
            "manual_review": bool(reasons),
            "review_reasons": reasons,
        }

    @classmethod
    def _remove_unowned_promotion_sentences(
        cls,
        sections: list[dict[str, Any]],
        *,
        verified_claims: list[str],
        words_per_minute: int,
    ) -> list[str]:
        verified = [cls._normalize(claim) for claim in verified_claims if cls._normalize(claim)]
        removed: list[str] = []
        for section in sections:
            kept: list[str] = []
            for sentence in re.split(r"(?<=[。！？!?])", str(section.get("script") or "")):
                text = sentence.strip()
                if not text:
                    continue
                normalized = cls._normalize(text)
                has_promotion = any(re.search(pattern, normalized) for pattern in PROMOTION_SEMANTIC_PATTERNS)
                owned_by_verified_claim = any(claim in normalized for claim in verified)
                if has_promotion and not owned_by_verified_claim:
                    removed.append(text)
                    continue
                kept.append(text)
            section["script"] = "".join(kept)
            section["keywords"] = [
                keyword
                for keyword in (section.get("keywords") or [])
                if not (
                    any(re.search(pattern, cls._normalize(keyword)) for pattern in PROMOTION_SEMANTIC_PATTERNS)
                    and not any(claim in cls._normalize(keyword) for claim in verified)
                )
            ]
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", section["script"]))
            section["duration_seconds"] = max(1, round(chinese_chars / words_per_minute * 60))
        return cls._dedupe(removed)

    @classmethod
    def _remove_unverified_claim_sentences(
        cls,
        sections: list[dict[str, Any]],
        *,
        claims: list[str],
        words_per_minute: int,
    ) -> list[str]:
        normalized_claims = [cls._normalize(claim) for claim in claims if cls._normalize(claim)]
        if not normalized_claims:
            return []
        removed: list[str] = []
        for section in sections:
            kept: list[str] = []
            for sentence in re.split(r"(?<=[。！？!?])", str(section.get("script") or "")):
                text = sentence.strip()
                if not text:
                    continue
                normalized = cls._normalize(text)
                if any(claim in normalized for claim in normalized_claims):
                    removed.append(text)
                    continue
                kept.append(text)
            section["script"] = "".join(kept)
            section["keywords"] = [
                keyword
                for keyword in (section.get("keywords") or [])
                if not any(claim in cls._normalize(keyword) for claim in normalized_claims)
            ]
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", section["script"]))
            section["duration_seconds"] = max(1, round(chinese_chars / words_per_minute * 60))
        return cls._dedupe(removed)

    @classmethod
    def _dedupe_repeated_sentences(
        cls,
        sections: list[dict[str, Any]],
        *,
        words_per_minute: int,
    ) -> list[str]:
        seen: set[str] = set()
        removed: list[str] = []
        for section in sections:
            kept: list[str] = []
            clauses = re.findall(r"[^。！？!?；;，,]+[。！？!?；;，,]?", str(section.get("script") or ""))
            for clause in clauses:
                text = clause.strip()
                if not text:
                    continue
                normalized = cls._normalize(text)
                if len(normalized) >= 4 and normalized in seen:
                    removed.append(text)
                    continue
                if len(normalized) >= 4:
                    seen.add(normalized)
                kept.append(text)
            section["script"] = "".join(kept)
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", section["script"]))
            section["duration_seconds"] = max(1, round(chinese_chars / words_per_minute * 60))
        return cls._dedupe(removed)

    @staticmethod
    def _product_lead(index: int, name: str, positioning: str) -> str:
        variants = (
            f"先看{name}，{positioning}是它的主线。",
            f"如果更在意{positioning}，{name}值得单独比较。",
            f"把选择转到{name}，重点会落在{positioning}。",
            f"{name}走的是{positioning}这条路线。",
        )
        return variants[(index - 1) % len(variants)]

    @staticmethod
    def _tasting_sentence(index: int, tasting: list[str]) -> str:
        joined = "、".join(tasting)
        variants = (
            f"杯中可以感受到{joined}。",
            f"闻香和入口的重点是{joined}。",
            f"喝到嘴里，{joined}会依次出现。",
        )
        return variants[(index - 1) % len(variants)]

    @staticmethod
    def _scenario_sentence(index: int, scenarios: list[str]) -> str:
        joined = "、".join(scenarios)
        variants = (
            f"放在{joined}这些场景里，它的风格更容易发挥。",
            f"{joined}是更匹配它的使用场景。",
            f"需要{joined}时，可以按这条风格继续选择。",
        )
        return variants[(index - 1) % len(variants)]

    @staticmethod
    def _ensure_sentence(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text if text.endswith(("。", "！", "？", ".", "!", "?")) else f"{text}。"

    @classmethod
    def _as_sentences(cls, values: list[str]) -> str:
        return "".join(cls._ensure_sentence(value) for value in values)

    @classmethod
    def _duplicate_clause_count(cls, value: str) -> int:
        seen: set[str] = set()
        duplicates = 0
        for clause in re.findall(r"[^。！？!?；;，,]+[。！？!?；;，,]?", str(value or "")):
            normalized = cls._normalize(clause)
            if len(normalized) < 4:
                continue
            if normalized in seen:
                duplicates += 1
            else:
                seen.add(normalized)
        return duplicates

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "")).strip("。！？!?；;，,")

    @classmethod
    def _dedupe(cls, values: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            normalized = cls._normalize(text)
            if text and normalized not in seen:
                seen.add(normalized)
                result.append(text)
        return result
