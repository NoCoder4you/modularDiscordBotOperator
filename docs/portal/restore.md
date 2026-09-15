# Restore and recovery runbook

## Normal workflow

Open the authorized bot's backup detail, choose **Preview restore**, review compatibility, resource
revision summaries, conflicts and restart requirements, then explicitly confirm. Never treat a
preview as durable: live revision or verified process-instance changes invalidate it. A successful
configuration restore may report that a restart is required; it never performs that restart.
Operators must separately hold the relevant lifecycle grant and invoke the existing supervisor flow.

## Recovery conditions

* **Corrupt backup:** do not retry restore. Keep the record for incident review, select another
  verified catalog backup, and investigate storage health through approved host operations.
* **Failed restore, rollback succeeded:** live data was returned using the internal safety snapshot.
  Review the correlated operation/request audit IDs, resolve the adapter/storage fault, and make a
  fresh preview before retrying.
* **Failed restore and rollback failed:** treat `manual_recovery_required` as a high-severity
  incident. Prevent further portal mutations for that bot, preserve audit IDs, use the most recent
  internal safety record through an approved platform recovery procedure, validate the typed
  resource, and only then restore service. Do not edit arbitrary files through the portal.
* **Disk full:** free capacity using approved host retention/operations. Failed staging directories
  are not catalogued; existing valid records remain. Retry only after capacity is confirmed.
* **Catalog corruption:** records fail closed rather than arbitrary directories becoming visible.
  Preserve the root and rebuild a catalog only with a future approved verifier/maintenance tool;
  Stage 14 intentionally has no browser repair endpoint.
* **Unsupported old/future format:** retain it for offline migration analysis. Do not modify its
  manifest or guess a layout. A typed migration belongs in a later reviewed stage.
* **Process restart during restore:** confirmation rejects the preview. Wait for canonical health to
  reconcile, then create a fresh preview. Restore permission never authorizes stop/start/restart.

Remaining risk is limited recovery tooling: catalog rebuild and schema migrations are intentionally
deferred, as are SQLite support and plans for resources whose Stage 13 ownership remains unresolved.
Remote/cloud targets, imports/downloads, scheduling UI, and manual deletion require separate threat
models and are recommended future scope only after typed resource coverage expands.
