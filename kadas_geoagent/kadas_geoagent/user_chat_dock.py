# -*- coding: utf-8 -*-
"""KADAS-only "user mode" wrapper around the shared OpenGeoAgent chat dock.

The shared :class:`open_geoagent.dialogs.chat_dock.ChatDockWidget` (which lives
in the QGIS OpenGeoAgent plugin and is reused unchanged by KADAS) is a rich
"developer" panel: provider/model pickers, agent modes, permission profiles, a
jobs table, tool-call details, screenshots and so on.

KADAS users wanted a *much* simpler face on the same engine: just an "ask" box,
the answer, and a list of previous questions -- nothing else. This module adds
that without forking or touching the shared dock. It:

* subclasses ``ChatDockWidget`` so all of the send/stream/worker plumbing,
  settings and project history are reused verbatim;
* wraps the original (developer) widget and a new minimal "user" page in a
  :class:`QStackedWidget`, with a header toggle to switch between them;
* drives the user page from the same ``self._messages`` list the developer
  transcript renders, by hooking the single ``_render_transcript`` refresh; and
* renders answers with ``QTextBrowser.setMarkdown`` so Claude's Markdown
  (tables, code fences, blockquotes) shows as formatted text rather than the
  developer dock's lighter custom HTML renderer.

The class is built lazily via :func:`build_kadas_chat_dock_class` because the
shared base class is only importable once :mod:`._shared` has put
``open_geoagent`` on ``sys.path``.
"""

from __future__ import annotations

# --- Pure helpers (no Qt / no shared package) -------------------------------
# Kept at module scope so they can be unit-tested in plain CI without QGIS,
# KADAS or PyQt installed.


def _message_text(msg, prefer_display=False):
    """Return the best text for a stored chat message.

    ``display_body`` carries UI-only annotations (e.g. an "image attached"
    note appended to the user's prompt). For the question line we want the
    clean prompt (``body``); for answers either is fine.
    """
    if prefer_display:
        text = msg.get("display_body") or msg.get("body") or ""
    else:
        text = msg.get("body") or ""
    return str(text).strip()


def _exchanges_from_messages(messages):
    """Group the flat message list into question/answer exchanges.

    Returns a list of dicts ``{"prompt_index", "question", "answer"}`` where
    ``prompt_index`` is the position of the originating "You" message (used as a
    stable id for selection). Consecutive assistant messages after a question
    are joined into a single answer; assistant messages with no preceding
    question (e.g. a restored transcript that starts mid-conversation) get an
    exchange with an empty question.
    """
    exchanges = []
    current = None
    for index, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        sender = msg.get("sender", "")
        if sender == "You":
            current = {
                "prompt_index": index,
                "question": _message_text(msg),
                "_answer_parts": [],
            }
            exchanges.append(current)
        else:
            body = _message_text(msg, prefer_display=True)
            if current is None:
                current = {
                    "prompt_index": index,
                    "question": "",
                    "_answer_parts": [],
                }
                exchanges.append(current)
            if body:
                current["_answer_parts"].append(body)
    for exchange in exchanges:
        exchange["answer"] = "\n\n".join(exchange.pop("_answer_parts"))
    return exchanges


def _compose_user_markdown(question, answer, running=False):
    """Build the Markdown shown in the user-mode answer pane for one exchange."""
    parts = []
    question = (question or "").strip()
    answer = (answer or "").strip()
    if question:
        parts.append(f"**You asked:**\n\n{question}")
        parts.append("\n---\n")
    if answer:
        parts.append(answer)
    elif running:
        parts.append("_Working…_")
    else:
        parts.append("_(No response yet.)_")
    return "\n\n".join(parts)


def _history_label(question, limit=80):
    """Return a single-line, length-capped label for the previous-questions list."""
    text = " ".join((question or "").split())
    if not text:
        return "(image prompt)"
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


# Persisted under QSettings; kept distinct from the shared dock's prefix so the
# KADAS-only toggle never collides with OpenGeoAgent settings.
KADAS_SETTINGS_PREFIX = "kadas_geoagent/"

_CACHED_CLASS = None


