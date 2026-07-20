# 专业研究可追溯证据管线与AI工作流评估

Traceable Evidence Pipeline & AI Research Workflow Evaluation

## 项目定位

本项目把公开网页、PDF和财报转换为可回查原文、经过准入审核、
能够安全交给专家与模型分析的证据包。

它不承诺找全互联网资料，不自动保证研究结论正确，也不使用重型
Claim—Inference图替代专家判断。

主线边界：

```text
研究问题与种子资料
→ 抓取、解析和质量标记
→ 文本分块与句子ID
→ LLM span-selection
→ 代码恢复逐字原文
→ EvidenceCard候选证据
→ 批量审核、聚合和准入
→ EvidenceRecord正式证据
→ 编译轻量研究上下文
→ 专家与强提示词分析
→ 人工终审和发布冻结
```

## 为什么采用span-selection

早期实验要求模型直接返回逐字引文，精确匹配率只有24%。V3将任务拆开：

- 模型负责判断哪些句子具有研究价值；
- 模型只返回句子ID；
- 代码从解析文本中恢复原句；
- 程序验证EvidenceCard与原文的绑定关系。

这一设计保证“引文来自输入材料”，但不等于证据召回完整、摘要必然正确
或最终分析结论正确。

## 五类正式对象

- `DocumentRecord`：来源文件、抓取状态、解析状态和质量信号；
- `EvidenceCard`：自动抽取、尚未准入的候选证据；
- `EvidenceRecord`：经过聚合和人工批量准入、带来源引用的正式证据；
- `ResearchBrief`：研究问题、范围、反证、开放问题和资料截止日期；
- `ReleaseManifest`：报告、证据、来源索引、上下文、配置、生产提示词和
  代码版本的冻结记录。

Bundle仅是EvidenceCard聚合过程中的临时结构，不进入长期对象模型。

## 三个人工门禁

1. 确认研究问题与范围；
2. 批量准入EvidenceRecord；
3. 最终审阅并冻结发布。

发布校验检查登记文件的字节完整性，以及Brief、EvidenceRecord、来源索引和
编译上下文之间的内部绑定。它不认证来源发布者身份、来源内容真实性、证据
召回完整性或报告结论正确性。

## 安装

### 从GitHub克隆（推荐）

```powershell
git clone https://github.com/ABCLDZ/traceable-research-pipeline.git
cd traceable-research-pipeline
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# 若要使用下文的裸 research-flow 命令，须在当前PowerShell会话激活
.\.venv\Scripts\Activate.ps1
```

Linux或macOS：

```bash
git clone https://github.com/ABCLDZ/traceable-research-pipeline.git
cd traceable-research-pipeline
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
# 若要使用下文的裸 research-flow 命令，须在当前shell会话激活
source ./.venv/bin/activate
```

不激活虚拟环境也可以工作，但必须显式使用该环境的解释器，例如
`.\.venv\Scripts\python.exe -m research_pipeline.cli`或
`./.venv/bin/python -m research_pipeline.cli`。

只安装Python CLI，不安装Agent Skill：

```text
python -m pip install "git+https://github.com/ABCLDZ/traceable-research-pipeline.git@v0.1.0"
```

### 配置DeepSeek

只有`extract`需要模型API。项目**不会自动读取**`.env`文件；请在启动命令的
同一终端会话中设置环境变量。

PowerShell：

```powershell
$env:DEEPSEEK_API_KEY = "your-api-key"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com" # 可选
$env:DEEPSEEK_MODEL = "deepseek-chat"                # 可选
```

Bash/Zsh：

```bash
export DEEPSEEK_API_KEY="your-api-key"
export DEEPSEEK_BASE_URL="https://api.deepseek.com" # optional
export DEEPSEEK_MODEL="deepseek-chat"               # optional
```

实时抽取会把经过解析和分块的来源文本片段发送到配置的
DeepSeek兼容API端点。不要提交受保密义务约束、包含个人敏感信息或不允许
传给第三方模型的材料。日志默认只保存提示词和输出哈希，不保存完整内容。

## Agent Skill

仓库维护一份符合开放Agent Skills格式的真源：
`skills/traceable-research/SKILL.md`。Codex和Claude Code使用同一份工作流，
不会复制业务代码；Skill只负责让Agent安全调用`research-flow` CLI。

把Skill安装到**实际研究项目**的两个Agent目录。`--project-root`必须指向
使用Skill的项目，而不是本工具仓库：

```powershell
$ResearchProject = "C:\path\to\your-research-project"
.\.venv\Scripts\python.exe scripts\install_agent_skill.py `
  --agent all --scope project --project-root $ResearchProject
```

只安装Codex或Claude Code：

```powershell
.\.venv\Scripts\python.exe scripts\install_agent_skill.py `
  --agent codex --scope project --project-root $ResearchProject
.\.venv\Scripts\python.exe scripts\install_agent_skill.py `
  --agent claude --scope project --project-root $ResearchProject
