# TRPG Game Master Agent Project Report Draft

This draft currently covers the first two parts of the project report: project idea description and motivation, and the specific model implementation. The sections on evaluation results, observations, and conclusions are intentionally left for later because the corresponding experimental results have not yet been finalized.

## 1. Project Idea Description and Motivation

This project studies how a large language model can serve as the game master in tabletop role-playing games (TRPGs). In a TRPG, the game is not fully determined by fixed scripts. Instead, the world evolves through continuous interaction between players and the game master. Players are free to propose actions in natural language, and the game master must interpret these actions, apply rules, decide uncertain outcomes, role-play non-player characters, and keep the story moving in a coherent and engaging direction. Because of this open-ended structure, TRPGs place much heavier demands on reasoning, memory, and improvisation than many other game formats.

The motivation for this project comes from the observation that existing LLM-based game-master systems are often narrow in scope. Many of them are designed for only one rule system, depend heavily on prompt engineering, and do not maintain a clear separation between rule knowledge, world knowledge, and evolving game state. As a result, they may generate fluent responses, but they often struggle with consistent adjudication, long-term continuity, and transparency of decision-making during extended play.

The goal of this project is therefore not simply to build a chatbot that can narrate fantasy scenes. Instead, the aim is to design a generic TRPG game-master agent with a modular architecture. The system should support multiple rulebooks, use external retrieval rather than memorizing all rules in a single prompt, and maintain a persistent notebook-style memory that can be inspected and manually edited by human users. This design is intended to make the system more extensible, more interpretable, and more practical for real gameplay.

Another important motivation is efficiency. TRPG sessions naturally accumulate large amounts of context, including dialogue history, scene state, player notes, and rule references. Passing all of this information directly into the model at every turn is both expensive and unreliable. The project therefore treats memory and retrieval as first-class components. Rules are stored in indexed documents, while game state is stored in notebook files that can be summarized, queried, and updated over time. This allows the language model to act more like a controller that decides when to read, retrieve, write, and narrate, instead of acting as the sole storage location for all information.

In summary, the project is motivated by a practical question: can an LLM-based system act as a usable and reasonably general TRPG game master if it is equipped with explicit retrieval, tool use, and notebook-based memory? The implementation developed in this project answers this question by combining language-model reasoning with modular subsystems for rules, memory, dialogue management, and controllable tool execution.

## 2. Specific Model Implementation

The current implementation follows a modular, tool-augmented multi-agent design. Rather than relying on one monolithic prompt, the system separates document retrieval, notebook memory, runtime dialogue control, and specialized agent behaviors. A command-line runtime coordinates these components during play. The current report focuses on the non-web implementation only.

### 2.1 Retrieval-Augmented Generation (RAG)

The retrieval component is responsible for providing the system with rule and lore knowledge from external documents. Source rulebooks and related materials are first converted into Markdown-based resources, then segmented into blocks with page and section metadata. These processed documents are indexed under the project's data directory, allowing the system to retrieve relevant passages when a player action depends on a rule, spell description, item effect, or world detail.

The current RAG implementation is built on LlamaIndex. It constructs vector indices for selected document collections and supports configurable embedding backends, including OpenAI-compatible embeddings, local HuggingFace embeddings, and DashScope-compatible Qwen embeddings. This design keeps the retrieval layer flexible and makes it possible to adapt the system to different deployment constraints. In practice, retrieval is not treated as a black box. The code preserves page numbers, section headings, and document identities so that later reasoning steps can refer to concrete source locations rather than only abstract semantic matches.

In addition to vector retrieval, the system also exposes document-level reading tools that operate on the Markdown representation directly. These tools can search a document by keyword, read a specific page, read a named section, or look up entries through a derived table of contents. This is important because TRPG rule use is often mixed: some situations require fuzzy semantic retrieval, while others require exact access to a known rule entry. The implementation therefore combines semantic indexing with deterministic text access, which improves both precision and interpretability.

### 2.2 Notebook-Based Memory System

The notebook system stores the evolving game state in human-readable files under the notebooks directory. Instead of hiding memory inside a model context window, the project makes the state explicit. Files such as scene state, dialogue state, campaign summaries, shared dialogue history, player notebooks, and rule summaries persist across turns and across sessions. This allows the runtime to maintain continuity even when a single LLM call only sees a limited context window.