def build_kadas_chat_dock_class():
    """Return (and cache) the KADAS user-mode chat dock class.

    Importing the shared base class must happen *after*
    ``ensure_open_geoagent_importable`` has run, so the subclass is defined
    inside this factory rather than at module import time.
    """
    global _CACHED_CLASS
    if _CACHED_CLASS is not None:
        return _CACHED_CLASS

    from qgis.PyQt.QtWidgets import (
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        QTextBrowser,
        QVBoxLayout,
        QWidget,
    )

    from open_geoagent.dialogs.chat_dock import (
        ChatDockWidget,
        PromptTextEdit,
        _markdown_to_basic_html,
        _qt_value,
    )

    from geoagent.core.telemetry import FEEDBACK_STATUSES, FeedbackLogger

    class KadasChatDockWidget(ChatDockWidget):
        """Shared chat dock with a minimal KADAS "user mode" front end."""

        def __init__(self, iface, parent=None):
            # Set before super().__init__ because the base constructor renders
            # restored project history, which calls our _render_transcript
            # override; the _user_ready guard makes that a no-op until the
            # user-mode widgets exist.
            self._user_ready = False
            self._user_selected_index = None
            self._user_follow_latest = True
            # Telemetry sink for the Developer-Mode "Training AI" feedback.
            self._feedback_logger = FeedbackLogger()
            # Path of a Markdown skill file to "upskill" the agent with.
            self._skill_file_path = ""
            # Whether to retrieve the real KADAS API reference for each question.
            self._api_docs_enabled = False
            super().__init__(iface, parent)
            self.setWindowTitle("KADAS GeoAgent")
            self._build_user_mode_ui()
            self._restore_skill_file()
            self._restore_api_docs_pref()
            self._user_ready = True
            # Per product decision: always open in the simple user mode.
            self._set_developer_mode(False)
            self._sync_user_view()

        # -- UI construction --------------------------------------------------

        def _build_user_mode_ui(self):
            """Wrap the developer widget and a new user page in a stack."""
            developer_widget = self.widget()

            # KADAS already gates User/Developer with the header button below, so the
            # base dock's own Mode selector would be a second, redundant developer
            # switch nested inside developer mode. Pin it to Developer and hide it.
            self.ui_mode_combo.setCurrentText("Developer")
            self.ui_mode_combo.hide()
            self.ui_mode_label.hide()

            container = QWidget()
            outer = QVBoxLayout(container)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            header = QWidget()
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(8, 4, 8, 4)
            title = QLabel("GeoAgent")
            title.setStyleSheet("font-weight: 600;")
            header_layout.addWidget(title)
            header_layout.addStretch(1)
            self.mode_toggle = QPushButton("Developer mode")
            self.mode_toggle.setCheckable(True)
            self.mode_toggle.setToolTip(
                "Switch between the simple user view and the full developer view."
            )
            self.mode_toggle.toggled.connect(self._set_developer_mode)
            header_layout.addWidget(self.mode_toggle)
            outer.addWidget(header)

            self.mode_stack = QStackedWidget()
            self.mode_stack.addWidget(self._build_user_page())  # index 0: user
            self.mode_stack.addWidget(developer_widget)  # index 1: dev
            outer.addWidget(self.mode_stack, 1)

            # "Training AI" telemetry panel. It lives below the stack so it sits
            # under the agent response in *either* view (simple answer pane or
            # full developer transcript). Hidden until Developer mode is active.
            #
            # Wrapped in a QScrollArea: the panel's minimum height (skill picker,
            # API-docs checkbox, status combo, notes box, footer) exceeded what a
            # short dock could give it, so the bottom rows -- including the "Log
            # feedback" button -- were clipped with no way to reach them. A scroll
            # area can shrink below its child's minimum and shows a scrollbar.
            self.training_panel = self._build_training_panel()
            self.training_scroll = QScrollArea()
            self.training_scroll.setWidget(self.training_panel)
            self.training_scroll.setWidgetResizable(True)
            self.training_scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.training_scroll.setHorizontalScrollBarPolicy(
                _qt_value("ScrollBarPolicy", "ScrollBarAlwaysOff")
            )
            # Floor keeps it usable when squeezed; ceiling stops it crowding out
            # the transcript on a tall dock.
            self.training_scroll.setMinimumHeight(90)
            self.training_scroll.setMaximumHeight(280)
            self.training_scroll.setVisible(False)
            outer.addWidget(self.training_scroll)

            self.setWidget(container)

        def _build_training_panel(self):
            """Build the Developer-Mode "Training AI" feedback section."""
            panel = QFrame()
            panel.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(4)

            heading = QLabel("Training AI")
            heading.setStyleSheet("font-weight: 600;")
            layout.addWidget(heading)

            hint = QLabel(
                "Rate the answer above and add notes; feedback is logged for "
                "training."
            )
            hint.setStyleSheet("color: gray; font-size: 10px;")
            hint.setWordWrap(True)
            layout.addWidget(hint)

            # Upskill-with-a-file selector: pick a Markdown skill/bundle file
            # whose content is injected into the agent's system context.
            skill_row = QHBoxLayout()
            skill_row.addWidget(QLabel("Upskill with:"))
            self.skill_file_edit = QLineEdit()
            self.skill_file_edit.setReadOnly(True)
            self.skill_file_edit.setPlaceholderText("No skill file selected")
            self.skill_file_edit.setToolTip(
                "A Markdown file (e.g. a SKILL.md or skills_prompt.md) whose "
                "contents are prepended to each request as extra guidance."
            )
            skill_row.addWidget(self.skill_file_edit, 1)
            self.skill_browse_btn = QPushButton("Browse…")
            self.skill_browse_btn.clicked.connect(self._browse_skill_file)
            skill_row.addWidget(self.skill_browse_btn)
            self.skill_clear_btn = QPushButton("Clear")
            self.skill_clear_btn.clicked.connect(self._clear_skill_file)
            skill_row.addWidget(self.skill_clear_btn)
            layout.addLayout(skill_row)

            # Auto-inject the real KADAS Python API for the current question.
            # Off by default: it is a context/latency trade, and the point of the
            # benchmarks is to measure whether it helps rather than assume it.
            self.api_docs_check = QCheckBox(
                "Include KADAS API reference for the question"
            )
            self.api_docs_check.setToolTip(
                "Look up the relevant KADAS API (generated from its SIP bindings) by "
                "keyword and add it to each request, so the model uses real signatures "
                "instead of guessing.\n\n"
                "Adds roughly 1-3k tokens to the turn it matches."
            )
            self.api_docs_check.toggled.connect(self._set_api_docs_enabled)
            layout.addWidget(self.api_docs_check)

            status_row = QHBoxLayout()
            status_row.addWidget(QLabel("Status:"))
            self.training_status = QComboBox()
            # Order matches FEEDBACK_STATUSES; default to Unclassified.
            for value in FEEDBACK_STATUSES:
                self.training_status.addItem(value.capitalize(), value)
            self.training_status.setCurrentIndex(
                list(FEEDBACK_STATUSES).index("unclassified")
            )
            status_row.addWidget(self.training_status, 1)
            layout.addLayout(status_row)

            self.training_feedback = QPlainTextEdit()
            self.training_feedback.setPlaceholderText(
                "What was good or wrong about this answer? (optional)"
            )
            self.training_feedback.setMaximumHeight(60)
            layout.addWidget(self.training_feedback)

            footer = QHBoxLayout()
            self.training_status_label = QLabel("")
            self.training_status_label.setStyleSheet("color: gray; font-size: 10px;")
            self.training_status_label.setWordWrap(True)
            footer.addWidget(self.training_status_label, 1)
            self.training_log_btn = QPushButton("Log feedback")
            self.training_log_btn.clicked.connect(self._log_training_feedback)
            footer.addWidget(self.training_log_btn)
            layout.addLayout(footer)

            return panel

        def _build_user_page(self):
            """Build the minimal user-mode page: history, answer, ask box."""
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setSpacing(6)

            history_label = QLabel("Previous questions")
            history_label.setStyleSheet("font-size: 10px; color: gray;")
            layout.addWidget(history_label)

            self.user_history_list = QListWidget()
            self.user_history_list.setMaximumHeight(90)
            self.user_history_list.itemClicked.connect(self._on_user_history_clicked)
            layout.addWidget(self.user_history_list)

            self.user_output = QTextBrowser()
            self.user_output.setReadOnly(True)
            self.user_output.setOpenExternalLinks(True)
            self.user_output.setPlaceholderText("Ask a question to get started.")
            layout.addWidget(self.user_output, 1)

            self.user_prompt_input = PromptTextEdit()
            self.user_prompt_input.setPlaceholderText(
                "Ask GeoAgent…  (Ctrl+Enter to send)"
            )
            self.user_prompt_input.setMaximumHeight(80)
            self.user_prompt_input.send_requested.connect(self._user_send)
            layout.addWidget(self.user_prompt_input)

            footer = QHBoxLayout()
            self.user_status = QLabel("")
            self.user_status.setStyleSheet("color: gray; font-size: 10px;")
            self.user_status.setWordWrap(True)
            footer.addWidget(self.user_status, 1)
            self.user_send_btn = QPushButton("Ask")
            self.user_send_btn.clicked.connect(self._user_send)
            footer.addWidget(self.user_send_btn)
            layout.addLayout(footer)

            return page

        # -- Mode switching ---------------------------------------------------

        def _set_developer_mode(self, developer):
            """Show the developer (True) or user (False) page."""
            self.mode_stack.setCurrentIndex(1 if developer else 0)
            self.mode_toggle.setText("User mode" if developer else "Developer mode")
            # The Training AI telemetry section is a developer-mode affordance.
            # Toggle the scroll wrapper, not the panel: the panel is the scroll
            # area's child, so hiding it would leave an empty scroll area behind.
            if getattr(self, "training_scroll", None) is not None:
                self.training_scroll.setVisible(bool(developer))
            if not developer:
                self._sync_user_view()

        # -- Training AI telemetry --------------------------------------------

        def _current_exchange(self):
            """Return the exchange the training feedback applies to, or None."""
            exchanges = _exchanges_from_messages(self._messages)
            if not exchanges:
                return None
            if self._user_selected_index is not None:
                for exchange in exchanges:
                    if exchange["prompt_index"] == self._user_selected_index:
                        return exchange
            return exchanges[-1]

        def _log_training_feedback(self):
            """Record the Training AI feedback for the current exchange."""
            exchange = self._current_exchange()
            if exchange is None:
                self.training_status_label.setText(
                    "Ask a question first — there is no answer to rate yet."
                )
                return
            status = self.training_status.currentData()
            notes = self.training_feedback.toPlainText().strip()
            extra = {}
            try:
                # Best-effort provenance so feedback is attributable to a run.
                extra["provider"] = self._qt_setting_provider()
            except Exception:
                pass
            event = self._feedback_logger.record_feedback(
                status=status,
                feedback=notes,
                question=exchange.get("question", ""),
                answer=exchange.get("answer", ""),
                integration="kadas",
                **extra,
            )
            self.training_feedback.clear()
            self.training_status.setCurrentIndex(
                list(FEEDBACK_STATUSES).index("unclassified")
            )
            self.training_status_label.setText(
                "Logged “{status}” feedback to {path}".format(
                    status=event.get("status", "unclassified"),
                    path=self._feedback_logger.log_path,
                )
            )

        def _qt_setting_provider(self):
            """Return the configured provider name for feedback provenance."""
            from qgis.PyQt.QtCore import QSettings

            settings = QSettings()
            value = settings.value(KADAS_SETTINGS_PREFIX + "provider", "")
            return str(value or "")

        # -- Upskill-with-a-file ----------------------------------------------

        _SKILL_FILE_SETTING = KADAS_SETTINGS_PREFIX + "skill_file"

        def _restore_skill_file(self):
            """Load the persisted skill-file selection into the UI."""
            from qgis.PyQt.QtCore import QSettings

            path = str(QSettings().value(self._SKILL_FILE_SETTING, "") or "")
            self._set_skill_file(path, persist=False)

        def _set_skill_file(self, path, persist=True):
            """Record the selected skill file and reflect it in the UI."""
            from qgis.PyQt.QtCore import QSettings

            self._skill_file_path = str(path or "")
            if getattr(self, "skill_file_edit", None) is not None:
                self.skill_file_edit.setText(self._skill_file_path)
            if persist:
                QSettings().setValue(self._SKILL_FILE_SETTING, self._skill_file_path)

        def _browse_skill_file(self):
            """Prompt for a Markdown skill file to upskill the agent with."""
            import os

            start_dir = ""
            if self._skill_file_path:
                start_dir = os.path.dirname(self._skill_file_path)
            path, _filter = QFileDialog.getOpenFileName(
                self,
                "Select skill file",
                start_dir,
                "Markdown files (*.md *.markdown);;All files (*)",
            )
            if path:
                self._set_skill_file(path)

        def _clear_skill_file(self):
            """Clear the selected skill file."""
            self._set_skill_file("")

        def _selected_skill_text(self):
            """Return the trimmed contents of the selected skill file, or ''.

            Read fresh on each turn so edits to the file take effect without
            reselecting it. Unreadable/oversized files degrade to ''.
            """
            import os

            path = self._skill_file_path
            if not path or not os.path.isfile(path):
                return ""
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read(200_000)
            except OSError:
                return ""
            return text.strip()

        _API_DOCS_SETTING = KADAS_SETTINGS_PREFIX + "inject_api_docs"

        def _restore_api_docs_pref(self):
            """Load the persisted 'include API reference' toggle into the UI."""
            from qgis.PyQt.QtCore import QSettings

            enabled = QSettings().value(self._API_DOCS_SETTING, False, type=bool)
            self._api_docs_enabled = bool(enabled)
            if getattr(self, "api_docs_check", None) is not None:
                self.api_docs_check.setChecked(self._api_docs_enabled)

        def _set_api_docs_enabled(self, enabled):
            """Persist the toggle so it survives a restart."""
            from qgis.PyQt.QtCore import QSettings

            self._api_docs_enabled = bool(enabled)
            QSettings().setValue(self._API_DOCS_SETTING, self._api_docs_enabled)

        def _api_docs_text(self, prompt):
            """Return KADAS API reference relevant to *prompt*, or ''.

            Retrieved fresh per turn by keyword, so only the API the question is about is
            paid for. Degrades to '' if geoagent is too old to ship the packs.
            """
            if not getattr(self, "_api_docs_enabled", False):
                return ""
            try:
                from geoagent.core.context_docs import build_context_block
            except ImportError:
                return ""
            try:
                return build_context_block(prompt)
            except OSError:
                return ""

        def _build_prompt_with_context(self, prompt):
            """Prepend the skill file and (optionally) the KADAS API reference.

            Extends the shared dock's context builder so a chosen SKILL.md /
            skills_prompt.md becomes extra guidance for the turn — the "upskill"
            step surfaced in the UI — and so the "Include KADAS API reference"
            toggle adds the real signatures for whatever was asked.

            Both go into the **user message**, never the system prompt. The system
            prompt plus the tool definitions form a byte-stable prefix that llama.cpp
            caches: re-sending an identical ~16k prefix to a local qwen2.5-7b costs
            ~0.5s, while changing it costs 13-22s because the whole prefix must be
            reprefilled. This guidance varies per question, so putting it in the system
            prompt would destroy that cache on every turn.

            The raw ``prompt`` (not the composed history) drives retrieval: matching
            triggers against the transcript would keep firing on whatever was discussed
            several turns ago.
            """
            composed = super()._build_prompt_with_context(prompt)

            api_docs = self._api_docs_text(prompt)
            if api_docs:
                composed = f"{api_docs}\n{composed}"

            skill_text = self._selected_skill_text()
            if not skill_text:
                return composed
            return (
                "Apply the following learned skills when relevant to the "
                "request.\n\n"
                f"--- BEGIN SKILLS ---\n{skill_text}\n--- END SKILLS ---\n\n"
                f"{composed}"
            )

        # -- User actions -----------------------------------------------------

        def _user_send(self):
            """Send the user-mode prompt through the shared chat pipeline."""
            text = self.user_prompt_input.toPlainText().strip()
            if not text:
                return
            if self._worker is not None:
                self.user_status.setText(
                    "Please wait for the current answer to finish."
                )
                return
            # Reuse the developer prompt box + full _send_prompt pipeline
            # (settings, context, worker, jobs, streaming) unchanged.
            self.prompt_input.setPlainText(text)
            self.user_prompt_input.clear()
            self._user_follow_latest = True
            self._send_prompt()
            self._sync_user_view()

        def _on_user_history_clicked(self, item):
            """Show the clicked previous question and its answer."""
            index = item.data(_qt_value("ItemDataRole", "UserRole"))
            self._user_selected_index = index
            self._user_follow_latest = False
            self._sync_user_view()

        # -- Sync from the shared message store --------------------------------

        def _send_prompt(self):
            """Follow the newest exchange whenever a prompt is sent."""
            self._user_follow_latest = True
            super()._send_prompt()

        def _render_transcript(self):
            """Refresh both the developer transcript and the user view."""
            super()._render_transcript()
            self._sync_user_view()

        def _clear_transcript(self):
            super()._clear_transcript()
            self._sync_user_view()

        def _on_worker_finished(self, result):
            super()._on_worker_finished(result)
            # super() clears self._worker only after rendering, so re-sync to
            # drop the "Working..." state and re-enable the Ask button.
            self._sync_user_view()

        def _sync_user_view(self):
            """Rebuild the user page from the shared ``self._messages`` list."""
            if not self._user_ready:
                return

            running = self._worker is not None
            self.user_send_btn.setEnabled(not running)
            self.user_prompt_input.setEnabled(not running)
            # "Working…" while a request is in flight; cleared once it finishes
            # (this also clears any transient "Please wait" hint from _user_send).
            self.user_status.setText("Working…" if running else "")

            exchanges = _exchanges_from_messages(self._messages)

            user_role = _qt_value("ItemDataRole", "UserRole")
            self.user_history_list.blockSignals(True)
            self.user_history_list.clear()
            for exchange in exchanges:
                item = QListWidgetItem(_history_label(exchange["question"]))
                item.setData(user_role, exchange["prompt_index"])
                self.user_history_list.addItem(item)
            self.user_history_list.blockSignals(False)

            if not exchanges:
                self._user_selected_index = None
                self._render_user_exchange(None, running)
                return

            if self._user_follow_latest or self._user_selected_index is None:
                self._user_selected_index = exchanges[-1]["prompt_index"]

            selected = next(
                (
                    exchange
                    for exchange in exchanges
                    if exchange["prompt_index"] == self._user_selected_index
                ),
                exchanges[-1],
            )
            self._user_selected_index = selected["prompt_index"]

            for row in range(self.user_history_list.count()):
                item = self.user_history_list.item(row)
                if item.data(user_role) == selected["prompt_index"]:
                    self.user_history_list.setCurrentRow(row)
                    break

            self._render_user_exchange(selected, running)

        def _render_user_exchange(self, exchange, running):
            """Render one exchange into the answer pane as Markdown."""
            if exchange is None:
                self.user_output.clear()
                return
            # Only the newest, followed exchange is "running"; an older one the
            # user clicked back to is already complete.
            is_latest = (
                self._user_follow_latest
                and self._messages
                and exchange["prompt_index"] >= len(self._messages) - 2
            )
            markdown = _compose_user_markdown(
                exchange["question"],
                exchange["answer"],
                running=running and is_latest,
            )
            if hasattr(self.user_output, "setMarkdown"):
                self.user_output.setMarkdown(markdown)
            else:  # pragma: no cover - very old Qt without Markdown support
                self.user_output.setHtml(_markdown_to_basic_html(markdown))
            scrollbar = self.user_output.verticalScrollBar()
            if scrollbar is not None and running and is_latest:
                scrollbar.setValue(scrollbar.maximum())

    _CACHED_CLASS = KadasChatDockWidget
    return _CACHED_CLASS
