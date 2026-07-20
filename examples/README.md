# Synthetic examples

本目录只描述不依赖网络、API密钥或真实公司材料的演示。

## 完整离线闭环

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe scripts\offline_demo.py .\.demo_run\offline
.\.venv\Scripts\research-flow.exe verify-release .\.demo_run\offline\release-v1
```

Linux或macOS：

```bash
./.venv/bin/python scripts/offline_demo.py ./.demo_run/offline
./.venv/bin/research-flow verify-release ./.demo_run/offline/release-v1
```

演示覆盖：

```text
synthetic DocumentRecord
→ exact-bound EvidenceCard
→ review_pack.json
→ admitted EvidenceRecord
→ ResearchBrief
→ compiled context
→ synthetic report
→ frozen release
→ SHA-256 verification
```

## 配置模板

复制`configs/example.yaml`，替换研究问题、范围、域名和`seed_urls`后再运行
真实采集。模板中的`example.com`地址是占位符，不是可用于研究的资料。
