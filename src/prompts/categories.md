## Seed categories (v2 — 2026-06-16, 24 seeds)

- `building-websites` — front-end, frameworks, deployment, CMS, mobile apps
- `optimising-ai` — caching, thinking, model selection, latency, cost
- `tool-combinations` — integrating multiple tools (Claude + Stitch + Supabase etc.)
- `future-trends` — industry predictions, hot-topic debates, where the field is heading
- `agent-engineering` — designing, instructing, evaluating individual agents (incl. goal-driven / agentic-OS patterns)
- `multi-agent-systems` — sub-agents, agent teams, orchestration, parallel-agent patterns
- `claude-code-workflows` — Claude Code productivity tricks, slash commands, hooks, skills, plan mode, sessions, CLI tooling
- `ai-agency-business` — running an AI agency: niche selection, careers, org design, building-in-public, marketing/conversion
- `memory-systems` — long-term memory, context persistence, vector stores, knowledge graphs, research/knowledge extraction
- `skill-engineering` — designing, packaging, and reusing AI skills / prompts as composable units
- `cost-optimisation` — reducing AI/tooling spend: caching, model routing, free tiers, token efficiency
- `client-retention` — keeping AI agency clients: success metrics, reporting, scope management, churn prevention
- `open-source-ai-tools` — open-source LLM tooling, self-hostable agents, community projects
- `browser-automation` — Playwright / browser-driver patterns for AI agents and QA
- `codex-workflows` — OpenAI Codex / CLI agent workflows and tooling
- `offer-design` — packaging and productising AI agency offers
- `design-systems` — UI/UX systems, component libraries, visual consistency for AI-built products
- `local-and-self-hosted-ai` — running models locally / on a VPS: Ollama, local model setup, deployment, self-hosting
- `content-and-video-generation` — AI video, UGC, ad-creative, and YouTube content automation
- `ai-security-and-compliance` — agent security, cybersecurity, privacy, AI compliance services
- `voice-and-conversational-agents` — voice agents, conversational/chat agents, Telegram & messaging integrations
- `context-engineering` — structuring context windows, retrieval, and prompt-context for agents
- `sales-and-lead-generation` — selling/positioning, sales frameworks, pricing/retainers, outreach, lead-gen, client acquisition
- `model-and-industry-analysis` — model releases, benchmarking/comparison, AI industry analysis & history

## Proposing new categories

- Only propose when none of the seeds plausibly fit
- Use kebab-case, lowercase
- First sighting is recorded with status `pending` and surfaced in the daily Slack summary
- Sighting #3 auto-promotes the slug to the seed list (status becomes `auto-promoted`)
- User may rename or merge at any time by editing `config.yml`

### Known fold-aliases (prefer the seed, do NOT re-propose these)

These concepts were swept into seeds on 2026-06-16 — map them to the seed in parentheses rather than proposing them again:

- local-models / local-ai-setup / local-ai-hosting / local-ai-deployment / vps-self-hosting → `local-and-self-hosted-ai`
- ai-video-generation / ugc-video-generation / youtube-content-automation / ad-creative-automation → `content-and-video-generation`
- agent-security / cybersecurity-fundamentals / privacy-and-compliance / ai-compliance-services → `ai-security-and-compliance`
- voice-agent-systems / conversational-agents / telegram-agent-integration → `voice-and-conversational-agents`
- sales-and-positioning / sales-frameworks / consulting-sales-ladder / agency-pricing-and-retainers / lead-generation / outreach-and-lead-generation / client-acquisition → `sales-and-lead-generation`
- model-benchmarking / model-compare / model-release-analysis / ai-industry-analysis / ai-history → `model-and-industry-analysis`
- multi-model-routing / model-routing-and-switching / model-compare → `cost-optimisation` (routing/switching for cost) or `model-and-industry-analysis` (comparing/benchmarking models)
- cms-and-content-management / mobile-app-development → `building-websites`
- research-automation / knowledge-extraction / knowledge-graphs → `memory-systems`
- agentic-os / aios-architecture / goal-driven-agents → `agent-engineering`; parallel-agent-patterns → `multi-agent-systems`
- cli-tooling → `claude-code-workflows`
- ai-policy-and-governance / ai-regulation / ai-safety-debate → `future-trends` (societal debate) or `model-and-industry-analysis` (industry/regulatory analysis); do NOT create a governance seed
- product-specific agent names (hermes-agent-mastery, hermes-agent, etc.) → `agent-engineering` — never make a seed for one product/framework
- `workflow` is too generic — never use it; pick the specific seed instead
