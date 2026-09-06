# nsearch Integration Blueprint for eqats

## Overview
The nsearch repository provides a C++ library and command-line tool for processing next-generation sequencing (NGS) data, including FASTA/FASTQ handling, read merging, error-based filtering, and sequence database search.

## Domain Mapping
- **Data Engines**: Raw data ingestion (FASTA/FASTQ), read merging, quality filtering, and support for compressed inputs.
- **Signal & Execution Logic**: Sequence database search can be viewed as a pattern‑matching signal generator; output formats (ALNOUT, CSV) represent actionable signals.
- **Risk Engineering**: Error‑based filtering acts as a risk control step, discarding low‑quality reads that could introduce noise.

## Feasibility Assessment
While the individual components are well‑engineered, their biological focus does not align with the financial‑time‑series orientation of eqats. The library expects nucleotide or amino‑acid sequences, operates on k‑mer‑style matching, and produces bio‑specific outputs. Adapting it to process price, volume, or alternative data would require substantial rewriting of core algorithms, negating the benefit of reuse.

## Integration Decision
Given the mismatch, a direct binding via PyO3 or Rust FFI would yield little value and increase maintenance burden. Instead, eqats should continue to use domain‑specific data engines (e.g., CSV/Parquet ingest, tick‑data processors) and signal libraries tailored to financial markets.

## Recommendation
If alternative data sources ever include genomic‑style sequences (e.g., CRISPR‑related equity signals), revisit this assessment. For now, no integration effort is warranted.