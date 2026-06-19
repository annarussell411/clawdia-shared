#!/bin/bash
PROMPT_FILE=~/personal-projects/clawdia/cron-jobs/morning-digest-prompt.md
PROMPT=$(cat "$PROMPT_FILE")
openclaw cron edit 16c48b00-559f-4bc7-9c9b-2c7120d83e00 --message "$PROMPT"
echo "Morning digest prompt updated"
