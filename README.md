# AI Agent Biology Memory Simulator

A Python-based AI agent simulator that mimics human-like cognitive and biological memory processes. Unlike standard LLM chatbots that simply append conversation history, this system features a dynamic, lossy, and emotion-driven memory architecture.

## Core Features

### 1. Multi-tiered Memory System
- **Working Memory (Short-term):** Acts as a mental RAM. Holds the most recent conversational context (up to a configurable limit) before it decays.
- **Episodic Memory:** Records specific events with sensory and emotional metadata (Valence, Arousal, Importance).
- **Semantic Memory:** Extracts generalized knowledge, facts, and beliefs from parsed episodic events.

### 2. Biological Memory Dynamics
- **Memory Decay (Lãng quên):** Memories gradually fade over time and through sleep cycles, simulating human forgetfulness.
- **Memory Drift (Biến dạng):** Memories can slightly distort or change details over time depending on emotional state and subsequent recalls.
- **Associative Chaining (Liên tưởng dây chuyền):** Recalling one memory naturally triggers related memories to surface, strengthening interconnected neural pathways.
- **Flashbulb Memories:** Highly emotional or critical events (high arousal + high importance) are permanently etched into the vector store and bypass the decay curve.

### 3. Sleep & Consolidation (Giấc ngủ)
The agent features a `sleep()` cycle simulating human REM sleep:
- **Consolidation:** Converts important short-term traces into long-term storage.
- **Semanticization:** Analyzes multiple episodic memories (using LLM reasoning) to deduce hidden connections, identify timelines, and form robust semantic beliefs and conclusions.
- **Garbage Collection:** Purges irrelevant or fully decayed memories to optimize performance.

### 4. Emotional Self-Model
The agent possesses a psychological `Ego` that reacts asymmetrically to stimuli:
- **Mood (-1.0 to 1.0):** Influences responses. Extreme mood swings invoke behavioral consequences (e.g., severe depression causes the agent to ignore input; mania causes hyper-association).
- **Stress (0.0 to 1.0):** Spikes rapidly during negative events but recovers very slowly.
- **Integrity:** Tracks the stability of the agent's core identity.

## Architecture & Components
- **`CognitiveEngine` (`core/engine.py`):** The central brain connecting memory extraction, self-state updates, and LLM perception/response pipelines.
- **`BiologicalMemory` (`core/memory.py`):** Handles memory traces, decay, consolidation, confabulation, and retrieval.
- **`SelfModel` (`core/self_model.py`):** Maintains emotional states, core beliefs, and behavioral modifiers.
- **`LLMClient` & `Embedder`:** Integration with LLM APIs (e.g., Google Gemini) for generation and high-dimensional vector embeddings.
- **`VectorStore`:** Internal database to simulate vector similarity search (Cosine Similarity).

## Setup & Execution
1. Configure your `.env` file with the required API keys (e.g., `GEMINI_API_KEY`).
2. Run `python main.py` to start interacting with the agent in the terminal.
3. Use the `sleep` command in the terminal prompt to force a sleep cycle and trigger deep semantic processing.
