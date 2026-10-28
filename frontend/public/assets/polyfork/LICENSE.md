# Polyfork assets

The models in this folder come from [Polyfork](https://polyfork.dev) and are fetched by
`frontend/scripts/fetch-polyfork-assets.mjs` from the pinned list in `src/lib/world/asset-manifest.json`.

Licence (per asset, see the `license` field in the manifest): use in commercial projects, no attribution,
**no redistribution of the files themselves**. Full terms: https://polyfork.dev/licensing

That is why the files are gitignored: only the manifest (ids and sha256 hashes) is committed.
Character animation clips are baked from Mixamo and are only served by Polyfork's CDN; they are loaded at runtime.
