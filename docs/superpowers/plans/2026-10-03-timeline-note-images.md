# Timeline Note Image Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current worktree.

**Goal:** Add local image insertion, mixed text/image editing, resizing, position dragging, five layout modes, drag-and-drop, image paste, and shell clipboard menu support to the completed-session timeline note composer.

**Architecture:** Keep the existing single-page frontend and Python loopback backend. Replace only the timeline note textarea with a native `contenteditable` editor whose image nodes serialize into a structured `content` array; keep the legacy `text` projection for existing APIs and old notes. Copy new image bytes into each session's `note-images/` directory during note save, serve only validated session-local image paths, and retain the existing note snapshot checks.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, Python standard library HTTP server and JSON persistence, Tauri 2 Rust native menu, Node `node:test`, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-03-timeline-note-images-design.md`

## Global Constraints

- The feature covers only the completed-session timeline note `.tn-card`; do not change the recording-time `.notepop` shortcut note.
- Images are copied into the current session's `note-images/` directory; the source file is never moved or overwritten.
- New notes persist both a plain-text `text` projection and structured `content`; old `{t, text}` notes remain readable and editable.
- Supported image MIME types are PNG, JPEG, GIF, and WebP; reject one image larger than 20 MiB.
- The first release supports only `inline`, `square`, `top-bottom`, `behind`, and `front` layouts; do not expose unsupported Word layout options as active controls.
- `flow` images move by changing their document anchor; `free` images move inside the note editor and persist relative `x/y` coordinates.
- Image data stays local and never enters transcription, summary, or cloud APIs.
- Preserve existing note timestamp bounds, stale snapshot checks, dark appearance, viewport constraints, and unrelated worktree changes.

## Review Focus

- A stale or missing asset must not make the backend read outside the current session or silently keep a broken reference; covered by Task 1 path and asset validation tests.
- A note containing text before, between, and after multiple images must round-trip without reordering or losing line breaks; covered by Task 2 serialization tests.
- Dragging an image must not accidentally resize it, edit its alt/file label, or open the browser's file navigation; covered by Task 3 pointer and drop-wiring tests.
- Switching between flow and free layouts must preserve the right position representation and restore it after reopening; covered by Task 3 layout/position tests and Task 1 persistence tests.
- Copy/paste must continue to work for normal text while image paste is intercepted only inside the note editor; covered by Task 4 shell/menu and frontend shortcut tests.

### Task 1: Persist note content and image assets in the backend

**Files:**
- Modify: `app.py:3660-3679,4651-4765,5010-5034,5150-5300,5496-5509`
- Create: `tests/test_timeline_note_images.py`
- Modify: `tests/test_timeline_notes.py`

**Interfaces:**
- Consumes: existing `App.add_transcript_note`, `App.update_transcript_note`, `App.delete_transcript_note`, `App._write_md`, and `/api/timeline_note*` request paths.
- Produces: `content`-aware note mutation methods, validated session-local image serving at `/note-image/<sid>/<filename>`, and Markdown output with relative image links for later frontend work.

- [ ] **Step 1: Write failing Python tests**

  Add tests for a three-node text/image/text note, multiple assets in one note, the `note-images/` directory and generated filenames, legacy text-only editing, rejected traversal/unsupported MIME/over-20-MiB assets, deletion cleanup, relative Markdown links, and image GET path validation. Keep the existing stale-index tests active.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `python3 -m unittest discover -s tests -p 'test_timeline_note_images.py' -v`

  Expected: FAIL because the current note methods do not accept `content`/assets and no image route exists.

- [ ] **Step 3: Implement the backend content helpers and note mutation interface**

  Add helpers in `App` for plain-text projection, extracting referenced `note-images/` paths, validating content nodes, decoding base64 assets, writing assets with `uuid.uuid4().hex` names, and removing unreferenced files. Extend `add_transcript_note` and `update_transcript_note` with optional `content` and `assets` arguments while retaining the existing text-only call shape. Materialize new assets before the session write, remove newly written files on a failed mutation, and preserve the current time/snapshot validation.

