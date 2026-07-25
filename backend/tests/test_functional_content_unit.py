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
