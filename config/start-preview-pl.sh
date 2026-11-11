#!/usr/bin/env bash
set -euo pipefail
ln -sfn /run/preview/config.json /PrairieLearn/config.json
exec /PrairieLearn/scripts/init.sh
