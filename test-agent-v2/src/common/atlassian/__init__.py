"""Read-only Atlassian client (Jira + Confluence + Bitbucket) — mixins over BaseClient."""

from common.atlassian.base import (
    BITBUCKET_API,
    RETRY_BACKOFFS,
    RETRY_STATUS,
    BaseClient,
)
from common.atlassian.bitbucket import BitbucketMixin
from common.atlassian.confluence import ConfluenceMixin
from common.atlassian.jira import JiraMixin


class AtlassianClient(JiraMixin, ConfluenceMixin, BitbucketMixin, BaseClient):
    """Read-only Jira + Confluence + Bitbucket over one retry core."""


__all__ = ["BITBUCKET_API", "RETRY_BACKOFFS", "RETRY_STATUS", "AtlassianClient"]
