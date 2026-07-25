-- Functional live-room plans project the authoritative script-layout worker
-- result without claiming that a requested draft has already been written.

ALTER TABLE functional_live_room_plans
    DROP CONSTRAINT IF EXISTS chk_functional_live_room_execution_status;

ALTER TABLE functional_live_room_plans
    ADD CONSTRAINT chk_functional_live_room_execution_status
        CHECK (
            execution_status IN (
                'not_requested',
                'requested',
                'maitu_running',
                'maitu_reconcile_required',
                'maitu_failed',
                'blocked',
                'demo_complete',
                'maitu_complete'
            )
        );
