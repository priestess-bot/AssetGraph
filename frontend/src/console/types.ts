import type { OperationalState, ProblemEvidence } from "../workbench/api";


export interface ConsoleSession {
  operatorId: string;
  roles: string[];
  authScheme: "bearer_memory";
}

export interface ConsoleSearchResult {
  entityType: string;
  entityCode: string;
  title: string;
  status: string;
  revision?: number;
  href: string;
  updatedAt: string;
}

export interface ConsoleTask {
  itemCode: string;
  itemType: "human_task" | "workflow_run";
  title: string;
  status: string;
  priority: number;
  summary: string;
  href: string;
  dueAt?: string;
  updatedAt: string;
  runCode: string;
  progressCompleted: number;
  progressTotal: number;
  ownerPrincipal?: string;
  claimedBy?: string;
}

export interface ConsoleNotification {
  notificationCode: string;
  state: Extract<OperationalState, "error" | "warning" | "reconcile_required">;
  title: string;
  summary: string;
  href: string;
  evidence: ProblemEvidence[];
  occurrenceCount: number;
  occurredAt: string;
  status: string;
}

export interface ConsoleEntityRevision {
  revision: number;
  status: string;
  schemaVersion: string;
  createdAt: string;
  createdBy?: string;
  fingerprint?: string;
  snapshot: Record<string, unknown>;
}

export interface ConsoleEntityRelation {
  relationType: string;
  entityType: string;
  entityCode: string;
  revision?: number;
  status?: string;
  href?: string;
  mappingQuality: string;
}

export interface ConsoleDiffChange {
  path: string;
  change: "added" | "removed" | "changed";
  before: unknown;
  after: unknown;
}

export interface ConsoleEntityDetail {
  entityType: string;
  entityCode: string;
  title: string;
  status: string;
  currentRevision: number;
  canonicalHref: string;
  sourceOfTruth: string;
  revisions: ConsoleEntityRevision[];
  diff: {
    fromRevision: number;
    toRevision: number;
    available: boolean;
    changes: ConsoleDiffChange[];
  };
  sources: ConsoleEntityRelation[];
  usedBy: ConsoleEntityRelation[];
}

export interface ConsoleDraft {
  draftCode: string;
  entityType: string;
  entityCode: string;
  draftKind: string;
  schemaVersion: string;
  draftRevision: number;
  baseEntityRevision: number;
  status: "active" | "consumed";
  document: Record<string, unknown>;
  contentFingerprint: string;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface ConsoleCommandResult {
  command: "confirm" | "publish" | "approve" | "reject" | "authorize";
  entityType: string;
  entityCode: string;
  entityRevision?: number;
  status: string;
  impact: string;
  receiptCode: string;
  replayed: boolean;
  draftRevision?: number;
  approvalCode?: string;
  authorizationCode?: string;
  authorizationToken?: string;
  tokenAvailable?: boolean;
  capability?: string;
  targetType?: string;
  targetId?: string;
  expiresAt?: string;
  layoutFidelity?: string;
  buildability?: string;
}
