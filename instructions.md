---
title: Monolithic code review toolkit
tags:
  - plugin
  - code-review
  - instructions
status: draft
---

# Monolithic code review toolkit

This plugin will expose skills to handle code review workflows for different stages of the work lifecycle:

1. [Task done](#1-task-done)
2. [User story done](#2-user-story-done)
3. [Feature done](#3-feature-done)
4. [Pull request comments and suggestions](#4-pull-request-comments-and-suggestions)

## 1. Task done

When a small unit of work is complete, the agent must review the changes introduced against the task requirements and goals. If discrepancies are found, the user will be presented with a brief report showing the findings, respective consequences, and proposed actions.

## 2. User story done

User stories usually represent a ticket or card — a larger unit of work. Upon completing the work for a user story, two immediate stages will require attention:

### 2.1 Pre-flight

Before pushing the last commits and starting a pull request, a review similar to stage one must take place, this time against the user story requirements, description, and definition of done. The same workflow applies: upon discovering problems that need addressing, the user is notified using the same contract — the findings, consequences, and proposed actions. When those are cleared, the work is ready to become a pull request.

### 2.2 Post-flight

The pull request was created; now it is time for an adversarial code review on the remote pull request. The agent must ingest the specs, user story description, requirements, and definition of done from the sources indicated during the plugin install, and then scan the diff looking for:

- Errors
- Gaps
- Recommended improvements (when the improvement is pertinent, not just all-around code enhancements)
- Off-scope work

The workflow consists of double-checking the findings against online up-to-date official documentation, user story documentation and artifacts, and extra context if provided. The findings must be categorized, then made into pull request comments.

> [!tip] Comment contract
> Comments must be compact, following **what was found → what are the consequences → what is suggested**. Tagging the pull request author is a good practice, unless the user refuses it.

### 2.3 Pull request received comments from team members

When human reviewers add comments to the pull request, the agent must:

1. Make a list of all comments and respective files with line numbers
2. Proceed with an adversarial fact-checking workflow to determine accuracy and relevance
3. For each comment, assign:
   - A fact-checking status (`true` / `false`)
   - A suggestion status (accept or decline the instructions or requests)
   - Justifications when applicable
   - A risk/relevance status (`high` / `medium` / `low`)
4. Organize and present the findings to the user in a canvas or equivalent medium, for consideration and decision-making

## 3. Feature done

When a feature is complete, the same workflows from the user story must be applied, this time using the documentation, context, and specs for the feature. A harder eye must be applied, and a more rigorous adversarial review.

The first priority is determining if the diff is in agreement with the definition of done, the goal, and the out-of-scope instructions for the feature as documented. In the end, the diff must be reviewed, actions applied, and team member comments addressed — either accepted and satisfied, declined with a reason, or ignored.

## 4. Pull request comments and suggestions

This is a delicate stage in the process of submitting code. The objections, recommendations, requests, and demands (when coming from a team lead or tech lead) must be rigorously analyzed, and the solution must then be polished and delivered with maximum zeal and efficiency.

There may be back and forth, but the agent only responds or acts under the user instructions — never automatically. It is expected that the agent deliver messages or implement code as per user instructions.

## Implementation

1. Take an existing code review skill or plugin and add its code to a folder in the project, so we can use it as reference. The folder will not be committed, and must be deleted as soon as the initial scaffolding ends.
2. Use the following template for the plugin: [Monolith-INC/agent-plugins-toolkit](https://github.com/Monolith-INC/agent-plugins-toolkit)
3. The README must have badges and be well structured and comprehensive
4. Add and update a changelog
5. When the plugin is ready, create a GitHub release
6. Planning phase must include specs and requirements, and be organized in feature / user-story / task
7. Create a project on Linear and make the preparations there. Check if Linear gives support to feature, user story, and task; otherwise, a Milestone can represent a feature, and the child artifacts named accordingly

> [!important] No template deviation
> There must be no deviation from the repository template provided. It represents the most important architectural decision and should never be departed from except under explicit user instructions.
