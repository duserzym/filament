# Database-backed recalculation

This phase builds local, deterministic reduction inputs and a two-engine hand-off.
Filament reduces acquisitions to per-fraction ratios, uncertainties and correlations;
IDTIMS_UPbRPy reads `idtims-fractions/1` and calculates dates. Neither app writes to
UPbDB or UPb Lab in this phase. The storage, synchronization and review below are
proposals, not deployed services.

## Store evidence and immutable revisions in UPbDB (proposed)

Store the `.raw` directory as a content-addressed bundle: a canonical manifest of
relative names, byte lengths and SHA-256 digests, with the manifest's digest as the
bundle identity. Store each original `.xls` and legacy `.trip` as a separate blob.
Keep original bytes and paths/names as metadata; never replace an original blob
with a rewritten file. Validate hashes on upload/download. Identical blobs dedupe
within the authorized storage boundary; access remains governed by lab membership.

A reduction revision references those blobs, an immutable parameter-set record
(schema name/version, exact canonical JSON and SHA-256), the saved masks and session
history, and pinned app/engine versions. Store the resulting contract row: fraction
identity, measured ratios, 1σ %SE, rho, oxide law, route and provenance. Retain warnings
such as a duplicated workbook terminal row or a cycle-level dead-time approximation.
The local session already saves versioned parameters and undoable changes; a raw
reduction records acquisition-file hashes and refuses replay against changed inputs.

An age-calculation revision references the exact contract row hash, tracer name and
calibration version, physical constants version/hash, reduction settings, engine
version, diagnostic substitutions and resulting dates/uncertainties. Ratios and dates
are different records owned by their respective engines. A date's evidence chain is:

`date → age inputs/settings → contract row → parameter set + masks/history → raw blobs`.

Use stable fraction/run/revision IDs independent of filenames. A published row must
also identify its parent revision and the operator; server acceptance adds reviewer,
approval time and an explicit current-revision pointer. Local undo changes working
state, while accepted revisions remain immutable.

## Review in UPb Lab (proposed)

Show TIMS cycles, accepted/rejected points, reduced ratios and fraction dates together.
Resolve `Source Grain` and `Source Spot` through the existing plucked-grain records,
so a reviewer can inspect the TIMS fraction beside the LA-ICP-MS spot on the same
grain. Missing or ambiguous links require an explicit link decision; sample names
alone must not imply identity. Keep fraction pairing separate from grain/spot linking.

The review view should compare revisions: changed parameters, masks, ratios, dates
and warnings, with links back to both source evidence and the exact engine versions.
Propose that lab members may create drafts, designated lab reviewers may approve a
current revision, and administrators manage those roles. Cross-lab approval policy
and whether independent review is mandatory need agreement before implementation.
An approval covers a particular revision hash, not a moving fraction record.

## Recalculate without overwriting evidence (built locally; database flow proposed)

A dead-time edit creates a new parameter hash and reduction revision. It invalidates
cached Pb intensity/functions, ratio statistics/correlations, the fraction contract
row and every dependent date/report. U acquisition reduction remains reusable when
only Pb dead time changes; the paired contract row and age calculation still acquire
new revisions. A mask change invalidates the affected statistics and dates, without
changing acquisition decoding. A tracer, blank, fractionation, common-Pb, Th/U or
physical-constant edit invalidates age results, while measured ratios remain valid.
Changing grain/spot identity invalidates the linking/review context, even if numerical
results stay the same. Previous approvals remain historical; derived drafts cannot
inherit current approval automatically.

Determinism requires pinned source bytes, engine/runtime/dependency versions,
conversion constants, canonical parameter/settings JSON, row correspondence and
mask history. Hash numerical results using repr-roundtrip floats and a fixed encoding;
exclude wall-clock export times or pin them explicitly. Record route-specific
numerical tolerances for vendor comparisons separately from bit-identical reruns of
the same engine. Unknown acquisition methods must fail or record an explicit workbook
fallback; they must not silently claim per-acquisition reduction.

## Mirror mode and scale (proposed)

Keep a local content-addressed blob store plus a paged metadata/index cache. Apps edit
locally first and append immutable drafts to an outbox; background synchronization
uploads missing blobs in batches, then manifests/revisions transactionally. Retries
use revision hashes as idempotency keys. Concurrent edits create branches; updating
the current pointer uses an expected-parent check, and conflicts require reconciliation.
Offline review may be a local draft; server approval is valid only after hash/role
checks. Show sync state and unavailable evidence clearly.

Many labs/runs require batched metadata queries and uploads, paged run/fraction lists,
chunked large blobs, content-addressed dedupe, and hash-indexed dependency lookups.
Fetch cycle arrays as a bundle for the selected run; never make one request per cycle.
Cache derived arrays by input + engine hash and evict/recompute them independently of
irreplaceable raw blobs. Authorization applies to each lab's manifests and references,
including deduplicated data. No server, schema migration or remote write is part of
this phase.
