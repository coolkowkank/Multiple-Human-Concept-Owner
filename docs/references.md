# References

Public sources that informed this blueprint or provide its closest precedents. Collected 3 Nov 2026 for research use.

## Harness engineering

- Martin Fowler (Birgitta Böckeler), "Harness Engineering - first thoughts": https://www.martinfowler.com/articles/exploring-gen-ai/harness-engineering-memo.html
- Martin Fowler, "Harness engineering for coding agent users": https://www.martinfowler.com/articles/harness-engineering.html
- OpenAI, "Harness engineering: leveraging Codex in an agent-first world": https://openai.com/index/harness-engineering/

## Multi-agent "software company" frameworks

- MetaGPT (FoundationAgents): https://github.com/foundationagents/metagpt
- ChatDev (OpenBMB): https://github.com/openbmb/ChatDev
- IBM overview of MetaGPT: https://www.ibm.com/think/topics/metagpt
- IBM overview of ChatDev: https://www.ibm.com/think/topics/chatdev

## Collective ownership of AI rules and group consensus

- Anthropic + Collective Intelligence Project, "Collective Constitutional AI" (2023): https://www.anthropic.com/research/collective-constitutional-ai-aligning-a-language-model-with-public-input
- OpenAI, "Democratic inputs to AI": https://openai.com/index/democratic-inputs-to-ai/
- Google DeepMind "Habermas machine", Science (2024): https://www.science.org/doi/10.1126/science.adq2852

## Governance and recorded decisions

- Ethereum.org, "What is a DAO?": https://ethereum.org/dao/
- Michael Nygard, "Architecture Decision Records" (via Martin Fowler): https://www.martinfowler.com/bliki/ArchitectureDecisionRecord.html

## Licensing

- Choose a License, MIT: https://choosealicense.com/licenses/mit/
- Choose a License, Apache 2.0: https://choosealicense.com/licenses/apache-2.0/
- Choose a License, non-software licenses: https://choosealicense.com/non-software/

## Agent harnesses and long-running agents (added 4 Nov 2026)

- Anthropic, "Effective harnesses for long-running agents" (2025-11-26): https://www.anthropic.com/research/effective-harnesses-for-long-running-agents - session-bridging via a progress file + git history, incremental one-feature-at-a-time progress, explicit end-to-end testing, "get your bearings" start-of-session ritual. Adopted: the bus LOG + git history is our progress bridge; one batch per turn; reviewer re-runs the verify command.
- HumanLayer (Dex Horthy), "12 Factor Agents" (2025-04-03): https://www.humanlayer.com/blog/12-factor-agents - own your prompts and control flow, unify execution state and business state, launch/pause/resume with simple APIs, contact humans with tool calls, small focused agents, stateless reducer. Adopted: seat prompts are code-owned, STATE/LOG unify state, gates are the human-contact tool, seats are single-responsibility reducers over bus state.
- A2A protocol, "A2A and MCP": https://a2a-protocol.org/latest/topics/a2a-and-mcp/ - A2A for agent-to-agent task delegation, MCP for tool access; complementary layers. Mapped as the standards-track future for cross-platform seat communication; the v1 relay is deliberately minimal and loopback-only.
- MAS-FIRE, "Fault Injection and Reliability Evaluation for LLM-Based Multi-Agent Systems": https://arxiv.org/html/2602.19843 - fault taxonomy (intra-agent, inter-agent: loss, delay, routing) and resilience/effectiveness metrics. Basis for the fault-injection and soak test stages.
- "Assessing and Enhancing the Robustness of LLM-based Multi-Agent Systems Through Chaos Engineering": https://arxiv.org/html/2505.03096 - chaos-engineering method for MAS robustness; informs the planned soak design.

## Multi-agent orchestration frameworks (surveyed 4 Nov 2026)

- Comparison surveys of LangGraph, CrewAI, AutoGen and OpenAI Agents SDK (e.g. https://arize.com/ai-agents/agent-frameworks/): all provide in-process agent graphs with framework-managed state and model APIs. We did not adopt one: the blueprint's seats must run on different platforms owned by different humans, which an in-process framework does not span; the bus + adapter interface is the cross-platform equivalent. Framework adapters remain possible per seat.
