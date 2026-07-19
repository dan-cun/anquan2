# Prompt candidates

`zh-CN/` contains the first five localized candidates for review:

- `primary_agent`
- `generator`
- `reporter`
- `language_chooser`
- `graphiti.agent_response`

The manifest marks these files as `candidate-only`. They are not loaded by the
default runtime resolver yet. Promote a candidate only after semantic review,
provider A/B checks, and a run-level regression test.