```

安装为用户级Skill：

```powershell
.\.venv\Scripts\python.exe scripts\install_agent_skill.py --agent all --scope user
```

安装位置分别为：

- Codex：`.agents/skills/traceable-research/`
- Claude Code：`.claude/skills/traceable-research/`

已有不同版本时，安装器默认拒绝覆盖；显式传入`--replace`后会先保留带时间戳的备份。
备份统一放在项目或用户主目录下的`.agent-skill-backups/`，不会留在Agent的
Skill发现目录中。
安装后可在Codex中使用`$traceable-research`，或在Claude Code中使用
`/traceable-research`。首次使用前，用安装了本Python包的解释器运行Skill内
的环境检查脚本；脚本会返回可靠的`command_prefix`。例如开发安装使用：

```powershell
.\.venv\Scripts\python.exe `
  "$ResearchProject\.agents\skills\traceable-research\scripts\check_environment.py"
```

Agent必须使用该JSON中的`command_prefix`，不能假设裸`research-flow`
已经进入`PATH`。

也可以在Codex中调用`$skill-installer`，并把以下仓库目录作为安装来源：

```text
https://github.com/ABCLDZ/traceable-research-pipeline/tree/v0.1.0/skills/traceable-research
```

这种方式只安装Agent说明，不会安装底层Python包；仍需执行上面的GitHub
Python安装命令。Claude Code用户建议克隆仓库后运行通用安装器。

## CLI

以下裸`research-flow`示例假定已经按安装段激活虚拟环境；未激活时用
该环境的`python -m research_pipeline.cli`替换`research-flow`。

```text
research-flow init CONFIG
research-flow ingest CONFIG
research-flow extract CONFIG
research-flow build-review-pack CONFIG
research-flow admit-evidence CONFIG --reviewer NAME
research-flow compile-context BRIEF EVIDENCE_RECORDS
research-flow freeze-release RELEASE_DIR [OPTIONS]
research-flow verify-release RELEASE_DIR
```

典型运行：

```powershell
Copy-Item configs/example.yaml configs/my-project.yaml
# 先替换研究问题、范围和seed_urls，再运行：
research-flow init configs/my-project.yaml
research-flow ingest configs/my-project.yaml
research-flow extract configs/my-project.yaml
research-flow build-review-pack configs/my-project.yaml
```

审核者编辑生成的 `review_pack.json`，将每项标记为
`admit`、`reject`、`merge`或`revise`。`admit-evidence`仅接受没有
`pending`项的完整批次，并使用原子写入生成EvidenceRecord集合。

## 解析质量

`parse_quality`与`table_preservation`是风险信号，不是完整性认证。
PDF表格、OCR材料、低文本量和乱码材料会触发人工复核提示。

## 实验结论

本项目由两个旧工作流收束而来：

- 上游证据采集实验验证了span-selection和程序化原文绑定；
- 下游重型论证治理经过真实任务、跨领域A/B和长期交接试验后未建立优势，
  严格模式影响召回低于强普通流程19.05个百分点，因此按预注册规则停止扩张。

生产主线只回收证据准入、开放问题、资料截止日期和发布冻结等轻量机制。
完整负面实验保存在 `experiments/argument_governance/`。

## 离线演示

无需网络或API密钥即可验证准入、上下文和发布闭环：

```powershell
.\.venv\Scripts\python.exe scripts\offline_demo.py .\.demo_run\offline
.\.venv\Scripts\research-flow.exe verify-release .\.demo_run\offline\release-v1
```

演示使用合成材料，不代表现实公司或现实研究结论。

## 当前不做

- 自动发现全网资料；
- 自动判断全部来源真伪；
- 自动形成正确行业结论；
- Claim—Inference复杂语义图；
- 自动语义影响传播；
- 数据库、前端和多Agent平台。

## 安全

- URL只允许HTTP/HTTPS，并阻止明显的本地地址和私有IP；
- 支持域名允许/阻止列表；
- 默认限制单个响应为50 MiB；
- LLM日志默认只保存提示词和输出哈希，不保存完整内容；
- 成本费率默认不猜测；如需估算，必须在环境变量中填入当前价格；
- `data/`默认不进入版本库。

完整安全边界和漏洞报告方式见[SECURITY.md](SECURITY.md)。本地URL检查用于
降低误抓内网地址的风险，不是完整的恶意网络沙箱或DNS重绑定防御。不要把
抓取器直接暴露为公共URL抓取服务。

## 项目历史

旧目录保持不变，新项目只迁移并修复已验证资产。实验报告是设计证据，
不是运行时依赖。

## 开源边界

- `configs/example.yaml`、离线演示与测试材料全部为合成内容；
- 不提交抓取原文、API日志、本地发布包、真实公司分析稿或密钥；
- `experiments/`只保留方法与评估结论，不是生产依赖，也不是完整数据集；
- GitHub Actions只运行离线测试、构建和冻结验证，不调用付费API。
- V3生产提示词只有一份真源：
  `src/research_pipeline/resources/extract_evidence_v3.md`；`prompts/`中的
  V1/V2仅保留为历史实验材料。

发布前可运行：

```powershell
.\.venv\Scripts\python.exe scripts\check_open_source.py
.\.venv\Scripts\python.exe -m pytest
```

## 许可证

本项目采用[Apache License 2.0](LICENSE)。
