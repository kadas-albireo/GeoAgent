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
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
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
            super().__init__(iface, parent)
            self.setWindowTitle("KADAS GeoAgent")
            self._build_user_mode_ui()
            self._user_ready = True
            # Per product decision: always open in the simple user mode.
            self._set_developer_mode(False)
            self._sync_user_view()

        # -- UI construction --------------------------------------------------

        def _build_user_mode_ui(self):
            """Wrap the developer widget and a new user page in a stack."""
            developer_widget = self.widget()

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
            self.mode_stack.addWidget(developer_widget)         # index 1: dev
            outer.addWidget(self.mode_stack, 1)

            self.setWidget(container)

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
            self.user_history_list.itemClicked.connect(
                self._on_user_history_clicked
            )
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
            self.mode_toggle.setText(
                "User mode" if developer else "Developer mode"
            )
            if not developer:
                self._sync_user_view()

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
