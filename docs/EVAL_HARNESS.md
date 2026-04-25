# Eval Harness（评测框架）

> 没有 eval 就不要发布 LLM 应用 —— Anthropic / Perplexity / OpenAI 的工程文化。

---

## 1. 评测目标

```
对 100+ 测试 query 跑 deepsearch-core，自动评分四个维度：
1. 事实准确性 (factual accuracy)
2. 来源覆盖度 (source coverage)  
3. 引用准确性 (citation accuracy)
4. 平均延迟 (P50 / P95)

每次 PR 自动跑，回归 → 阻止合并。
```

---

## 2. 评测集

### 2.1 数据集结构

```jsonl
// eval/datasets/general.jsonl
{"id": "g001", "query": "What's new in Claude 4.7?", "policy": "general", "expected_facts": ["1M context", "Opus released", "April 2026"], "expected_min_sources": 3, "max_seconds": 30}
{"id": "g002", "query": "MCP protocol streaming support", "policy": "tech", "expected_facts": ["resources/subscribe", "notifications"], "expected_min_sources": 2, "max_seconds": 30}
```

```jsonl
// eval/datasets/finance.jsonl
{"id": "f001", "query": "腾讯 2025Q4 财报 AI 业务进展", "policy": "finance", "expected_facts": ["腾讯混元", "AI 营收"], "expected_sources_include": ["hkex.com.hk", "tencent.com"], "max_seconds": 60}
{"id": "f002", "query": "美联储 2026-04 FOMC 政策预期", "policy": "finance", "expected_facts": ["利率决议", "QT"], "expected_sources_include": ["federalreserve.gov"]}
```

### 2.2 计划的数据集

| 数据集 | 数量 | 难度 | 来源 |
|--------|------|------|------|
| `general.jsonl` | 50 | 简单 → 中等 | 时事 / 通识 |
| `finance.jsonl` | 30 | 中等 → 困难 | FinSight 12 题 + 自建 18 题 |
| `tech.jsonl` | 30 | 中等 → 困难 | LLM / 框架 / 论文 |
| `academic.jsonl` | 20 | 困难 | arxiv / nature 论文综述 |
| `multilingual.jsonl` | 20 | 中等 | 中英日法德五语 |
| `adversarial.jsonl` | 10 | 困难 | prompt injection / 钓鱼源 |

---

## 3. 评分指标

### 3.1 事实准确性（最关键）

```python
def score_factual_accuracy(answer: str, expected_facts: list[str]) -> float:
    """LLM-as-judge：用 sonnet 判断 answer 中是否包含 expected_facts。"""
    judge_prompt = f"""
    Expected facts:
    {expected_facts}
    
    Generated answer:
    {answer}
    
    For each expected fact, output 1 if covered (verbatim or paraphrase), 0 if not.
    Output JSON array of 0/1.
    """
    scores = await judge_llm.complete_json(judge_prompt)
    return sum(scores) / len(scores)
```

### 3.2 来源覆盖度

```python
def score_source_coverage(citations, expected_sources_include) -> float:
    cited_domains = {urlparse(c.url).netloc for c in citations}
    matched = sum(1 for src in expected_sources_include 
                  if any(src in d for d in cited_domains))
    return matched / len(expected_sources_include)
```

### 3.3 引用准确性

```python
async def score_citation_accuracy(answer: str, citations: list[Citation]) -> float:
    """随机抽 N 个 [n] 标记，验证对应 source 是否真的支持该论断。"""
    claims = extract_cited_claims(answer)
    sample = random.sample(claims, min(5, len(claims)))
    
    verified = 0
    for claim, cite_idx in sample:
        source = citations[cite_idx]
        # LLM 验证：source.snippet 是否支持 claim
        verified += await llm_verify(claim, source.snippet)
    
    return verified / len(sample)
```

### 3.4 延迟

直接从 events 表算：
- 首字节延迟（first event_type=token_stream 的 timestamp - run_started）
- 总延迟（run_finished - run_started）

---

## 4. 评测运行器

### 4.1 命令行

```bash
# 跑全套
uv run python eval/runner.py --dataset general,finance --output reports/

# 单个数据集
uv run python eval/runner.py --dataset finance.jsonl

# 单条用例（debug）
uv run python eval/runner.py --case f001
```

