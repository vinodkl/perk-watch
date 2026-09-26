# PerkWatch V2 Phase 7: Local tracing and monitoring

Trace both offline data preparation (including RAG embedding builds) and agent questions without retaining private content or adding a hosted tracing provider. See [PerkWatch V2 design](perk-watch-v2-design.md).

## Goal

One local trace ID per preparation run or question ties its steps and final outcome together. A small command shows recent failures, retries, skipped work, and slow steps. Traces are diagnostics, not conversation memory or a source of benefit facts.

## Plan

1. Generate a random `trace_id` for each `prepare_data.py` run and each `app.answer(question)` call. Append JSONL events under `PERKWATCH_DATA_DIR/prepared/traces/`, never under a tracked evaluation folder. Use the same small event format for both paths; keep the existing preparation report and evaluation metrics rather than replacing them.
2. Emit allowlisted events with UTC timestamp, `trace_id`, sequence number, run kind (`prepare` or `answer`), event name, elapsed milliseconds (monotonic clock), and outcome. Include only relevant safe metadata: card ID, stage, processed/skipped counts, embedding model and batch size, tool name, retry count, and token count when supplied by a provider. Record fixed error categories, not exception text. Print the trace ID in each CLI command's output or stderr.
3. Trace the existing preparation stages in `prepare/run.py`: source discovery, benefit extraction/validation, transaction import/deduplication, merchant matching, community filtering, SQLite replacement, benefit and community embedding builds, commit, and report writing. For each stage record duration, counts, skipped reason category, and failure outcome. Preserve the current policy for skipped bad source files; a fatal failure should be visible without falsely reporting a successful prepare or changing commit behavior.
4. For RAG setup, distinguish embedding disabled (no provider), zero rows, provider batch attempts, successful vector counts, response-length/index validation errors, and SQLite write failures. Instrument the batch boundary in `OpenAIEmbeddingProvider.embed` and the two build calls in `prepare/rag_search_index.py`; log model name, number of input rows, batch count, duration, and provider usage only if returned. Never record input text, vectors, hashes, or raw provider responses.
5. Trace agent `answer_started`, `model_call_finished`, `tool_attempt_finished`, `selection_checked`, and `answer_finished`, including rejected inputs, repeated calls, provider failures, fallback selection, retry exhaustion, and call-limit exits. Keep the existing tool-result callback and metrics. If memory is added later, trace read/write outcomes, not stored values.
6. Add `scripts/show_traces.py` to summarize recent preparation and answer runs, failures, skips, retries, and slow steps by trace ID. JSONL remains readable with standard command-line tools; no dashboard or background process is required. Keep files bounded with a documented retention period and a local deletion path.
7. Exercise a repeatable preparation run (including embedding enabled and disabled) and representative agent evaluation cases. Confirm traces explain failures without changing answers, stored data, or preparation output. Consider Braintrust only later, if local inspection is inadequate and separate approval is given for any outbound trace data.

## Privacy and reliability

- Use an explicit field allowlist. Never log questions, prompts, model responses, full tool arguments or results, transaction IDs/rows, source paths or IDs, source excerpts, merchant descriptions, credentials, embedding text/vectors, raw exceptions, or hidden model reasoning. The outbound PII redactor is not sufficient for logs because it deliberately preserves amounts and merchant names.
- Keep trace files ignored by git and local to `PERKWATCH_DATA_DIR`. Set restrictive file permissions where supported; do not use shared temporary directories. Do not send traces to Braintrust or another service by default.
- A trace-write failure must not change the answer or preparation result; surface a brief diagnostic warning without leaking data. Avoid duplicate final events and ensure failure/limit exits still record an outcome when writing is available.

## Done when

- Every CLI question and preparation run has a trace ID, ordered events, and a final outcome, including failure and call-limit exits.
- Preparation traces show stage counts and timings, whether embedding was disabled or built, provider batch results, and failures without exposing text or vectors. Repeated imports remain repeatable and the existing report remains intact.
- The local summary shows preparation and answer failures, skips, retries, and slow steps without accessing raw card records.
- Tests with sensitive benefit text, transaction descriptions, tool payloads, provider responses, and exception messages confirm none appear in the JSONL file or summary; disabled or failed tracing leaves answers and prepared data unchanged.
- The local-data guard and full test suite pass. No real trace or generated output is committed.

## Depends on

[Phase 5: Evaluation and search improvements](perk-watch-v2-phase-5-evaluation.md). This phase can run independently of [Phase 6: Jev experiments](perk-watch-v2-phase-6-jev-experiments.md).
