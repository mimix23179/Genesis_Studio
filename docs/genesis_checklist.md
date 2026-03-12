### Genesis Studio is an open-source program to build your idea's to reality.
# Below here is a checklist to track what's done and what needs to be done for the project.

## Checklist

# Project Structure and Core Functionality
- [x] Create the base structure of the project.
- [x] Implement the core functionality of the program.
- [x] Create a user-friendly interface.

# Sidebar and Navigation
- [x] Implement a sidebar for navigation.
- [x] Implement a conversation list in the sidebar.
- [x] Persistently remember conversations across sessions.

# Chat Interface and Ollama Integration
- [x] Create a chat interface for user interaction
- [x] Implement a backend to use Ollama in the program
- [x] Implement llm calls to Ollama in the backend
- [x] Implement llm interaction in the chat interface
- [x] Implement smooth token streaming in the chat interface
- [x] Make the chat bubbles look nice and user-friendly
- [x] Integrate formatting in the Genesis responses (code blocks, lists, etc.)

# Settings and Customization
- [x] Create a settings page for user customization.
- [x] Implement options for customizing the chat interface (Upload images, Accent picker, Blur, etc.).
- [x] Implement Runtime options in the settings page.

# Genesis Studio Expansion
- [ ] Design the first Genesis Studio hivemind roadmap and define the boundaries for each major subsystem.
- [ ] Add an Animation Maker workspace with a scoped generation pipeline, preview surface, and export flow.
- [ ] Add an Image Generator workspace with prompt controls, model controls, job history, and local asset management.
- [ ] Add a Coding Pipeline workspace for structured code planning, diff generation, validation, and safe review.

# Coding Pipeline Foundation
- [ ] Implement a request parser that converts user coding goals into a strict patch job.
- [ ] Define a patch job schema with target files, problem summary, expected behavior, constraints, and output format.
- [ ] Add a context gatherer that selects only relevant files, symbols, and nearby code slices.
- [ ] Add architecture memory injection so Genesis can follow project-specific rules during patch generation.
- [ ] Implement a planner stage that outputs a structured patch strategy in JSON before code generation.
- [ ] Implement a patcher stage that produces unified diffs only.
- [ ] Add low-temperature deterministic settings for patch generation jobs.
- [ ] Add a patch validator that checks file scope, patch applicability, syntax safety, and convention compliance.
- [ ] Add an apply-or-reject review step so generated diffs are never blindly accepted.

# Coding Pipeline Iteration Targets
- [ ] Start with single-file bug fix jobs.
- [ ] Support two-file synchronized patch jobs.
- [ ] Support renderer/schema mismatch fixes.
- [ ] Support docstring, property, and event wiring fixes.
- [ ] Support syntax-safe local refactors before attempting larger architectural rewrites.

# Supporting Runtime Systems
- [ ] Add repository scanning and symbol lookup tools for patch jobs.
- [ ] Add dependency-aware prompt building for local Ollama coding tasks.
- [ ] Add optional compile, lint, and test execution after patch generation.
- [ ] Add patch history, review logs, and rollback-friendly job records.