The notebook design is intentionally editable. Human users can inspect and correct notebook contents when needed, which makes debugging and state repair much easier than in purely hidden-memory systems. The implementation distinguishes between shared notebooks and player-specific notebooks. Shared files record the global conversation and overall campaign context, while individual player folders contain private notes, event logs, and character-sheet material. Access control is also reflected in the tool layer: the game master can inspect all notebooks, while player agents are restricted to their own notebook space.

The system also uses summarization to control memory growth. For example, shared dialogue history can be summarized into a shorter rolling context, and the rule retrieval subsystem can compile a condensed rules summary notebook from larger rulebooks. This notebook-centered design directly supports the project's original objective of building a persistent, inspectable, and low-cost memory mechanism for long-running TRPG sessions.

### 2.3 Tool Layer

The tool layer is the interface between language-model reasoning and reliable external operations. In the current implementation, tools are defined as callable functions that can be passed directly into LangGraph or LangChain-style agents. This design turns important game operations into explicit actions rather than implicit text generation.

Several tool groups are implemented. First, the system includes a dice-rolling tool that supports standard TRPG dice expressions and returns transparent roll details. This avoids relying on the language model to simulate randomness. Second, the system provides document tools for reading pages, reading named sections, searching documents, and querying rule-related indices. Third, notebook tools allow the runtime to read and update structured memory files, append dialogue history, summarize long logs, and navigate player-specific notebooks. Finally, runtime tools support turn progression, speaker management, and interrupt handling during multi-party dialogue.

This tool-based design serves two purposes. On the engineering side, it reduces hallucination by delegating factual operations to deterministic functions. On the gameplay side, it makes the game master's decisions more interpretable because the runtime can show when a rule was looked up, when a notebook was updated, or when a dice roll was performed.

### 2.4 Dialogue System

The dialogue system manages turn-taking and shared conversational state for the game master and the players. The current runtime keeps a dialogue state file that stores the default speaking order, the current active speaker, round and turn information, temporary speaking overrides, and interrupt requests. A dialogue coordinator wraps these operations and provides a simple orchestration layer over the underlying tools.

At runtime, the command-line interface checks the active speaker, gathers shared context from the current dialogue summary and any extra scenario information, and then routes control to the appropriate actor. After an actor responds, the response is appended to the shared dialogue history and the turn can be advanced automatically. This structure is intentionally lightweight: instead of embedding all orchestration logic inside a single agent prompt, the code keeps dialogue control in explicit state transitions and tool calls.

This design choice is especially useful for TRPG play because dialogue is not only free-form conversation. It also needs ordering, interruption, pacing, and hand-off between the game master and multiple players. By making turn management explicit, the current implementation provides a stable runtime skeleton that later reasoning components can build on.

### 2.5 Agents

The agent layer contains specialized roles rather than one universal model instance for every task. This separation reflects the practical observation that rule interpretation, game-master narration, and player-side action generation benefit from different prompts, tools, and sometimes different models.

The primary runtime controller is the game-master agent. This agent is responsible for narrating the world, responding to player actions, consulting the available tools, and maintaining logs of its visible outputs and tool usage. In the current implementation it is built as a ReAct-style agent over the full tool set, which allows it to decide when to inspect notebooks, look up rules, advance state, or produce narrative responses. This makes the GM agent the central decision-maker during play, but not the sole holder of game knowledge.

The system also includes player-side agents. Human input is wrapped through a lightweight human-player interface that records the user's turn and allows notebook access. LLM-controlled players use a separate player agent with a narrower tool set and a player-specific prompt. These agents can consult their own notebooks, access reference materials intended for players, request interrupts, and nominate the next speaker. This setup allows the project to simulate a multi-actor TRPG table rather than only a single user talking to a single game-master model.

The most specialized component is the rule retrieval agent. This agent is not just a thin retrieval wrapper. It is implemented as a real ReAct-style planning agent with two distinct modes. In bootstrap mode, it reads rulebook content and produces a condensed rules summary notebook for later use by the game master. In search mode, it answers focused rule questions by combining retrieval, document reading tools, and explicit reasoning steps. The implementation also logs prompt snapshots, tool calls, tool outputs, and visible assistant messages, making the rule adjudication process observable during development.

The current codebase also separates model responsibilities at the configuration level. Dialogue agents use one configurable chat-model path, while the rule retrieval subsystem can use a different main model and an additional summarization model for compressed rule notes. This reflects the project's broader design philosophy: the system should be modular not only in software structure, but also in how model capacity is allocated across subtasks.

## 3. Evaluation Results of the System

