# Contoso Data Intelligence

### Turning Unstructured Comments into Actionable Supply Chain Data

---

## The Business Problem

Contoso maintains **hundreds of thousands of free-text component comments** written by employees describing part changes — replacements, retirements, transitions, and alternatives. These comments are **business-critical**: if a part is being replaced by another, it **cannot be scrapped**.

The challenge? There is **no standard format**. Part numbers follow no consistent pattern, and the language used to describe replacements varies wildly — *"phasing out," "path forward," "provisional replacement," "shifted toward,"* and dozens of other phrasings.

**Manual review at this scale (300K–400K rows) is not feasible.** Rule-based parsing fails because the language and part number formats are too inconsistent.

---

## How the Idea Evolved

### Phase 1 — First Attempt: Custom Named Entity Recognition

The project started with a Custom NER (Named Entity Recognition) approach — training a custom AI model to spot part numbers in free text. It showed early promise but hit practical limits: every training example required **manual labeling**, the service could only process **25 documents per request**, and **scaling to 400K rows wasn't viable**.

### Phase 2 — The Breaking Point: Fine-Tuning Becomes Unsustainable

As the team continued refining the Custom NER model, a critical problem surfaced: **the model was getting the must-be-correct cases wrong.** When confidence was low, Custom NER would simply return no entity at all — silently dropping parts that the business *cannot* afford to miss.

Worse, retraining was fragile and unpredictable. Adding just **three new training records caused a 12% swing** in results from the previous model version. Each retraining cycle risked introducing new regressions, making the refinement process tedious and unreliable. The root cause: label quality sensitivity meant that small inconsistencies in training data could cascade into disproportionate accuracy drops.

### Phase 3 — The Pivot: LLM-Based Extraction

Given these challenges, the team posed a question: **what if we skip fine-tuning entirely and use a large language model (LLM) — AI that already understands language — to do the extraction?**

The LLM approach was framed as a decision gate — if it achieved high accuracy on the must-have test cases, Custom NER would no longer be needed. The team tested it and confirmed: **the LLM approach worked, with high accuracy on the required cases.**

Instead of training a custom model from scratch, the solution now uses **Azure OpenAI (GPT-5-mini)** with carefully engineered prompts to:

1. **Detect replacement intent** — does this comment describe one part replacing another?
2. **Extract the parts** — which is the old part? Which is the new one?
3. **Explain its reasoning** — what phrase triggered the detection, and how confident is the model?

This approach eliminated the labeling bottleneck entirely, removed the fragile retraining loop, and delivered the accuracy the business required.

---

## How It Works Today

The solution is a streamlined pipeline that reads Contoso's component comments and produces a structured, analyst-ready output:

```
┌─────────────────────┐
│                     │
│   Excel File with   │
│ Component Comments  │
│   (raw free text)   │
│                     │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│                     │
│   Text Cleanup      │
│  Strip HTML, fix    │
│  formatting issues  │
│                     │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│                     │
│  Azure OpenAI (LLM) │
│  Analyzes each row  │
│  for replacement    │
│  intent + extracts  │
│  part numbers       │
│                     │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│                     │
│  Structured Output  │
│  Excel file with    │
│  original data +    │
│  AI-extracted cols  │
│                     │
└─────────────────────┘
```

### What the Output Looks Like

For every comment, the AI adds these columns:

| Column | What It Tells You |
|---|---|
| **Replacement Intent** | Yes (1) or No (0) — does this comment describe a replacement? |
| **Old Part** | The part being retired or phased out |
| **New Part** | The replacement part being adopted |
| **Cue Phrase** | The exact words that signal the replacement (e.g., *"phasing out in favor of"*) |
| **Confidence** | How certain the model is (0% to 100%) |
| **Rationale** | A plain-English explanation of the model's reasoning |

![Output example](output_example.png)

> **Example:** Given the comment *"Manufacturing feedback suggests phasing out V18NLT4L5 in favor of R1KEWIQ74RNA-7R"*, the AI returns:
> - Intent: **Yes** | Old: **V18NLT4L5** | New: **R1KEWIQ74RNA-7R**
> - Cue: *"phasing out…in favor of"* | Confidence: **95%**

---

## Azure Resources & Consumed Revenue (ACR)

This solution runs on a minimal set of Azure services, each contributing to **Azure Consumed Revenue (ACR)**:

| Resource | Purpose | ACR Impact |
|---|---|---|
| **Azure AI Services (Cognitive Services)** | Hosts the GPT-5-mini model that powers the extraction agent | Pay-per-use based on volume processed (token-based pricing) |
| **Resource Group** | Organizes all resources under a single manageable unit | No direct cost — management layer only |

The infrastructure footprint is intentionally lightweight — no VMs, no clusters, no complex networking. Costs scale directly with usage (number of comments processed), keeping the barrier to entry low while generating measurable ACR.

---

## Business Impact

| Before | After |
|---|---|
| Manual review of 400K comments | Automated AI processing in minutes |
| Inconsistent human judgment | Consistent, explainable AI decisions |
| No audit trail | Every decision includes rationale + confidence |
| Parts incorrectly scrapped | Replacement intent flagged before scrap decisions |
| Unstructured text, unusable at scale | Structured, query-ready tabular output |

---

## What's Next

- **Scale to production** — Process the full 300K–400K comment backlog through Azure OpenAI
- **Integrate into Fabric** — Feed AI-enriched data directly into Contoso's data pipeline (ETL)
- **Continuous processing** — Automatically analyze new comments as they arrive
- **Confidence-based routing** — Auto-approve high-confidence results, flag low-confidence rows for human review
- **Cross-reference validation** — Validate extracted part numbers against Contoso's known part universe

---

*This document was prepared for executive review. For technical implementation details, see [README.md](README.md).*
