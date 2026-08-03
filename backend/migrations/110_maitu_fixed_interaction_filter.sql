-- Reclassify already stored fixed Maitu interactions using the current filter rules.

UPDATE maitu_live_interactions
SET is_arrival = TRUE, updated_at = now()
WHERE NOT is_arrival
  AND (
      btrim(normalized_content) LIKE U&'%\6765\4E86'
      OR btrim(normalized_content) LIKE U&'%\5173\6CE8\4E86%'
  );
