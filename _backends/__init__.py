# Provider backends for the Aletheia runner. Each module is single-provider
# (one SDK, no mixing): it exposes API_KEY_VAR, default_model(), make_client(),
# and stream_reply(client, system, messages, model, max_tokens) yielding text.
