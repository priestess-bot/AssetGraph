import { afterEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "./api";
import { setWorkbenchAccessToken } from "../workbench/api";


function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}


describe("Console API", () => {
  afterEach(() => {
    setWorkbenchAccessToken();
    vi.unstubAllGlobals();
  });

  it("validates a memory-only bearer and attaches it to later shared requests", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ operator_id: "operator-a", auth_scheme: "bearer_memory", roles: ["control_plane_operator"] }))
      .mockResolvedValueOnce(response([]));
    vi.stubGlobal("fetch", fetchMock);

    const session = await consoleApi.session("temporary-secret");
    setWorkbenchAccessToken("temporary-secret");
    await consoleApi.tasks();

    expect(session.operatorId).toBe("operator-a");
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({ Authorization: "Bearer temporary-secret" });
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({ Authorization: "Bearer temporary-secret" });
  });

  it("keeps release decisions behind the memory-only operator credential", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response({
      command: "approve",
      entity_type: "release",
      entity_code: "RELEASE-001",
      entity_revision: 1,
      status: "approved",
      impact: "fixed",
      receipt_code: "COMMAND-RELEASE-001",
      replayed: false,
      approval_code: "APPROVAL-001",
    }));
    vi.stubGlobal("fetch", fetchMock);
    setWorkbenchAccessToken("temporary-secret");

    await consoleApi.decideRelease("RELEASE-001", {
      expectedManifestRevision: 1,
      decision: "approve",
      reasonCode: "CONTENT_DELIVERY_APPROVED",
      summary: "Reviewed output",
      approvedScope: { carrier: "rendered_video" },
      idempotencyKey: "release-approve-001",
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/console/releases/RELEASE-001/decision");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.headers).toMatchObject({ Authorization: "Bearer temporary-secret" });
    expect(JSON.parse(String(init.body))).toEqual({
      expected_manifest_revision: 1,
      decision: "approve",
      structured_reason: { reason_code: "CONTENT_DELIVERY_APPROVED", summary: "Reviewed output" },
      approved_scope: { carrier: "rendered_video" },
      idempotency_key: "release-approve-001",
    });
  });

  it("normalizes stable task, notification, and search deep links", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response([{ item_code: "TASK-1", item_type: "human_task", title: "review", status: "open", priority: 10, summary: "Review", href: "/governance/runs?run=RUN-1", updated_at: "2026-07-23T00:00:00Z", run_code: "RUN-1", progress_completed: 1, progress_total: 2 }]))
      .mockResolvedValueOnce(response([{ notification_code: "ALERT-1", state: "warning", title: "STALE", summary: "Snapshot stale", href: "/assets/library?asset=A-1", evidence: { snapshot: "S-1" }, occurrence_count: 2, occurred_at: "2026-07-23T00:00:00Z", status: "open" }]))
      .mockResolvedValueOnce(response([{ entity_type: "asset", entity_code: "A-1", title: "Asset", status: "ready", revision: 3, href: "/assets/library?asset=A-1", updated_at: "2026-07-23T00:00:00Z" }]));
    vi.stubGlobal("fetch", fetchMock);

    const tasks = await consoleApi.tasks();
    const notifications = await consoleApi.notifications();
    const search = await consoleApi.search("A-1");

    expect(tasks[0]).toMatchObject({ itemCode: "TASK-1", href: "/governance/runs?run=RUN-1" });
    expect(notifications[0]).toMatchObject({ notificationCode: "ALERT-1", evidence: [{ kind: "snapshot", ref: "S-1" }] });
    expect(search[0]).toMatchObject({ entityCode: "A-1", revision: 3, href: "/assets/library?asset=A-1" });
  });

  it("normalizes entity revisions, structured diffs, and verified relations", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response({
      entity_type: "asset",
      entity_code: "A-1",
      title: "Asset",
      status: "ready",
      current_revision: 2,
      canonical_href: "/assets/library?asset=A-1",
      source_of_truth: "postgresql",
      revisions: [
        { revision: 2, status: "ready", schema_version: "asset.v1", created_at: "2026-07-23T01:00:00Z", fingerprint: "abc", snapshot: { title: "new" } },
        { revision: 1, status: "draft", schema_version: "asset.v1", created_at: "2026-07-22T01:00:00Z", snapshot: { title: "old" } },
      ],
      diff: { from_revision: 1, to_revision: 2, available: true, changes: [{ path: "$.title", change: "changed", before: "old", after: "new" }] },
      sources: [{ relation_type: "imported_from", entity_type: "source_system", entity_code: "maitu", mapping_quality: "verified" }],
      used_by: [{ relation_type: "used_by_run", entity_type: "workflow_run", entity_code: "RUN-1", href: "/governance/runs?run=RUN-1", mapping_quality: "verified" }],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const entity = await consoleApi.entity("asset", "A-1", 1, 2);

    expect(fetchMock.mock.calls[0]?.[0]).toContain("/api/console/entities/asset/A-1?from_revision=1&to_revision=2");
    expect(entity.revisions).toHaveLength(2);
    expect(entity.diff.changes[0]).toEqual({ path: "$.title", change: "changed", before: "old", after: "new" });
    expect(entity.sources[0]).toMatchObject({ entityCode: "maitu", mappingQuality: "verified" });
    expect(entity.usedBy[0]).toMatchObject({ entityCode: "RUN-1", href: "/governance/runs?run=RUN-1" });
  });

  it("sends expected revisions to draft and named command endpoints", async () => {
    const draftBody = {
      draft_code: "DRAFT-1",
      entity_type: "content_project",
      entity_code: "CONTENT-1",
      draft_kind: "input",
      schema_version: "console-draft.v1",
      draft_revision: 2,
      base_entity_revision: 1,
      status: "active",
      document: { title: "Project", generation_goal: "Goal" },
      content_fingerprint: "a".repeat(64),
      created_by: "operator-a",
      updated_by: "operator-a",
      created_at: "2026-07-23T00:00:00Z",
      updated_at: "2026-07-23T00:01:00Z",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(draftBody))
      .mockResolvedValueOnce(response(draftBody))
      .mockResolvedValueOnce(response({ command: "confirm", entity_type: "content_project", entity_code: "CONTENT-1", entity_revision: 1, status: "confirmed", impact: "fixed", receipt_code: "COMMAND-1", replayed: false, draft_revision: 3 }))
      .mockResolvedValueOnce(response({ command: "authorize", entity_type: "workflow_run", entity_code: "RUN-1", entity_revision: 3, status: "issued", impact: "fixed", receipt_code: "COMMAND-2", replayed: false, authorization_code: "AUTH-1", authorization_token: "one-time", token_available: true }));
    vi.stubGlobal("fetch", fetchMock);

    const loaded = await consoleApi.draft("content_project", "CONTENT-1", "input");
    const saved = await consoleApi.saveDraft("content_project", "CONTENT-1", "input", {
      expectedRevision: 1,
      baseEntityRevision: 1,
      document: { title: "Project", generation_goal: "Goal" },
    });
    const confirmed = await consoleApi.confirmContentProject("CONTENT-1", {
      expectedEntityRevision: 1,
      expectedDraftRevision: 2,
      idempotencyKey: "confirm-001",
    });
    const authorization = await consoleApi.issueAuthorization("RUN-1", {
      taskCode: "TASK-1",
      expectedTaskRevision: 3,
      idempotencyKey: "authorize-001",
    });

    expect(loaded?.draftRevision).toBe(2);
    expect(saved.document).toMatchObject({ generation_goal: "Goal" });
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toMatchObject({ expected_revision: 1, base_entity_revision: 1 });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toMatchObject({ expected_entity_revision: 1, expected_draft_revision: 2 });
    expect(confirmed).toMatchObject({ status: "confirmed", receiptCode: "COMMAND-1" });
    expect(authorization).toMatchObject({ authorizationToken: "one-time", tokenAvailable: true });
  });
});
