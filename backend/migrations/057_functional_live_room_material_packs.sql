-- A live-room plan freezes the selected pack identities while its inventory
-- snapshot records the resolved published revision and exact asset whitelist.

ALTER TABLE functional_live_room_plans
    ADD COLUMN IF NOT EXISTS selected_material_pack_codes JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE functional_live_room_plans
    ADD CONSTRAINT chk_functional_live_room_selected_material_packs
        CHECK (jsonb_typeof(selected_material_pack_codes) = 'array');
