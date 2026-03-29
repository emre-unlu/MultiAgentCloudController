# AIOps Kubernetes Diagnostics Agent

A multi-agent Kubernetes diagnostics system that combines:

- a **LangGraph-based workflow** for routing, diagnosis, supervision, and reporting,
- a **Kubernetes MCP server** for safe observability and cluster tooling,
- **Chroma MCP / ChromaDB** for incident-history retrieval and persistence,
- **AIOpsLab** for benchmark environments, fault injection, and evaluation.

## Overview

This project is designed to diagnose Kubernetes incidents in a token-efficient way.

Instead of letting agents repeatedly consume raw tool outputs, each agent follows an internal execution loop:

`agent -> use_tool -> summarize_output -> agent`

This allows the system to:

- reduce token usage,
- keep context focused on structured evidence rather than raw logs and metrics,
- improve repeatability across diagnostic stages,
- reuse the same execution pattern across multiple agents.

The system has two layers:

### 1. Outer workflow graph
The outer graph controls the full incident lifecycle:

- route the request,
- answer informational questions directly,
- perform lightweight triage,
- retrieve similar historical incidents,
- run diagnosis,
- validate diagnosis with a supervisor,
- generate mitigation/report output,
- persist new incident knowledge.

### 2. Inner agent execution loop
Each reasoning-heavy agent can use an internal loop:

`agent -> tool -> summarizer -> agent`

This loop is used to keep tool interaction efficient and grounded.

## High-Level Workflow

```text
router
 ├─> information_agent -> END
 └─> detection_lite
      -> incident_retrieval
      -> diagnosis_agent
      -> supervisor_agent
      -> mitigation_report
      -> persistence
      -> END
```

### Workflow stages

#### Router
Determines whether the request is:

- **information**: a question answerable without a full diagnostic run,
- **diagnostics**: an operational problem requiring investigation.

#### Information agent
Handles informational or lightweight operational questions.

Examples:

- cluster overview questions,
- service topology questions,
- “what does this metric mean?” style questions,
- safe explanatory tasks that do not require a full incident workflow.

#### Detection-lite
Runs an inexpensive triage pass to identify:

- suspected services,
- suspected pods,
- candidate fault types,
- initial evidence summaries.

This stage exists mainly to prepare a good retrieval query before deeper diagnosis.

#### Incident retrieval
Uses **Chroma MCP** backed by **ChromaDB** to retrieve similar incidents from the incident-history store.

The goal is to:

- preload useful historical context,
- identify possible previously solved incidents,
- extract mitigation hints,
- guide the main diagnosis stage.

#### Diagnosis agent
A single agent responsible for the main technical investigation.

Internally, it covers:

- detection,
- localization,
- analysis.

These are conceptually separate outputs, but they are produced inside one diagnosis stage rather than three separate outer-graph agents.

#### Supervisor agent
Validates the diagnosis result.

It checks:

- whether the evidence is sufficient,
- whether the conclusion is grounded,
- whether another diagnosis pass is needed,
- whether the system should proceed with uncertainty.

#### Mitigation report
Produces the final operator-facing response, including:

- summary of the issue,
- affected services/pods,
- supporting evidence,
- probable root cause,
- mitigation suggestions,
- confidence and uncertainty notes.

#### Persistence
Stores incident knowledge back into the incident-history system when appropriate.

This is used to improve retrieval for future incidents.

## Architecture

This project is intended to work alongside two external components:

### 1. Kubernetes-Mcp
Your existing MCP server repository acts as the observability and tooling layer.

Responsibilities include:

- Kubernetes API access,
- Prometheus metrics access,
- Jaeger trace access,
- Neo4j topology queries,
- safe shell / kubectl execution,
- exposing these capabilities through MCP tools.

### 2. AIOpsLab
AIOpsLab is used as the benchmark and fault-injection environment.

Responsibilities include:

- deploying benchmark applications,
- injecting faults,
- running workloads,
- evaluating diagnosis and mitigation performance.

### 3. Chroma MCP / ChromaDB
Used as the incident-history layer.

Responsibilities include:

- retrieval of similar incidents,
- metadata filtering,
- storing structured incident summaries,
- enabling incident-guided diagnosis.

## Design Principles

### Token efficiency
Agents should not repeatedly consume large raw tool outputs.

Instead:

- tools return raw data,
- summarizers compress and structure the output,
- agents continue reasoning over summaries.

### Clear layer separation
- **Outer graph**: workflow orchestration
- **Inner graph**: agent execution policy
- **Kubernetes-Mcp**: observability/tooling
- **Chroma MCP**: incident memory
- **AIOpsLab**: benchmark environment

### Grounded diagnosis
All important diagnosis claims should be traceable to tool evidence or retrieved incident context.

### Reusability
The inner tool-summary loop should be generic and reusable across multiple agents.

## Planned Repository Structure

```text
aiops-k8s-agent/
├── agent/
│   └── src/
│       ├── graph/
│       │   ├── state.py
│       │   ├── routes.py
│       │   ├── workflow.py
│       │   └── render_graph.py
│       ├── subgraphs/
│       │   ├── tool_loop.py
│       │   └── runners/
│       │       ├── information_runner.py
│       │       ├── detection_lite_runner.py
│       │       ├── diagnosis_runner.py
│       │       └── supervisor_runner.py
│       ├── agents/
│       │   ├── router_agent.py
│       │   ├── information_agent.py
│       │   ├── detection_lite_agent.py
│       │   ├── diagnosis_agent.py
│       │   └── supervisor_agent.py
│       ├── retrieval/
│       │   ├── incident_retriever.py
│       │   └── persistence.py
│       ├── reporting/
│       │   └── mitigation_report.py
│       ├── prompts/
│       ├── schemas/
│       └── main.py
│
├── experiments/
│   ├── adapters/
│   │   └── aiopslab_runner.py
│   └── run_experiment.py
│
├── results/
├── docs/
└── README.md
```

## Outer Workflow State

The outer workflow state is expected to track:

- user query and route,
- cluster context,
- detection-lite output,
- retrieved incidents and retrieval confidence,
- diagnosis result,
- supervisor verdict,
- mitigation/report output,
- persistence status.

## Inner Tool Loop State

The inner loop is expected to track:

- current goal,
- selected tool and tool input,
- latest raw tool result,
- latest structured summary,
- collected summaries,
- tool budget,
- final output for the current agent.

## Initial Implementation Plan

We will implement the project in this order:

1. **README and architecture agreement**
2. **Core workflow state and routes**
3. **Reusable inner tool loop**
4. **Outer workflow graph**
5. **Runner nodes for information, detection-lite, diagnosis, and supervisor**
6. **Incident retrieval through Chroma MCP**
7. **Mitigation report and persistence layer**
8. **AIOpsLab adapter and experiment runner**

