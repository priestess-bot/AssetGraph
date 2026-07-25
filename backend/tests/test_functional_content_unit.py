from app.services.functional_content import FunctionalContentService


def test_product_order_is_preserved_in_story_context_and_product_segments() -> None:
    content = {"product_order": [" PRODUCT-001 ", "PRODUCT-002"]}
    story = FunctionalContentService._story_content("Explain product choices", content, {})
    segments = FunctionalContentService._segments(
        [
            {"block_code": "BLOCK-OPEN", "module_type": "opening"},
            {"block_code": "BLOCK-FACT-1", "module_type": "product_fact"},
            {"block_code": "BLOCK-FACT-2", "module_type": "product_fact"},
            {"block_code": "BLOCK-FACT-3", "module_type": "product_fact"},
        ],
        content["product_order"],
    )

    assert story["product_order"] == [" PRODUCT-001 ", "PRODUCT-002"]
    assert [segment["product_refs"] for segment in segments] == [
        [],
        ["PRODUCT-001"],
        ["PRODUCT-002"],
        [],
    ]


def test_selected_content_strategy_policy_reaches_script_and_program_actions() -> None:
    policy = FunctionalContentService._content_strategy_policy_snapshot(
        {
            "duration_policy": {"target_duration_seconds": 1800, "pacing": "opening_fast"},
            "module_recipes": [{"module_key": "opening", "guidance": "先建立选择问题"}],
            "product_rotation_policy": {"cadence": "every_two_modules"},
            "interaction_policy": {"cadence": "module_end", "prompt_focus": "use_case"},
            "conversion_policy": {"cta_style": "summarize_choice", "cta_cadence": "closing"},
            "host_style": {"tone": "clear", "delivery": "short_sentences"},
        }
    )
    content = {
        "primary_template_ref": {
            "template_code": "TPL-STRATEGY-001",
            "revision": 2,
            "contribution": "primary_structure",
            "selection_role": "primary",
        },
        "template_contribution_decisions": [
            {
                "template_code": "TPL-STRATEGY-001",
                "accepted_modules": ["opening"],
                "content_strategy_policy": policy,
            }
        ],
    }

    blocks = FunctionalContentService._script_blocks("帮助用户选择", content, [])
    opening = blocks[0]
    conversion = blocks[-1]

    assert opening["template_sources"][0]["module_guidance"] == ["先建立选择问题"]
    assert opening["interaction_intent"] == {
        "type": "template_interaction",
        "policy": {"cadence": "module_end", "prompt_focus": "use_case"},
    }
    assert conversion["cta_intent"] == {
        "type": "comment",
        "policy": {"cta_style": "summarize_choice", "cta_cadence": "closing"},
    }

    segments = FunctionalContentService._segments(
        [{**block, "block_code": f"BLOCK-{index}"} for index, block in enumerate(blocks)]
    )
    assert segments[0]["interaction_actions"] == [opening["interaction_intent"]]
    assert segments[0]["metadata"] == {
        "template_product_rotation_policy": {"cadence": "every_two_modules"},
        "template_duration_policy": {"target_duration_seconds": 1800, "pacing": "opening_fast"},
        "template_host_style": {"tone": "clear", "delivery": "short_sentences"},
    }
    assert segments[-1]["cta_actions"] == [conversion["cta_intent"]]


def test_strategy_outline_compiles_primary_order_and_secondary_supplement() -> None:
    def source_stage(
        module_key: str, title: str, purpose: str, start_ms: int
    ) -> dict[str, int | str]:
        return {
            "module_key": module_key,
            "title": title,
            "purpose": purpose,
            "source_session_code": "CAPTURE-001",
            "start_ms": start_ms,
            "end_ms": start_ms + 30_000,
        }
    content = {
        "theme": "夏日饮品选择",
        "primary_template_ref": {
            "template_code": "TPL-PRIMARY",
            "revision": 4,
            "contribution": "primary_structure",
            "selection_role": "primary",
        },
        "secondary_template_refs": [
            {
                "template_code": "TPL-SUPPLEMENT",
                "revision": 2,
                "contribution": "secondary_supplement",
                "selection_role": "secondary",
            }
        ],
        "template_contribution_decisions": [
            {
                "template_code": "TPL-PRIMARY",
                "accepted_modules": ["opening", "conversion"],
                "program_outline": [
                    source_stage("opening", "开场", "建立选择目标", 0),
                    source_stage("conversion", "收束", "引导下一步", 60_000),
                ],
                "content_strategy_policy": {
                    "interaction_policy": {"cadence": "module_end"},
                    "conversion_policy": {"cta_style": "summarize_choice"},
                },
            },
            {
                "template_code": "TPL-SUPPLEMENT",
                "accepted_modules": ["comparison"],
                "program_outline": [
                    source_stage("comparison", "对比", "说明适用差异", 30_000),
                ],
                "content_strategy_policy": {},
            },
        ],
    }

    blocks = FunctionalContentService._script_blocks("帮助观众选择", content, [])

    assert [block["module_type"] for block in blocks] == [
        "opening",
        "comparison",
        "conversion",
    ]
    assert blocks[1]["template_sources"][0]["template_code"] == "TPL-SUPPLEMENT"
    assert blocks[1]["template_sources"][0]["strategy_stage"] == source_stage(
        "comparison", "对比", "说明适用差异", 30_000
    )
    assert blocks[-1]["cta_intent"] == {
        "type": "comment",
        "policy": {"cta_style": "summarize_choice"},
    }

    segments = FunctionalContentService._segments(
        [{**block, "block_code": f"BLOCK-{index}"} for index, block in enumerate(blocks)]
    )
    assert [segment["semantic_goal"] for segment in segments] == [
        "建立选择目标",
        "说明适用差异",
        "引导下一步",
    ]
    assert [segment["program_phase"] for segment in segments] == [
        "opening",
        "body",
        "conversion",
    ]
    assert segments[1]["metadata"]["template_strategy_stage"]["source_session_code"] == "CAPTURE-001"
