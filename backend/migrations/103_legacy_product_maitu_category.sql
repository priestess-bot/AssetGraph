-- Normalize the pre-taxonomy `product` category so legacy assets remain listable.

UPDATE assets
SET maitu_category = CASE
    WHEN COALESCE(media_kind, '') = 'video' OR asset_type = 'VID' THEN 'product_video'
    ELSE 'product_image'
END,
updated_at = now()
WHERE maitu_category = 'product';
