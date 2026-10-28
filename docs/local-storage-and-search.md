# Local file storage and GeoServer search

## Files and PostGIS

Uploaded files and generated artifacts use `LOCAL_UPLOAD_DIR` (default `./uploads`).
`store_file` and `store_file_stream` return a unique ID and a URL under
`BASE_URL/api/stream/`. Streamed uploads enforce `MAX_FILE_SIZE` and remove partial
files on failure. Metadata includes size and SHA256. The file streaming API keeps
compression and range requests; legacy `/uploads/` URLs remain supported.

PostGIS remains the spatial data store. `DATABASE_URL`, `GEODATA_DATABASE_URL`,
layer import/export, and generated geoprocessing results retain their existing roles.

For Docker deployments, persist uploads and the vector database with volumes or
bind mounts. Data in a container's writable layer does not survive container
replacement. Preserve existing uploads before recreating a container.
`BASE_URL` must be reachable by the browser.

## Local vector retrieval

```dotenv
EMBEDDING_PROVIDER=hashing
USE_OPENAI_EMBEDDINGS=false
NALAMAP_GEOSERVER_VECTOR_DB=./data/geoserver_vectors.db
NALAMAP_GEOSERVER_EMBEDDING_FACTORY=
```

These defaults are explicit in the shared environment template and apply to both
local and external deployment profiles. No separate retrieval switch is required.
Add a GeoServer backend in Settings and wait for metadata preloading before
searching. Retrieval runs locally on that index; fetching source data can still
require network access. Dynamic tool selection is a separate, unchanged setting.

Hashing runs locally without API keys or downloaded model weights. It uses lexical
features, n-grams and weighting to compare queries with GeoServer metadata. It is
not a trained semantic model. SQLite with sqlite-vec stores the vectors locally;
if the extension cannot load, retrieval falls back to an in-memory store, which
does not persist across restarts.

## Optional local semantic embeddings

`NALAMAP_GEOSERVER_EMBEDDING_FACTORY=module:create_embeddings` can replace hashing
with a local model. The no-argument factory must return a
`langchain_core.embeddings.Embeddings` implementation with `embed_documents(texts)`
and `embed_query(text)`. The factory takes priority over built-in providers.
Install and configure any local model runtime/weights separately; no new model
dependency is introduced by this cleanup.

Selection order: custom factory, optional existing OpenAI embeddings, then hashing.
Keep `USE_OPENAI_EMBEDDINGS` unset/false for local-only operation. A custom factory
must load local weights or call a local service for offline use.

Changing embedding models requires rebuilding the index because dimensions and
vector spaces can differ. Back up the old database, select a new database path,
and reload GeoServer metadata. Do not mix vectors from different models.

## Deploying source changes

The production Compose backend copies source into its image. Editing source or
restarting an old container does not rebuild the image. After preserving uploads,
rebuild/recreate the backend and Nginx as appropriate, then refresh the browser.
