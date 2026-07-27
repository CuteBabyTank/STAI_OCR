# Statement-Format Decision

## Verified implementation scope

The reconciliation import path accepts UTF-8/UTF-8-with-BOM CSV transaction
text. The API reads an uploaded file as `utf-8-sig` text and passes it to the CSV
statement importer; the reconciliation module parses CSV rows into transactions.
It does not currently provide a statement-PDF table/text extractor or a
statement-image OCR-to-transaction path.

| Input type | Current status | Meaning for the benchmark |
| --- | --- | --- |
| CSV transaction ingestion | Implemented | A structured statement export with the expected columns can be imported and reconciled. This is the supported proof-of-concept statement input. |
| Text/table extraction from statement PDFs | Not implemented in reconciliation ingestion | A PDF may contain extractable text or tables, but the repository does not turn that document into validated reconciliation transactions. |
| OCR of statement images | Not implemented in reconciliation ingestion | Receipt OCR support does not imply statement-image OCR or validated transaction extraction. |

## Recommendation

Use **CSV as the explicitly scoped proof-of-concept input** for the final
experiment, while asking the instructor whether structured CSV statement exports
are acceptable for the project claim. This is preferable to implicitly treating
receipt extraction support as statement-PDF/image support.

If the instructor requires native statement PDFs or images, select either:

1. add and validate a PDF/image statement extractor before the final experiment;
   or
2. convert synthetic PDF/image statements into a separately validated structured
   representation, then score reconciliation from that representation as a
   distinct pipeline stage.

Do not implement a new PDF/image statement parser during Stage 2. Any later
conversion must preserve source hashes, document validation, and clearly state
that reconciliation is evaluated on the structured representation rather than on
unvalidated PDF/image extraction.
