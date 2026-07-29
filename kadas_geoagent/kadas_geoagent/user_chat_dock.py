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
        SETTINGS_PREFIX,
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
            # Seed KADAS-appropriate defaults before the base class restores
            # settings in super().__init__ (see the method for the rationale).
            self._apply_kadas_defaults()
            super().__init__(iface, parent)
            self.setWindowTitle("KADAS GeoAgent")
            self._build_user_mode_ui()
            self._restore_skill_file()
            self._user_ready = True
            # Per product decision: always open in the simple user mode.
            self._set_developer_mode(False)
            self._sync_user_view()

        # -- KADAS defaults ---------------------------------------------------

        def _apply_kadas_defaults(self):
            """Seed KADAS-appropriate settings the first time the dock is used.

            KADAS ships as a turnkey product: the end user should not have to
            open Developer mode and configure the engine before it works. These
            are written to the shared OpenGeoAgent QSettings only when they are
            still unset, so a developer who changes them in Developer mode keeps
            their choice across restarts.

            * agent_mode -> "KADAS": the KADAS tool surface (swisstopo, OSM,
              annotations) rather than the generic QGIS one.
            * permission_profile -> "Trusted auto-approve" and
              auto_approve_tools -> True: the agent runs its tools without a
              confirmation prompt on every step.
            * max_tokens -> 32768 (the Settings spinbox maximum): the providers
              we bill (e.g. Anthropic) require a concrete output-token budget;
              the "Auto" sentinel leaves it unset and the request fails.
            """
            from qgis.PyQt.QtCore import QSettings

            settings = QSettings()
            defaults = {
                "agent_mode": "KADAS",
                "permission_profile": "Trusted auto-approve",
                "auto_approve_tools": True,
                "max_tokens": 32768,
            }
            for key, value in defaults.items():
                full_key = f"{SETTINGS_PREFIX}{key}"
                if settings.value(full_key) is None:
                    settings.setValue(full_key, value)

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
            self.training_panel = self._build_training_panel()
            self.training_panel.setVisible(False)
            outer.addWidget(self.training_panel)

            # Everything goes inside one scroll area.
            #
            # In Developer mode the stack shows the full chat dock, whose minimum
            # height (~600px) already exceeds a typical dock. A QVBoxLayout cannot
            # shrink a child below its minimum, so it lays the training panel out
            # *past the bottom edge* of the dock -- the panel was positioned around
            # y=630 in a 500px dock. Scrolling the panel itself does not help,
            # because the panel is off-screen, not merely clipped: that is why the
            # earlier per-panel scroll area showed no scrollbar.
            #
            # Scrolling the whole dock is what actually makes the bottom reachable.
            # On a tall dock the scrollbar never appears, so nothing changes there.
            scroll = QScrollArea()
            scroll.setWidget(container)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                _qt_value("ScrollBarPolicy", "ScrollBarAlwaysOff")
            )
            self.dock_scroll = scroll
            self.setWidget(scroll)

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

            # The "Inject API docs (documancer)" toggle lives in the shared
            # OpenGeoAgent Settings dock only; it used to be duplicated here.

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
            if getattr(self, "training_panel", None) is not None:
                self.training_panel.setVisible(bool(developer))
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

        def _build_prompt_with_context(self, prompt):
            """Prepend the selected skill file to the shared dock's context.

            Extends the shared dock's context builder so a chosen SKILL.md /
            skills_prompt.md becomes extra guidance for the turn (the "upskill"
            step surfaced in the UI).

            The KADAS API reference (documancer) is handled entirely by the
            shared dock's ``inject_api_docs`` setting in the OpenGeoAgent Settings
            dock, so it is not duplicated here.

            The skill text goes into the **user message**, never the system
            prompt. The system prompt plus the tool definitions form a byte-stable
            prefix that llama.cpp caches: re-sending an identical ~16k prefix to a
            local qwen2.5-7b costs ~0.5s, while changing it costs 13-22s because
            the whole prefix must be reprefilled. This guidance varies per
            question, so putting it in the system prompt would destroy that cache
            on every turn.
            """
            composed = super()._build_prompt_with_context(prompt)

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
