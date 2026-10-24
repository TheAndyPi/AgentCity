#!/bin/sh
# Prefer the available bundled runtime; no machine-wide Node changes are needed.
set -eu
cd "$(dirname "$0")"
agentcity_node_bin="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
if [ -x "$agentcity_node_bin/node" ]; then
  PATH="$agentcity_node_bin:$PATH"
  export PATH
fi
if [ "$#" -eq 0 ]; then set -- run dev; fi
exec npm "$@"
