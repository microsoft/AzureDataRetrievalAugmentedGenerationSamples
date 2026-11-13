# Original synthetic fixtures

Run `python scripts/make-fixtures.py` from the sample root to materialize
`movies.synthetic.json`. The generator contains all fixture content and uses no
network or embedding service. The generated file can be distributed with this sample.

The three short movie descriptions and titles are original sample content under
the repository MIT license. IDs are stable. Embeddings are 1536-dimensional
orthogonal unit vectors, stored as ordinary arrays of numbers.

These are preembedded schema and integration fixtures, not meaningful language
embeddings. Query vector `[1, 0, ..., 0]` targets `synthetic-orbit-rescue`.
Only this exact deterministic vector, not an OpenAI-generated query, is suitable
for checking their vector ordering. Full-text search and semantic reranking use
the actual original text. Do not interpret fixture vector results as semantic
embedding-quality evidence.