### 4.2 输出格式

```
================================================================
EVAL RESULTS — 2026-04-25
================================================================
Dataset: general (50 cases)

Case ID    | Factual | Sources | Cite   | Latency P50/P95 | Status
-----------|---------|---------|--------|-----------------|--------
g001       |   1.00  |   1.00  |  0.80  |  3.2s / 5.1s    | ✅
g002       |   0.67  |   0.50  |  1.00  |  4.5s / 7.2s    | ⚠️ regression
g003       |   1.00  |   1.00  |  1.00  |  2.8s / 4.2s    | ✅
...

================================================================
Aggregate
================================================================
Factual accuracy:    0.87 (target: ≥0.85)  ✅
Source coverage:     0.81 (target: ≥0.75)  ✅
Citation accuracy:   0.89 (target: ≥0.85)  ✅
Latency P50:         3.5s (target: ≤5s)    ✅
Latency P95:         9.2s (target: ≤15s)   ✅
Token / query:       4.2k (target: ≤10k)   ✅

Overall: PASS (5/5 metrics within threshold)
```

### 4.3 Markdown 报告

```bash
uv run python eval/runner.py --dataset all --format markdown --output eval/reports/2026-04-25.md
```

生成漂亮的 markdown 报告，可以直接贴到 PR 里。

---

## 5. 与 CI 集成

### 5.1 GitHub Actions

```yaml
# .github/workflows/eval.yml
name: Eval Harness

on:
  pull_request:
    paths:
      - 'deepsearch_core/**'
      - 'eval/datasets/**'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      
      - name: Run eval (smoke subset)
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}
        run: |
          uv run python eval/runner.py \
            --dataset general,finance \
            --sample 20 \
            --baseline eval/baselines/main.json \
            --max-regression 0.05
      
      - name: Comment PR
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('eval/reports/latest.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: report
            });
```

### 5.2 预算门禁

```python
# eval/runner.py
def enforce_budget_gate(results, baseline):
    """如果质量回归超过 5% 或者 token 消耗 +20%，CI 失败。"""
    
    if results.factual_accuracy < baseline.factual_accuracy - 0.05:
        sys.exit(1)
    
    if results.token_per_query > baseline.token_per_query * 1.2:
        sys.exit(1)
    
    if results.latency_p95 > baseline.latency_p95 * 1.5:
        sys.exit(1)
```

---

## 6. 持续改进 Loop

```
1. 收集用户真实 query（脱敏）
2. 标注 expected_facts（半自动：LLM 提取 + 人工审核）
3. 加入 dataset
4. 跑 eval，看哪类 query 表现最差
5. 针对性改 prompt / policy / search 策略
6. 跑 eval 验证提升
7. 没回归就发布
```

这是 deepsearch-core 长期质量保证的核心机制。

---

## 7. Eval-Driven Development（EDD）

### 7.1 新功能开发流程

```
1. 写 5-10 个测试 query 添加到 dataset
2. 跑 eval：当前肯定过不了
3. 实现新功能（例如新搜索引擎）
4. 再跑 eval：所有新 case 应该过
5. 跑全量 eval：旧 case 不能回归
```

这是 TDD 的 LLM 应用版本。

### 7.2 推荐工具

| 工具 | 用途 |
|------|------|
| `lm-evaluation-harness` | EleutherAI 的标杆工具 |
| `inspect_ai` | UK AISI 出品，专注安全 eval |
| `langfuse` | trace + scoring |
| `phoenix` | Arize 出品，可视化 eval |

deepsearch-core 自带的 runner 是轻量版，足够日常 CI 用。复杂场景可接 inspect_ai。

---

## 8. 路线图

| 版本 | Eval 能力 |
|------|----------|
| **v0.1** | 手写 runner + 100 case |
| **v0.2** | LLM-as-judge + GitHub Actions 集成 |
| **v0.3** | 接入 inspect_ai + 多语言 dataset |
| **v0.5** | 自动从 events 生成新 case（持续学习）|
| **v1.0** | 公开 leaderboard，对比 GPT Researcher / ODR |