- [ ] **Step 4: Extend Markdown persistence and the image GET route**

  Make `_write_md` render text nodes in order and emit `![safe filename](note-images/<generated-file>)` for image nodes. Add a strict `/note-image/<sid>/<filename>` handler that permits only a safe session ID, a filename under that session's `note-images/`, and supported image MIME types. Pass `content` and `assets` from the three existing POST routes.

- [ ] **Step 5: Run the focused tests to verify they pass**

  Run: `python3 -m unittest discover -s tests -p 'test_timeline_note_images.py' -v && python3 -m unittest discover -s tests -p 'test_timeline_notes.py' -v`

  Expected: all focused image and legacy timeline-note tests PASS.

- [ ] **Step 6: Commit the backend task**

  ```bash
  git add app.py tests/test_timeline_note_images.py tests/test_timeline_notes.py
  git commit -m "feat: persist timeline note images"
  ```

### Task 2: Replace the paper note textarea with a structured image-aware editor

**Files:**
- Modify: `index.html:1780-1865,2811-2829,5030-5240`
- Create: `tests/timeline-note-images.test.js`
- Modify: `tests/timeline-note-ui.test.js`

**Interfaces:**
- Consumes: Task 1's `content` node schema, `assets` save payload, `/note-image/<sid>/<filename>`, and existing note add/update response shape.
- Produces: `renderTranscriptNoteContent(content, legacyText)`, `serializeTranscriptNoteContent()`, image insertion controls, and a note save payload that preserves text/image order.

- [ ] **Step 1: Write failing frontend wiring tests**

  Assert the paper card contains a `contenteditable` editor, an image picker accepting the four supported MIME types, generated image nodes marked `contenteditable=false`, structured serialization hooks, multi-image insertion, and the existing Enter/Shift+Enter behavior. Assert old text-only notes still have a rendering path.

- [ ] **Step 2: Run the focused frontend tests to verify they fail**

  Run: `node --test tests/timeline-note-images.test.js tests/timeline-note-ui.test.js`

  Expected: FAIL because the paper card still contains only `textarea#transcriptNoteText`.

- [ ] **Step 3: Implement the editor markup and scoped CSS**

  Replace the textarea with `div#transcriptNoteText[contenteditable=true]`, add a hidden multiple image input and visible “插入图片” control, and add styles for editor text, image selection, delete button, corner resize handle, drag indicator, and dark mode. Keep `.tn-card` sizing and existing paper animation unchanged.

- [ ] **Step 4: Implement content rendering and serialization**

  Render only DOM created from validated `content` nodes; convert text newlines to `<br>`, create image nodes with local `src`, layout, display width, and position data, and never restore arbitrary stored HTML. Serialize text nodes and image nodes in DOM order, produce the legacy `text` projection, and preserve the current caret/range when inserting an image.

- [ ] **Step 5: Wire file selection, preview, and note save/update**

  Read selected files as base64 previews after MIME and 20 MiB checks, assign temporary asset IDs, insert them at the current range in selection order, and send `{content, assets}` to `/api/timeline_note` or `/api/timeline_note_update`. Load existing notes through the new renderer; keep the current timestamp and stale-note snapshot behavior.

- [ ] **Step 6: Run the focused frontend tests to verify they pass**

  Run: `node --test tests/timeline-note-images.test.js tests/timeline-note-ui.test.js`

  Expected: all structured-editor, legacy-note, save-payload, and keyboard-hint tests PASS.

- [ ] **Step 7: Commit the editor task**

  ```bash
  git add index.html tests/timeline-note-images.test.js tests/timeline-note-ui.test.js
  git commit -m "feat: add image-aware timeline note editor"
  ```

### Task 3: Add drag/drop, paste, resizing, movement, and layout menu behavior

**Files:**
- Modify: `index.html:1780-1865,2811-2829,5030-5240`
- Modify: `tests/timeline-note-images.test.js`

**Interfaces:**
- Consumes: Task 2's editor node data attributes, selection/range helpers, and serialization payload.
- Produces: drag/drop and paste event handlers, resize and movement persistence, and the five-mode image context menu.

