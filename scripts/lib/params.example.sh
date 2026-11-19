#!/usr/bin/env bash
# Settings of this deployment that are its own and no secret. ./scripts/init-env.sh copies this
# file to lib/params.sh (gitignored); fill it in there. Every line is a plain export KEY="value":
# the scripts source the file, and the agent started on the host reads it too.

# Required: provider:model of the chat model, for the provider anthropic or openai. Fill in by
# hand, e.g. anthropic:claude-sonnet-5-5.
export LLM_MODEL=""

# Optional: provider:model of a stronger model, of LLM_MODEL's provider since it calls with the
# same LLM_API_KEY. A person listed in LLM_RETRY_EMAILS who sends "נסה שוב, אח שלי" (commas,
# periods, exclamation and question marks ignored) gets their last other message answered again
# by it, over the whole conversation; the old reply stays.
# export LLM_RETRY_MODEL="openai:gpt-6.2-astra"
# Optional, with LLM_RETRY_MODEL: JSON list of the lowercase emails allowed the retry phrase.
# export LLM_RETRY_EMAILS='["person@example.com"]'

# Required: the OAuth client ID of the page's Sign in with Google button, which every ID token
# must name as its audience. Fill in by hand (docs/sign-in.md).
export GOOGLE_CLIENT_ID=""

# Optional: JSON object from a person's lowercase email to the limit that replaces
# AGENT_TURN_LIMIT of stack-params.sh for them.
# export AGENT_TURN_LIMIT_OVERRIDES='{"person@example.com": 50}'

# Optional: the address the README and NOTICE give for a commercial license. Tracked files may
# show this address; the pre-commit hook refuses any other address of this file.
export LICENSE_CONTACT=""

# deploy.sh --ec2 only: the stack whose EC2 instance this repo's stack runs on. Blank: this
# repo's stack is a host, with an instance of its own. The host stack of another Docker Compose
# repo (its EC2_STACK): this repo's stack is a guest on that instance, which is deployed first,
# from its own repo, in the account and region of aws-config.sh.
export EC2_HOST_STACK=""
