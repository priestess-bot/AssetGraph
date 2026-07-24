-- Published catalog revisions are immutable. Superseding changes only status;
-- definition edits always create a new numbered revision.

CREATE OR REPLACE FUNCTION protect_catalog_revision()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'active' AND NEW.status IN ('superseded', 'deprecated')
       AND (to_jsonb(OLD) - 'status') = (to_jsonb(NEW) - 'status') THEN
        RETURN NEW;
    END IF;
    IF OLD.status IN ('active', 'superseded', 'deprecated', 'retired') THEN
        RAISE EXCEPTION 'immutable catalog revision cannot be mutated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_metric_revision_immutable ON metric_definition_revisions;
CREATE TRIGGER trg_metric_revision_immutable
BEFORE UPDATE ON metric_definition_revisions
FOR EACH ROW EXECUTE FUNCTION protect_catalog_revision();

DROP TRIGGER IF EXISTS trg_data_contract_immutable ON data_contracts;
CREATE TRIGGER trg_data_contract_immutable
BEFORE UPDATE ON data_contracts
FOR EACH ROW EXECUTE FUNCTION protect_catalog_revision();

DROP TRIGGER IF EXISTS trg_learning_policy_immutable ON learning_policy_versions;
CREATE TRIGGER trg_learning_policy_immutable
BEFORE UPDATE ON learning_policy_versions
FOR EACH ROW EXECUTE FUNCTION protect_catalog_revision();

DROP TRIGGER IF EXISTS trg_effect_policy_immutable ON effect_eligibility_policy_versions;
CREATE TRIGGER trg_effect_policy_immutable
BEFORE UPDATE ON effect_eligibility_policy_versions
FOR EACH ROW EXECUTE FUNCTION protect_catalog_revision();
