# Task 7 Kaggle training operations

This runbook wraps the frozen Task 7 trainer without changing the model,
adapter, taxonomy, splits, initialization, or acceptance criteria. Generated
checkpoints, logs, locks, and backup state remain under `/kaggle/working` and
must not be committed.

## Safe migration from the active legacy session

Do not replace or stop the currently running process merely to adopt this
workflow. Let its existing backup worker publish and verify the next monotonic
checkpoint. Before the next Kaggle session:

1. Confirm the private dataset `siddarthareddyc/takeoff-task7-durable-checkpoints`
   contains the newest expected `optimizer_updates` and SHA-256.
2. Attach that private dataset read-only to the new notebook.
3. Copy neither checkpoint nor input dataset in place. Point `--resume` at the
   verified read-only checkpoint and use a fresh `/kaggle/working` output.
4. Start the backup worker, then the launcher. The launcher refuses a duplicate
   live PID, a mismatched run ID, or a checkpoint older than its local/verified
   backup state.
5. Keep `--num-workers 0` on Kaggle unless a bounded test proves workers safe.

## Commands

Set these shell variables in the notebook to the already validated paths:

```bash
export PYTHONPATH="$BACKEND"
export OUTPUT=/kaggle/working/takeoff-training/swiss-dwellings-rooms-maskrcnn-r50fpnv2-task7-bounded-v1
export BACKUP_STATE=/kaggle/working/task7-backup-state.json
export RECOVERY_CHECKPOINT=/kaggle/input/datasets/siddarthareddyc/takeoff-task7-durable-checkpoints/checkpoint-progress.pt
export RECOVERY_SHA256=f798c447bf24293f27a14fec3f951e6962445dd863716421b2ed98db8167ee26
```

The currently accessible recovery artifact is expected to report epoch `0`,
`next_batch_index=1216`, `optimizer_attempts=304`,
`optimizer_updates=301`, `skipped_optimizer_updates=3`, and
`epoch_complete=false`. These values are evidence for this artifact only; the
preflight still fails closed if the attached durable dataset contains a newer
checkpoint or if any value conflicts with the immutable file contents.

Start checkpoint publishing in one cell. It publishes only atomic checkpoint
files, retries transient CLI failures, refuses a regression relative to the
last verified state, downloads the published checkpoint, and records state
only after SHA-256 equality:

```bash
python -m ml.training.maskrcnn_task7_ops backup \
  --checkpoint "$OUTPUT/checkpoint-progress.pt" \
  --dataset siddarthareddyc/takeoff-task7-durable-checkpoints \
  --state "$BACKUP_STATE" --poll-seconds 60
```

First run the read-only resume preflight. It checks the immutable checkpoint
hash, run identity, newest local and durable-remote positions, model,
optimizer, scheduler, AMP scaler and RNG state, and the exact deterministic
mid-epoch cursor. A successful check reports `next_batch_index_zero_based` and
`next_display_batch` without creating a trainer process:

```bash
python -m ml.training.maskrcnn_task7_ops validate-resume \
  --config "$CONFIG" --output "$OUTPUT" \
  --resume "$RECOVERY_CHECKPOINT" --resume-sha256 "$RECOVERY_SHA256" \
  --backup-state "$BACKUP_STATE" \
  --remote-dataset siddarthareddyc/takeoff-task7-durable-checkpoints
```

Only after that command returns `"status": "PASS"`, start or resume training
in a separate cell with the same checkpoint and SHA-256:

```bash
python -m ml.training.maskrcnn_task7_ops launch \
  --backend "$BACKEND" --config "$CONFIG" --adapter-root "$ADAPTER" \
  --initialization "$INITIALIZATION" --output "$OUTPUT" \
  --resume "$RECOVERY_CHECKPOINT" --backup-state "$BACKUP_STATE" \
  --resume-sha256 "$RECOVERY_SHA256" \
  --remote-dataset siddarthareddyc/takeoff-task7-durable-checkpoints \
  --num-workers 0 --heartbeat-every-batches 10 \
  --checkpoint-every-optimizer-updates 50
```

Status is read-only:

```bash
python -m ml.training.maskrcnn_task7_ops status \
  --output "$OUTPUT" --config "$CONFIG" --backup-state "$BACKUP_STATE"
```

It reports epoch, batch, optimizer updates, recent throughput, approximate ETA,
checkpoint age, and the latest verified backup record.

## Safe interruption and resume

Request a cooperative stop before Kaggle limits or quota exhaustion:

```bash
python -m ml.training.maskrcnn_task7_ops stop --output "$OUTPUT"
```

The trainer notices the marker only at an optimizer boundary, atomically writes
`checkpoint-progress.pt` with `epoch_complete=false` and the next batch index,
then exits. Wait for `interrupted_checkpoint_complete`, and wait for the backup
worker's `checkpoint_backup_verified` event before ending the session. Resume
only from that verified artifact. Never omit `--resume` from the operations
launcher; it deliberately has no initialization-only training mode.

If backup verification fails, preserve the local checkpoint and retry. Do not
publish an older checkpoint or manually replace the private dataset contents.
