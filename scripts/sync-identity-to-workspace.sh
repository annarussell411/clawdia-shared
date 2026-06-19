cat > sync-identity-to-workspace.sh << 'EOF'
#!/bin/bash
# Push identity files from repo to live OpenClaw workspace
cp ~/personal-projects/clawdia-agent/identity/*.md ~/.openclaw/workspace/
echo "Identity files synced to workspace"
EOF
chmod +x sync-identity-to-workspace.sh