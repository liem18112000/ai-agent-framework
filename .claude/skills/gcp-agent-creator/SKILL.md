---
name: gcp-agent-creator
description: >-
  Scaffolds a new GCP domain skill+agent pair for the LUZ ops repo, following
  the pattern used by gcp-iam/gcp-gke/gcp-cloudrun/gcp-pubsub/gcp-gcs/
  gcp-network/gcp-secretmanager. Use when the user asks to add ops coverage
  for a new GCP domain (e.g. BigQuery, AlloyDB, Cloud Armor, Cloud DNS) not
  yet covered. Don't use this to answer domain questions directly — invoke the
  existing gcp-<domain> skill for that instead.
metadata:
  category: DevOps
---

# GCP Agent Creator — LUZ Ops

Meta-skill: given a new GCP domain name, produces a `SKILL.md` +
subagent `.md` pair under `.claude/skills/gcp-<domain>/` and
`.claude/agents/gcp-<domain>.md`, grounded in this repo's actual
infrastructure — not generic GCP tutorial content.

## Procedure

### 1. Research the domain in this repo

Grep `luz_kubernetes/`, `luz_kubernetes_infra/`, `luz_dockerfiles/` for the
new domain's resource type before writing anything. At minimum search for:
the GCP resource's Terraform type (e.g. `google_bigquery_dataset`), the
domain's CLI namespace (e.g. `bq`, `gcloud alloydb`), and any `env.sh`
variables naming its resources. Prefer delegating this to an Explore-type
subagent when the sweep is broad — mirror the two-pass research done for the
original 7 domains (one pass for infra facts, one pass confirming skill
format conventions if this is the first time authoring a skill in a session).

Record: project(s) it lives in (`klara-nonprod`/`klara-prod`/
`klara-performance`/`klara-infra`), concrete resource names, Terraform file
paths, and any manual provisioning scripts — the same categories covered by
the existing 7 skills.

### 2. Author the skill — `SKILL.md` template

```yaml
---
name: gcp-<domain>
description: >-
  <One sentence: what it covers for THIS repo>. Use when <concrete trigger
  verbs/nouns tied to actual repo paths>. Don't use for <adjacent domain,
  name the sibling gcp-<other> skill explicitly>.
metadata:
  category: <Security|Containers|Serverless|Storage|Networking|DevOps>
---

# <Human title> — LUZ Ops

<1 short paragraph overview.>

## Environments
<Only if domain-specific nuance exists beyond the standard 4-project map;
otherwise skip — don't repeat boilerplate every skill already states.>

## Known resources in this repo
<Concrete names + file:path pointers found in step 1. No placeholders.>

## Common commands
<gcloud/kubectl/terraform snippets using the ACTUAL project/resource names
found in step 1, not <PROJECT_ID>-style placeholders.>

## Safety notes
<Which mutating actions are dangerous against klara-prod/klara-infra for this
specific domain, and the confirmation rule: never run a mutating/destructive
command against klara-prod without showing the user the exact change first.>

## Reference Directory
<Bullet list of the concrete file paths from step 1 — the submodules are the
source of truth, don't duplicate their content into a local references/
folder.>
```

Keep each skill self-contained (no shared cross-file references between
skills, matching the `google/skills` catalog convention) and keep the
`description` field written as LLM routing criteria — explicit "Use when /
Don't use for" clauses naming sibling skills, since that's what makes
automatic skill selection work.

### 3. Author the agent — `.claude/agents/gcp-<domain>.md` template

```yaml
---
name: gcp-<domain>
description: <1-2 sentences, same routing style as the skill description>
tools: Read, Grep, Glob, Bash, Skill
model: inherit
---

You are the LUZ ops <domain> expert for this repo (klara-nonprod,
klara-prod, klara-performance, klara-infra — region europe-west6 except
dev-vn which is asia-southeast1).

Before acting, load the `gcp-<domain>` skill via the Skill tool for the
current resource inventory and conventions.

Safety rule: never run a mutating or destructive command (kubectl apply,
terraform apply, gcloud create/update/delete, secret writes) against
klara-prod or klara-infra without first showing the user the exact command
and diff/plan and getting explicit confirmation. Read-only inspection
commands (list/describe/get/plan) need no confirmation.
```

### 4. File placement

- `ops/.claude/skills/gcp-<domain>/SKILL.md`
- `ops/.claude/agents/gcp-<domain>.md`

### 5. Verify

Confirm the frontmatter YAML parses (matching `name` in both files), and that
the skill body cites concrete repo facts (project/cluster/resource names,
`file:path` references) rather than generic placeholders.

## Reference Directory

- `.claude/skills/gcp-iam/SKILL.md`, `.claude/skills/gcp-gke/SKILL.md`, etc. —
  worked examples of the template above.
- `.claude/agents/gcp-iam.md`, `.claude/agents/gcp-gke.md`, etc. — worked
  examples of the agent template above.
