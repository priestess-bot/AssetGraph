import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, queryString, requestJson } from "../workbench/api";

const ROOT = "/api/releases";

export interface ReleaseSummary {
  releaseCode: string;
  subjectType: string;
  subjectCode: string;
  subjectRevision: number;
  carrierKind: string;
  status: string;
  manifestCode: string;
  manifestFingerprint: string;
  deliveryCount: number;
  createdAt?: string;
  updatedAt?: string;
}

export interface ReleaseDetail extends ReleaseSummary {
  releaseFingerprint: string;
  manifest: {
    manifestCode: string;
    revisionNumber: number;
    manifestFingerprint: string;
    subjectRefs: Record<string, unknown>;
    artifactRefs: Array<Record<string, unknown>>;
    rightsSnapshot: Record<string, unknown>;
    qualitySnapshot: Record<string, unknown>;
    lineageSnapshot: Record<string, unknown>;
    carrierFacet: Record<string, unknown>;
    createdAt?: string;
  };
  approvals: Array<{ approvalCode: string; decision: string; decidedBy: string; decidedAt?: string; structuredReason: Record<string, unknown>; approvedScope: Record<string, unknown> }>;
  deliveries: Array<{ deliveryCode: string; status: string; targetType: string; targetId: string; adapterType: string; externalIdentity: Record<string, unknown>; readbackEvidence: Record<string, unknown>; errorCode?: string; createdAt?: string; completedAt?: string }>;
}

function object(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function summary(value: unknown): ReleaseSummary {
  if (!isRecord(value)) throw new Error("发布记录响应无效");
  const releaseCode = asString(value.release_code);
  if (!releaseCode) throw new Error("发布记录缺少编码");
  return {
    releaseCode,
    subjectType: asString(value.subject_type),
    subjectCode: asString(value.subject_code),
    subjectRevision: asNumber(value.subject_revision),
    carrierKind: asString(value.carrier_kind),
    status: asString(value.status),
    manifestCode: asString(value.manifest_code),
    manifestFingerprint: asString(value.manifest_fingerprint),
    deliveryCount: asNumber(value.delivery_count),
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
  };
}

function detail(value: unknown): ReleaseDetail {
  const base = summary(value);
  if (!isRecord(value)) throw new Error("发布详情响应无效");
  const manifest = object(value.manifest);
  return {
    ...base,
    releaseFingerprint: asString(value.release_fingerprint),
    manifest: {
      manifestCode: asString(manifest.manifest_code),
      revisionNumber: asNumber(manifest.revision_number),
      manifestFingerprint: asString(manifest.manifest_fingerprint),
      subjectRefs: object(manifest.subject_refs),
      artifactRefs: asArray(manifest.artifact_refs).filter(isRecord),
      rightsSnapshot: object(manifest.rights_snapshot),
      qualitySnapshot: object(manifest.quality_snapshot),
      lineageSnapshot: object(manifest.lineage_snapshot),
      carrierFacet: object(manifest.carrier_facet),
      createdAt: asOptionalString(manifest.created_at),
    },
    approvals: asArray(value.approvals).flatMap((row) => isRecord(row) ? [{
      approvalCode: asString(row.approval_code), decision: asString(row.decision), decidedBy: asString(row.decided_by), decidedAt: asOptionalString(row.decided_at), structuredReason: object(row.structured_reason), approvedScope: object(row.approved_scope),
    }] : []),
    deliveries: asArray(value.deliveries).flatMap((row) => isRecord(row) ? [{
      deliveryCode: asString(row.delivery_code), status: asString(row.status), targetType: asString(row.target_type), targetId: asString(row.target_id), adapterType: asString(row.adapter_type), externalIdentity: object(row.external_identity), readbackEvidence: object(row.readback_evidence), errorCode: asOptionalString(row.error_code), createdAt: asOptionalString(row.created_at), completedAt: asOptionalString(row.completed_at),
    }] : []),
  };
}

export const releasesApi = {
  list: (projectCode?: string) => {
    const scopedProjectCode = projectCode?.trim();
    const url = `${ROOT}${queryString({ project_code: scopedProjectCode })}`;
    return requestJson<unknown[]>(url).then((rows) => rows.map(summary));
  },
  get: (releaseCode: string) => requestJson<unknown>(`${ROOT}/${encodeURIComponent(releaseCode)}`).then(detail),
  validate: (releaseCode: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(releaseCode)}/validate`, { actor: "functional-operator" }).then(detail),
  prepareDeliveryPackage: (releaseCode: string, targetName: string, idempotencyKey: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(releaseCode)}/delivery-packages`, { actor: "functional-operator", target_name: targetName, idempotency_key: idempotencyKey }).then(detail),
  deliveryPackageUrl: (releaseCode: string) => `${ROOT}/${encodeURIComponent(releaseCode)}/delivery-package`,
  revoke: (releaseCode: string, reason: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(releaseCode)}/revoke`, { actor: "functional-operator", reason }).then(detail),
};
