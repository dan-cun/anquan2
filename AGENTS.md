# Change Provenance Contract

After every source, configuration, Prompt, model, tool, image, or deployment change in this
repository, record and display all of the following in the final handoff:

1. Git commit: full HEAD SHA and short SHA.
2. Dirty state: `clean` or `dirty`, plus the changed-path count when dirty.
3. Image digest: immutable digest or image ID for every image built or deployed by the change.
4. Prompt version: active Prompt count and a canonical SHA256 over sorted
   `(prompt_key, version, checksum, source)` records. List individually changed Prompts.
5. Model configuration version: provider, model, base URL, configured flags, and a canonical
   SHA256 over those non-secret fields.
6. Tool version: tool count, per-tool declared version when available, and a canonical SHA256
   over sorted public tool definitions.

Never record API keys, tokens, credential values, secret headers, or raw environment secrets.
For a field that cannot be read, write `unavailable` and state the concrete reason; do not omit it.

When a benchmark or deployment image is involved, collect Prompt, model, and tool provenance from
that running image rather than assuming the source worktree matches it. Report source and running
image provenance separately when they differ.