At the current stage, the system has not yet been evaluated through a controlled A/B comparison against a single general-purpose LLM interface. The following evaluation is therefore a preliminary qualitative assessment inferred from the notebook state, shared dialogue history, campaign summary files, and GM debug logs. Even with this limitation, the notebook traces already make it possible to estimate how the system behaves in practice and where it provides advantages over a single large model used only through a web chat interface.

Overall, the system appears more suitable than a single standalone LLM for long-form TRPG facilitation. The main reason is not that its language generation is always better, but that its behavior is more structured. The notebooks preserve state across turns, the dialogue runtime enforces a speaking order, and the GM can ground itself in both the adventure document and the rules summary before responding. A single web-based LLM can often role-play fluently for a few turns, but it does not naturally provide persistent, editable state, explicit scene tracking, or transparent tool traces.

The notebook evidence supports this claim. In the observed Odyssey playthrough, the runtime advanced the campaign from the tavern introduction to the ambush setup outside the boar cave. The scene notebook records the current page as 34, the chapter as "Heroes of the Prophecy," the active quest as hunting the corrupted boar, and the current scene as a foggy ambush setup outside the cave. It also stores local tactical details such as the failed spiked barricade, the boar already being alerted, and the scout Javen still being in progress. This is exactly the kind of intermediate state that is difficult to maintain reliably in a plain chat session, but natural in a notebook-driven runtime.

For example, the notebook state does not merely say that combat is coming soon. It explicitly stores values such as:

> "scene": "野猪洞穴外 - 浓雾中的伏击准备"
> 
> "traps_set": {"spiked_barricade": "failed", "rope_snare": "not_attempted", "spiked_pitfall": "not_attempted"}
> 
> "boar_alerted": true

This type of state is operational rather than decorative. It preserves the tactical setup of the encounter in a form that can be reused on later turns.

The GM logs also show that the system can ground its narration in external documents rather than improvising entirely from prior conversation. Before generating major responses, the GM reads the dialogue state, checks notebook sections such as the rules summary, and reads pages from the adventure module. In the early session logs, it first reads the rules summary and then opens the relevant pages of the adventure book before composing the opening narration. Later logs show direct reading of page 34, including the boar cave, trap setup, and ambush details. This indicates that the runtime is able to anchor its behavior in explicit sources, which is an important advantage over a single-model web interface that usually relies on whatever information remains in the active chat context.

The source text itself contains concrete scenario details that later reappear in notebook state. For example, the module describes the approach to the cave as follows:

> "最终，这条小路在一个阴暗的山洞口结束。洞里回荡着刺耳的咕噜声和痛苦的尖叫声。"

It then immediately defines trap preparation as a mechanical part of the scene:

> "团队可以选择为野猪设置各种陷阱。每个陷阱都需要一个成功的感知（生存）检定来组装。失败的检定可能会导致某人跌倒并发出巨大的声响，这时野猪就会察觉到队伍的存在。"

The later notebook state, which marks the spiked barricade as failed and the boar as alerted, is consistent with this source structure.

Another practical advantage is interpretability. The current system exposes tool calls and notebook updates as first-class artifacts. This makes it possible to inspect why a response was produced, whether the GM actually consulted the adventure text, and whether scene information was written into persistent memory. In a traditional web-chat workflow, this information is largely hidden. Here, by contrast, the logs reveal when the system reads the module, when it queries rules, and when it updates scene information. The logs also show that explicit dice tools and rule-query tools are available and were invoked in other observed turns, which suggests that numeric operations can be externalized instead of being improvised in free text.

The same architecture is also useful for character creation. A plain LLM chat session cannot directly and reliably generate a correct level-1 character sheet when the required information is split across multiple large documents and must also be written into persistent state. In this project, however, the GM agent can do so with tool support. One observed notebook entry stores a generated character sheet for Bruce as follows:

> "name": "Bruce"
> 
> "race": "牛头人"
> 
> "class": "游荡者"
> 
> "hp": 10
> 
> "ac": 13
> 
> "equipment": ["刺剑", "皮甲", "盗贼工具", "背包", "撬棍", "2支火把", "50尺麻绳", "10gp"]

This is significant because the result depends on cross-document synthesis rather than on a single prompt recall. The Minotaur race comes from the Odyssey campaign-side rules, while the rogue's starting equipment comes from the original D&D rules text. A single GPT-style web session, or a simpler ReAct agent without this notebook-and-tool structure, typically cannot read such large files, extract the needed pieces from different books, combine them correctly, and then record the finished state in a reusable notebook. The GM agent, by contrast, can use tools to retrieve the relevant sources and persist the result as structured party state.

