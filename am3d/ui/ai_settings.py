"""Explicit provider and credential configuration for Create with AI."""

from __future__ import annotations

from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_ALIAS = "default"


def _secret_leaks(secret: str, values) -> bool:
    """Check nonsecret preference keys and values without exposing a key."""
    if not secret:
        return False
    from am3d.ai.credentials import (
        contains_percent_encoded_secret,
        contains_percent_encoded_secret_text,
    )

    for value in values:
        text = str(value)
        if secret in text:
            return True
        try:
            if contains_percent_encoded_secret_text(text, secret):
                return True
        except ValueError:
            # Over-budget or excessive encoding in saved text is ambiguous.
            return True
        if not text.lstrip().lower().startswith(("https://", "http://")):
            continue
        try:
            parsed = urlsplit(text)
            if contains_percent_encoded_secret(parsed.path, secret):
                return True
        except ValueError:
            # Ambiguous URL encoding in existing preferences must not be
            # carried forward when credentials are saved or rotated.
            return True
    return False


class AISettingsDialog(QDialog):
    """Settings for one explicitly configured OpenAI-compatible endpoint."""

    def __init__(self, session_credentials=None, parent=None):
        super().__init__(parent)
        self.session_credentials = session_credentials
        self.setWindowTitle("Create with AI Settings")
        self.setMinimumWidth(520)
        self.setMaximumHeight(360)
        self.resize(560, 360)
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        scroll = QScrollArea(self)
        scroll.setObjectName("aiSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.NoFrame)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(2, 2, 8, 2)
        body_layout.setSpacing(8)

        group = QGroupBox("Provider")
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        note = QLabel(
            "Choose an endpoint and enter the exact model name you intend to use. "
            "No model is selected by default; model availability and pricing have not been qualified.")
        note.setWordWrap(True)
        note.setTextFormat(Qt.PlainText)
        form.addRow(note)

        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setAccessibleName("AI provider HTTPS endpoint")
        form.addRow("HTTPS endpoint", self.endpoint_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setAccessibleName("Explicit AI model name")
        self.model_edit.setPlaceholderText("Required before Generate")
        form.addRow("Model name", self.model_edit)

        self.storage_combo = QComboBox()
        self.storage_combo.setAccessibleName("Provider key storage")
        self.storage_combo.addItem("System credential store", "system")
        self.storage_combo.addItem("Session-only key (memory)", "session")
        form.addRow("Key storage", self.storage_combo)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setAccessibleName("Provider API key")
        self.key_edit.setPlaceholderText("Blank keeps the selected store's current key")
        form.addRow("API key", self.key_edit)

        self.key_state = QLabel("Key is never saved in application preferences.")
        self.key_state.setWordWrap(True)
        self.key_state.setTextFormat(Qt.PlainText)
        form.addRow(self.key_state)

        body_layout.addWidget(group)
        self.delete_key_button = QPushButton("Delete key from selected store")
        self.delete_key_button.setAccessibleName("Delete key from selected credential store")
        self.delete_key_button.clicked.connect(self._delete_key)
        body_layout.addWidget(self.delete_key_button)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.setAccessibleName("Save or cancel AI settings")
        self.dialog_buttons = buttons
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.setTabOrder(self.endpoint_edit, self.model_edit)
        self.setTabOrder(self.model_edit, self.storage_combo)
        self.setTabOrder(self.storage_combo, self.key_edit)
        self.setTabOrder(self.key_edit, self.delete_key_button)
        self.setTabOrder(self.delete_key_button,
                         buttons.button(QDialogButtonBox.Save))
        self.setTabOrder(buttons.button(QDialogButtonBox.Save),
                         buttons.button(QDialogButtonBox.Cancel))

    def _load(self):
        settings = QSettings("3DMASTER2005", "app")
        self.endpoint_edit.setText(str(settings.value("ai/endpoint", _ENDPOINT)))
        self.model_edit.setText(str(settings.value("ai/model", "")))
        mode = str(settings.value("ai/credentialStorage", "system"))
        index = self.storage_combo.findData(mode)
        self.storage_combo.setCurrentIndex(max(0, index))
        self.key_edit.clear()

    def _credential_store(self):
        mode = self.storage_combo.currentData()
        if mode == "session":
            if self.session_credentials is None:
                from am3d.ai.credentials import SessionCredentialStore
                self.session_credentials = SessionCredentialStore()
            return self.session_credentials
        from am3d.ai.credentials import SystemCredentialStore
        return SystemCredentialStore()

    def _settings_values(self, settings):
        values = []
        for key in settings.allKeys():
            values.append(key)
            try:
                values.append(settings.value(key))
            except Exception:
                # QSettings access errors must not leak provider key input.
                return None
        values.extend((self.endpoint_edit.text().strip(),
                       self.model_edit.text().strip(), _ALIAS))
        return values

    def _save(self):
        endpoint = self.endpoint_edit.text().strip()
        model = self.model_edit.text().strip()
        entered_key = self.key_edit.text()
        if not endpoint:
            self._fixed_error("Enter an HTTPS endpoint before saving settings.")
            return
        try:
            from am3d.ai.providers import _validate_endpoint
            _validate_endpoint(endpoint, ("api.openai.com",))
        except Exception:
            self._fixed_error(
                "The endpoint must use HTTPS on api.openai.com with no credentials, query, fragment, or custom port.")
            return

        try:
            store = self._credential_store()
            existing_key = store.get(_ALIAS)
        except Exception:
            self._fixed_error(
                "The selected credential store is unavailable. Unlock the system store or select session-only storage.")
            return

        settings = QSettings("3DMASTER2005", "app")
        values = self._settings_values(settings)
        if values is None:
            self._fixed_error("Application preferences could not be checked safely. No settings were saved.")
            return
        credentials_to_check = {value for value in (entered_key, existing_key)
                                if isinstance(value, str) and value}
        if any(_secret_leaks(credential, values)
               for credential in credentials_to_check):
            self._fixed_error(
                "The provider key matches endpoint, model, or saved preference text. Correct those fields before saving.")
            return

        if entered_key:
            try:
                store.set(_ALIAS, entered_key)
            except Exception:
                self._fixed_error(
                    "The key could not be saved in the selected credential store. Unlock it or select session-only storage.")
                return

        settings.setValue("ai/endpoint", endpoint)
        settings.setValue("ai/model", model)
        settings.setValue("ai/credentialStorage", self.storage_combo.currentData())
        settings.sync()
        if settings.status() != QSettings.NoError:
            self._fixed_error("Application preferences could not be saved. Check the local settings location.")
            return
        self.key_edit.clear()
        self.key_state.setText(
            "Key saved in the selected credential store. The key field has been cleared."
            if (entered_key or existing_key) else
            "No key is saved yet. Enter one here before a provider request.")
        self.accept()

    def _delete_key(self):
        try:
            self._credential_store().delete(_ALIAS)
        except Exception:
            self._fixed_error(
                "The key could not be deleted because the selected credential store is unavailable.")
            return
        self.key_edit.clear()
        self.key_state.setText("Key deleted from the selected credential store.")

    def _fixed_error(self, message: str):
        box = QMessageBox(self)
        box.setWindowTitle("AI Settings")
        box.setIcon(QMessageBox.Warning)
        box.setTextFormat(Qt.PlainText)
        box.setText(message)
        box.exec()
