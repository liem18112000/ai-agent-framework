---
name: gcp-pubsub
description: >-
  Pub/Sub expert for the LUZ ops repo — topic/subscription naming, the shared
  Terraform template, Eventarc→GKE wiring, and manual bootstrap scripts. Use
  when creating, inspecting, or debugging a Pub/Sub topic/subscription or DLQ,
  or wiring Eventarc from a topic to a GKE endpoint. Don't use for Cloud Run
  service definitions alone (see gcp-cloudrun) or IAM role grants alone (see
  gcp-iam).
metadata:
  category: Serverless
---

# Pub/Sub — LUZ Ops

No standalone dedicated Pub/Sub Terraform module exists for most services —
topics/subscriptions are provisioned either via the shared Cloud Run
service-template or via one-off manual `gcloud` scripts.

## Known resources

- `software-release` topic in **klara-infra** —
  `luz_kubernetes_infra/terraform/devops/google-pub-sub/main.tf:2`, with a
  Cloud Run invoker IAM binding for `notify-software-release`.
- Shared per-service template (`luz_kubernetes/terraform/common-cloudrun-resources/service-template/pubsub.tf`):
  naming pattern `pubsub-topic-<service>` / `pubsub-subscription-<service>`,
  DLQ `dlq-topic-<service>` / `dlq-subscription-<service>`, push-delivery into
  the paired Cloud Run service.
- `luz_kubernetes/terraform/common-cloudrun-resources/eventarc-pubsub-gke/main.tf`
  — reusable Eventarc trigger module wiring a Pub/Sub topic to a private GKE
  HTTP endpoint via a network attachment (used optionally by
  `serverless-workflow-runtime`).
- `ILETTER_MEDIA_THUMBNAIL_TOPIC=${LUZ_ENV}-iletter-media-thumbnail-topic`,
  subscription `${LUZ_ENV}-iletter-media-thumbnail-topic-sub` —
  `luz_kubernetes/configuration/env.sh:31-32`.
- Manual bootstrap scripts (`luz_kubernetes/cluster/gcp/manual_script/`):
  `create_luz_earchive_sync_pubsub_topic_and_subscription.sh`,
  `create_luz_epost_sse_pubsub_topic_and_subscription.sh`,
  `create_ecp_log_pubsub_topic_and_subscription.sh`,
  `update_ecp_log_pubsub_dead_letter_queue.sh`.
- `luz-salary-run/pubsub/main.tf` defines its own topic/subscription pair.

## Common commands

```bash
# list topics / subscriptions
gcloud pubsub topics list --project klara-nonprod
gcloud pubsub subscriptions list --project klara-nonprod

# inspect a DLQ backlog
gcloud pubsub subscriptions describe dlq-subscription-<service> --project klara-prod

# pull a few messages without acking (peek)
gcloud pubsub subscriptions pull pubsub-subscription-<service> --project klara-nonprod --limit=5 --auto-ack=false
```

## Safety notes

Never `gcloud pubsub subscriptions pull --auto-ack` (destructive read) or
delete a topic/subscription in `klara-prod` without explicit confirmation —
deleting a subscription drops any in-flight/unacked messages permanently.
Prefer `--auto-ack=false` for inspection.

## Reference Directory

- `luz_kubernetes/terraform/common-cloudrun-resources/service-template/pubsub.tf`
- `luz_kubernetes/terraform/common-cloudrun-resources/eventarc-pubsub-gke/main.tf`
- `luz_kubernetes_infra/terraform/devops/google-pub-sub/main.tf`
- `luz_kubernetes/cluster/gcp/manual_script/*pubsub*.sh`
