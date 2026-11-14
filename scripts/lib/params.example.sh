#!/usr/bin/env bash
# Settings of this deployment that are its own and no secret. ./scripts/init-env.sh copies this
# file to lib/params.sh (gitignored); fill it in there. Every line is a plain export KEY="value":
# the scripts source the file, and the agent started on the host reads it too.

# Required: provider:model of the chat model, for the provider anthropic or openai. Fill in by
# hand, e.g. anthropic:claude-sonnet-5-5.
export LLM_MODEL=""

# Required: the OAuth client ID of the page's Sign in with Google button, which every ID token
# must name as its audience. Fill in by hand (docs/sign-in.md).
export GOOGLE_CLIENT_ID=""

# Optional: JSON object from a person's lowercase email to the limit that replaces
# AGENT_TURN_LIMIT of stack-params.sh for them.
# export AGENT_TURN_LIMIT_OVERRIDES='{"person@example.com": 50}'

# Optional: the address the README and NOTICE give for a commercial license. Tracked files may
# show this address; the pre-commit hook refuses any other address of this file.
export LICENSE_CONTACT=""