From these observations, the overall evaluation is cautiously positive. The system already demonstrates several practical advantages over single-model role-play: stronger long-horizon continuity, explicit scene tracking, document-grounded narration, and more inspectable decision-making. A concrete example is the boar-hunt sequence: instead of only remembering that "the party is fighting a boar," the notebook stores where the party is in the published adventure, what trap has failed, whether the boar has been alerted, and which companion is still scouting. This kind of structured memory is a meaningful improvement for campaign play.

At the same time, the evaluation also shows that the system is not yet fully stable as an autonomous GM. The benefits of modularity are already visible, but they are currently strongest in state persistence and traceability rather than in consistently smooth moment-to-moment role-play. For that reason, the present assessment is that the architecture is promising and already more practical than a single raw chat model for campaign management, but it still requires better coordination between narration, action adjudication, and notebook updates before it can be considered fully reliable.

## 4. Key Observations and Conclusions

Several observations can already be drawn from the notebook traces.

First, the campaign appears to be progressing correctly at the macro level. The current scene state matches the attached adventure text for the early boar-hunt chapter: the party has moved beyond the tavern introduction and reached the setup outside the boar cave, which is consistent with the published sequence in Odyssey of the Dragonlords. The notebook does not merely store a vague summary of this progress. It records concrete tactical developments, such as the failed spiked barricade and the boar being alerted, which suggests that the runtime can preserve meaningful intermediate world state rather than only chapter-level summaries.

The alignment can be seen by comparing the adventure text with the notebook trace. The module says that failed trap setup may cause noise and alert the boar, while the notebook later records:

> "traps_set": {"spiked_barricade": "failed", ...}
> 
> "boar_alerted": true
> 
> "notes": "尖刺路障设置失败，野猪可能已觉察。贾文仍在前方侦察。"

This is a strong example of successful world-state persistence.

Second, what worked best in the current system was grounding and persistence. The GM logs show a consistent pattern of reading the adventure text and consulting the rules summary before producing major narration. This led to outputs that were often well aligned with the module text, especially in the opening scene at the Sour Vintage and in the later transition toward the boar cave encounter. The architecture also performed well in preserving multi-turn state. The dialogue state tracks the active speaker, turn order, and pending interruptions, while the scene notebook preserves the current quest context and encounter status. These are precisely the areas where a single large model in a web interface usually becomes brittle over time.

Third, the weakest area in the observed run was local coordination during live play. The shared dialogue history shows repeated player-side messages asking to scan the environment, and the GM at one point continued to ask for exploration input even after the human player had already declared an intention to fight the boar directly. This suggests that the system can preserve the larger campaign state while still struggling with immediate action resolution. In other words, the architecture is already better at remembering where the game is than at always deciding what should happen next.

There is also evidence of temporary grounding drift. In the observed shared dialogue history, one GM response described the party as standing before an ancient ruin with a large stone gate and mysterious runes, which does not match the actual early Odyssey boar-hunt scenario. This is a useful failure case. It suggests that even when notebook and document grounding exist, the model can still fall back to generic fantasy patterns if the current local context is not enforced strongly enough. The fact that this drift is visible in the notebooks is itself informative: the notebook-based design does not automatically prevent mistakes, but it makes them much easier to diagnose.

Another weakness is memory consistency across notebook surfaces. The scene notebook had already advanced to page 34 and contained detailed ambush-state information, while the campaign summary still reflected a page-32 opening summary. This indicates that different memory files can drift out of sync if they are not updated together. For long campaigns, this matters because stale summaries may later mislead the agents even when the more detailed scene state is correct.

One surprising observation is that the most valuable contribution of the architecture may not be better prose generation by itself. The more important gain is control. The notebooks, tool calls, and logs turn hidden model behavior into inspectable runtime state. This means that even when the GM makes a weak decision, the failure is often observable as a mismatch between the dialogue history, the scene notebook, and the adventure source. That kind of visibility is extremely useful for debugging and would be much harder to obtain from a single-model web session.

In conclusion, the current system already demonstrates that a notebook-centered, tool-augmented architecture is a meaningful step beyond plain single-model role-play for TRPG campaigns. It works especially well for state persistence, source grounding, and runtime transparency. However, the play traces also show that smooth scene-level adjudication, stronger local grounding, and tighter synchronization between notebooks are still necessary. The campaign can progress, and it can remain connected to the source module, but the system does not yet do so with the consistency of a skilled human GM. The most defensible overall conclusion is therefore that the architecture is effective as a controllable campaign runtime, but still immature as a fully autonomous game master.