# Post-Eval Prompt & Metrics Fixes — Design Document

**Date**: 2026-02-18
**Status**: Approved

## Problem

First eval run (90% refusal accuracy, 100% retrieval recall) revealed three issues:

1. **Language inconsistency** — LLM sometimes responds in English despite German questions and German source documents
2. **False refusals** — Q5 (Provider A Netzkostenbeitrag) and Q7 (Batteriemodule max.) were incorrectly refused despite correct chunks being retrieved. The refusal instruction is too conservative.
3. **German refusal detection gap** — Q8 hedged in German ("nicht genug Informationen") but the eval metric only checks English refusal phrases, so it wasn't caught.

## Changes

### 1. German language instruction (`app/generation/prompts.py`)

- Add explicit rule: always respond in German
- Change the refusal phrase template to German

### 2. Reduce false refusals (`app/generation/prompts.py`)

- Reword refusal instruction from "refuse when not confident" to "refuse only when context contains no relevant information"
- Encourage using partial/related information with noted limitations

### 3. German-aware refusal detection (`eval/metrics.py`)

- Add German refusal phrases to the detection list