- [ ] **Step 1: Extend failing frontend tests**

  Add assertions for `dragover`/`drop` insertion indicators, image-only clipboard interception with plain-text paste passthrough, pointer-capture resize handles, flow-anchor movement, free `x/y` movement, and exactly the five active layout values (`inline`, `square`, `top-bottom`, `behind`, `front`).

- [ ] **Step 2: Run the focused test to verify the new assertions fail**

  Run: `node --test tests/timeline-note-images.test.js`

  Expected: FAIL because no image drag, paste, resize, position, or layout-menu wiring exists.

- [ ] **Step 3: Implement drag/drop and image paste**

  Track the last valid caret Range; on image drag-over show a thin insertion line and prevent browser navigation; on drop insert one or more images at the indicated Range. Handle clipboard image files only when the editor is focused, while allowing ordinary text copy/paste to follow native contenteditable behavior.

- [ ] **Step 4: Implement resize and movement**

  Use a dedicated corner handle with pointer capture for proportional resize and clamp the width to the editor's available width. For `flow` layouts, pointer-drag the image to a caret insertion line and update DOM order; for `free` layouts, pointer-drag within the editor and persist clamped relative `position.x/y`. Distinguish movement from resize at pointer-down so the two gestures cannot cross-trigger.

- [ ] **Step 5: Implement the five-option right-click layout menu**

  Open a fixed menu only for the selected image, apply the selected `layout` value, preserve the image asset and reusable position data, and close on outside pointer or Escape. Do not expose unsupported Word modes. Re-render without losing the editor selection or note content.

- [ ] **Step 6: Run the focused tests to verify they pass**

  Run: `node --test tests/timeline-note-images.test.js tests/timeline-note-ui.test.js`

  Expected: all drag/drop, paste, resize, movement, layout, and existing note tests PASS.

- [ ] **Step 7: Commit the interaction task**

  ```bash
  git add index.html tests/timeline-note-images.test.js
  git commit -m "feat: add draggable timeline note images"
  ```

### Task 4: Restore native shell clipboard commands and run the full verification set

**Files:**
- Modify: `tauri-shell/src/main.rs:381-401`
- Create: `tests/shell-clipboard-menu.test.js`
- Modify: `README.md` only if the implemented behavior requires a user-facing feature note

**Interfaces:**
- Consumes: Task 2's contenteditable editor and the current macOS Tauri menu construction.
- Produces: native Edit → Copy/Cut/Paste/Select All commands without intercepting normal editor shortcuts.

- [ ] **Step 1: Write the failing shell-menu test**

  Assert that the macOS menu construction includes standard Edit submenu items for Copy, Cut, Paste, and Select All, while preserving the existing microphone menu item.

- [ ] **Step 2: Run the test to verify it fails**

  Run: `node --test tests/shell-clipboard-menu.test.js`

  Expected: FAIL because `app_menu` currently exposes no Edit submenu.

- [ ] **Step 3: Add the standard Tauri Edit submenu**

  Use Tauri's predefined menu items under a macOS `Edit` submenu; do not add custom clipboard commands or alter the existing app menu event handling. Keep Windows behavior on WebView2 native shortcuts unless runtime testing demonstrates a separate failure.

- [ ] **Step 4: Run the full automated verification set**

  Run: `node --test tests/*.test.js && python3 -m unittest discover -s tests -v`

  Expected: all Node and Python tests PASS. If an unrelated pre-existing failure remains, record its exact test and output separately from image-note results.

- [ ] **Step 5: Perform live UI verification**

  Launch the test App using the repository's existing workflow and verify: one/multiple image insertion, text-image-text order, Finder copy/paste, drag/drop indicator, resize, flow movement, free movement, five layout modes, delete/modify persistence, dark mode, narrow window constraints, and a reopened project. Confirm project folder contents and served image paths.

- [ ] **Step 6: Commit shell and verification changes**

  ```bash
  git add tauri-shell/src/main.rs tests/shell-clipboard-menu.test.js README.md
  git commit -m "feat: restore native clipboard menu for notes"
  ```

