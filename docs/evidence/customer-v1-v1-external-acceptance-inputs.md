# Customer Experience v1 External Acceptance Inputs

Date: 2026-07-26
Updated: 2026-07-31

The implementation is not blocked on these inputs. They are collected here so
the product owner can provide one approved batch after all locally executable
work is complete. Secrets must be supplied through the runtime environment, not
committed to this repository.

The Maitu account, test room, and approved existing Maitu resources were
provided on 2026-07-31. Room `41172` completed read-only and mutation canaries;
`V1-0107`, `V1-0108`, `V1-0502`, `V1-0503`, and `V1-0506` are closed. Ordinary
image/video auto-upload was not exercised and remains `manual_only`. The normal
Console path also completed a `product_e2e` run through room inspection,
explicit reset, queue/worker execution and refreshed three-scene readback; see
`docs/evidence/live-room-41172-product-e2e-2026-07-31T14-48-54-818Z`.

## Input Batch

| Needed input | Minimum content | Checklist items unlocked |
| --- | --- | --- |
| Approved recording | One non-sensitive MP4/WebM recording with known source room and permission to analyze | `V1-0308` |
| Approved business brief | Product name, approved fact sources, target audience, required theme/story/design and prohibited claims | `V1-0412` |
| New operations user | A person who has not used the current interface and can spend one uninterrupted session | `V1-0803`, `V1-0804`, `V1-0808` |
| Optional Maitu upload samples | One ordinary image and one ordinary video that may be uploaded and deleted in the test account | Future promotion of `upload_image/upload_video` from `manual_only` |

## True-User Task Script

The participant receives the running product and the approved inputs, but not an
implementation guide. The observer may state the desired outcome only.

1. Find or import the four required materials, classify them, configure the
   product-on-table relation, and assemble a reusable selection.
2. Upload the recording, repair one transcript segment, and produce a reviewed
   single-source reference template.
3. Create approved facts and a content project, confirm the DesignBrief, select
   primary/secondary references, and reach a reviewable live-room plan.
4. Produce the local vertical video and review the Maitu BuildPlan. Automatic
   draft writing may be used only for the allowlisted offline room `41172` with
   the exact inspected title and explicit deletion confirmation; never click
   go-live.
5. Import the supplied operating file, resolve its mapping, inspect attribution,
   and create one operator-confirmed reproduction draft.

## Observation Record

For each task record start/end time, completion without intervention, error
count, backtracks, unclear labels, missing information, and every engineering
intervention. A task counts as successful only when its intended saved artifact
can be reopened from the Console. Screenshots must exclude secrets and personal
data.

## Maitu Canary Record

For each capability save the adapter contract fingerprint, account/environment
identifier, room ID/title, UTC timestamp, before screenshot/readback, exact
operation, after screenshot, refresh/reopen readback, result, and rollback. A
failed or incomplete record leaves the capability `manual_only`. Go-live must
remain false throughout the canary.
