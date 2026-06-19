cat > sync-identity-from-workspace.sh << 'EOF'
#!/bin/bash
# Pull identity files from live workspace to repo (capture Clawdia's autonomous edits)
cp ~/.openclaw/workspace/IDENTITY.md ~/personal-projects/clawdia-agent/identity/
cp ~/.openclaw/workspace/SOUL.md ~/personal-projects/clawdia-agent/identity/
cp ~/.openclaw/workspace/AGENTS.md ~/personal-projects/clawdia-agent/identity/
cp ~/.openclaw/workspace/MEMORY.md ~/personal-projects/clawdia-agent/identity/
cp ~/.openclaw/workspace/USER.md ~/personal-projects/clawdia-agent/identity/
cp ~/.openclaw/workspace/TOOLS.md ~/personal-projects/clawdia-agent/identity/
echo "Identity files synced from workspace"
EOF
chmod +x sync-identity-from-workspace.sh