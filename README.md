# clawdia-shared
Shareable repo for Clawdia agent jobs and skills

# clawdia
A repo for Clawdia (Openclaw agent) and other Openclaw friends we may create along the way. Contains shareable 
jobs and skills, as well as a template for Clawdia's identity and workspace files that can be synced with the live agent.


# Clawdia Agent

Personal AI assistant running on OpenClaw 2026.6.5 via DeepSeek V4 Pro.
To replicate or learn from Clawdia, build your own OpenClaw agent (follow setup guides from OpenClaw), then add selected 
cron jobs and scripts from this repo to add scheduled tasks and skills to your agent. 
Use the file `./scripts/sync-from-workspace.sh` if you want to set up a synchronisation between your Git repo and the agent.
This will give you a ready-made template for a household assistant agent, which you can customize further with your own 
skills and cron jobs.

## Purpose 
Clawdia is a versatile 'personal assistant' agent tasked with helping our household with a range of administrative,
research and organisational tasks. The goal is to create a replicable template for a handy 'household helper' agent
for busy working families that can help uplift learning and efficiency, and reduce cognitive load. 
This is an experiment by a tired parent who can't do it all - as such, there may be deficits in
code quality or structural efficiency. Best efforts made! 

## Template Identity Files 
The files in identity/ are a template for the identity files used by the agent. They need customisation to deploy to an 
agent. You can customize these with your own details, preferences, and context to create a personalized agent identity.
More detail is better, but be clear and concise. The more the agent understands about its user and context, the better 
it can assist.

## Structure

- `identity/` — Clawdia's identity files (AGENTS, SOUL, IDENTITY, USER, MEMORY)
- `skills/` — Custom skills (grocery-manager, taskflow, etc)
- `cron-jobs/` — Scheduled task configurations and prompts for rcurring tasks 
- `skills/` —  Specific skills that Clawdia can use via Telegram to assist user 

## Maintenance
 
- Sync files from live workspace: `./scripts/sync-from-workspace.sh`
- Sync files to live workspace: `./scripts/sync-to-workspace.sh` (be careful with this one - it will overwrite files in 
- the workspace with what's in the repo, so make sure to pull any changes from the workspace before running)
