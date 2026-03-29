# Git-remote (ensimmäinen push)

Julkinen GitHub-repo tälle projektille: **[Kiiskil/DataBank-MCP](https://github.com/Kiiskil/DataBank-MCP)** (`https://github.com/Kiiskil/DataBank-MCP.git`).

Kun et ole vielä liittänyt paikallista repoa etärepoon:

1. Varmista että GitHubissa on repo (tyhjänä tai sisällöllä).
2. Paikallisesti:

```bash
cd /polku/datapankki-mcp
git init
git branch -m main
git add -A
git commit -m "Initial: datapankki-MCP (ZT-RAG)"
git remote add origin git@github.com:Kiiskil/DataBank-MCP.git
# tai HTTPS:
# git remote add origin https://github.com/Kiiskil/DataBank-MCP.git
git push -u origin main
```

**Coder-MCP-server** -repo viittaa tähän erillisenä projektina; ei git submodule -tilaa oletuksena.
