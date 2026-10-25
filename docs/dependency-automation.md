# Dependency automation

Dependabot uses Conventional Commit titles and checks weekly. Minor and patch
updates are grouped into one PR per ecosystem; major updates remain separate.
The pytest compatibility exclusion remains in place. Security updates retain
their independent schedule.

CodeRabbit reviews non-draft PRs, including bot PRs and incremental commits.
Reviews and approvals remain enabled, while generated description summaries,
review status messages, review metadata, fortunes and poems are disabled to
reduce notification noise. GitHub notification delivery is still controlled by
each user's notification and subscription settings.

Native GitHub auto-merge is enabled
only for verified same-repository Dependabot minor and patch updates targeting
`main`. Major updates require manual review. No PR code runs in the privileged
workflow.

## Repository prerequisites

Enable Allow auto-merge and squash merging. Protect `main` with one required
approval, stale approval dismissal, conversation resolution, strict required CI,
and enforcement for administrators. No automation account should bypass the rule.
This workflow intentionally requires classic branch protection; additional
rulesets continue to apply when GitHub merges the PR.

Required checks: ["tests","hassfest","hacs","pull-request-title"].

Enable the CodeRabbit app for this repository. The committed configuration
requests changes for findings and allows approval after a clean review.

## Automation credential

Create a fine-grained personal access token limited to the two repositories
`Assidefok/SCSGATE` and `Assidefok/3cat_show_downloader`. Grant Administration
(read, to verify protection), Contents (read/write), Pull requests (read/write),
Workflows (read/write, to merge Actions updates), and Issues (read/write, for
release-please labels). Store its value as the **Actions repository secret**
`AUTOMATION_TOKEN` in each repository. Never commit the token or post it in a PR.
Choose an expiry and renew it before it expires. An equivalently scoped GitHub
App installation token can also be used, provided it is refreshed automatically.

If the secret is missing, the workflow records a warning and skips auto-merge
without creating a failed run for every dependency PR. Required CI and reviews
remain enforced; merge these PRs manually until the credential is configured.
When configured, it uses the
credential to read protection and enable squash auto-merge, and pins the expected
PR head. GitHub still enforces required CI, approvals and resolved conversations.
Using a separate credential ensures merges trigger subsequent push and release
workflows; merges made with GITHUB_TOKEN would suppress those events.

SCSGATE release-please also uses this token (or an existing RELEASE_PLEASE_TOKEN)
so release PRs can run CI without requiring manual workflow approval.
If neither secret is configured, release-please records a warning and skips
release automation without creating a failed run on every push. No release is
created until a credential is configured.

## Verification

For the next minor or patch Dependabot PR, verify its title, the CodeRabbit
review, successful required checks, auto-merge, and a subsequent workflow on
`main`. A major update must remain open. These end-to-end checks require the
credential and a real Dependabot PR; passing CI on the configuration PR alone
does not prove auto-merge or publication.
